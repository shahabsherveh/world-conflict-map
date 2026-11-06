"""Group events into conflict entities.

Rule (v2): an unlinked event joins an existing conflict when the country matches,
the event is within `radius_km` of the conflict's anchor point, and the date falls
within the conflict's time span. Otherwise a new conflict is created.

Proximity (not shared keywords) is what defines a theatre of conflict: an earlier
version matched any shared word, which let the country name alone ("yemen") merge
unrelated cities. Markers are still drawn per event, so grouping only affects how
conflicts are presented, never where a marker sits.

Isolated here so it can be replaced with richer clustering later.
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.extract.location import haversine_km
from app.models import Conflict, ConflictEvent, EditLog

DEFAULT_RADIUS_KM = 100.0


def city_of(place_name: str | None) -> str | None:
    """First component of a GDELT place string, normalised for matching."""
    if not place_name:
        return None
    city = place_name.split(",")[0].strip().lower()
    return city or None


def _time_overlaps(event: ConflictEvent, conflict: Conflict) -> bool:
    if event.event_date < conflict.start_date:
        return False
    return not (conflict.end_date is not None and event.event_date > conflict.end_date)


def _anchor(session: Session, conflict: Conflict, cache: dict[int, tuple[float, float] | None]):
    """Coordinates representing a conflict: those of its earliest geolocated event.

    Cached per conflict so grouping does not re-query for every candidate event.
    Conflicts created in the current run must be seeded into the cache by the
    caller: their event is still pending, and the session runs with
    autoflush=False, so a query here would see nothing and cache None.
    """
    if conflict.id in cache:
        return cache[conflict.id]
    stmt = (
        select(ConflictEvent)
        .where(ConflictEvent.conflict_id == conflict.id)
        .order_by(ConflictEvent.event_date, ConflictEvent.id)
    )
    anchor = None
    for event in session.scalars(stmt):
        if event.lat is not None and event.lon is not None:
            anchor = (event.lat, event.lon)
            break
    cache[conflict.id] = anchor
    return anchor


def _matches(
    session: Session,
    event: ConflictEvent,
    conflict: Conflict,
    radius_km: float,
    cache: dict[int, tuple[float, float] | None],
) -> bool:
    if conflict.country != event.country:
        return False
    if not _time_overlaps(event, conflict):
        return False

    if event.lat is None or event.lon is None:
        # No coordinates: fall back to the city name so the event is still grouped.
        return city_of(conflict.name) == city_of(event.place_name)

    anchor = _anchor(session, conflict, cache)
    if anchor is None:
        return city_of(conflict.name) == city_of(event.place_name)
    return haversine_km(event.lat, event.lon, anchor[0], anchor[1]) <= radius_km


def group_events(session: Session, radius_km: float = DEFAULT_RADIUS_KM) -> int:
    """Link unlinked events to conflicts. Returns the number of conflicts created."""
    # Process oldest first so a conflict is anchored on its earliest event;
    # otherwise event insertion order can split one theatre into two conflicts.
    unlinked = list(
        session.scalars(
            select(ConflictEvent)
            .where(ConflictEvent.conflict_id.is_(None))
            .order_by(ConflictEvent.event_date, ConflictEvent.id)
        )
    )
    created = 0
    anchors: dict[int, tuple[float, float] | None] = {}
    for event in unlinked:
        match = next(
            (
                conflict
                for conflict in session.scalars(
                    select(Conflict).where(Conflict.country == event.country)
                )
                if _matches(session, event, conflict, radius_km, anchors)
            ),
            None,
        )
        if match is None:
            match = Conflict(
                name=event.place_name or event.country or "Unnamed conflict",
                country=event.country,
                start_date=event.event_date,
                status="active",
            )
            session.add(match)
            session.flush()
            created += 1
            # The conflict's own event is still pending (`conflict_id` is assigned
            # below), so _anchor() cannot see it: seed the cache instead. Without
            # this every later event of this conflict falls through to the
            # city-name fallback below, fragmenting one theatre into per-city
            # conflicts for the rest of the run.
            anchors[match.id] = (
                (event.lat, event.lon) if event.lat is not None and event.lon is not None else None
            )
        event.conflict_id = match.id
    return created


def regroup_all(session: Session, radius_km: float = DEFAULT_RADIUS_KM) -> int:
    """Unlink every event and rebuild the conflicts from scratch.

    Repairs data produced by an older grouping rule; it is not part of the daily
    run, which only ever links new events. Conflict rows are derived again, so
    conflict-level curation (a renamed conflict, an ended status) is lost — check
    for it before applying. Event rows are never rewritten apart from their
    `conflict_id`, so no marker moves. Conflict ids restart from 1, so the audit
    rows that point at them are dropped rather than left dangling.

    Returns the number of conflicts created.
    """
    session.execute(update(ConflictEvent).values(conflict_id=None))
    session.flush()
    session.execute(delete(Conflict))
    session.execute(delete(EditLog).where(EditLog.target_type == "conflict"))
    session.flush()
    return group_events(session, radius_km)
