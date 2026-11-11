"""Tests for the Markdown briefing generator (`scripts/briefing.py`)."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import briefing  # noqa: E402  # ty: ignore[import-not-found]  (script, not a module)

from app.db import make_session_factory  # noqa: E402
from app.models import Base, Conflict, ConflictEvent, RawEvent  # noqa: E402


def build_db(tmp_path: Path) -> Path:
    """A small DB with the shapes that matter: counts, no counts, and no link."""
    path = tmp_path / "brief.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    session: Session = make_session_factory(engine)()

    stalwart = Conflict(name="Stalwart War", country="SY", start_date=date(2024, 1, 1))
    quiet = Conflict(name="Quiet War", country="YE", start_date=date(2024, 1, 1))
    session.add_all([stalwart, quiet])
    session.flush()

    def add(conflict, eid, day, url, sources=None, articles=None, place="Aleppo"):
        session.add(
            ConflictEvent(
                conflict_id=conflict.id,
                source_event_id=eid,
                place_name=place,
                country=conflict.country,
                event_date=day,
                event_type="battle",
                intensity=4,
                source_url=url,
            )
        )
        if sources is not None:
            session.add(
                RawEvent(
                    source_event_id=eid,
                    source_day=day,
                    payload=json.dumps({"num_sources": sources, "num_articles": articles}),
                )
            )

    # Four outlets / twelve articles, three days apart.
    add(stalwart, "s1", date(2024, 3, 1), "https://www.alpha-news.example/story/one", 4, 12)
    add(stalwart, "s2", date(2024, 3, 4), "https://beta.example/story/two", 2, 3)
    # One outlet, many articles: lower corroboration, more recent.
    add(quiet, "q1", date(2024, 3, 5), "https://gamma.example/story/three", 1, 9)
    # No raw row at all (manual / pruned): counts unknown, not zero.
    add(quiet, "q2", date(2024, 3, 2), "https://delta.example/story/four")
    # Not renderable: no source link.
    session.add(
        ConflictEvent(
            conflict_id=stalwart.id,
            source_event_id="s3",
            place_name="Aleppo",
            country="SY",
            event_date=date(2024, 3, 3),
            event_type="airstrike",
            intensity=5,
            source_url=None,
        )
    )
    # Outside the window entirely.
    add(stalwart, "s4", date(2024, 5, 1), "https://alpha-news.example/later", 4, 12)
    session.commit()
    session.close()
    engine.dispose()
    return path


def read(path: Path, start: date, end: date, region: str | None = None) -> list[briefing.Conflict]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return briefing.load_conflicts(connection, start, end, region)
    finally:
        connection.close()


def render(
    path: Path,
    start=date(2024, 3, 1),
    end=date(2024, 3, 7),
    region=None,
    top=briefing.DEFAULT_THEATRES,
    per_theatre=briefing.DEFAULT_EVENTS_PER_THEATRE,
) -> str:
    return briefing.render(
        read(path, start, end, region),
        start,
        end,
        region,
        top=top,
        per_theatre=per_theatre,
    )


def test_briefing_links_every_event_and_omits_unlinked_ones(tmp_path) -> None:
    out = render(build_db(tmp_path))
    assert "https://www.alpha-news.example/story/one" in out
    # The airstrike row has no source URL: omitted, not printed bare.
    assert "airstrike" not in out
    for line in out.splitlines():
        if line.startswith("- "):
            assert "](http" in line, line


def test_briefing_is_deterministic(tmp_path) -> None:
    path = build_db(tmp_path)
    assert render(path) == render(path)


def test_briefing_ranks_by_recency_then_corroboration(tmp_path) -> None:
    out = render(build_db(tmp_path))
    # Quiet War has the most recent event (2024-03-05), so it leads; Stalwart War
    # is second despite stronger corroboration.
    assert out.index("## Quiet War") < out.index("## Stalwart War")
    # Within one conflict, newest first.
    stalwart = out[out.index("## Stalwart War") :]
    assert stalwart.index("2024-03-04") < stalwart.index("2024-03-01")


def test_events_outside_the_window_are_excluded(tmp_path) -> None:
    path = build_db(tmp_path)
    out = render(path)
    assert "2024-05-01" not in out
    late = render(path, start=date(2024, 5, 1), end=date(2024, 5, 7))
    assert "Stalwart War" in late
    assert "Quiet War" not in late


def test_corroboration_reports_the_strongest_event_not_a_sum(tmp_path) -> None:
    """Summing per-event counts would double-count one article covering many events."""
    out = render(build_db(tmp_path))
    # Stalwart War: 4/12 and 2/3 — the strongest single event, never 6 outlets.
    assert "4 outlets, 12 articles" in out
    assert "6 outlets" not in out


def test_region_filter_changes_selection_only(tmp_path) -> None:
    path = build_db(tmp_path)
    full = render(path)
    filtered = render(path, region="YE")
    assert "Quiet War" in filtered
    assert "Stalwart War" not in filtered
    # Same document type: title, period and the same per-event line format.
    assert filtered.startswith("# Global Conflict Briefing — YE")
    assert "**Period:** 2024-03-01 to 2024-03-07" in filtered
    ye_lines = [line for line in filtered.splitlines() if line.startswith("- ")]
    full_ye_lines = [
        line
        for line in full.splitlines()
        if line.startswith("- ") and ("gamma.example" in line or "delta.example" in line)
    ]
    assert len(ye_lines) == 2
    assert ye_lines == full_ye_lines


def test_hosts_are_human_readable(tmp_path) -> None:
    out = render(build_db(tmp_path))
    assert "[alpha-news.example]" in out  # no www., no scheme
    assert "](" in out


def test_missing_counts_render_without_a_badge(tmp_path) -> None:
    out = render(build_db(tmp_path))
    quiet_block = out[out.index("## Quiet War") : out.index("## Stalwart War")]
    # The manual event has no stored counts: it must not claim "0 outlets".
    assert "0 outlet" not in quiet_block
    delta_line = next(line for line in quiet_block.splitlines() if "delta.example" in line)
    assert "outlet" not in delta_line and "article" not in delta_line


def test_empty_window_says_so(tmp_path) -> None:
    out = render(build_db(tmp_path), start=date(2030, 1, 1), end=date(2030, 1, 7))
    assert "No armed-conflict events were recorded for this period." in out


def test_no_non_http_links_are_emitted(tmp_path) -> None:
    path = build_db(tmp_path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE conflict_event SET source_url = 'javascript:alert(1)' WHERE source_event_id = 'q1'"
    )
    connection.commit()
    connection.close()

    out = render(path)
    assert "javascript:" not in out
    assert "gamma.example" not in out


def test_duplicate_articles_are_folded_into_one_line(tmp_path) -> None:
    """GDELT emits one row per actor pair, so one story repeated as three lines."""
    path = build_db(tmp_path)
    connection = sqlite3.connect(path)
    for extra in ("q1b", "q1c"):
        connection.execute(
            "INSERT INTO conflict_event (source_event_id, conflict_id, place_name, country,"
            " event_date, event_type, intensity, source_url, provenance, created_at, updated_at)"
            " SELECT ?, conflict_id, place_name, country, event_date, event_type, intensity,"
            " source_url, provenance, created_at, updated_at"
            " FROM conflict_event WHERE source_event_id = 'q1'",
            (extra,),
        )
    connection.commit()
    connection.close()

    out = render(path)
    gamma = [line for line in out.splitlines() if "gamma.example" in line]
    assert len(gamma) == 1
    assert "2 related reports" in gamma[0]
    # The heading counts stored rows (2 originals + 2 folded), not rendered lines.
    quiet_block = out[out.index("## Quiet War") : out.index("## Stalwart War")]
    assert "4 events" in quiet_block


def test_output_is_capped_but_says_what_it_left_out(tmp_path) -> None:
    path = build_db(tmp_path)
    top_only = render(path, top=1)
    assert len([line for line in top_only.splitlines() if line.startswith("## ")]) == 1
    assert "The 1 busiest are below" in top_only
    assert "2 theatres with activity" in top_only

    capped = render(path, top=1, per_theatre=1)
    shown = capped[capped.index("## ") :]
    assert shown.count("\n- ") == 2  # one event line plus the "N more" note
    everything = render(path, top=None, per_theatre=99)
    assert "busiest are below" not in everything


def test_cli_prints_markdown_without_touching_the_database(tmp_path, capsys, monkeypatch) -> None:
    path = build_db(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv("GCM_DATABASE_URL", f"sqlite:///{path}")

    assert briefing.main(["--days", "7", "--end", "2024-03-07"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Global Conflict Briefing")
    assert path.read_bytes() == before  # read-only connection, no writes


def test_cli_rejects_an_inverted_window_and_a_missing_database(tmp_path, capsys) -> None:
    path = build_db(tmp_path)
    assert briefing.main(["--days", "0", "--db", str(path)]) == 2
    assert "at least 1" in capsys.readouterr().err
    assert briefing.main(["--db", str(tmp_path / "absent.db")]) == 2
    assert "no database at" in capsys.readouterr().err


@pytest.mark.parametrize("count", ["3", " 3 ", 3])
def test_count_parsing_tolerates_strings_and_junk(count) -> None:
    assert briefing._count(count) == 3
    assert briefing._count("not a number") == 0
    assert briefing._count(None) == 0
    assert briefing._count("-5") == 0
