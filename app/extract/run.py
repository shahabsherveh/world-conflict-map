"""Extraction pipeline entrypoint: fetch → adapt → filter → persist → group."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import load_config
from app.db import get_session
from app.extract.base import BaseSourceAdapter, EventDraft
from app.extract.classifier import ZeroShotConflictClassifier
from app.extract.filter import filter_by_zero_shot
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import group_events
from app.ingest.gdelt import GDELTClient, read_day_from_dir
from app.ingest.normalizer import dedupe_new
from app.ingest.raw_store import (
    mark_raw_events,
    pending_raw_events,
    pending_raw_source_days,
    prune_raw_events,
    raw_payload,
    store_raw_events,
)
from app.models import ConflictEvent, IngestionRun, utcnow
from app.queries import existing_source_event_ids


def to_drafts(raw_events: list[dict[str, str]], adapter: BaseSourceAdapter) -> list[EventDraft]:
    drafts: list[EventDraft] = []
    for raw in raw_events:
        draft = adapter.to_event_draft(raw)
        if draft is not None:
            drafts.append(draft)
    return drafts


def persist_drafts(
    session: Session, drafts: list[EventDraft], existing: set[str] | None = None
) -> int:
    """Insert conflict events (provenance='auto'), skipping ids already stored."""
    if existing is None:
        ids = [d.source_event_id for d in drafts if d.source_event_id]
        existing = existing_source_event_ids(session, ids)

    new_count = 0
    for draft in drafts:
        if draft.source_event_id and draft.source_event_id in existing:
            continue
        session.add(
            ConflictEvent(
                source_event_id=draft.source_event_id,
                place_name=draft.place_name,
                country=draft.country,
                lat=draft.lat,
                lon=draft.lon,
                event_date=draft.event_date,
                event_type=draft.event_type,
                actor_a=draft.actor_a,
                actor_b=draft.actor_b,
                fatalities=draft.fatalities,
                intensity=draft.intensity,
                summary=draft.summary,
                source_url=draft.source_url,
                confidence=draft.confidence,
                provenance="auto",
            )
        )
        new_count += 1
    session.commit()
    return new_count


def process_pending_raw_events(
    session: Session,
    adapter: BaseSourceAdapter,
    classifier: ZeroShotConflictClassifier | None,
    threshold: float,
    source_day: date,
    batch_size: int = 2000,
) -> tuple[int, int]:
    """Process stored raw rows for one day; returns (rows processed, events persisted)."""
    processed = 0
    new_total = 0
    while True:
        raw_rows = pending_raw_events(session, source_day=source_day, limit=batch_size)
        if not raw_rows:
            break

        drafts: list[EventDraft] = []
        not_conflict_ids: list[str] = []
        for row in raw_rows:
            draft = adapter.to_event_draft(raw_payload(row))
            if draft is None:
                not_conflict_ids.append(row.source_event_id)
            else:
                drafts.append(draft)

        kept = filter_by_zero_shot(drafts, classifier, threshold) if classifier else drafts
        kept_ids = {draft.source_event_id for draft in kept if draft.source_event_id}
        filtered_ids = [
            draft.source_event_id
            for draft in drafts
            if draft.source_event_id and draft.source_event_id not in kept_ids
        ]
        existing = existing_source_event_ids(session, list(kept_ids))
        duplicate_ids = [source_id for source_id in kept_ids if source_id in existing]
        persisted_ids = [source_id for source_id in kept_ids if source_id not in existing]

        new_count = persist_drafts(session, kept, existing=existing)
        finished_at = utcnow()
        mark_raw_events(session, not_conflict_ids, "not_armed_conflict", finished_at)
        mark_raw_events(session, filtered_ids, "filtered_out", finished_at)
        mark_raw_events(session, duplicate_ids, "duplicate", finished_at)
        mark_raw_events(session, persisted_ids, "persisted", finished_at)
        session.commit()

        processed += len(raw_rows)
        new_total += new_count
    return processed, new_total


def retry_stranded_raw_days(
    session: Session,
    adapter: BaseSourceAdapter,
    classifier: ZeroShotConflictClassifier | None,
    threshold: float,
    targets: list[date],
) -> int:
    """Process pending raw rows for days this run does not fetch.

    `store_raw_events` commits before extraction, so a failure inside processing
    (the model dying mid-run, a killed process) leaves rows pending for that day.
    The daily run only targets recent days, so those rows were never retried — and
    `prune_raw_events` only deletes processed rows, so they accumulated forever
    while their events never reached the map.

    Days in `targets` are skipped: the caller stores and processes those itself.
    Returns the number of events persisted.
    """
    new_events = 0
    for source_day in pending_raw_source_days(session):
        if source_day in targets:
            continue
        processed, new_count = process_pending_raw_events(
            session, adapter, classifier, threshold, source_day
        )
        new_events += new_count
        print(
            f"{source_day}: retried {processed} stranded raw rows, {new_count} new events",
            flush=True,
        )
    return new_events


def describe_exception(exc: BaseException, limit: int = 2000) -> str:
    """`ExcType: message`, truncated so one huge response body can't own the row."""
    return f"{type(exc).__name__}: {exc}".strip()[:limit]


