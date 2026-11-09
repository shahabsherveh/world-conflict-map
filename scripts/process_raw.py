"""Process pending `raw_event` rows without fetching or ingesting.

This is the second half of the two-phase pipeline:
    ingest raw rows (--raw-only) -> process raw rows (this script)

It does not create `ingestion_run` rows; those describe ingestion. Outcomes are
recorded on each `raw_event` row instead.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.db import get_session
from app.extract.gdelt_adapter import GDELTAdapter
from app.extract.grouping import group_events
from app.extract.run import load_classifier, process_pending_raw_events, resolve_target_days
from app.ingest.raw_store import pending_raw_source_days
from app.models import RawEvent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="process the last N complete days")
    parser.add_argument("--start", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (YYYY-MM-DD)")
    parser.add_argument("--batch-size", type=int, default=2000, help="rows per batch")
    parser.add_argument("--dry-run", action="store_true", help="print pending counts only")
    args = parser.parse_args()

    if args.days is not None and (args.start or args.end):
        parser.error("use either --days or --start/--end, not both")
    if (args.start is None) != (args.end is None):
        parser.error("provide both --start and --end")
    if args.days is not None and args.days < 1:
        parser.error("--days must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    session = get_session()
    try:
        if args.days is not None or args.start is not None:
            try:
                targets = resolve_target_days(days=args.days, start=args.start, end=args.end)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        else:
            targets = pending_raw_source_days(session)

        if not targets:
            print("No pending raw rows.")
            return 0

        if args.dry_run:
            for day in targets:
                count = session.scalar(
                    select(func.count())
                    .select_from(RawEvent)
                    .where(
                        RawEvent.source_day == day,
                        RawEvent.processed_at.is_(None),
                    )
                )
                print(f"{day}: {count} pending")
            return 0

        cfg = load_config()
        # This script deliberately writes no `ingestion_run` row (see module
        # docstring), so a degradation is only announced on stderr here.
        classifier, _degraded_reason = load_classifier()
        adapter = GDELTAdapter()
        total_processed = 0
        total_new = 0
        for day in targets:
            processed, new_count = process_pending_raw_events(
                session,
                adapter,
                classifier,
                float(cfg["zero_shot_threshold"]),
                day,
                batch_size=args.batch_size,
            )
            total_processed += processed
            total_new += new_count
            print(f"{day}: {processed} processed, {new_count} new events", flush=True)

        created = group_events(session)
        session.commit()
    finally:
        session.close()

    print(
        f"Processed {total_processed} raw rows; persisted {total_new} new events; "
        f"{created} conflicts created"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
