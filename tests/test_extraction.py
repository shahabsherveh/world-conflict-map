import zipfile
from datetime import date, timedelta

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
    warn_if_model_cache_is_local,
)
from app.extract.filter import filter_by_zero_shot
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import _same_place, group_events, regroup_all
from app.extract.intensity import derive_intensity
from app.extract.run import persist_drafts, resolve_target_days, to_drafts
from app.ingest.audit import STALE_REASON, settle_stale_runs
from app.ingest.gdelt import GDELTClient
from app.ingest.normalizer import COLUMNS
from app.models import Base, Conflict, ConflictEvent, EditLog, IngestionRun, RawEvent, utcnow


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


def day_runs(session: Session) -> list[IngestionRun]:
    """Per-day fetch/extract rows, excluding the whole-invocation phase rows."""
    return list(
        session.scalars(
            select(IngestionRun)
            .where(IngestionRun.source_day.is_not(None))
            .order_by(IngestionRun.id)
        )
    )


def phase_runs(session: Session) -> list[IngestionRun]:
    return list(
        session.scalars(
            select(IngestionRun).where(IngestionRun.phase.is_not(None)).order_by(IngestionRun.id)
        )
    )


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
        "num_sources": "4",
        "source_url": "http://example.com",
    }
    raw.update(overrides)
    return raw


def adapter_confidence(**overrides: str) -> float:
    """`_confidence` for a raw row, narrowed to float (the adapter always sets it)."""
    draft = GDELTAdapter().to_event_draft(make_raw(**overrides))
    assert isinstance(draft, EventDraft)
    assert draft.confidence is not None
    return draft.confidence


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


def test_confidence_treats_absent_counts_as_no_corroboration() -> None:
    """One absence, one value: an unparsable count means the same as no count."""
    assert adapter_confidence(num_articles="", num_sources="") == 0.0
    assert adapter_confidence(num_articles="n/a", num_sources="x") == 0.0

    raw = make_raw()
    raw.pop("num_articles")
    raw.pop("num_sources")
    draft = GDELTAdapter().to_event_draft(raw)
    assert isinstance(draft, EventDraft)
    assert draft.confidence == 0.0


def test_confidence_rewards_distinct_outlets_over_article_volume() -> None:
    """Ten articles from one outlet is syndication; from four outlets, corroboration."""
    one_outlet = adapter_confidence(num_articles="12", num_sources="1")
    two_outlets = adapter_confidence(num_articles="12", num_sources="2")
    four_outlets = adapter_confidence(num_articles="12", num_sources="4")

    assert four_outlets > one_outlet
    # Guards the blend itself: with the same article count, adding an outlet must
    # move the score. If the `num_sources` term were dropped, these would be equal.
    assert two_outlets > one_outlet


def test_confidence_stays_in_range_for_extreme_counts() -> None:
    assert adapter_confidence(num_articles="9999", num_sources="9999") == 1.0

    # A negative count is not corroboration; it must not push the score below zero.
    assert adapter_confidence(num_articles="-5", num_sources="-5") == 0.0


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


