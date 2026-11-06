from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import get_db
from app.db import make_session_factory
from app.main import app
from app.models import Base, Conflict, ConflictEvent, EditLog, IngestionRun


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # Same settings as the app (autoflush off); see tests/test_extraction.make_session.
    session = make_session_factory(engine)()

    def override():
        yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c, session
    app.dependency_overrides.clear()
    session.close()


def seed(session: Session) -> Conflict:
    conflict = Conflict(name="War A", country="SY", start_date=date(2024, 1, 1))
    session.add(conflict)
    session.flush()
    session.add_all(
        [
            ConflictEvent(
                conflict_id=conflict.id,
                event_date=date(2024, 1, 10),
                country="SY",
                lat=1.0,
                lon=2.0,
                intensity=4,
                source_url="http://x/a",
            ),
            ConflictEvent(
                conflict_id=conflict.id,
                event_date=date(2024, 2, 10),
                country="SY",
                lat=1.0,
                lon=2.0,
                intensity=5,
                source_url="http://x/b",
            ),
        ]
    )
    session.commit()
    return conflict


def test_list_conflicts_filters_by_range(client) -> None:
    c, session = client
    seed(session)
    resp = c.get("/api/conflicts", params={"start": "2024-02-01", "end": "2024-02-28"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "War A"
    assert data[0]["event_count"] == 1
    assert data[0]["intensity"] == 5
    assert "headline" in data[0]


def test_list_conflicts_includes_eventless_manual_conflict(client) -> None:
    c, session = client
    session.add(Conflict(name="Manual only", country="SY", start_date=date(2024, 1, 1)))
    session.commit()

    resp = c.get("/api/conflicts", params={"start": "2024-01-01", "end": "2024-12-31"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "Manual only"
    assert resp.json()[0]["event_count"] == 0


def test_conflict_detail_includes_events(client) -> None:
    c, session = client
    conflict = seed(session)
    resp = c.get(f"/api/conflicts/{conflict.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 2
    assert data["events"][0]["source_url"] in ("http://x/a", "http://x/b")


def test_patch_conflict_logs_edit(client) -> None:
    c, session = client
    conflict = seed(session)
    resp = c.patch(f"/api/conflicts/{conflict.id}", json={"name": "Renamed War"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed War"
    logs = session.query(EditLog).all()
    assert len(logs) == 1
    assert logs[0].target_type == "conflict"
    assert logs[0].field == "name"
    assert logs[0].old_value == "War A"
    assert logs[0].new_value == "Renamed War"


def test_post_event_sets_manual_provenance(client) -> None:
    c, _session = client
    resp = c.post("/api/events", json={"event_date": "2024-03-01", "country": "UA", "intensity": 3})
    assert resp.status_code == 201
    assert resp.json()["provenance"] == "manual"


def test_post_conflict_creates(client) -> None:
    c, _session = client
    resp = c.post(
        "/api/conflicts", json={"name": "War B", "country": "UA", "start_date": "2024-05-01"}
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "War B"
    assert resp.json()["status"] == "active"


def test_post_event_with_conflict(client) -> None:
    c, session = client
    conflict = seed(session)
    resp = c.post(
        "/api/events",
        json={"event_date": "2024-04-01", "conflict_id": conflict.id, "intensity": 2},
    )
    assert resp.status_code == 201
    assert resp.json()["conflict_id"] == conflict.id
    assert resp.json()["provenance"] == "manual"


def test_patch_rejects_null_required_fields(client) -> None:
    c, session = client
    conflict = seed(session)
    event = session.query(ConflictEvent).first()

    for payload in ({"name": None}, {"start_date": None}, {"status": None}):
        assert c.patch(f"/api/conflicts/{conflict.id}", json=payload).status_code == 422
    for payload in ({"event_date": None}, {"intensity": None}):
        assert c.patch(f"/api/events/{event.id}", json=payload).status_code == 422


def test_conflict_date_order_is_validated(client) -> None:
    c, session = client
    conflict = seed(session)

    assert (
        c.post(
            "/api/conflicts",
            json={"name": "Backwards", "start_date": "2024-06-01", "end_date": "2024-01-01"},
        ).status_code
        == 422
    )
    assert (
        c.patch(f"/api/conflicts/{conflict.id}", json={"end_date": "2023-12-31"}).status_code == 422
    )
    assert (
        c.patch(f"/api/conflicts/{conflict.id}", json={"end_date": "2024-03-01"}).status_code == 200
    )
    assert (
        c.patch(f"/api/conflicts/{conflict.id}", json={"start_date": "2024-04-01"}).status_code
        == 422
    )


def test_post_event_rejects_missing_conflict(client) -> None:
    c, session = client
    resp = c.post("/api/events", json={"event_date": "2024-01-01", "conflict_id": 9999})
    assert resp.status_code == 404
    assert session.query(ConflictEvent).count() == 0


def test_event_source_url_must_be_http(client) -> None:
    c, session = client
    seed(session)
    event = session.query(ConflictEvent).first()

    assert (
        c.post(
            "/api/events",
            json={"event_date": "2024-01-01", "source_url": "javascript:alert(1)"},
        ).status_code
        == 422
    )
    assert (
        c.patch(f"/api/events/{event.id}", json={"source_url": "data:text/html,x"}).status_code
        == 422
    )
    assert (
        c.patch(
            f"/api/events/{event.id}",
            json={"source_url": "https://example.com/drone-attack"},
        ).status_code
        == 200
    )


def test_post_event_includes_headline(client) -> None:
    c, _session = client
    resp = c.post(
        "/api/events",
        json={
            "event_date": "2024-01-01",
            "source_url": "https://example.com/missile-strike",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["headline"] == "missile strike"


def test_patch_event_includes_headline(client) -> None:
    c, session = client
    seed(session)
    event = session.query(ConflictEvent).first()
    resp = c.patch(
        f"/api/events/{event.id}",
        json={"source_url": "https://example.com/drone-attack"},
    )
    assert resp.status_code == 200
    assert resp.json()["headline"] == "drone attack"


def test_headline_falls_back_to_summary_for_numeric_article_ids(client) -> None:
    """Regression: a bare article id says nothing in a list, so use the summary."""
    c, _session = client
    created = c.post(
        "/api/events",
        json={
            "event_date": "2024-01-01",
            "source_url": "https://example.com/2087359569",
            "summary": "Shelling reported north of the city",
        },
    ).json()
    assert created["headline"] == "Shelling reported north of the city"


def test_conflict_summary_headline_comes_from_newest_event_in_range(client) -> None:
    """The header must quote the latest incident, not the first one listed."""
    c, session = client
    seed(session)  # events on 2024-01-10 (slug "a") and 2024-02-10 (slug "b")
    data = c.get("/api/conflicts", params={"start": "2024-01-01", "end": "2024-12-31"}).json()
    assert data[0]["headline"] == "b"


def test_conflict_detail_prefers_an_in_span_headline_over_a_later_one(client) -> None:
    """A manual event outside the conflict's own span may supply the headline only
    when the span itself has none — an event inside it wins."""
    c, session = client
    conflict = Conflict(
        name="War A",
        country="SY",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        status="ended",
    )
    session.add(conflict)
    session.flush()
    session.add_all(
        [
            ConflictEvent(
                conflict_id=conflict.id,
                event_date=date(2024, 1, 10),
                country="SY",
                source_url="https://example.com/inside-the-span",
            ),
            ConflictEvent(
                conflict_id=conflict.id,
                event_date=date(2024, 6, 15),
                country="SY",
                source_url="https://example.com/after-the-span",
            ),
        ]
    )
    session.commit()

    data = c.get(f"/api/conflicts/{conflict.id}").json()
    assert [e["event_date"] for e in data["events"]] == ["2024-01-10"]
    assert data["headline"] == "inside the span"


def test_list_endpoints_reject_inverted_range(client) -> None:
    c, _session = client
    params = {"start": "2024-02-01", "end": "2024-01-01"}
    assert c.get("/api/conflicts", params=params).status_code == 422
    assert c.get("/api/events", params=params).status_code == 422


def test_patch_conflict_rejects_empty_name(client) -> None:
    c, session = client
    conflict = seed(session)
    assert c.patch(f"/api/conflicts/{conflict.id}", json={"name": ""}).status_code == 422


def test_conflict_not_found(client) -> None:
    c, _session = client
    assert c.get("/api/conflicts/9999").status_code == 404


def test_event_not_found(client) -> None:
    c, _session = client
    assert c.get("/api/events/9999").status_code == 404


def test_sources_endpoint(client) -> None:
    c, _session = client
    resp = c.get("/api/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert "gdelt" in body["source"].lower()
    assert body["base_url"].startswith("http")


def test_ingestion_runs_returns_newest_first_and_honors_limit(client) -> None:
    c, session = client
    for index in range(3):
        session.add(
            IngestionRun(
                source_day=date(2024, 1, 1 + index),
                mode="full",
                started_at=datetime(2024, 1, 1 + index),
                finished_at=datetime(2024, 1, 1 + index, 0, 1),
                status="success",
                items_seen=100 + index,
                items_new=index,
            )
        )
    session.commit()

    resp = c.get("/api/ingestion-runs", params={"limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert [run["items_new"] for run in data] == [2, 1]
    assert data[0]["status"] == "success"
    assert data[0]["source_day"] == "2024-01-03"
    assert data[0]["mode"] == "full"
    assert data[0]["finished_at"] is not None


def test_ingestion_runs_empty(client) -> None:
    c, _session = client
    resp = c.get("/api/ingestion-runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_ingestion_runs_limit_bounds(client) -> None:
    c, _session = client
    assert c.get("/api/ingestion-runs", params={"limit": 0}).status_code == 422
    assert c.get("/api/ingestion-runs", params={"limit": 101}).status_code == 422


def test_event_headline_derived_from_source_url(client) -> None:
    c, session = client
    seed(session)
    events = c.get("/api/events", params={"start": "2024-01-01", "end": "2024-12-31"}).json()
    # seeded source_urls are "http://x/a" / "http://x/b" -> slug "a"/"b"
    assert all(e["headline"] for e in events)


def test_event_create_rejects_out_of_range_values(client) -> None:
    c, _session = client
    assert (
        c.post("/api/events", json={"event_date": "2024-03-01", "intensity": 99}).status_code == 422
    )
    assert c.post("/api/events", json={"event_date": "2024-03-01", "lat": 999}).status_code == 422
    assert (
        c.post("/api/conflicts", json={"name": "X", "start_date": "2024-01-01", "status": "bogus"})
    ).status_code == 422


def test_event_text_fields_are_bounded_like_their_columns(client) -> None:
    """Regression: a 3 KB place name was stored whole and rendered in a list row."""
    c, session = client
    seed(session)
    event = session.query(ConflictEvent).first()

    for payload in (
        {"place_name": "x" * 256},
        {"country": "y" * 121},
        {"event_type": "z" * 81},
        {"actor_a": "a" * 256},
        {"summary": "s" * 5001},
        {"source_url": "https://example.com/" + "u" * 1024},
    ):
        assert (
            c.post("/api/events", json={"event_date": "2024-03-01", **payload}).status_code == 422
        ), payload
        assert c.patch(f"/api/events/{event.id}", json=payload).status_code == 422, payload

    assert (
        c.post(
            "/api/conflicts", json={"name": "X", "start_date": "2024-01-01", "country": "c" * 121}
        ).status_code
        == 422
    )
    assert (
        c.patch(f"/api/conflicts/{event.conflict_id}", json={"country": "c" * 121}).status_code
        == 422
    )


def test_conflict_list_query_count_is_bounded(client) -> None:
    """Regression: listing conflicts must not issue one query per conflict."""
    from sqlalchemy import event as sa_event

    c, session = client
    for _ in range(8):
        seed(session)
    bind = session.get_bind()
    count = {"n": 0}

    def before(*_args, **_kwargs):
        count["n"] += 1

    sa_event.listen(bind, "before_cursor_execute", before)
    try:
        resp = c.get("/api/conflicts", params={"start": "2024-01-01", "end": "2024-12-31"})
    finally:
        sa_event.remove(bind, "before_cursor_execute", before)
    assert resp.status_code == 200
    assert count["n"] <= 5, f"N+1 regression: {count['n']} queries for {len(resp.json())} conflicts"