def merge_notes(*notes: str | None) -> str | None:
    """Join the reasons a run produced less than it should into one cell."""
    return "; ".join(note for note in notes if note) or None


def cache_note(skipped: list[str]) -> str | None:
    """Stderr is gone by morning; a short-loaded day has to say so on its row."""
    if not skipped:
        return None
    return f"{len(skipped)} corrupt cached export file(s) skipped"


@contextmanager
def pipeline_phase(session: Session, mode: str, phase: str) -> Generator[None, None, None]:
    """Time one whole-invocation step on its own `ingestion_run` row.

    `retry_stranded_raw_days`, `group_events` and `prune_raw_events` run once per
    invocation, outside the per-day rows, so a crash there used to leave nothing
    behind but the day rows that had already committed.

    The row is created up front as `running` (like a day row), so a long grouping
    step is visible while it runs and a killed process leaves evidence of where it
    died. It is then finished in place: a healthy step keeps its duration, a crash
    keeps `failed` + the reason. `source_day` stays null and `phase` names the
    step, so the two kinds of row are distinguishable without parsing `error`.
    """
    row = IngestionRun(status="running", source_day=None, mode=mode, phase=phase)
    session.add(row)
    session.commit()
    try:
        yield
    except Exception as exc:
        try:
            # Discard whatever half-done work the phase left in the session, then
            # re-load the row and record the reason on it. The column default for
            # `started_at` fires at INSERT, so the row already has both ends
            # ordered correctly.
            session.rollback()
            row.status = "failed"
            row.error = describe_exception(exc)
            row.finished_at = utcnow()
            session.commit()
        except Exception as record_exc:  # noqa: BLE001 — never mask the real failure
            print(
                f"WARNING: could not record {phase} failure ({describe_exception(record_exc)})",
                file=sys.stderr,
                flush=True,
            )
        raise
    row.status = "success"
    row.finished_at = utcnow()
    session.commit()


def load_classifier() -> tuple[ZeroShotConflictClassifier | None, str | None]:
    """Return `(classifier, degraded_reason)`.

    A missing model is deliberate graceful degradation, not a failure: the map
    still updates, just unfiltered (and therefore clustered on country
    centroids). The reason is returned so the caller can persist it — a stderr
    line from a cron run is gone by the time anyone asks "did the filter run?".
    `degraded_reason` is None when the filter loaded normally.
    """
    try:
        return ZeroShotConflictClassifier(), None
    except Exception as exc:  # noqa: BLE001 — degrade gracefully if the model isn't available
        reason = describe_exception(exc)
        print(
            f"WARNING: zero-shot filter unavailable ({reason}); continuing without it.",
            file=sys.stderr,
            flush=True,
        )
        return None, f"zero-shot filter unavailable ({reason}); ran unfiltered"


