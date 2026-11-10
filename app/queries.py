"""Query helpers used by the API layer."""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Conflict, ConflictEvent, IngestionRun, RawEvent


def conflicts_active_in_range(session: Session, start: date, end: date) -> list[Conflict]:
    """Conflicts with an event in [start, end], plus eventless conflicts.

    "Ongoing" conflicts with events are bounded by their last known event, so
    they stop appearing once they go quiet. Manually created conflicts can have
    no events yet; include those when their own date span overlaps the range so
    a newly created conflict is immediately visible.
    """
    events_in_range = select(ConflictEvent.conflict_id).where(
        ConflictEvent.event_date >= start, ConflictEvent.event_date <= end
    )
    stmt = (
        select(Conflict)
        .where(
            Conflict.id.in_(events_in_range)
            | (
                ~Conflict.events.any()
                & (Conflict.start_date <= end)
                & (Conflict.end_date.is_(None) | (Conflict.end_date >= start))
            )
        )
        .order_by(Conflict.start_date)
    )
    return list(session.scalars(stmt))


def events_in_range(
    session: Session, start: date, end: date, conflict_id: int | None = None
) -> list[ConflictEvent]:
    stmt = select(ConflictEvent).where(
        ConflictEvent.event_date >= start, ConflictEvent.event_date <= end
    )
    if conflict_id is not None:
        stmt = stmt.where(ConflictEvent.conflict_id == conflict_id)
    stmt = stmt.order_by(ConflictEvent.event_date)
    return list(session.scalars(stmt))


def events_for_conflict(session: Session, conflict_id: int) -> list[ConflictEvent]:
    """Every event linked to a conflict, oldest first.

    Deliberately unbounded by the conflict's own date span: `conflict_id` is the
    authoritative link, and a human can shorten the span without unlinking the
    events that fall outside it.
    """
    stmt = (
        select(ConflictEvent)
        .where(ConflictEvent.conflict_id == conflict_id)
        .order_by(ConflictEvent.event_date, ConflictEvent.id)
    )
    return list(session.scalars(stmt))


def latest_event(session: Session, conflict_id: int) -> ConflictEvent | None:
    stmt = (
        select(ConflictEvent)
        .where(ConflictEvent.conflict_id == conflict_id)
        .order_by(ConflictEvent.event_date.desc(), ConflictEvent.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _count(value: str | int | float | None) -> int:
    """Parse one stored count; absent, unparsable or negative means zero.

    Mirrors `app.extract.gdelt_adapter._count`. The badge and the stored
    `confidence` must agree on what a missing count means, or the same event
    would be described two different ways depending on which one you read.
    """
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def corroboration_counts(
    session: Session, source_event_ids: Iterable[str | None]
) -> dict[str, tuple[int, int]]:
    """`(outlets, articles)` per GDELT event id, in one query.

    The counts live in the stored raw payload, which is why the read projects
    two `json_extract` scalars instead of the payloads themselves: a payload
    holds every non-empty GDELT column (~1 KB), and a busy conflict has
    thousands of events, so selecting them whole would move megabytes per
    detail request.

    An id with no raw row is *absent* from the result, not zero. The counts are
    unknown for a manual event, or for one whose raw row retention has pruned;
    the API reports that as null rather than claiming no outlet backed a real
    event. Absent *keys* inside a stored payload are zero, matching the
    adapter's documented invariant.
    """
    ids = list(
        dict.fromkeys(source_event_id for source_event_id in source_event_ids if source_event_id)
    )
    if not ids:
        return {}
    stmt = select(
        RawEvent.source_event_id,
        func.json_extract(RawEvent.payload, "$.num_sources"),
        func.json_extract(RawEvent.payload, "$.num_articles"),
    ).where(RawEvent.source_event_id.in_(ids))
    return {row[0]: (_count(row[1]), _count(row[2])) for row in session.execute(stmt)}


def existing_source_event_ids(session: Session, ids: list[str]) -> set[str]:
    """Subset of `ids` already present in `conflict_event.source_event_id`."""
    if not ids:
        return set()
    stmt = select(ConflictEvent.source_event_id).where(ConflictEvent.source_event_id.in_(ids))
    return {row[0] for row in session.execute(stmt) if row[0]}


def recent_ingestion_runs(session: Session, limit: int = 20) -> list[IngestionRun]:
    """Newest pipeline runs first, with id as a stable tie-breaker."""
    stmt = (
        select(IngestionRun)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def latest_successful_ingestion_run(session: Session) -> IngestionRun | None:
    """Most recent run that actually got events onto the map.

    Ordered by `finished_at`, not `started_at`: a long backfill that started
    before a short daily run still counts as the newest data, and a `running`
    row (finished_at is null) never looks like success.

    Day rows only (`source_day` set). A successful grouping/pruning row spans no
    day, so it cannot answer "which day's data is current" — and a step row is
    not proof on its own that any events were ingested.

    `raw_only` runs are excluded on purpose. They store raw rows and stop, so a
    cron misconfigured with `--raw-only` would keep "succeeding" while the map
    froze — the exact failure this query exists to catch. NULL `mode` is kept:
    those are rows from before the column existed, which still produced events.
    """
    stmt = (
        select(IngestionRun)
        .where(
            IngestionRun.status == "success",
            IngestionRun.finished_at.is_not(None),
            IngestionRun.source_day.is_not(None),
            or_(IngestionRun.mode.is_(None), IngestionRun.mode != "raw_only"),
        )
        .order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()