def test_group_events_upgrades_an_unanchored_conflict_once_it_gets_coordinates() -> None:
    """Regression: an anchorless conflict must not stay anchorless for the run.

    The anchor is documented as "the earliest geolocated event", but the cache
    stored None for a conflict whose first event had no coordinates and never
    replaced it. Every later event then had to match the city name exactly, so a
    nearby town in the same theatre became a second conflict.
    """
    session = make_session()
    session.add_all(
        [
            # Oldest event carries no coordinates, so the conflict starts unanchored.
            _ev("a", "SY", "Aleppo, Aleppo, Syria", None, None, 10),
            # Same city: matches by name and gives the conflict its anchor.
            _ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 11),
            # ~46 km away, different city name: must match by distance, not name.
            _ev("c", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 12),
        ]
    )
    session.commit()

    created = group_events(session)
    session.commit()

    assert created == 1, "the anchorless conflict was never upgraded"
    conflicts = list(session.scalars(select(Conflict)))
    assert len(conflicts) == 1
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
    """Single-text only: the filter must fall back when classify_many is absent."""

    def classify(self, text: str, threshold: float = 0.7) -> tuple[bool, float]:
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

    def classify(self, text: str, threshold: float = 0.7) -> tuple[bool, float]:
        raise AssertionError("classify_many should be preferred when available")

    def classify_many(self, texts: list[str], threshold: float = 0.7) -> list[tuple[bool, float]]:
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
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0
    events = session.scalars(select(ConflictEvent)).all()
    assert len(events) == 1
    assert events[0].source_event_id == "9001"
    assert events[0].provenance == "auto"
    assert len(session.scalars(select(Conflict)).all()) == 1

    runs = day_runs(session)
    assert len(runs) == 1
    assert runs[0].status == "success"
    assert runs[0].source_day == day
    assert runs[0].mode == "full"
    assert runs[0].items_seen == 1
    assert runs[0].items_new == 1
    assert runs[0].finished_at is not None

    # Every invocation step is timed too, so a healthy run is fully visible.
    assert [row.phase for row in phase_runs(session)] == [
        "retry_stranded_raw_days",
        "group_events",
        "prune_raw_events",
    ]
    assert all(row.status == "success" for row in phase_runs(session))

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
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=day, end=day, source_dir=tmp_path, raw_only=True) == 0
    assert session.scalars(select(ConflictEvent)).all() == []
    raw_row = session.scalar(select(RawEvent))
    assert raw_row is not None
    assert raw_row.processed_at is None
    assert raw_row.outcome is None
    run = session.scalar(select(IngestionRun).where(IngestionRun.source_day == day))
    assert run is not None
    assert run.source_day == day
    assert run.mode == "raw_only"
    assert run.items_seen == 1
    assert run.items_new == 0
    # Raw-only skips extraction, so grouping never runs; only pruning is timed.
    assert [row.phase for row in phase_runs(session)] == ["prune_raw_events"]

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
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=days[0], end=days[1], source_dir=tmp_path) == 0
    runs = day_runs(session)
    assert [(run.status, run.items_seen, run.items_new) for run in runs] == [
        ("success", 1, 1),
        ("success", 1, 1),
    ]


def test_run_records_failed_ingestion_run(monkeypatch, tmp_path) -> None:
    day = date(2024, 1, 15)
    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    def boom(*_args, **_kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(run_module, "read_day_from_dir", boom)
    with pytest.raises(RuntimeError, match="read failed"):
        run_module.run(start=day, end=day, source_dir=tmp_path)

    runs = day_runs(session)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].source_day == day
    assert runs[0].mode == "full"
    assert runs[0].items_seen == 0
    assert runs[0].finished_at is not None
    # The durable "why": stdout from a cron run is gone by the time anyone asks.
    assert runs[0].error == "RuntimeError: read failed"
    assert runs[0].degraded_reason is None
    # The pre-loop retry committed before the day blew up, and says so.
    assert [(row.phase, row.status) for row in phase_runs(session)] == [
        ("retry_stranded_raw_days", "success")
    ]


def test_describe_exception_truncates_a_huge_message() -> None:
    """httpx errors can embed a whole response body; the row must stay bounded."""
    described = run_module.describe_exception(RuntimeError("x" * 10_000))
    assert described.startswith("RuntimeError: xxx")
    assert len(described) == 2000


def test_run_records_why_the_zero_shot_filter_was_skipped(monkeypatch, tmp_path) -> None:
    """A run without the filter still succeeds, but must say so durably.

    Unfiltered GDELT keeps country-centroid coordinates, so the map fills with
    clustered junk — yet the run used to look identical to a healthy one, and
    the only warning was a stderr line nobody kept.
    """
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    reason = "zero-shot filter unavailable (OSError: model missing); ran unfiltered"
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, reason))

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0

    run = day_runs(session)[0]
    # Degradation is not a failure: the event still lands on the map.
    assert run.status == "success"
    assert run.error is None
    assert run.degraded_reason == reason
    assert len(session.scalars(select(ConflictEvent)).all()) == 1


def test_run_marks_a_healthy_filtered_run_as_not_degraded(monkeypatch, tmp_path) -> None:
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (StubClassifier(), None))

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0

    run = day_runs(session)[0]
    assert run.status == "success"
    assert run.error is None
    assert run.degraded_reason is None


