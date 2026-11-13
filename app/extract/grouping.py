"""Group events into conflict entities.

Rule (v3): an unlinked event joins an existing conflict when the country matches,
the event is within `radius_km` of the conflict's anchor point, and its date falls
within the conflict's time span — from the start date until `gap_days` after the
conflict's most recent event. Otherwise a new conflict is created.

Proximity (not shared keywords) is what defines a theatre of conflict: an earlier
version matched any shared word, which let the country name alone ("yemen") merge
unrelated cities. Markers are still drawn per event, so grouping only affects how
conflicts are presented, never where a marker sits.

Isolated here so it can be replaced with richer clustering later.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.extract.location import haversine_km
from app.models import Conflict, ConflictEvent, EditLog

DEFAULT_RADIUS_KM = 100.0

# How long a theatre keeps collecting events after its last one. Without a cap the
# span only ever widens (nothing sets `end_date`), so a single event bridged two
# dates a year apart into one conflict: on the real DB that was 365 days for 63 of
# 1,443 conflicts, every one of them a stale 2025-10-29 row resurrecting a live
# 2026 theatre. Fourteen days keeps a quiet week inside one conflict while a
# genuinely dormant theatre starts a new one.
DEFAULT_GAP_DAYS = 14

# Name the grouping rule invents when an event has no place string to borrow.
UNNAMED_CONFLICT = "Unnamed conflict"


def city_of(place_name: str | None) -> str | None:
    """First component of a GDELT place string, normalised for matching."""
    if not place_name:
        return None
    city = place_name.split(",")[0].strip().lower()
    return city or None


def _time_overlaps(
    event: ConflictEvent, conflict: Conflict, last_date: date, gap_days: int
) -> bool:
    """Does the event fall inside the conflict's window?

    `last_date` is the conflict's latest event date (its own start date when it has
    no dated events). An explicit `end_date` still wins: a human ending a conflict
    means it, and no gap extends it.
    """
    if event.event_date < conflict.start_date:
        return False
    if conflict.end_date is not None:
        return event.event_date <= conflict.end_date
    return (event.event_date - last_date).days <= gap_days


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
    gap_days: int,
    last_dates: dict[int, date],
    places: dict[int, set[str]],
) -> bool:
    # `is not` distinguishes two absent countries from a pair that matches. Written
    # as `!=` this was always false for NULL: `NULL = NULL` is NULL, never true, so
    # the ~495 ungeocoded events could never join each other and each became its
    # own single-event conflict.
    if event.country is None or conflict.country is None:
        if event.country is not conflict.country:
            return False
    elif conflict.country != event.country:
        return False
    # .get, not []: a conflict can exist with no linked events yet (seeded, or
    # holding only manual events), and its own start date is then the window.
    last_date = last_dates.get(conflict.id, conflict.start_date)
    if not _time_overlaps(event, conflict, last_date, gap_days):
        return False

    if event.lat is None or event.lon is None:
        # No coordinates: fall back to the city name so the event is still grouped.
        return _place_matches(session, conflict, event, places)

    anchor = _anchor(session, conflict, cache)
    if anchor is None:
        return _place_matches(session, conflict, event, places)
    return haversine_km(event.lat, event.lon, anchor[0], anchor[1]) <= radius_km


def _same_place(conflict: Conflict, event: ConflictEvent) -> bool:
    """Name-only fallback, for a conflict that has no stored place strings.

    Used for a seeded or manually created conflict, which has no events to name a
    place: its free-text name is then the only evidence there is. A conflict built
    from events goes through `_place_matches` instead, because `Conflict.name` is
    editable and must not steer grouping once a human has renamed it.
    """
    return city_of(conflict.name) == city_of(event.place_name)


def _stored_cities(session: Session, conflict: Conflict, cache: dict[int, set[str]]) -> set[str]:
    """Cities named by the conflict's stored events, cached per conflict.

    Cached because the fallback runs for every candidate of every ungeocoded event,
    and a conflict's place strings do not change during one grouping pass.
    """
    if conflict.id in cache:
        return cache[conflict.id]
    cities: set[str] = set()
    stmt = select(ConflictEvent.place_name).where(ConflictEvent.conflict_id == conflict.id)
    for (place_name,) in session.execute(stmt):
        city = city_of(place_name)
        if city is not None:
            cities.add(city)
    cache[conflict.id] = cities
    return cities


def _place_matches(
    session: Session, conflict: Conflict, event: ConflictEvent, cache: dict[int, set[str]]
) -> bool:
    """Fallback for a pair where at least one side has no coordinates.

    Compares the event's city with the cities the conflict's *events* name, not with
    `Conflict.name`. The name was the first event's place string, which held until a
    human renamed the conflict (the UI supports that) or the first event was
    placeless: while the conflict has no anchor there is no distance to measure, so a
    renamed conflict could never collect another event and split into a second
    conflict for the same theatre.

    A conflict with no stored place strings is seeded or manual, and falls back to
    its name. An event with no place string yields None and matches nothing, which is
    what keeps the unlocated tail (495 single-event conflicts on the real DB) from
    collapsing into one.
    """
    city = city_of(event.place_name)
    if city is None:
        return False
    stored = _stored_cities(session, conflict, cache)
    if stored:
        return city in stored
    return _same_place(conflict, event)


def _country_matches(country: str | None):
    """Candidate conflicts for an event's country, NULL included.

    `Conflict.country == None` would already compile to `IS NULL` (SQLAlchemy rewrites
    it), so this is not a bug fix. `is_(None)` states the intent where a reader would
    otherwise have to know that rewrite to trust the comparison.
    """
    if country is None:
        return Conflict.country.is_(None)
    return Conflict.country == country


def _last_event_dates(session: Session) -> dict[int, date]:
    """Latest event date per conflict, for the gap window.

    Conflicts created during this run are absent here; `group_events` falls back to
    their start date and updates the map as it links events.
    """
    stmt = select(ConflictEvent.conflict_id, ConflictEvent.event_date).where(
        ConflictEvent.conflict_id.is_not(None)
    )
    last: dict[int, date] = {}
    for conflict_id, event_date in session.execute(stmt):
        if conflict_id is None:  # excluded by the WHERE, stated for the type checker
            continue
        if event_date > last.get(conflict_id, event_date):
            last[conflict_id] = event_date
    return last


def group_events(
    session: Session,
    radius_km: float = DEFAULT_RADIUS_KM,
    gap_days: int = DEFAULT_GAP_DAYS,
) -> int:
    """Link unlinked events to conflicts. Returns the number of conflicts created.

    Manual events are never claimed. Their `conflict_id` is whatever a human set
    (possibly nothing, meaning "unassigned"), and grouping exists to guess links
    for machine-extracted events, not to overrule that choice.
    """
    # Process oldest first so a conflict is anchored on its earliest event;
    # otherwise event insertion order can split one theatre into two conflicts.
    unlinked = list(
        session.scalars(
            select(ConflictEvent)
            .where(
                ConflictEvent.conflict_id.is_(None),
                ConflictEvent.provenance != "manual",
            )
            .order_by(ConflictEvent.event_date, ConflictEvent.id)
        )
    )
    created = 0
    anchors: dict[int, tuple[float, float] | None] = {}
    last_dates = _last_event_dates(session)
    places: dict[int, set[str]] = {}
    for event in unlinked:
        match = next(
            (
                conflict
                for conflict in session.scalars(
                    select(Conflict)
                    .where(_country_matches(event.country))
                    # Without an ORDER BY the first match was whatever rowid order
                    # returned, so which of two eligible conflicts absorbed an event
                    # depended on insertion history. Oldest first is stable and puts
                    # a new event with the theatre that has been running longest.
                    .order_by(Conflict.start_date, Conflict.id)
                )
                if _matches(
                    session, event, conflict, radius_km, anchors, gap_days, last_dates, places
                )
            ),
            None,
        )
        if match is None:
            match = Conflict(
                name=event.place_name or event.country or UNNAMED_CONFLICT,
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
            # The new event is pending too (autoflush off), so its place is only in
            # the cache if it is seeded here; `_stored_cities` cannot read it back.
            places[match.id] = {city} if (city := city_of(event.place_name)) else set()
        event.conflict_id = match.id
        # Keep the place evidence in step with what was just linked, for the same
        # reason as above: a later ungeocoded event in this run must see it.
        city = city_of(event.place_name)
        if city is not None:
            if match.id not in places:
                _stored_cities(session, match, places)
            places[match.id].add(city)
        # Keep the window in step with what was just added, so a later event in this
        # same loop measures its gap from this one rather than from an older query.
        if event.event_date > last_dates.get(match.id, match.start_date):
            last_dates[match.id] = event.event_date
        # A conflict whose earlier events had no coordinates starts anchorless, so
        # `_matches` fell back to comparing city names. Now that this event gives it
        # coordinates, record them: leaving None cached keeps the fallback for the
        # rest of the run and splits one theatre into a conflict per city.
        if anchors.get(match.id) is None and event.lat is not None and event.lon is not None:
            anchors[match.id] = (event.lat, event.lon)
    return created


def regroup_all(
    session: Session,
    radius_km: float = DEFAULT_RADIUS_KM,
    gap_days: int = DEFAULT_GAP_DAYS,
) -> int:
    """Unlink every event and rebuild the conflicts from scratch.

    Repairs data produced by an older grouping rule; it is not part of the daily
    run, which only ever links new events. Conflict rows are derived again, so
    conflict-level curation (a renamed conflict, an ended status) is lost — check
    for it before applying. Event rows are never rewritten apart from their
    `conflict_id`, so no marker moves.

    Manual events are exempt: they keep their `conflict_id`, and the conflict row
    that holds them survives so that link stays valid. Re-linking them silently
    was worse than useless — conflict ids restart from 1, so a hand-placed event
    would have come back attached to an unrelated conflict.

    Returns the number of conflicts created.
    """
    manual_conflicts = select(Conflict.id).where(
        Conflict.events.any(ConflictEvent.provenance == "manual")
    )
    session.execute(
        update(ConflictEvent).where(ConflictEvent.provenance != "manual").values(conflict_id=None)
    )
    session.flush()
    session.execute(delete(Conflict).where(~Conflict.id.in_(manual_conflicts)))
    session.execute(
        delete(EditLog).where(
            EditLog.target_type == "conflict",
            EditLog.target_id.not_in(manual_conflicts),
        )
    )
    session.flush()
    return group_events(session, radius_km, gap_days)
