import json
from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ingest.raw_store import (
    mark_raw_events,
    pending_raw_events,
    pending_raw_source_days,
    prune_raw_events,
    raw_payload,
    store_raw_events,
)
from app.models import Base, RawEvent


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def make_raw(event_id: str = "1", **overrides: str) -> dict[str, str]:
    raw = {
        "global_event_id": event_id,
        "sql_date": "20240115",
        "event_root_code": "19",
        "source_url": "http://example.com/strike",
        "_source_file": "20240115000000.export.CSV.zip",
    }
    raw.update(overrides)
    return raw


def test_store_raw_events_persists_payload_and_source_metadata() -> None:
    session = make_session()
    inserted = store_raw_events(session, [make_raw()], source_day=date(2024, 1, 16))
    session.commit()

    assert inserted == 1
    row = session.scalar(select(RawEvent))
    assert row is not None
    assert row.source_event_id == "1"
    assert row.source_day == date(2024, 1, 16)
    assert row.event_date == date(2024, 1, 15)
    assert row.event_root_code == "19"
    assert row.source_file == "20240115000000.export.CSV.zip"
    assert row.processed_at is None
    assert row.outcome is None

    payload = json.loads(row.payload)
    assert payload["source_url"] == "http://example.com/strike"
    assert "_source_file" not in payload
    assert raw_payload(row)["_source_file"] == "20240115000000.export.CSV.zip"


def test_store_raw_events_is_idempotent_by_global_event_id() -> None:
    session = make_session()
    raw = [make_raw("1"), make_raw("1"), make_raw("2")]
    assert store_raw_events(session, raw, source_day=date(2024, 1, 16)) == 2
    assert store_raw_events(session, raw, source_day=date(2024, 1, 16)) == 0
    session.commit()
    assert len(session.scalars(select(RawEvent)).all()) == 2


def test_mark_and_pending_raw_events() -> None:
    session = make_session()
    store_raw_events(session, [make_raw("1"), make_raw("2")], source_day=date(2024, 1, 16))
    session.commit()
    assert len(pending_raw_events(session, source_day=date(2024, 1, 16))) == 2
    assert pending_raw_events(session, source_day=date(2024, 1, 17)) == []
    assert pending_raw_source_days(session) == [date(2024, 1, 16)]

    finished = datetime(2024, 1, 16, 12, 0)
    assert mark_raw_events(session, ["1"], "persisted", finished) == 1
    session.commit()

    row = session.scalar(select(RawEvent).where(RawEvent.source_event_id == "1"))
    assert row is not None
    assert row.outcome == "persisted"
    assert row.processed_at == finished
    assert [row.source_event_id for row in pending_raw_events(session)] == ["2"]
    assert pending_raw_source_days(session) == [date(2024, 1, 16)]
    mark_raw_events(session, ["2"], "not_armed_conflict", finished)
    session.commit()
    assert pending_raw_source_days(session) == []


def test_prune_raw_events_keeps_pending_and_recent_rows() -> None:
    session = make_session()
    store_raw_events(
        session,
        [make_raw("old"), make_raw("new"), make_raw("pending")],
        source_day=date(2024, 1, 16),
    )
    session.commit()
    mark_raw_events(session, ["old", "new"], "persisted", datetime(2024, 1, 16, 12, 0))
    old = session.scalar(select(RawEvent).where(RawEvent.source_event_id == "old"))
    old.ingested_at = datetime(2020, 1, 1)
    session.commit()

    assert prune_raw_events(session, 0) == 0
    assert prune_raw_events(session, 30) == 1
    session.commit()
    remaining = {row.source_event_id for row in session.scalars(select(RawEvent))}
    assert remaining == {"new", "pending"}
