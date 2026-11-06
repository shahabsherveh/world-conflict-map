"""FastAPI routes for conflicts, events, and manual edits."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    ConflictCreate,
    ConflictDetail,
    ConflictEventOut,
    ConflictOut,
    ConflictSummary,
    ConflictUpdate,
    EventCreate,
    EventUpdate,
    IngestionRunOut,
    SourcesOut,
)
from app.config import load_config
from app.db import get_session
from app.extract.classifier import slug_to_text
from app.models import Conflict, ConflictEvent, EditLog
from app.queries import (
    conflicts_active_in_range,
    events_in_range,
    latest_event,
    latest_events_by_conflict,
    recent_ingestion_runs,
)

router = APIRouter(prefix="/api")


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")


def _headline(latest) -> str | None:
    """Prefer the newest article headline; fall back to event summary."""
    if latest and latest.source_url:
        text = slug_to_text(latest.source_url)
        if text and not text.isdigit():
            return text
    if latest and latest.summary:
        return latest.summary
    return None


def _summarize(
    conflict: Conflict, events: list[ConflictEvent], fallback_latest: ConflictEvent | None
) -> ConflictSummary:
    intensity = max((e.intensity for e in events), default=0)
    latest_in_range = max(events, key=lambda e: e.event_date) if events else None
    # Headline should always be present, even when the range has no events.
    latest = latest_in_range or fallback_latest
    return ConflictSummary(
        id=conflict.id,
        name=conflict.name,
        country=conflict.country,
        start_date=conflict.start_date,
        end_date=conflict.end_date,
        status=conflict.status,
        intensity=intensity,
        lat=latest_in_range.lat if latest_in_range else None,
        lon=latest_in_range.lon if latest_in_range else None,
        event_count=len(events),
        headline=_headline(latest),
    )


def _apply_patch(db: Session, obj, updates: dict, target_type: str) -> None:
    for field, value in updates.items():
        old = getattr(obj, field)
        if old != value:
            db.add(
                EditLog(
                    target_type=target_type,
                    target_id=obj.id,
                    field=field,
                    old_value="" if old is None else str(old),
                    new_value="" if value is None else str(value),
                )
            )
            setattr(obj, field, value)


@router.get("/conflicts", response_model=list[ConflictSummary])
def list_conflicts(start: date, end: date, db: DbSession):
    _validate_range(start, end)
    conflicts = conflicts_active_in_range(db, start, end)
    if not conflicts:
        return []

    # One query for all events in range instead of one per conflict (N+1).
    by_conflict: dict[int, list[ConflictEvent]] = {}
    for event in events_in_range(db, start, end):
        if event.conflict_id is not None:
            by_conflict.setdefault(event.conflict_id, []).append(event)

    latest_by_conflict = latest_events_by_conflict(db, [c.id for c in conflicts])
    return [
        _summarize(c, by_conflict.get(c.id, []), latest_by_conflict.get(c.id)) for c in conflicts
    ]


@router.get("/conflicts/{conflict_id}", response_model=ConflictDetail)
def get_conflict(conflict_id: int, db: DbSession):
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    end = conflict.end_date or date.today()
    events = events_in_range(db, conflict.start_date, end, conflict_id=conflict_id)
    summary = _summarize(conflict, events, latest_event(db, conflict_id))
    return ConflictDetail(
        **summary.model_dump(),
        events=[_event_out(e) for e in events],
    )


def _event_out(event: ConflictEvent) -> ConflictEventOut:
    out = ConflictEventOut.model_validate(event)
    headline = slug_to_text(event.source_url) if event.source_url else None
    if headline and headline.isdigit():
        headline = None
    return out.model_copy(update={"headline": headline or event.summary})


@router.get("/events", response_model=list[ConflictEventOut])
def list_events(start: date, end: date, db: DbSession, conflict_id: int | None = None):
    _validate_range(start, end)
    events = events_in_range(db, start, end, conflict_id=conflict_id)
    return [_event_out(e) for e in events]


@router.get("/events/{event_id}", response_model=ConflictEventOut)
def get_event(event_id: int, db: DbSession):
    event = db.get(ConflictEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_out(event)


@router.patch("/conflicts/{conflict_id}", response_model=ConflictOut)
def update_conflict(conflict_id: int, payload: ConflictUpdate, db: DbSession):
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")

    updates = payload.model_dump(exclude_unset=True)
    new_start = updates.get("start_date", conflict.start_date)
    new_end = updates.get("end_date", conflict.end_date)
    if new_end is not None and new_end < new_start:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")

    _apply_patch(db, conflict, updates, "conflict")
    db.commit()
    db.refresh(conflict)
    return conflict


@router.post("/conflicts", response_model=ConflictOut, status_code=201)
def create_conflict(payload: ConflictCreate, db: DbSession):
    conflict = Conflict(**payload.model_dump())
    db.add(conflict)
    db.commit()
    db.refresh(conflict)
    return conflict


@router.patch("/events/{event_id}", response_model=ConflictEventOut)
def update_event(event_id: int, payload: EventUpdate, db: DbSession):
    event = db.get(ConflictEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    _apply_patch(db, event, payload.model_dump(exclude_unset=True), "event")
    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.post("/events", response_model=ConflictEventOut, status_code=201)
def create_event(payload: EventCreate, db: DbSession):
    if payload.conflict_id is not None and db.get(Conflict, payload.conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    event = ConflictEvent(provenance="manual", **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.get("/ingestion-runs", response_model=list[IngestionRunOut])
def list_ingestion_runs(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return recent_ingestion_runs(db, limit)


@router.get("/sources", response_model=SourcesOut)
def list_sources():
    cfg = load_config()
    return SourcesOut(
        source="GDELT 2.0 raw event files",
        base_url=cfg["base_url"],
        lookback_days=int(cfg["lookback_days"]),
    )
