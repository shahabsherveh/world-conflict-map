"""Backfill `ingestion_run` rows from completed raw-event processing.

This is a one-off/recovery helper for data processed before run auditing existed.
It requires every raw row to be processed, and is idempotent per source day.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session
from app.models import IngestionRun, RawEvent, utcnow


def main() -> int:
    session = get_session()
    try:
        pending = session.scalar(
            select(func.count()).select_from(RawEvent).where(RawEvent.processed_at.is_(None))
        )
        if pending:
            print(
                f"error: {pending} raw rows are still pending; run scripts/process_raw.py first",
                file=sys.stderr,
            )
            return 1

        days = list(
            session.scalars(select(RawEvent.source_day).distinct().order_by(RawEvent.source_day))
        )
        created = 0
        for day in days:
            exists = session.scalar(
                select(IngestionRun.id)
                .where(IngestionRun.source_day == day, IngestionRun.mode == "backfill")
                .limit(1)
            )
            if exists:
                print(f"{day}: audit row already exists (id {exists})")
                continue

            items_seen = session.scalar(
                select(func.count()).select_from(RawEvent).where(RawEvent.source_day == day)
            )
            items_new = session.scalar(
                select(func.count())
                .select_from(RawEvent)
                .where(
                    RawEvent.source_day == day,
                    RawEvent.outcome.in_(("persisted", "duplicate")),
                )
            )
            started_at = session.scalar(
                select(func.min(RawEvent.ingested_at)).where(RawEvent.source_day == day)
            )
            finished_at = session.scalar(
                select(func.max(RawEvent.processed_at)).where(RawEvent.source_day == day)
            )
            run = IngestionRun(
                source_day=day,
                mode="backfill",
                status="success",
                started_at=started_at or utcnow(),
                finished_at=finished_at,
                items_seen=items_seen or 0,
                items_new=items_new or 0,
            )
            session.add(run)
            session.commit()
            created += 1
            print(f"{day}: items_seen={run.items_seen}, items_new={run.items_new}")
    finally:
        session.close()

    print(f"Created {created} retrospective audit row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