def test_run_records_a_stranded_retry_failure_outside_the_day_rows(monkeypatch, tmp_path) -> None:
    """The pre-loop retry runs before any day row exists, so it needs its own."""
    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    def boom(*_args, **_kwargs):
        raise RuntimeError("retry exploded")

    monkeypatch.setattr(run_module, "retry_stranded_raw_days", boom)
    with pytest.raises(RuntimeError, match="retry exploded"):
        run_module.run(start=date(2024, 1, 15), end=date(2024, 1, 15), source_dir=tmp_path)

    assert day_runs(session) == []
    runs = phase_runs(session)
    assert len(runs) == 1
    run = runs[0]
    assert run.phase == "retry_stranded_raw_days"
    assert run.source_day is None
    assert run.status == "failed"
    assert run.mode == "full"
    # The phase column names the step, so `error` stays a plain reason.
    assert run.error == "RuntimeError: retry exploded"
    assert run.finished_at is not None
    assert run.finished_at >= run.started_at


def test_run_records_a_grouping_failure_outside_the_day_rows(monkeypatch, tmp_path) -> None:
    """Grouping runs once per invocation, after the day rows already committed.

    Without a phase row the run looked clean — every day `success` — even though
    no conflict had been created or updated.
    """
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    def boom(_session):
        raise RuntimeError("grouping exploded")

    monkeypatch.setattr(run_module, "group_events", boom)
    with pytest.raises(RuntimeError, match="grouping exploded"):
        run_module.run(start=day, end=day, source_dir=tmp_path)

    runs = phase_runs(session)
    assert [(run.phase, run.status) for run in runs] == [
        ("retry_stranded_raw_days", "success"),
        ("group_events", "failed"),
    ]
    assert runs[1].mode == "full"
    assert runs[1].error == "RuntimeError: grouping exploded"
    assert day_runs(session)[0].status == "success"


def test_run_reports_a_partly_corrupt_cached_day(monkeypatch, tmp_path) -> None:
    """`--source-dir` skips unreadable zips; the day must not look fully ingested."""
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")
    stamp = run_module.GDELTClient().fifteen_minute_stamps(day)[1]
    (tmp_path / f"{stamp}.export.CSV.zip").write_bytes(b"not a zip")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0
    run = day_runs(session)[0]
    # The readable files still produced events, so the run succeeds — but it
    # says the day's cache was short.
    assert run.status == "success"
    assert run.degraded_reason == "1 corrupt cached export file(s) skipped"


def test_run_times_every_successful_phase(monkeypatch, tmp_path) -> None:
    """A healthy invocation is as visible as a failing one: each step is timed."""
    day = date(2024, 1, 15)
    write_sample_event_zip(tmp_path, day, "9001")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=day, end=day, source_dir=tmp_path) == 0

    phases = {row.phase: row for row in phase_runs(session)}
    assert set(phases) == {"retry_stranded_raw_days", "group_events", "prune_raw_events"}
    for phase, row in phases.items():
        assert row.status == "success", phase
        assert row.source_day is None
        assert row.error is None
        assert row.finished_at is not None
        assert row.finished_at >= row.started_at, phase


