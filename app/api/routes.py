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
    PipelineHealthOut,
    SourcesOut,
)
from app.config import load_config
from app.db import get_session
from app.extract.classifier import slug_to_text
from app.models import Conflict, ConflictEvent, EditLog, utcnow
from app.queries import (
    conflicts_active_in_range,
    corroboration_counts,
    events_for_conflict,
    events_in_range,
    latest_successful_ingestion_run,
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


def _validate_coordinates(lat: float | None, lon: float | None) -> None:
    """A marker needs both numbers; half a coordinate is silently unmappable.

    The UI's map layer skips any event missing either value, so a record with only
    `lat` (or with `lon` cleared) disappeared from the map with no error at all.
    """
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="lat and lon must be provided together")


def _headline(event: ConflictEvent) -> str | None:
    """Prefer the article headline; fall back to the event summary.

    GDELT sometimes links a bare article id rather than a slug, which says nothing
    in a list, so it falls through to the summary.
    """
    if event.source_url:
        text = slug_to_text(event.source_url)
        if text and not text.isdigit():
            return text
    return event.summary or None


def _summarize(conflict: Conflict, events: list[ConflictEvent]) -> ConflictSummary:
    intensity = max((e.intensity for e in events), default=0)
    # Newest event wins; `id` breaks same-day ties so the summary does not flip
    # between requests (the DB only orders by event_date).
    latest = max(events, key=lambda e: (e.event_date, e.id)) if events else None
    return ConflictSummary(
        id=conflict.id,
        name=conflict.name,
        country=conflict.country,
        start_date=conflict.start_date,
        end_date=conflict.end_date,
        status=conflict.status,
        intensity=intensity,
        lat=latest.lat if latest else None,
        lon=latest.lon if latest else None,
        event_count=len(events),
        headline=_headline(latest) if latest else None,
    )


def _in_conflict_span(event: ConflictEvent, conflict: Conflict) -> bool:
    if event.event_date < conflict.start_date:
        return False
    return conflict.end_date is None or event.event_date <= conflict.end_date


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

    # No out-of-range fallback here: conflicts_active_in_range returns a conflict
    # only when it has an event in range (or has none at all), so every conflict
    # with events has its newest one right here.
    return [_summarize(c, by_conflict.get(c.id, [])) for c in conflicts]


@router.get("/conflicts/{conflict_id}", response_model=ConflictDetail)
def get_conflict(conflict_id: int, db: DbSession):
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    # List every linked event, not just those inside the conflict's own span: the
    # list view counts by requested range, so span-scoping here made the sidebar
    # promise events the panel refused to show (and hid anything dated in the
    # future, since the upper bound was `today` when `end_date` was null).
    events = events_for_conflict(db, conflict_id)
    summary = _summarize(conflict, events)
    in_span = [event for event in events if _in_conflict_span(event, conflict)]
    if in_span:
        # Headline preference only: what the conflict calls itself still describes
        # its active span, so a late out-of-span (usually manual) event does not
        # take the title.
        summary = summary.model_copy(
            update={"headline": _headline(max(in_span, key=lambda e: (e.event_date, e.id)))}
        )
    return ConflictDetail(
        **summary.model_dump(),
        events=_events_out(db, events),
    )


def _event_out(event: ConflictEvent, counts: tuple[int, int] | None = None) -> ConflictEventOut:
    out = ConflictEventOut.model_validate(event)
    headline = slug_to_text(event.source_url) if event.source_url else None
    if headline and headline.isdigit():
        headline = None
    sources, articles = counts if counts is not None else (None, None)
    return out.model_copy(
        update={
            "headline": headline or event.summary,
            "sources": sources,
            "articles": articles,
            "well_corroborated": _well_corroborated(sources, articles),
        }
    )


# "Well corroborated" is a counts predicate, not a `confidence` threshold: the
# score is ordinal and its scale has never been validated, so a 0.5 line would
# look measured while being an arbitrary convention. Two independent outlets and
# three articles is a floor a reader can check against the badge itself.
WELL_CORROBORATED_MIN_SOURCES = 2
WELL_CORROBORATED_MIN_ARTICLES = 3


def _well_corroborated(sources: int | None, articles: int | None) -> bool:
    if sources is None or articles is None:
        return False
    return sources >= WELL_CORROBORATED_MIN_SOURCES and articles >= WELL_CORROBORATED_MIN_ARTICLES


def _events_out(db: Session, events: list[ConflictEvent]) -> list[ConflictEventOut]:
    """Serialize a page of events with one corroboration lookup.

    Never look counts up per event: a conflict detail can be hundreds of rows,
    and that is the N+1 this module already got bitten by (Gotcha #5).
    """
    counts = corroboration_counts(db, [event.source_event_id for event in events])
    return [_event_out(event, counts.get(event.source_event_id or "")) for event in events]


@router.get("/events", response_model=list[ConflictEventOut])
def list_events(start: date, end: date, db: DbSession, conflict_id: int | None = None):
    _validate_range(start, end)
    events = events_in_range(db, start, end, conflict_id=conflict_id)
    return _events_out(db, events)


@router.get("/events/{event_id}", response_model=ConflictEventOut)
def get_event(event_id: int, db: DbSession):
    event = db.get(ConflictEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return _events_out(db, [event])[0]


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
    updates = payload.model_dump(exclude_unset=True)
    # Validate the merged record, not the payload: `{"lat": 1}` is a fine partial
    # update when lon is already stored, but `{"lon": null}` alone would leave the
    # row with half a coordinate.
    _validate_coordinates(updates.get("lat", event.lat), updates.get("lon", event.lon))
    _apply_patch(db, event, updates, "event")
    db.commit()
    db.refresh(event)
    return _events_out(db, [event])[0]


@router.post("/events", response_model=ConflictEventOut, status_code=201)
def create_event(payload: EventCreate, db: DbSession):
    if payload.conflict_id is not None and db.get(Conflict, payload.conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    _validate_coordinates(payload.lat, payload.lon)
    event = ConflictEvent(provenance="manual", **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return _events_out(db, [event])[0]


@router.get("/ingestion-runs", response_model=list[IngestionRunOut])
def list_ingestion_runs(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return recent_ingestion_runs(db, limit)


@router.get("/pipeline-health", response_model=PipelineHealthOut)
def pipeline_health(db: DbSession):
    """Answer "is the map still updating?" without reading logs or the DB.

    Kept off `/health` on purpose: that endpoint is the container's liveness
    probe (CI and deploy both curl it), and it must stay cheap and 200 even when
    the DB is missing or empty.
    """
    threshold = int(load_config()["pipeline_stale_hours"])
    run = latest_successful_ingestion_run(db)
    if run is None or run.finished_at is None:
        return PipelineHealthOut(
            last_success_at=None,
            last_success_day=None,
            age_hours=None,
            stale=True,
            threshold_hours=threshold,
        )
    age_hours = (utcnow() - run.finished_at).total_seconds() / 3600
    return PipelineHealthOut(
        last_success_at=run.finished_at,
        last_success_day=run.source_day,
        age_hours=round(age_hours, 1),
        stale=age_hours > threshold,
        threshold_hours=threshold,
    )


@router.get("/sources", response_model=SourcesOut)
def list_sources():
    cfg = load_config()
    return SourcesOut(
        source="GDELT 2.0 raw event files",
        base_url=cfg["base_url"],
        lookback_days=int(cfg["lookback_days"]),
    )
