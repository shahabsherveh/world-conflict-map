from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.extract.base import BaseSourceAdapter, EventDraft
from app.extract.filter import filter_by_zero_shot
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import group_events
from app.extract.intensity import derive_intensity
from app.extract.run import persist_drafts, to_drafts
from app.models import Base, Conflict, ConflictEvent


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def make_raw(**overrides: str) -> dict[str, str]:
    raw = {
        "global_event_id": "1",
        "sql_date": "20240115",
        "event_root_code": "19",
        "event_base_code": "190",
        "actor1_name": "Army A",
        "actor2_name": "Rebels",
        "action_geo_fullname": "Aleppo, Syria",
        "action_geo_country_code": "SY",
        "action_geo_lat": "36.2",
        "action_geo_long": "37.13",
        "goldstein_scale": "-7.5",
        "num_articles": "20",
        "source_url": "http://example.com",
    }
    raw.update(overrides)
    return raw


def test_derive_intensity() -> None:
    assert derive_intensity("battle", None, None) == 4
    assert derive_intensity("assault", None, None) == 3
    assert derive_intensity("mass_violence", None, None) == 5
    assert derive_intensity("battle", 10, -10.0) == 5  # capped at 5
    assert 1 <= derive_intensity("unknown", None, None) <= 5


def test_adapter_drops_non_conflict() -> None:
    """A protest (root 14) must be dropped by the root-code filter itself.

    The fixture carries a valid `sql_date` on purpose: without it the adapter
    bails on date parsing instead, which would let a filter regression pass.
    """
    adapter = GDELTAdapter()
    protest = {
        "global_event_id": "9",
        "sql_date": "20240115",
        "event_root_code": "14",
        "event_base_code": "140",
        "action_geo_lat": "10.0",
        "action_geo_long": "20.0",
        "source_url": "http://example.com/protest",
    }
    assert adapter.to_event_draft(protest) is None


def test_adapter_rejects_malformed_date() -> None:
    adapter = GDELTAdapter()
    bad = make_raw()
    bad["sql_date"] = "not-a-date"
    assert adapter.to_event_draft(bad) is None


def test_adapter_maps_battle() -> None:
    adapter = GDELTAdapter()
    draft = adapter.to_event_draft(make_raw())
    assert isinstance(draft, EventDraft)
    assert draft.source_event_id == "1"
    assert draft.event_type == "battle"
    assert draft.event_date.isoformat() == "2024-01-15"
    assert draft.lat == 36.2
    assert draft.lon == 37.13
    assert draft.intensity == 5
    assert draft.actor_a == "Army A"
    assert draft.actor_b == "Rebels"
    assert draft.source_url == "http://example.com"
    assert draft.confidence == 1.0
    assert "Army A vs Rebels" in (draft.summary or "")


def test_adapter_is_a_base_source_adapter() -> None:
    assert issubclass(GDELTAdapter, BaseSourceAdapter)


def test_persist_drafts_creates_auto_events() -> None:
    session = make_session()
    drafts = to_drafts([make_raw()], GDELTAdapter())
    count = persist_drafts(session, drafts)
    assert count == 1
    events = session.scalars(select(ConflictEvent)).all()
    assert len(events) == 1
    assert events[0].provenance == "auto"
    assert events[0].source_event_id == "1"


def test_persist_drafts_idempotent() -> None:
    session = make_session()
    drafts = to_drafts([make_raw()], GDELTAdapter())
    assert persist_drafts(session, drafts) == 1
    assert persist_drafts(session, drafts) == 0
    assert len(session.scalars(select(ConflictEvent)).all()) == 1


def _ev(eid, country, place, lat, lon, day):
    return ConflictEvent(
        source_event_id=eid,
        country=country,
        place_name=place,
        lat=lat,
        lon=lon,
        event_date=date(2024, 1, day),
        intensity=4,
    )


def test_group_events_links_nearby_places() -> None:
    """Events a few km apart belong to the same conflict."""
    session = make_session()
    session.add_all(
        [
            _ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10),
            _ev("b", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 12),
        ]
    )
    session.commit()
    created = group_events(session)
    session.commit()
    assert created == 1
    assert len(session.scalars(select(Conflict)).all()) == 1


def test_group_events_splits_distant_places() -> None:
    """Cities far apart in the same country are separate conflicts."""
    session = make_session()
    session.add_all(
        [
            _ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10),
            _ev("b", "SY", "Damascus, Damascus, Syria", 33.51, 36.29, 11),
        ]
    )
    session.commit()
    group_events(session)
    session.commit()
    assert len(session.scalars(select(Conflict)).all()) == 2


def test_group_events_does_not_merge_distant_cities_in_one_country() -> None:
    """Regression: the country word alone must never merge distinct theatres."""
    session = make_session()
    session.add_all(
        [
            _ev("a", "YM", "Jabal Habashi, Taizz, Yemen", 13.474, 43.888, 10),
            _ev("b", "YM", "Sanaa, Sanaa, Yemen", 15.355, 44.207, 11),
            _ev("c", "YM", "Al-Hudaydah, Hudaydah, Yemen", 14.798, 42.955, 12),
        ]
    )
    session.commit()
    group_events(session)
    session.commit()
    assert len(session.scalars(select(Conflict)).all()) == 3


def test_group_events_respects_time_window() -> None:
    session = make_session()
    conflict = Conflict(
        name="Aleppo, Aleppo, Syria",
        country="SY",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    session.add(conflict)
    session.flush()
    session.add(_ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10))
    session.commit()
    session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "a").update(
        {"conflict_id": conflict.id}
    )
    session.commit()

    # Same place, but well after the conflict ended -> new conflict.
    session.add(_ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 15))
    session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "b").update(
        {"event_date": date(2024, 6, 15)}
    )
    session.commit()

    group_events(session)
    session.commit()
    assert len(session.scalars(select(Conflict)).all()) == 2


class StubClassifier:
    def classify(self, text: str, threshold: float = 0.7):
        return ("missile" in text), 1.0


def make_draft(source_event_id: str, source_url: str | None) -> EventDraft:
    return EventDraft(
        source_event_id=source_event_id,
        place_name=None,
        country=None,
        lat=None,
        lon=None,
        event_date=date(2024, 1, 1),
        event_type="battle",
        actor_a=None,
        actor_b=None,
        fatalities=None,
        intensity=4,
        summary=None,
        source_url=source_url,
        confidence=None,
    )


def test_filter_by_zero_shot_keeps_conflicts_and_no_url() -> None:
    drafts = [
        make_draft("1", "http://x/missile-strike"),
        make_draft("2", "http://x/podcast"),
        make_draft("3", None),
    ]
    kept = filter_by_zero_shot(drafts, StubClassifier())
    assert [d.source_event_id for d in kept] == ["1", "3"]
