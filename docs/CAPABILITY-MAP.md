# Capability Map: Global Conflict Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `storage` | Data model + persistence: conflict events, conflicts, manual edits, ingestion runs, time-series state | — |
| `ingestion` | Daily fetch of structured conflict events from GDELT → normalized, deduped raw rows persisted before extraction | `storage` |
| `extraction` | Event-source adapter: filter to armed conflicts, map fields, derive intensity. **Swappable source boundary (GDELT now, T5/LLM later).** | `ingestion`, `storage` |
| `api` | HTTP API: query conflicts/events by time frame; manual edit/create | `storage` |
| `ui` | Interactive map, time scrub, click-for-news, manual edit | `api` |

Build order: `storage` → `ingestion` → `extraction` → `api` → `ui`

Diagrams of these boundaries, the daily pipeline, and the schema live in
[`diagrams/`](diagrams/README.md) as `.drawio` files.

## Project conventions (shared by all module specs)

### Tech stack
- Python 3.11+, FastAPI (backend + serves UI)
- SQLite via SQLAlchemy 2.0, migrations via Alembic
- GDELT 2.0 raw event files (`.export.CSV.zip`) via `httpx` (structured conflict
  events — already geolocated + classified)
- `transformers` + `torch` (zero-shot armed-conflict filter, CPU)
- Leaflet + OpenStreetMap tiles (frontend, no API key)

### Commands
- Setup: `python -m venv .venv && . .venv/bin/activate`
- Install (CPU torch first; a plain requirements install pulls the multi-GB CUDA build):
  `pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt`
- Gate tools (contributors): `pip install -r requirements-ci.txt` (pinned ruff, ty, pymarkdown)
- Migrate: `alembic upgrade head`
- Model (once): `python scripts/download_model.py` (~570 MB; the pipeline warns and
  skips the filter if it is unavailable)
- Extract (fetch + filter + persist + group): `python -m app.extract.run`
- Serve: `uvicorn app.main:app --reload --port 8000`
- Test: `pytest`
- Lint/format/types: `ruff check . && ruff format --check . && ty check`
- Markdown: `pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks`
- All CI gates: `./scripts/ci-check.sh` (see `ci-cd.md`)

### Project structure
- `app/` — backend package
- `app/static/` — UI (index.html, app.js, style.css)
- `tests/` — pytest
- `tests/fixtures/` — zero-shot evaluation samples
- `config/` — data-source config
- `docs/` — intent and specs

### Code style
- Python: PEP 8, ruff-formatted (`ruff format`), full type hints, ruff lint.
- JS: plain modern ES, no framework, no build step.

### Testing strategy
- pytest for all backend modules.
- `storage`/`api`: unit + integration tests.
- `ingestion`/`extraction`: fixture-based tests (inline GDELT TSV records).
- `ui`: jsdom smoke test (`tests/ui/map-smoke.mjs`) plus manual/browser checks.
