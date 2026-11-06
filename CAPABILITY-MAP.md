# Capability Map: Global Conflict Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `storage` | Data model + persistence: conflict events, conflicts, manual edits, ingestion runs, time-series state | — |
| `ingestion` | Daily fetch of structured conflict events from GDELT → normalized, deduped raw rows persisted before extraction | `storage` |
| `extraction` | Event-source adapter: filter to armed conflicts, map fields, derive intensity. **Swappable source boundary (GDELT now, T5/LLM later).** | `ingestion`, `storage` |
| `api` | HTTP API: query conflicts/events by time frame; manual edit/create | `storage` |
| `ui` | Interactive map, time scrub, click-for-news, manual edit | `api` |

Build order: `storage` → `ingestion` → `extraction` → `api` → `ui`

## Project conventions (shared by all module specs)

### Tech stack
- Python 3.11+, FastAPI (backend + serves UI)
- SQLite via SQLAlchemy 2.0, migrations via Alembic
- GDELT 2.0 raw event files (`.export.CSV.zip`) via `httpx` (structured conflict events — already geolocated + classified)
- Leaflet + OpenStreetMap tiles (frontend, no API key)

### Commands
- Setup: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- Migrate: `alembic upgrade head`
- Extract (fetch + filter + persist): `python -m app.extract.run`
- Serve: `uvicorn app.main:app --reload --port 8000`
- Test: `pytest`
- Lint: `ruff check . && black --check .`

### Project structure
- `app/` — backend package
- `app/static/` — UI (index.html, app.js, style.css)
- `tests/` — pytest
- `tests/fixtures/` — sample GDELT responses
- `config/` — data-source config
- `docs/` — intent and specs

### Code style
- Python: PEP 8, black-formatted, full type hints, ruff lint.
- JS: plain modern ES, no framework, no build step.

### Testing strategy
- pytest for all backend modules.
- `storage`/`api`: unit + integration tests.
- `ingestion`/`extraction`: fixture-based tests (sample GDELT JSON records).
- `ui`: manual smoke test; automated browser tests optional later.
