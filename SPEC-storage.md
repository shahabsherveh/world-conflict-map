# Spec: storage — data model + persistence

## Objective
Define and persist the entities everything else reads and writes: news items, conflict
events, conflicts (merged), and manual edits — with the timestamps needed to answer
"what was active in [start, end]?".

## Tech stack
SQLite + SQLAlchemy 2.0 ORM + Alembic migrations. (Conventions: CAPABILITY-MAP.md)

## Schema
- `conflict_event`: id, source_event_id (unique, nullable — GDELT `GLOBALEVENTID` for
  dedupe), conflict_id (FK, nullable), place_name, country, lat, lon, event_date,
  event_type, actor_a, actor_b, fatalities (nullable), intensity (1–5), summary,
  source_url, confidence (0–1), provenance ('auto' | 'manual'), created_at, updated_at
- `conflict`: id, name, country, start_date, end_date (nullable), status
  ('active' | 'ended'), created_at, updated_at
- `edit_log`: id, target_type ('event' | 'conflict'), target_id, field, old_value,
  new_value, edited_at
- `ingestion_run`: id, started_at, finished_at, status, items_seen, items_new

## Commands
- `alembic revision --autogenerate -m "<msg>"`
- `alembic upgrade head`
- `pytest tests/test_storage.py`

## Project structure (module)
- `app/db.py` — engine/session
- `app/models.py` — SQLAlchemy models
- `app/migrations/` — Alembic

## Code style
Conventions: CAPABILITY-MAP.md. Models are SQLAlchemy 2.0 declarative with typed columns.

## Testing strategy
- Test every query the API needs: conflicts active in a range, events in a range by
  conflict, events for a conflict ordered by date.
- Test edit_log appends on change; test `source_event_id` uniqueness on `conflict_event`.

## Boundaries
- Always: use migrations (never hand-edit the .db); write tests for new queries.
- Ask first: schema changes (new column/table), adding indexes.
- Never: commit the .db file or secrets.

## Success criteria
- Schema migrates cleanly from scratch (`alembic upgrade head` on an empty db).
- "Conflicts active in [start,end]" returns conflicts whose [start_date, end_date]
  overlaps the range.
- Duplicate `source_event_id` is rejected (unique constraint).
- Manual edits are persisted and logged with old/new values.

## Open questions
- None blocking. Intensity scale settled at 1–5.
