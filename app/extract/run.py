"""Extraction pipeline entrypoint: fetch → adapt → filter → persist → group."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.config import load_config
from app.db import get_session
from app.extract.base import BaseSourceAdapter, EventDraft
from app.extract.classifier import ZeroShotConflictClassifier
from app.extract.filter import filter_by_zero_shot
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import group_events
from app.ingest.gdelt import GDELTClient
from app.ingest.normalizer import dedupe_new
from app.models import ConflictEvent
from app.queries import existing_source_event_ids


def to_drafts(raw_events: list[dict[str, str]], adapter: BaseSourceAdapter) -> list[EventDraft]:
    drafts: list[EventDraft] = []
    for raw in raw_events:
        draft = adapter.to_event_draft(raw)
        if draft is not None:
            drafts.append(draft)
    return drafts


def persist_drafts(session: Session, drafts: list[EventDraft]) -> int:
    """Insert conflict events (provenance='auto'), skipping ids already stored."""
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


def load_classifier() -> ZeroShotConflictClassifier | None:
    try:
        return ZeroShotConflictClassifier()
    except Exception:  # noqa: BLE001 — degrade gracefully if the model isn't available
        return None


def run() -> int:
    cfg = load_config()
    target = date.today() - timedelta(days=int(cfg["lookback_days"]))

    raw_events = dedupe_new(GDELTClient(base_url=cfg["base_url"]).fetch_day(target))
    drafts = to_drafts(raw_events, GDELTAdapter())

    classifier = load_classifier()
    if classifier is not None:
        drafts = filter_by_zero_shot(drafts, classifier, float(cfg["zero_shot_threshold"]))

    session = get_session()
    try:
        new_count = persist_drafts(session, drafts)
        group_events(session)
        session.commit()
    finally:
        session.close()

    print(f"Extracted {new_count} new conflict events for {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
