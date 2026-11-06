"""Query helpers used by the API layer."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conflict, ConflictEvent, IngestionRun


def conflicts_active_in_range(session: Session, start: date, end: date) -> list[Conflict]:
    """Conflicts with at least one event in [start, end].

    "Ongoing" conflicts (end_date IS NULL) are bounded by their last known
    event, so they stop appearing once they go quiet instead of matching every
    future range.
    """
    stmt = (
        select(Conflict)
        .join(ConflictEvent, ConflictEvent.conflict_id == Conflict.id)
        .where(ConflictEvent.event_date >= start, ConflictEvent.event_date <= end)
        .distinct()
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


def latest_event(session: Session, conflict_id: int) -> ConflictEvent | None:
    stmt = (
        select(ConflictEvent)
        .where(ConflictEvent.conflict_id == conflict_id)
        .order_by(ConflictEvent.event_date.desc(), ConflictEvent.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def latest_events_by_conflict(
    session: Session, conflict_ids: list[int]
) -> dict[int, ConflictEvent]:
    """Most recent event per conflict in a single query (avoids N+1)."""
    if not conflict_ids:
        return {}
    stmt = (
        select(ConflictEvent)
        .where(ConflictEvent.conflict_id.in_(conflict_ids))
        .order_by(
            ConflictEvent.conflict_id, ConflictEvent.event_date.desc(), ConflictEvent.id.desc()
        )
    )
    latest: dict[int, ConflictEvent] = {}
    for event in session.scalars(stmt):
        if event.conflict_id is not None and event.conflict_id not in latest:
            latest[event.conflict_id] = event
    return latest


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
