import zipfile
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import make_session_factory
from app.extract import run as run_module
from app.extract.base import BaseSourceAdapter, EventDraft
from app.extract.classifier import (
    CONFLICT_LABEL,
    NOT_CONFLICT_LABEL,
    ZeroShotConflictClassifier,
    slug_to_text,
)
from app.extract.filter import filter_by_zero_shot
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import group_events, regroup_all
from app.extract.intensity import derive_intensity
from app.extract.run import persist_drafts, resolve_target_days, to_drafts
from app.ingest.gdelt import GDELTClient
from app.ingest.normalizer import COLUMNS
from app.models import Base, Conflict, ConflictEvent, EditLog, IngestionRun, RawEvent


def make_session() -> Session:
    """Session configured exactly like the app's (autoflush=False).

    Production never autoflushes, so a fixture with it on can write a pending
    row that the app has not written yet and hide real bugs (see
    test_group_events_keeps_one_conflict_per_theatre_with_autoflush_off).
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


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


def test_confidence_treats_a_missing_count_as_no_corroboration() -> None:
    """One absence, one value: an unparsable count means the same as no count."""
    adapter = GDELTAdapter()
    assert adapter.to_event_draft(make_raw(num_articles="7")).confidence == 0.7
    assert adapter.to_event_draft(make_raw(num_articles="50")).confidence == 1.0
    assert adapter.to_event_draft(make_raw(num_articles="")).confidence == 0.0
    assert adapter.to_event_draft(make_raw(num_articles="n/a")).confidence == 0.0
    raw = make_raw()
    del raw["num_articles"]
    assert adapter.to_event_draft(raw).confidence == 0.0


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


def write_gdelt_zip(directory, stamp: str, **fields: str) -> None:
    row = [""] * len(COLUMNS)
    for key, value in fields.items():
        row[COLUMNS.index(key)] = value
    with zipfile.ZipFile(directory / f"{stamp}.export.CSV.zip", "w") as archive:
        archive.writestr("sample.export.CSV", "\t".join(row) + "\n")


def write_sample_event_zip(directory, day: date, event_id: str) -> None:
    stamp = GDELTClient().fifteen_minute_stamps(day)[0]
    write_gdelt_zip(
        directory,
        stamp,
        global_event_id=event_id,
        sql_date=day.strftime("%Y%m%d"),
        event_root_code="19",
        event_base_code="190",
        action_geo_fullname="Aleppo, Syria",
        action_geo_country_code="SY",
        action_geo_lat="36.2",
        action_geo_long="37.13",
        goldstein_scale="-7.5",
        num_articles="10",
        source_url="http://example.com/missile-strike",
    )


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


def test_group_events_keeps_one_conflict_per_theatre_with_autoflush_off() -> None:
    """Regression: grouping must not degrade to city-name matching mid-run.

    A conflict created in this loop has no committed event yet, and the app
    session never autoflushes, so looking its anchor up in the DB returned None
    and was cached for the rest of the run. Every later event then had to match
    the city name exactly, splitting one theatre into one conflict per city
    (475 instead of 428 for a single day of GDELT data).
    """
    session = make_session()
    session.add_all(
        [
            _ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10),
            _ev("b", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 12),
            _ev("c", "SY", "Manbij, Aleppo, Syria", 36.53, 37.95, 14),
        ]
    )
    session.commit()

    created = group_events(session)
    session.commit()

    assert created == 1, "each new city name became its own conflict"
    conflicts = list(session.scalars(select(Conflict)))
    assert [c.name for c in conflicts] == ["Aleppo, Aleppo, Syria"]
    assert {e.conflict_id for e in session.scalars(select(ConflictEvent))} == {conflicts[0].id}


def test_regroup_all_merges_fragmented_conflicts_without_moving_markers() -> None:
    """Legacy shape: one theatre split into a conflict per city.

    Regrouping must collapse it and leave every coordinate exactly where it was —
    a marker only ever moves because a human moved it.
    """
    session = make_session()
    aleppo = Conflict(name="Aleppo", country="SY", start_date=date(2024, 1, 10))
    azaz = Conflict(name="Azaz", country="SY", start_date=date(2024, 1, 12))
    session.add_all([aleppo, azaz])
    session.flush()
    first, second = (
        _ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10),
        _ev("b", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 12),
    )
    first.conflict_id, second.conflict_id = aleppo.id, azaz.id
    session.add_all([first, second])
    session.flush()  # EditLog needs the event id
    session.add_all(
        [
            EditLog(target_type="conflict", target_id=azaz.id, field="name", new_value="x"),
            EditLog(target_type="event", target_id=second.id, field="lat", new_value="1"),
        ]
    )
    session.commit()

    created = regroup_all(session)
    session.commit()

    assert created == 1
    events = session.scalars(select(ConflictEvent).order_by(ConflictEvent.id)).all()
    assert len({e.conflict_id for e in events}) == 1
    assert [(e.lat, e.lon) for e in events] == [(36.20, 37.13), (36.58, 37.05)]
    # Reassigned ids must not leave audit rows pointing at the wrong conflict.
    assert session.scalars(select(EditLog)).one().target_type == "event"


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


def test_group_events_processes_oldest_event_first() -> None:
    """Regression: insertion order must not split one theatre into two conflicts."""
    session = make_session()
    session.add_all(
        [
            _ev("later", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 15),
            _ev("earlier", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10),
        ]
    )
    session.commit()
    group_events(session)
    session.commit()
    assert len(session.scalars(select(Conflict)).all()) == 1


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
    # autoflush is off (the app's setting), so the new row needs an explicit flush
    # before the UPDATE below can address it.
    session.flush()
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


class BatchStubClassifier:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def classify_many(self, texts: list[str], threshold: float = 0.7):
        self.calls.append(list(texts))
        return [("missile" in text, 1.0) for text in texts]


def test_filter_by_zero_shot_keeps_conflicts_and_no_url() -> None:
    drafts = [
        make_draft("1", "http://x/missile-strike"),
        make_draft("2", "http://x/podcast"),
        make_draft("3", None),
    ]
    kept = filter_by_zero_shot(drafts, StubClassifier())
    assert [d.source_event_id for d in kept] == ["1", "3"]


def test_slug_to_text_handles_trailing_slash() -> None:
    assert slug_to_text("https://x/story/missile-strike-on-kyiv/") == ("missile strike on kyiv")


def test_filter_by_zero_shot_reads_trailing_slash_urls() -> None:
    """Regression: GDELT URLs ending in `/` must not produce an empty slug."""
    drafts = [make_draft("1", "http://x/missile-strike/")]
    kept = filter_by_zero_shot(drafts, StubClassifier())
    assert [d.source_event_id for d in kept] == ["1"]


def test_filter_batches_and_dedupes_slugs() -> None:
    drafts = [
        make_draft("1", "http://x/missile-strike"),
        make_draft("2", "http://y/missile-strike"),
        make_draft("3", "http://x/podcast"),
        make_draft("4", None),
    ]
    classifier = BatchStubClassifier()
    kept = filter_by_zero_shot(drafts, classifier)
    assert len(classifier.calls) == 1
    assert sorted(classifier.calls[0]) == ["missile strike", "podcast"]
    assert [d.source_event_id for d in kept] == ["1", "2", "4"]


class FakePipeline:
    def __call__(self, texts, labels, batch_size=16):
        assert batch_size == 16
        return [{"labels": labels, "scores": [0.9, 0.1]} for _ in texts]


def test_classify_many_batches_and_handles_empty_texts() -> None:
    classifier = ZeroShotConflictClassifier.__new__(ZeroShotConflictClassifier)
    classifier._pipeline = FakePipeline()
    classifier._labels = [CONFLICT_LABEL, NOT_CONFLICT_LABEL]
    assert classifier.classify_many(["strike", ""]) == [(True, 0.9), (False, 0.0)]


def test_resolve_target_days_last_week() -> None:
    assert resolve_target_days(days=3, today=date(2026, 11, 5)) == [
        date(2026, 11, 2),
        date(2026, 11, 3),
        date(2026, 11, 4),
    ]


def test_resolve_target_days_explicit_range() -> None:
    assert resolve_target_days(start=date(2026, 10, 29), end=date(2026, 11, 2)) == [
        date(2026, 10, 29),
        date(2026, 10, 30),
        date(2026, 10, 31),
        date(2026, 11, 1),
        date(2026, 11, 2),
    ]
    with pytest.raises(ValueError):
        resolve_target_days(start=date(2026, 11, 2), end=date(2026, 10, 29))


def test_run_reads_local_files(monkeypatch, tmp_path) -> None:
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: None)

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0
    events = session.scalars(select(ConflictEvent)).all()
    assert len(events) == 1
    assert events[0].source_event_id == "9001"
    assert events[0].provenance == "auto"
    assert len(session.scalars(select(Conflict)).all()) == 1

    runs = session.scalars(select(IngestionRun)).all()
    assert len(runs) == 1
    assert runs[0].status == "success"
    assert runs[0].source_day == day
    assert runs[0].mode == "full"
    assert runs[0].items_seen == 1
    assert runs[0].items_new == 1
    assert runs[0].finished_at is not None

    raw_rows = session.scalars(select(RawEvent)).all()
    assert len(raw_rows) == 1
    assert raw_rows[0].source_day == day
    assert raw_rows[0].outcome == "persisted"
    assert raw_rows[0].processed_at is not None


def test_run_raw_only_stores_without_processing(monkeypatch, tmp_path) -> None:
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: None)

    assert run_module.run(start=day, end=day, source_dir=tmp_path, raw_only=True) == 0
    assert session.scalars(select(ConflictEvent)).all() == []
    raw_row = session.scalar(select(RawEvent))
    assert raw_row is not None
    assert raw_row.processed_at is None
    assert raw_row.outcome is None
    run = session.scalar(select(IngestionRun))
    assert run is not None
    assert run.source_day == day
    assert run.mode == "raw_only"
    assert run.items_seen == 1
    assert run.items_new == 0

    # A second pass processes the pending raw row without re-inserting it.
    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0
    assert len(session.scalars(select(ConflictEvent)).all()) == 1
    raw_row = session.scalar(select(RawEvent))
    assert raw_row is not None
    assert raw_row.outcome == "persisted"


def test_run_records_one_ingestion_run_per_day(monkeypatch, tmp_path) -> None:
    days = [date(2024, 1, 15), date(2024, 1, 16)]
    for index, day in enumerate(days):
        write_sample_event_zip(tmp_path, day, f"90{index}")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: None)

    assert run_module.run(start=days[0], end=days[1], source_dir=tmp_path) == 0
    runs = session.scalars(select(IngestionRun).order_by(IngestionRun.id)).all()
    assert [(run.status, run.items_seen, run.items_new) for run in runs] == [
        ("success", 1, 1),
        ("success", 1, 1),
    ]


def test_run_records_failed_ingestion_run(monkeypatch, tmp_path) -> None:
    day = date(2024, 1, 15)
    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: None)

    def boom(*_args, **_kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(run_module, "read_day_from_dir", boom)
    with pytest.raises(RuntimeError, match="read failed"):
        run_module.run(start=day, end=day, source_dir=tmp_path)

    runs = session.scalars(select(IngestionRun)).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].source_day == day
    assert runs[0].mode == "full"
    assert runs[0].items_seen == 0
    assert runs[0].finished_at is not None