def test_run_retries_raw_rows_stranded_by_a_failed_processing_pass(monkeypatch, tmp_path) -> None:
    """Regression: raw rows committed before a crash were never retried.

    `store_raw_events` commits before extraction, and the daily run only targets
    recent days, so rows left pending for day X are never processed again — and
    `prune_raw_events` only deletes processed rows, so they also accumulate
    forever. The next run must pick them up.
    """
    stranded_day = date(2024, 1, 15)
    next_day = date(2024, 1, 16)
    write_sample_event_zip(tmp_path, stranded_day, "9001")
    write_sample_event_zip(tmp_path, next_day, "9002")

    session = make_session()
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    real_process = run_module.process_pending_raw_events
    calls = {"n": 0}

    def flaky_process(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model died mid-run")
        return real_process(*args, **kwargs)

    monkeypatch.setattr(run_module, "process_pending_raw_events", flaky_process)

    with pytest.raises(RuntimeError, match="model died mid-run"):
        run_module.run(start=stranded_day, end=stranded_day, source_dir=tmp_path)

    stranded = session.scalars(select(RawEvent)).one()
    assert stranded.processed_at is None, "raw row should still be pending after the failure"

    # The next day's run does not target the stranded day, yet must process it.
    assert run_module.run(start=next_day, end=next_day, source_dir=tmp_path) == 0

    outcomes = {
        row.source_day: row.outcome
        for row in session.scalars(select(RawEvent).order_by(RawEvent.source_day))
    }
    assert outcomes == {stranded_day: "persisted", next_day: "persisted"}
    events = session.scalars(select(ConflictEvent)).all()
    assert len(events) == 2


def test_filter_keeps_an_event_whose_url_has_no_slug() -> None:
    """Regression: an empty slug classified as "not conflict" and dropped the event.

    A URL like `https://example.com/` carries no evidence either way; the filter
    must not manufacture a rejection out of the missing text.
    """
    drafts = [make_draft("1", "https://example.com/"), make_draft("2", "http://x/podcast")]
    kept = filter_by_zero_shot(drafts, StubClassifier())
    assert [d.source_event_id for d in kept] == ["1"]


def test_group_events_does_not_claim_manual_events() -> None:
    session = make_session()
    manual = _ev("m", "SY", "Aleppo, Syria", 36.20, 37.13, 10)
    manual.provenance = "manual"
    session.add(manual)
    session.flush()

    group_events(session)
    session.flush()

    assert manual.conflict_id is None
    assert session.scalars(select(Conflict)).all() == []


def test_regroup_all_keeps_manual_links_and_their_conflict() -> None:
    """Regrouping rebuilds auto conflicts; a human's placement must survive it."""
    session = make_session()
    curated = Conflict(name="Human conflict", country="SY", start_date=date(2024, 1, 1))
    session.add(curated)
    session.flush()
    manual = _ev("m", "SY", "Aleppo, Syria", 36.20, 37.13, 10)
    manual.provenance = "manual"
    manual.conflict_id = curated.id
    # Different country: grouping cannot legitimately absorb it into the manual
    # conflict, so a rebuild must create its own row.
    auto = _ev("a", "YE", "Aden, Yemen", 12.8, 45.0, 11)
    auto.conflict_id = curated.id
    session.add_all([manual, auto])
    session.flush()
    session.add(EditLog(target_type="conflict", target_id=curated.id, field="name", new_value="x"))
    session.commit()

    created = regroup_all(session)
    session.commit()

    assert created == 1
    # The manual conflict keeps its id, its name and its audit row; without that
    # exemption the rebuild deleted it and the event link came back pointing at
    # an unrelated conflict.
    kept = session.get(Conflict, curated.id)
    assert kept is not None
    assert kept.name == "Human conflict"
    assert manual.conflict_id == curated.id
    assert auto.conflict_id != curated.id
    assert session.scalars(select(EditLog)).one().target_id == curated.id


def test_run_reports_a_download_that_never_succeeded(monkeypatch) -> None:
    """A day short one 15-minute window is a success — but a visible one."""
    day = date(2024, 1, 15)
    stamp = run_module.GDELTClient().fifteen_minute_stamps(day)[1]

    class FlakyClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_day(self, _target, failed_slots=None):
            if failed_slots is not None:
                failed_slots.append(stamp)
            return []

    session = make_session()
    monkeypatch.setattr(run_module, "GDELTClient", FlakyClient)
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    assert run_module.run(start=day, end=day) == 0
    run = day_runs(session)[0]
    assert run.status == "success"
    assert run.degraded_reason == "1 download(s) skipped after retries"


def test_settle_stale_runs_fails_only_abandoned_rows() -> None:
    """A `running` row from a killed process must stop claiming to be live."""
    session = make_session()
    abandoned = IngestionRun(
        status="running",
        source_day=date(2024, 1, 1),
        started_at=utcnow() - timedelta(hours=13),
    )
    live = IngestionRun(status="running", source_day=date(2024, 1, 2))
    done = IngestionRun(
        status="success",
        source_day=date(2024, 1, 3),
        started_at=utcnow() - timedelta(hours=20),
        finished_at=utcnow() - timedelta(hours=19),
    )
    session.add_all([abandoned, live, done])
    session.commit()

    assert settle_stale_runs(session, older_than_hours=12) == 1

    session.refresh(abandoned)
    assert abandoned.status == "failed"
    assert abandoned.error == STALE_REASON
    assert abandoned.finished_at is not None
    live_row = session.get(IngestionRun, live.id)
    done_row = session.get(IngestionRun, done.id)
    assert live_row is not None and live_row.status == "running"
    assert done_row is not None and done_row.status == "success"


def test_run_settles_a_row_left_running_by_a_killed_process(monkeypatch) -> None:
    day = date(2024, 1, 15)
    session = make_session()

    class EmptyClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_day(self, _target, _failed_slots=None):
            return []

    abandoned = IngestionRun(
        status="running",
        source_day=date(2024, 1, 14),
        started_at=utcnow() - timedelta(hours=13),
    )
    session.add(abandoned)
    session.commit()
    abandoned_id = abandoned.id

    monkeypatch.setattr(run_module, "GDELTClient", EmptyClient)
    monkeypatch.setattr(run_module, "get_session", lambda: session)
    monkeypatch.setattr(run_module, "load_classifier", lambda: (None, None))

    run_module.run(start=day, end=day)

    # run() closes its session, so re-fetch through the (reopened) session.
    row = session.get(IngestionRun, abandoned_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == STALE_REASON


def test_group_events_starts_a_new_conflict_after_a_dormant_gap() -> None:
    """Regression: a year-long gap must not resurrect a dormant theatre.

    The time span only ever widened (nothing sets `end_date`), so one stale event
    bridged onto the current window. On the real DB that was 365 days for 63 of
    1,443 conflicts.
    """
    session = make_session()
    conflict = Conflict(
        name="Aleppo, Aleppo, Syria",
        country="SY",
        start_date=date(2024, 1, 1),
        status="active",
    )
    session.add(conflict)
    session.flush()
    session.add(_ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 1))
    session.flush()
    session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "a").update(
        {"conflict_id": conflict.id}
    )
    session.commit()

    # A year later at the same spot: the theatre was dormant, so this is new.
    session.add(_ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 1))
    session.flush()
    session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "b").update(
        {"event_date": date(2025, 1, 2)}
    )
    session.commit()

    group_events(session)
    session.commit()
    assert len(session.scalars(select(Conflict)).all()) == 2


