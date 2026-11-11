"""Render a dated Markdown briefing from the stored data.

Usage:
    python scripts/briefing.py --days 7
    python scripts/briefing.py --days 7 --region SY > briefing.md
    python scripts/briefing.py --end 2026-11-04 --days 7

Stdlib only, no network, and read-only: the briefing is generated from the same
SQLite file the map serves, so a subscriber sees exactly what the map shows. This
is the demand-test engine for Phase 5 (tasks/todo.md Task 12): publish it, count
engagement, decide from the numbers instead of from opinion.

Ranking is by corroboration, not by the stored `confidence` score: the score is
ordinal and its scale has never been validated, so it cannot honestly order
"how well established" an event is across outlets. Articles and outlets are
counts a reader can check against the source list.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "conflicts.db"

# An upstream link is only printed if it is http(s): these go out to subscribers.
SAFE_SCHEMES = frozenset({"http", "https"})

# Per-conflict caps. An uncapped issue is ~13k lines on the real data (1,436
# theatres), which is both unreadable and past the "one page" rule in the plan.
DEFAULT_THEATRES = 10
DEFAULT_EVENTS_PER_THEATRE = 3


@dataclass(frozen=True)
class Event:
    id: int
    conflict_id: int | None
    event_date: date
    place_name: str | None
    country: str | None
    event_type: str | None
    intensity: int
    source_url: str | None
    sources: int | None
    articles: int | None
    # GDELT rows sharing this event's article. One story becomes several events
    # (each actor pair gets its own row), so printing each one repeats the same
    # sentence and link under the same heading.
    duplicate_count: int = 1


@dataclass(frozen=True)
class Conflict:
    id: int
    name: str
    country: str | None
    events: tuple[Event, ...]
    # Stored rows, including the ones folded into `events` as duplicate reports.
    # Kept separately so the heading still says how much activity there was.
    stored_event_count: int = 0


def _count(value: object) -> int:
    """Parse one stored count; absent, unparsable or negative means zero."""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    if not isinstance(value, (str, bytes)):
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme.lower() not in SAFE_SCHEMES:
        return None
    return url


def _display_name(url: str) -> str:
    """Outlet label for a link: the host without `www.`, as a reader would say it."""
    host = urlparse(url).netloc.lower()
    return re.sub(r"^www\.", "", host) or "source"


def load_conflicts(
    connection: sqlite3.Connection,
    start: date,
    end: date,
    region: str | None = None,
) -> list[Conflict]:
    """Conflicts with at least one event in [start, end], in a deterministic order.

    Ordering is `(earliest event in range, conflict id)`; the caller re-ranks by
    corroboration. Ties never depend on SQLite's row order, so the same database
    always renders the same document — a subscriber diffing two issues should only
    see real changes.
    """
    params: list[object] = [start.isoformat(), end.isoformat()]
    region_clause = ""
    if region:
        region_clause = " AND (c.country = ? COLLATE NOCASE OR e.country = ? COLLATE NOCASE)"
        params.extend([region, region])

    rows = connection.execute(
        f"""
        SELECT e.id, e.conflict_id, e.event_date, e.place_name, e.country,
               e.event_type, e.intensity, e.source_url,
               json_extract(r.payload, '$.num_sources') AS sources,
               json_extract(r.payload, '$.num_articles') AS articles
        FROM conflict_event e
        JOIN conflict c ON c.id = e.conflict_id
        LEFT JOIN raw_event r ON r.source_event_id = e.source_event_id
        WHERE e.event_date >= ? AND e.event_date <= ?{region_clause}
        ORDER BY e.event_date, e.id
        """,
        params,
    ).fetchall()

    grouped: dict[int, list[Event]] = {}
    for row in rows:
        event = Event(
            id=row[0],
            conflict_id=row[1],
            event_date=date.fromisoformat(row[2]),
            place_name=row[3],
            country=row[4],
            event_type=row[5],
            intensity=_count(row[6]),
            source_url=_safe_url(row[7]),
            sources=None if row[8] is None else _count(row[8]),
            articles=None if row[9] is None else _count(row[9]),
        )
        conflict_id = row[1]
        prior = {seen.source_url for seen in grouped.setdefault(conflict_id, [])}
        if event.source_url in prior:
            # Same article, another actor pair: fold it into the event already
            # listed and keep counting, instead of repeating the line.
            for index, existing in enumerate(grouped[conflict_id]):
                if existing.source_url == event.source_url:
                    grouped[conflict_id][index] = replace(
                        existing, duplicate_count=existing.duplicate_count + 1
                    )
                    break
            continue
        grouped[conflict_id].append(event)

    names: dict[int, tuple[str, str | None]] = {}
    if grouped:
        ids = ",".join("?" * len(grouped))
        names = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                f"SELECT id, name, country FROM conflict WHERE id IN ({ids})",
                list(grouped),
            )
        }

    stored: dict[int, int] = {}
    for row in rows:
        stored[row[1]] = stored.get(row[1], 0) + 1
    conflicts = [
        Conflict(
            id=cid,
            name=names[cid][0],
            country=names[cid][1],
            events=tuple(events),
            stored_event_count=stored[cid],
        )
        for cid, events in grouped.items()
    ]
    conflicts.sort(key=lambda c: (c.events[0].event_date, c.id))
    return conflicts


def _corroboration(events: Iterable[Event]) -> tuple[int, int]:
    """`(outlets, articles)` across an event list, summing over its distinct articles.

    Each event carries its own article's counts, so summing them double-counts an
    article that covers several events. Taking the strongest single event is the
    conservative reading — it never claims more corroboration than one event has.
    """
    best = (0, 0)
    for event in events:
        if event.sources is None or event.articles is None:
            continue
        if (event.sources, event.articles) > best:
            best = (event.sources, event.articles)
    return best


def _rank_key(conflict: Conflict) -> tuple[int, int, int, int, int]:
    sources, articles = _corroboration(conflict.events)
    latest = max(event.event_date for event in conflict.events)
    # Newest activity first, then corroboration, then size; id last so the order
    # is total and reproducible.
    return (-latest.toordinal(), -sources, -articles, -len(conflict.events), conflict.id)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _event_line(event: Event) -> str | None:
    """One bullet, or None when the event has no source to link.

    An unlinked claim is exactly what a briefing must not carry, so an event
    without a safe upstream URL is omitted rather than printed bare.
    """
    if not event.source_url:
        return None
    where = event.place_name or event.country or "location unknown"
    kind = event.event_type or "incident"
    corroboration = ""
    if event.sources is not None and event.articles is not None:
        corroboration = (
            f" ({_plural(event.sources, 'outlet')}, {_plural(event.articles, 'article')})"
        )
    folded = (
        f", {_plural(event.duplicate_count - 1, 'related report')}"
        if event.duplicate_count > 1
        else ""
    )
    return (
        f"- {event.event_date.isoformat()} — **{where}** — {kind}{corroboration}{folded}. "
        f"[{_display_name(event.source_url)}]({event.source_url})"
    )


def render(
    conflicts: Sequence[Conflict],
    start: date,
    end: date,
    region: str | None = None,
    issue: int | None = None,
    top: int | None = DEFAULT_THEATRES,
    per_theatre: int = DEFAULT_EVENTS_PER_THEATRE,
) -> str:
    """Render the briefing Markdown. Pure: same input, same bytes."""
    title = "# Global Conflict Briefing"
    if region:
        title += f" — {region}"
    if issue is not None:
        title += f" (issue {issue})"

    lines = [
        title,
        "",
        f"**Period:** {start.isoformat()} to {end.isoformat()}  ",
        "**Source:** GDELT 2.0 event feed, grouped into theatres; every line links its article.",
        "",
    ]

    if not conflicts:
        lines.append("No armed-conflict events were recorded for this period.")
        return "\n".join(lines) + "\n"

    ranked = sorted(conflicts, key=_rank_key)
    shown = ranked if top is None else ranked[:top]
    totals = sum(c.stored_event_count for c in conflicts)
    headline = (
        f"{_plural(len(conflicts), 'theatre')} with activity, {_plural(totals, 'event')} in total. "
    )
    if len(shown) < len(conflicts):
        headline += f"The {len(shown)} busiest are below; run with `--top 0` for all. "
    lines += [
        headline + "Ranked by recency, then by how many independent outlets carried it.",
        "",
    ]

    for conflict in shown:
        sources, articles = _corroboration(conflict.events)
        latest = max(event.event_date for event in conflict.events)
        lines.append(f"## {conflict.name}")
        lines.append("")
        meta = [
            f"{_plural(conflict.stored_event_count, 'event')}",
            f"latest {latest.isoformat()}",
        ]
        if sources and articles:
            meta.append(
                f"best-corroborated: {_plural(sources, 'outlet')}, {_plural(articles, 'article')}"
            )
        lines += [" · ".join(meta), ""]

        linked = [
            event
            for event in sorted(conflict.events, key=lambda e: (e.event_date, e.id), reverse=True)
            if event.source_url
        ]
        for event in linked[:per_theatre]:
            lines.append(_event_line(event) or "")
        if not linked:
            lines.append("- No event in this period carries a source link.")
        elif len(linked) > per_theatre:
            more = conflict.stored_event_count - per_theatre
            lines.append(f"- …{more} more in this theatre, not shown.")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a Markdown briefing from the conflict database.",
    )
    parser.add_argument("--days", type=int, default=7, help="window length in days (default 7)")
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="last day of the window (default: today)",
    )
    parser.add_argument("--region", default=None, help="filter to one country code or name")
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_THEATRES,
        help="how many theatres to list, 0 for all (default 10)",
    )
    parser.add_argument(
        "--events-per-theatre",
        type=int,
        default=DEFAULT_EVENTS_PER_THEATRE,
        help="recent sourced events to show per theatre (default 3)",
    )
    parser.add_argument("--issue", type=int, default=None, help="issue number for the title")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="database file (default: $GCM_DATABASE_URL or ./conflicts.db)",
    )
    return parser.parse_args(argv)


def database_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    import os

    url = os.environ.get("GCM_DATABASE_URL")
    if url and url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :])
    if url:
        raise SystemExit(f"error: --db is required for a non-SQLite database ({url})")
    return DEFAULT_DB


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.days < 1:
        print("error: --days must be at least 1", file=sys.stderr)
        return 2
    path = database_path(args.db)
    if not path.exists():
        print(f"error: no database at {path}", file=sys.stderr)
        return 2

    end = args.end or date.today()
    start = end - timedelta(days=args.days - 1)
    # Read-only: a briefing run must never touch the pipeline's database.
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conflicts = load_conflicts(connection, start, end, args.region)
    finally:
        connection.close()
    top = None if args.top <= 0 else args.top
    sys.stdout.write(
        render(
            conflicts,
            start,
            end,
            args.region,
            args.issue,
            top=top,
            per_theatre=max(1, args.events_per_theatre),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