def resolve_target_days(
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    today: date | None = None,
) -> list[date]:
    """Return included target days, oldest first.

    `days=N` means the last N complete days (ending yesterday), matching the
    config's lookback semantics. Explicit start/end are inclusive.
    """
    today = today or date.today()
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("start and end must be provided together")
        if end < start:
            raise ValueError(f"end date {end} is before start date {start}")
        return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    if days is None or days < 1:
        raise ValueError("days must be >= 1")
    last_complete = today - timedelta(days=1)
    return [last_complete - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def run(
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    source_dir: Path | None = None,
    raw_only: bool = False,
) -> int:
    cfg = load_config()
    if days is None and start is None and end is None:
        days = int(cfg["lookback_days"])

    targets = resolve_target_days(days=days, start=start, end=end)
    run_mode = "raw_only" if raw_only else "full"
    degraded_reason: str | None = None
    if raw_only:
        classifier = None
    else:
        classifier, degraded_reason = load_classifier()
    threshold = float(cfg["zero_shot_threshold"])
    adapter = GDELTAdapter()
    client = None if source_dir is not None else GDELTClient(base_url=cfg["base_url"])

    session = get_session()
    total_new = 0
    total_raw = 0
    created = 0
    try:
        if not raw_only:
            with pipeline_phase(session, run_mode, "retry_stranded_raw_days"):
                total_new += retry_stranded_raw_days(
                    session, adapter, classifier, threshold, targets
                )

        for target in targets:
            run_record = IngestionRun(
                status="running",
                source_day=target,
                mode=run_mode,
                degraded_reason=degraded_reason,
            )
            session.add(run_record)
            session.commit()

            raw_count = 0
            raw_new = 0
            processed = 0
            new_count = 0
            skipped_cache: list[str] = []
            try:
                if source_dir is not None:
                    raw_events = read_day_from_dir(source_dir, target, skipped_cache)
                else:
                    assert client is not None
                    raw_events = client.fetch_day(target)

                raw_count = len(raw_events)
                raw_events = dedupe_new(raw_events)
                raw_new = store_raw_events(session, raw_events, source_day=target)
                session.commit()
                total_raw += raw_new

                if not raw_only:
                    processed, new_count = process_pending_raw_events(
                        session, adapter, classifier, threshold, target
                    )
                    total_new += new_count
            except Exception as exc:
                session.rollback()
                run_record.status = "failed"
                # Without this the only record of *why* was stdout of a cron
                # job, which is usually gone by the time anyone notices.
                run_record.error = describe_exception(exc)
                run_record.finished_at = utcnow()
                run_record.items_seen = raw_count
                session.commit()
                raise

            run_record.status = "success"
            run_record.finished_at = utcnow()
            run_record.items_seen = raw_count
            run_record.items_new = new_count
            # The classifier note was set at creation; a partly corrupt cache is
            # only known now, so merge rather than overwrite.
            run_record.degraded_reason = merge_notes(degraded_reason, cache_note(skipped_cache))
            session.commit()
            print(
                f"{target}: {raw_count} raw, {raw_new} new raw, "
                f"{processed} processed, {new_count} new events",
                flush=True,
            )

        if not raw_only:
            with pipeline_phase(session, run_mode, "group_events"):
                created = group_events(session)
                session.commit()

        with pipeline_phase(session, run_mode, "prune_raw_events"):
            pruned = prune_raw_events(session, int(cfg["raw_retention_days"]))
            session.commit()
    finally:
        session.close()

    if raw_only:
        print(
            f"Stored {total_raw} new raw rows across {len(targets)} day(s)",
            flush=True,
        )
    else:
        print(
            f"Extracted {total_new} new conflict events across {len(targets)} day(s); "
            f"{created} conflicts created",
            flush=True,
        )
    if pruned:
        print(f"Pruned {pruned} processed raw rows past retention", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="process the last N complete days")
    parser.add_argument("--start", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (YYYY-MM-DD)")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="read cached .export.CSV.zip files instead of downloading",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="store raw rows only; skip extraction/filtering",
    )
    args = parser.parse_args(argv)

    try:
        return run(
            days=args.days,
            start=args.start,
            end=args.end,
            source_dir=args.source_dir,
            raw_only=args.raw_only,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