def test_group_events_keeps_a_quiet_week_inside_one_conflict() -> None:
    """The gap cap must not split a theatre that is merely quiet for a few days."""
    session = make_session()
    session.add_all(
        [
            _ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 1),
            _ev("b", "SY", "Aleppo, Aleppo, Syria", 36.21, 37.14, 8),
            _ev("c", "SY", "Aleppo, Aleppo, Syria", 36.22, 37.15, 15),
        ]
    )
    session.commit()

    group_events(session)
    session.commit()
    conflicts = session.scalars(select(Conflict)).all()
    assert len(conflicts) == 1
    assert {e.source_event_id for e in conflicts[0].events} == {"a", "b", "c"}


def test_group_events_gap_is_measured_from_the_last_event_not_the_start() -> None:
    """Events 10 days apart chain indefinitely; the gap is not a total duration.

    A total-duration cap would cut this theatre off at day 14 even though it never
    went quiet, which is the opposite of what the cap is for.
    """
    session = make_session()
    # Add and flush in date order: commit() would assign the ids after the flush,
    # and with autoflush off the tiebreak by id can then put the last event first.
    for day in (1, 11, 21):
        session.add(_ev(f"e{day}", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, day))
        session.flush()
    session.commit()

    group_events(session)
    session.commit()
    conflicts = session.scalars(select(Conflict)).all()
    assert len(conflicts) == 1
    assert {e.source_event_id for e in conflicts[0].events} == {"e1", "e11", "e21"}


def test_group_events_never_lets_an_explicit_end_date_absorb_later_events() -> None:
    """A human ending a conflict outranks the gap window."""
    session = make_session()
    conflict = Conflict(
        name="Aleppo, Aleppo, Syria",
        country="SY",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 10),
        status="ended",
    )
    session.add(conflict)
    session.flush()
    session.add(_ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 5))
    session.add(_ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 12))
    session.commit()

    group_events(session)
    session.commit()
    # "b" is 2 days after "a" -- inside the 14-day gap -- but past the end date.
    hosted = session.scalars(select(ConflictEvent).where(ConflictEvent.conflict_id == conflict.id))
    assert [e.source_event_id for e in hosted] == ["a"]


