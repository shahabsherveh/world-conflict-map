# Spec: api — HTTP API + manual edits

## Objective
Serve conflicts/events filtered by time frame, expose conflict detail with underlying
news, and provide manual edit/create endpoints. Serve the UI static files.

## Tech stack
FastAPI + Pydantic. (Conventions: CAPABILITY-MAP.md)

## Endpoints
- `GET /api/conflicts?start=&end=` → conflicts active in range (intensity + location)
- `GET /api/conflicts/{id}` → detail: conflict + its events (event_type, fatalities, source_url)
- `GET /api/events?start=&end=&conflict_id=` → events in range
- `GET /api/events/{id}` → single event detail incl. source_url
- `PATCH /api/events/{id}`, `PATCH /api/conflicts/{id}` → manual edits (logged to edit_log)
- `POST /api/events`, `POST /api/conflicts` → manual creation (`provenance='manual'`)
- `GET /api/sources` → data-source list (transparency)
- Static: `/` → `app/static/index.html`

## Commands
- `uvicorn app.main:app --reload --port 8000`
- `pytest tests/test_api.py`

## Project structure (module)
- `app/api/routes.py`, `app/api/schemas.py`, `app/main.py`

## Code style
Conventions: CAPABILITY-MAP.md. Pydantic response models for every endpoint.

## Testing strategy
- FastAPI TestClient integration tests against a seeded in-memory/temp SQLite DB.
- Test: time-frame filtering, conflict-detail shape, PATCH writes edit_log, POST sets
  `provenance='manual'`.

## Boundaries
- Always: validate inputs (Pydantic); return typed response models.
- Ask first: adding endpoints, changing response schema.
- Never: return raw DB rows; leak secrets in responses.

## Success criteria
- `GET /api/conflicts?start&end` returns exactly the conflicts overlapping the range.
- PATCHing an event updates it and appends an edit_log row.
- The UI (static files) loads from `/`.

## Open questions
- Pagination needed? (Likely not for a personal tool — confirm.)
- CORS not needed if same-origin — confirm.
