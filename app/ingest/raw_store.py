"""Persist parsed GDELT rows before extraction/filtering."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import Executable

from app.models import RawEvent, utcnow

CHUNK_SIZE = 1000


def _execute_dml(session: Session, stmt: Executable) -> int:
    """Run an INSERT/UPDATE/DELETE and return its affected row count.

    `Session.execute` is typed as returning `Result`, which has no `rowcount`;
    for DML it actually returns a `CursorResult`. The cast is a lie only to the
    type checker — the runtime object genuinely is a CursorResult.
    """
    result = cast(CursorResult, session.execute(stmt))
    return max(0, result.rowcount or 0)


def _parse_event_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value or "", "%Y%m%d").date()
    except ValueError:
        return None


def _payload(raw: dict[str, str]) -> str:
    """Store the non-empty source columns; `_source_file` is a separate column."""
    values = {key: value for key, value in raw.items() if value and not key.startswith("_")}
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def raw_payload(row: RawEvent) -> dict[str, str]:
    """Reconstruct the source dict for the adapter."""
    data = json.loads(row.payload)
    if row.source_file:
        data["_source_file"] = row.source_file
    return data


def store_raw_events(session: Session, raw_events: list[dict[str, str]], source_day: date) -> int:
    """Insert parsed rows, skipping duplicate GLOBALEVENTIDs. Returns inserted count."""
    ingested_at = utcnow()
    rows: list[dict] = []
    for raw in raw_events:
        source_event_id = raw.get("global_event_id")
        if not source_event_id:
            continue
        rows.append(
            {
                "source_event_id": source_event_id,
                "source_day": source_day,
                "event_date": _parse_event_date(raw.get("sql_date")),
                "event_root_code": raw.get("event_root_code") or None,
                "source_file": raw.get("_source_file") or None,
                "payload": _payload(raw),
                "ingested_at": ingested_at,
            }
        )

    inserted = 0
    for start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[start : start + CHUNK_SIZE]
        stmt = (
            sqlite_insert(RawEvent)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=["source_event_id"])
        )
        result = _execute_dml(session, stmt)
        inserted += result
    return inserted


def pending_raw_source_days(session: Session) -> list[date]:
    """Distinct source days that still have unprocessed rows."""
    stmt = (
        select(RawEvent.source_day)
        .where(RawEvent.processed_at.is_(None))
        .distinct()
        .order_by(RawEvent.source_day)
    )
    return list(session.scalars(stmt))


def pending_raw_events(
    session: Session, source_day: date | None = None, limit: int = 2000
) -> list[RawEvent]:
    """Unprocessed rows, oldest first; optionally scoped to one source day."""
    stmt = select(RawEvent).where(RawEvent.processed_at.is_(None))
    if source_day is not None:
        stmt = stmt.where(RawEvent.source_day == source_day)
    stmt = stmt.order_by(RawEvent.id).limit(limit)
    return list(session.scalars(stmt))


def mark_raw_events(
    session: Session,
    source_event_ids: list[str],
    outcome: str,
    processed_at: datetime | None = None,
) -> int:
    """Mark rows processed with their outcome; duplicate ids are ignored."""
    ids = list(
        dict.fromkeys(source_event_id for source_event_id in source_event_ids if source_event_id)
    )
    if not ids:
        return 0
    processed_at = processed_at or utcnow()
    updated = 0
    for start in range(0, len(ids), CHUNK_SIZE):
        chunk = ids[start : start + CHUNK_SIZE]
        updated += _execute_dml(
            session,
            update(RawEvent)
            .where(RawEvent.source_event_id.in_(chunk))
            .values(outcome=outcome, processed_at=processed_at),
        )
    return updated


def prune_raw_events(session: Session, retention_days: int) -> int:
    """Delete processed raw rows older than the retention window.

    Unprocessed rows are never deleted; they may still be needed for retry.
    """
    if retention_days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=retention_days)
    return _execute_dml(
        session,
        delete(RawEvent).where(
            RawEvent.processed_at.is_not(None),
            RawEvent.ingested_at < cutoff,
        ),
    )