def test_group_events_links_events_that_have_no_country() -> None:
    """Regression: `country = NULL` matches nothing, so ungeocoded events never merged.

    GDELT leaves `country` empty on some rows. The candidate query compared
    `Conflict.country == event.country`, which for NULL compiles to `country = NULL`
    and matches no row at all, so every such event started its own conflict.

    The events share a place but get different names on purpose: with the same string
    the city-name fallback would link them even with the country query still broken,
    and the test would pass for the wrong reason.
    """
    session = make_session()
    session.add_all(
        [
            ConflictEvent(
                source_event_id="a",
                country=None,
                place_name="Aleppo, Aleppo, Syria",
                lat=36.20,
                lon=37.13,
                event_date=date(2024, 1, 5),
                intensity=3,
            ),
            ConflictEvent(
                source_event_id="b",
                country=None,
                place_name="Aleppo",
                lat=36.21,
                lon=37.14,
                event_date=date(2024, 1, 9),
                intensity=3,
            ),
        ]
    )
    session.commit()

    created = group_events(session)
    session.commit()
    assert created == 1
    conflicts = session.scalars(select(Conflict)).all()
    assert len(conflicts) == 1
    assert {e.source_event_id for e in conflicts[0].events} == {"a", "b"}


def test_group_events_keeps_placeless_events_apart() -> None:
    """Events with no place string share no evidence, so they must not merge.

    The city-name fallback is all such an event has when it has no coordinates, and
    `city_of(None)` is None: two placeless events match nothing, so each keeps its
    own conflict. Deliberately pinned as behaviour, not as an accident -- collapsing
    them would fabricate a theatre out of rows that name no place at all.
    """
    session = make_session()
    session.add_all(
        [
            ConflictEvent(
                source_event_id=eid,
                country=None,
                place_name=None,
                lat=None,
                lon=None,
                event_date=date(2024, 1, 5),
                intensity=3,
            )
            for eid in ("a", "b")
        ]
    )
    session.commit()

    assert group_events(session) == 2
    session.commit()
    conflicts = session.scalars(select(Conflict)).all()
    assert len(conflicts) == 2
    assert {c.name for c in conflicts} == {"Unnamed conflict"}
    # The fallback is what keeps them apart; the country/coordinate checks alone
    # would let the second event join the first on "same country, nothing else".
    hosted = [(c, e) for c in conflicts for e in c.events]
    assert len(hosted) == 2
    assert not any(_same_place(c, e) for c, e in hosted)


def test_group_events_matches_anchorless_conflict_by_stored_places_not_its_name() -> None:
    """Regression: a renamed conflict could never collect another event.

    The no-coordinate fallback compared the event's city with `Conflict.name`,
    documented as "the place string of the conflict's first event". A manual rename
    breaks that (the UI supports renaming), and while the conflict has no anchor there
    is no distance to measure, so the next event in the same theatre opened a second
    conflict instead of joining it.
    """
    session = make_session()
    session.add(_ev("a", "SY", "Aleppo, Aleppo, Syria", None, None, 10))
    session.commit()
    assert group_events(session) == 1

    conflict = session.scalars(select(Conflict)).one()
    conflict.name = "Battle of Aleppo"  # what a PATCH does to the record
    session.commit()

    # Same place, now geolocated: joins by the stored place string, and gives the
    # conflict the anchor it never had.
    session.add(_ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 12))
    session.commit()
    assert group_events(session) == 0
    session.commit()
    assert session.query(Conflict).count() == 1
    assert {e.source_event_id for e in conflict.events} == {"a", "b"}

    # The anchor really is set: a differently named town ~46 km away now joins by
    # distance, which the name comparison could never do.
    session.add(_ev("c", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 14))
    session.commit()
    assert group_events(session) == 0
    session.commit()
    assert session.query(Conflict).count() == 1


def test_group_events_keeps_an_anchorless_conflict_to_its_own_place() -> None:
    """No anchor means no distance to measure, so a different city still splits.

    Mutation guard: the fallback is a place comparison, not "same country, therefore
    same conflict". Dropping it on the anchorless path would reinstate exactly the
    country-level merging that the 100 km rule replaced.
    """
    session = make_session()
    session.add_all(
        [
            _ev("a", "SY", "Homs, Homs, Syria", None, None, 10),
            _ev("b", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 12),
        ]
    )
    session.commit()

    assert group_events(session) == 2
    session.commit()
    assert session.query(Conflict).count() == 2
    assert session.scalars(select(Conflict)).all()[0].name == "Homs, Homs, Syria"


