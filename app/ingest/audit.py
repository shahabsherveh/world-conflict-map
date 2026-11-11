"""Settle ingestion runs orphaned by a killed process."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import execute_dml
from app.models import IngestionRun, utcnow

# Longer than a daily run (cron is 24 h apart) and shorter than the interval, so an
# orphan is settled before the next invocation starts. A multi-hour backfill has to
# raise this, or a later daily run would declare it dead while it is still working.
STALE_AFTER_HOURS = 12.0

STALE_REASON = "settled as failed: the run never finished (process died or was killed)"


def settle_stale_runs(session: Session, older_than_hours: float = STALE_AFTER_HOURS) -> int:
    """Mark `running` rows older than the cutoff as failed.

    A killed pipeline leaves its row `running` on purpose — it shows where the
    process died — but nothing ever settled it, so `/api/ingestion-runs` showed an
    eternal "running" row and every later run appended more of them.

    Called at the start of a pipeline invocation, not from the web app: the
    pipeline is the only writer, and a web process settling rows on startup could
    declare a live backfill dead.
    """
    cutoff = utcnow() - timedelta(hours=older_than_hours)
    settled = execute_dml(
        session,
        update(IngestionRun)
        .where(IngestionRun.status == "running", IngestionRun.started_at < cutoff)
        .values(status="failed", error=STALE_REASON, finished_at=utcnow()),
    )
    # Commit here: the caller is invoking this precisely to make the state visible,
    # and a caller that dies before its own commit would otherwise lose the fix.
    session.commit()
    return settled
