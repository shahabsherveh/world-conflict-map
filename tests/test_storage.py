from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Conflict, ConflictEvent, EditLog
from app.queries import conflicts_active_in_range, events_in_range


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_conflicts_active_in_range() -> None:
    session = make_session()
    conflict_a = Conflict(
        name="War A", country="X", start_date=date(2024, 1, 1), end_date=date(2024, 6, 1)
    )
    conflict_b = Conflict(name="War B", country="Y", start_date=date(2024, 3, 1))  # ongoing
    conflict_c = Conflict(
        name="War C", country="Z", start_date=date(2023, 1, 1), end_date=date(2023, 12, 31)
    )
    session.add_all([conflict_a, conflict_b, conflict_c])
    session.flush()
    # War A active in Feb, War B active in April, War C only in 2023.
    session.add_all(
        [
            ConflictEvent(conflict_id=conflict_a.id, event_date=date(2024, 2, 5), country="X"),
            ConflictEvent(conflict_id=conflict_b.id, event_date=date(2024, 4, 5), country="Y"),
            ConflictEvent(conflict_id=conflict_c.id, event_date=date(2023, 6, 5), country="Z"),
        ]
    )
    session.commit()

    active = conflicts_active_in_range(session, date(2024, 2, 1), date(2024, 4, 1))
    assert {c.name for c in active} == {"War A"}

    spring = conflicts_active_in_range(session, date(2024, 3, 1), date(2024, 5, 1))
    assert {c.name for c in spring} == {"War B"}

    # A quiet ongoing conflict must NOT match a future range with no events.
    future = conflicts_active_in_range(session, date(2030, 1, 1), date(2030, 2, 1))
    assert future == []


def test_events_in_range() -> None:
    session = make_session()
    conflict = Conflict(name="War A", country="X", start_date=date(2024, 1, 1))
    session.add(conflict)
    session.flush()
    session.add_all(
        [
            ConflictEvent(conflict_id=conflict.id, event_date=date(2024, 1, 10), country="X"),
            ConflictEvent(conflict_id=conflict.id, event_date=date(2024, 2, 10), country="X"),
            ConflictEvent(conflict_id=conflict.id, event_date=date(2024, 3, 10), country="X"),
        ]
    )
    session.commit()

    events = events_in_range(session, date(2024, 2, 1), date(2024, 2, 28))
    assert [e.event_date for e in events] == [date(2024, 2, 10)]


def test_source_event_id_unique() -> None:
    session = make_session()
    session.add(ConflictEvent(source_event_id="EVT1", event_date=date(2024, 1, 1), country="X"))
    session.commit()
    session.add(ConflictEvent(source_event_id="EVT1", event_date=date(2024, 1, 2), country="X"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_edit_log_appends() -> None:
    session = make_session()
    session.add(
        EditLog(target_type="event", target_id=1, field="intensity", old_value="2", new_value="3")
    )
    session.commit()
    assert session.query(EditLog).count() == 1