def test_group_events_ungeocoded_event_sees_places_linked_earlier_in_the_run() -> None:
    """The fallback must see a place linked earlier in this same run.

    The session runs with autoflush off, so a just-linked event is not in the database
    when the fallback reads the conflict's place strings. Without updating the cache as
    events are linked, an ungeocoded event in a newly active town opened a second
    conflict even though the event that introduced the town was a few rows earlier.
    """
    session = make_session()
    session.add(_ev("a", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 10))
    session.commit()
    assert group_events(session) == 1

    session.add_all(
        [
            # ~46 km away: joins the anchored conflict by distance and adds "azaz"
            # to its known places.
            _ev("b", "SY", "Azaz, Aleppo, Syria", 36.58, 37.05, 12),
            # Same town, this time ungeocoded: only the cache knows about "azaz".
            _ev("c", "SY", "Azaz, Aleppo, Syria", None, None, 13),
        ]
    )
    session.commit()

    assert group_events(session) == 0
    session.commit()
    assert session.query(Conflict).count() == 1
    conflict = session.scalars(select(Conflict)).one()
    assert {e.source_event_id for e in conflict.events} == {"a", "b", "c"}


def test_group_events_keeps_unlocated_events_apart_from_located_conflicts() -> None:
    """An unlocated event must not join a conflict that has coordinates.

    They share no anchor, and a countryless, placeless event carries no evidence it
    belongs to a particular theatre.
    """
    session = make_session()
    session.add_all(
        [
            ConflictEvent(
                source_event_id="geo",
                country=None,
                place_name=None,
                lat=36.20,
                lon=37.13,
                event_date=date(2024, 1, 5),
                intensity=3,
            ),
            ConflictEvent(
                source_event_id="nog",
                country=None,
                place_name=None,
                lat=None,
                lon=None,
                event_date=date(2024, 1, 6),
                intensity=3,
            ),
        ]
    )
    session.commit()

    group_events(session)
    session.commit()
    conflicts = session.scalars(select(Conflict)).all()
    assert len(conflicts) == 2
    assert {c.country for c in conflicts} == {None}


def test_group_events_picks_the_same_conflict_regardless_of_row_order() -> None:
    """Regression: candidate selection was whatever rowid order returned.

    Two eligible conflicts (same country, both within range) and no ORDER BY meant
    the winner depended on insertion history, so the same data grouped differently
    after a re-import. The oldest theatre must win, consistently.
    """

    def run(reverse: bool) -> set[str]:
        session = make_session()
        older = Conflict(
            name="Aleppo, Aleppo, Syria", country="SY", start_date=date(2024, 1, 1), status="active"
        )
        newer = Conflict(
            name="Aleppo, Aleppo, Syria", country="SY", start_date=date(2024, 1, 5), status="active"
        )
        for conflict in (newer, older) if reverse else (older, newer):
            session.add(conflict)
            session.flush()
        session.add(_ev("anchor-old", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 1))
        session.add(_ev("anchor-new", "SY", "Aleppo, Aleppo, Syria", 36.20, 37.13, 5))
        session.flush()
        session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "anchor-old").update(
            {"conflict_id": older.id}
        )
        session.query(ConflictEvent).filter(ConflictEvent.source_event_id == "anchor-new").update(
            {"conflict_id": newer.id}
        )
        session.add(_ev("fresh", "SY", "Aleppo, Aleppo, Syria", 36.21, 37.14, 7))
        session.commit()

        group_events(session)
        session.commit()
        fresh = session.scalars(
            select(ConflictEvent).where(ConflictEvent.source_event_id == "fresh")
        ).one()
        # The conflict it joined determines the label; older is the earliest.
        winner = session.get(Conflict, fresh.conflict_id)
        assert winner is not None
        return set() if winner.start_date == date(2024, 1, 1) else {"NEWER"}

    assert run(reverse=False) == set()
    assert run(reverse=True) == set()


def test_model_cache_warning_when_hf_home_unset(monkeypatch, capsys) -> None:
    # Running the pipeline by hand must not silently load ~/.cache while the
    # cron/container use /data/hf-cache (GCM_HF_HOME).
    monkeypatch.delenv("HF_HOME", raising=False)
    warn_if_model_cache_is_local()
    assert "HF_HOME is not set" in capsys.readouterr().err


def test_model_cache_warning_silent_when_hf_home_set(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HF_HOME", "/tmp/some-cache")
    warn_if_model_cache_is_local()
    assert capsys.readouterr().err == ""
