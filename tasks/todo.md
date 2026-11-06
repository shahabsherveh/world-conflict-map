# Tasks: Global Conflict Map

Build order: storage → ingestion → extraction → api → ui. Full plan: `tasks/plan.md`.

## Phase 1: Foundation

### Task 1: Project scaffolding
**Description:** Initialize the Python project: venv, `requirements.txt`, the `app`
package, a minimal FastAPI app with a `/health` endpoint, pytest/ruff/black config, `.gitignore`.

**Acceptance criteria:**
- [x] `pip install -r requirements.txt` succeeds in a fresh venv
- [x] `uvicorn app.main:app` serves `GET /health` → 200
- [x] `pytest` runs and passes a trivial test
- [x] `ruff check .` and `black --check .` pass

**Verification:**
- [x] Tests pass: `pytest`
- [x] Manual check: `GET /health` returned `{"status":"ok"}` (curl not present; verified via urllib)
- [x] Lint: `ruff check . && black --check .`

**Dependencies:** None

**Files likely touched:**
- `requirements.txt`
- `pyproject.toml`
- `app/__init__.py`, `app/main.py`
- `tests/test_health.py`
- `.gitignore`

**Estimated scope:** Medium (3–5 files)

### Task 2: Storage — data model + migrations
**Description:** SQLAlchemy models (`conflict_event`, `conflict`, `edit_log`,
`ingestion_run`), Alembic setup + initial migration, session helper, and core query
helpers (`conflicts_active_in_range`, `events_in_range`) with tests.

**Acceptance criteria:**
- [x] `alembic upgrade head` creates the schema on an empty DB
- [x] `conflicts_active_in_range(start, end)` returns conflicts overlapping the range
- [x] `events_in_range(start, end)` filters correctly
- [x] `conflict_event.source_event_id` is unique; edits append to `edit_log`

**Verification:**
- [x] Tests pass: `pytest tests/test_storage.py`
- [x] Manual check: `alembic upgrade head` from empty DB

**Dependencies:** Task 1

**Files likely touched:**
- `app/db.py`
- `app/models.py`
- `app/migrations/*` (Alembic)
- `tests/test_storage.py`

**Estimated scope:** Medium (3–5 files)

## Checkpoint: Foundation
- [x] App runs and `/health` returns 200
- [x] Schema migrates cleanly from empty DB
- [x] Storage query tests pass

---

## Phase 2: Data pipeline

### Task 3: Ingestion — GDELT fetch + dedupe
**Description:** GDELT client (`httpx`) that downloads the previous day's 15-minute
`.export.CSV.zip` files, a normalizer (positional TSV → raw event dict), and a run
entrypoint that dedupes by `GLOBALEVENTID` and records `ingestion_run`.

**Acceptance criteria:**
- [x] Fetches and normalizes GDELT events from fixture TSV/zip
- [x] Re-running adds no duplicates (idempotent)
- [x] A missing 15-min file (404) is skipped and the run completes

**Verification:**
- [x] Tests pass: `pytest tests/test_ingestion.py`
- [x] Manual check: live download parsed 1,587 events from a real `.export.CSV.zip`

**Dependencies:** Task 2

**Files likely touched:**
- `app/ingest/__init__.py`, `run.py`, `gdelt.py`, `normalizer.py`
- `config/gdelt.yaml`
- `tests/test_ingestion.py`, `tests/fixtures/gdelt/*`

**Estimated scope:** Medium (3–5 files)

### Task 4: Extraction — adapter + filter + intensity
**Description:** `BaseSourceAdapter` + `EventDraft`; GDELT adapter that keeps only
armed-conflict event codes, maps fields, and a pure `derive_intensity` function. Fixture tests.

**Acceptance criteria:**
- [x] `BaseSourceAdapter.to_event_draft(raw) -> EventDraft | None` defined
- [x] A GDELT "battle" record maps to an event with country/lat/lon/event_type/intensity
- [x] A protest/diplomacy record is dropped (returns None)
- [x] `derive_intensity` stays within 1–5 across cases

**Verification:**
- [x] Tests pass: `pytest tests/test_extraction.py`

**Dependencies:** Task 2

**Files likely touched:**
- `app/extract/__init__.py`, `base.py`, `gdelt_adapter.py`, `intensity.py`
- `tests/test_extraction.py`, `tests/fixtures/gdelt/*`

**Estimated scope:** Medium (3–5 files)

### Task 5: Extraction — run pipeline + conflict grouping
**Description:** Wire the pipeline: read raw ingested events, run the adapter, persist
`conflict_event` (provenance `auto`), and group events into `conflict`s via the simple
rule (same country + events within 100 km of the conflict anchor + overlapping time), with
city-name fallback for events lacking coordinates.

**Acceptance criteria:**
- [x] Run processes only new raw events (idempotent)
- [x] Produces `conflict_event`s with `provenance='auto'`
- [x] Grouping helper links events to `conflict`s (v1 simple rule)

**Verification:**
- [x] Tests pass: `pytest tests/test_extraction.py -k run`
- [x] Manual check: live run persisted 68 armed-conflict events + 22 conflicts from a real GDELT file

**Dependencies:** Task 3, Task 4

**Files likely touched:**
- `app/extract/run.py`, `app/extract/grouping.py`
- `tests/test_extraction.py`

**Estimated scope:** Medium (3–5 files)

## Checkpoint: Data pipeline
- [x] Ingest + extract produce `conflict_event`s from fixture GDELT data
- [x] Armed-conflict filtering drops non-conflict records
- [x] Re-runs are idempotent (no duplicate events)

---

## Phase 3: API + UI

### Task 6: API — routes + manual edits
**Description:** FastAPI routes + Pydantic schemas for conflicts/events/sources; manual
PATCH/POST with `edit_log`; serve static UI; wire into `app.main`.

**Acceptance criteria:**
- [x] `GET /api/conflicts?start&end` returns conflicts overlapping the range
- [x] `GET /api/conflicts/{id}` includes its events (event_type, fatalities, source_url)
- [x] `PATCH` writes `edit_log`; `POST` sets `provenance='manual'`
- [x] `/` serves `app/static/index.html`

**Verification:**
- [x] Tests pass: `pytest tests/test_api.py`
- [x] Manual check: live API returned 22 conflicts + detail + sources + static UI

**Dependencies:** Task 2

**Files likely touched:**
- `app/api/__init__.py`, `routes.py`, `schemas.py`
- `app/main.py`
- `tests/test_api.py`

**Estimated scope:** Medium (3–5 files)

### Task 7: UI — map view + time scrub + click-for-news
**Description:** Leaflet map with conflict markers sized/colored by intensity, time-range
controls re-querying `/api/conflicts`, and a click-for-news side panel.

**Acceptance criteria:**
- [x] Loading `/` shows markers for seeded conflicts
- [x] Changing the time range re-renders without a full page reload
- [x] Clicking a marker shows conflict details + events (with source links)

**Verification:**
- [x] JS syntax valid (`node --check`), static files served, API data shape matches UI
- [ ] Visual browser smoke (user): open `http://localhost:8000`, scrub time, click a marker

**Dependencies:** Task 6

**Files likely touched:**
- `app/static/index.html`, `app/static/app.js`, `app/static/style.css`

**Estimated scope:** Medium (3–5 files)

### Task 8: UI — manual edit/create controls
**Description:** Edit/create controls wired to PATCH/POST, with auto-vs-manual provenance shown.

**Acceptance criteria:**
- [x] Editing a conflict field persists and re-renders
- [x] Creating a conflict/event persists with `provenance='manual'`
- [x] Auto vs manual provenance is visible

**Verification:**
- [x] PATCH/POST endpoints tested (`pytest tests/test_api.py`); UI wired to them
- [ ] Visual browser smoke (user): edit a conflict and confirm it persists after reload

**Dependencies:** Task 7

**Files likely touched:**
- `app/static/app.js`, `app/static/index.html`, `app/static/style.css`

**Estimated scope:** Small (1–2 files)

## Checkpoint: API + UI
- [x] Full UI wired end-to-end against seeded data (view, scrub, click, edit)
- [ ] Visual browser smoke by user pending

---

## Phase 4: Polish

### Task 9: End-to-end seed + README + cron
**Description:** Seed script, full ingest→extract→serve walkthrough, README with setup and
daily cron instructions, `.gitignore` finalization.

**Acceptance criteria:**
- [x] Full flow works from a fresh clone following the README
- [x] Daily cron invocation is documented (`scripts/daily.sh` + crontab line)
- [x] README covers setup, run, manual editing, and the future T5/LLM swap

**Verification:**
- [x] Seed verified on a fresh DB (4 conflicts / 12 events); tests pass; pipeline verified live

**Dependencies:** Task 5, Task 8

**Files likely touched:**
- `README.md`
- `scripts/seed.py`, `scripts/daily.sh`
- `.gitignore`

**Estimated scope:** Medium (3–5 files)

## Checkpoint: Complete
- [x] Fresh-clone setup documented and verified
- [x] All acceptance criteria met (75 tests passing)
- [ ] Visual browser smoke test by user (open http://localhost:8000)

---

# Session handoff state

Updated after the code-review pass and context setup.

## Status
All original plan tasks complete. Raw GDELT storage, two-phase processing, audit
backfill, batched zero-shot filtering, and API hardening are applied. The working tree
is clean on `main`; `conflicts.db`, `data/`, and `.venv/` are untracked via `.gitignore`.

## Verification baseline (re-run these first)
```bash
source .venv/bin/activate
pytest            # 75 passed
ruff check .      # clean
black --check .   # clean
alembic current   # b7da7a666155 (head)
curl-free smoke: python -c "from fastapi.testclient import TestClient; ..."
```

The earlier broken-venv caveat no longer applies; `pytest`, `black`, and `alembic` run
normally in this environment.

## Changes since the original plan
- Grouping: keyword overlap → proximity (100 km + time window), anchor cached per conflict.
- Zero-shot filter added (`cross-encoder/nli-deberta-v3-small`, threshold 0.7);
  measured 80% precision / 100% recall vs 32% baseline on a 25-article labelled set
  (after fixing trailing-slash URLs, which previously produced empty slugs).
- UI: per-event markers, headline tooltips/popups, collapsible conflict list,
  per-event Raw data panel, "Open conflict" drill-down.
- Fixes: date-range `end_date IS NULL` leak, UTC date off-by-one, conflicting-city merge,
  N+1 in `/api/conflicts`, input bounds, CWD-dependent paths.
- API hardening: null updates return 422, conflict/event date order is enforced, event
  creation cannot reference a missing conflict, source URLs must be http(s), inverted
  ranges are rejected, event create/update return headlines, and SQLite FKs are enabled.
- UI manual correction: event edit form (including lat/lon and “Pick on map”),
  keyboard-operable conflict buttons, live notice/error region, loading/error/empty
  states, eventless manual conflicts listed, and safe external links.
- HTTP/static smoke passed via `uvicorn --reload` (health, UI, JS/CSS, API). Browser
  checks now run through headless Chrome via the `chrome-devtools` MCP (setup in
  `tests/ui/README.md`); a human visual pass is still worthwhile.
- Removed: no-op `app/ingest/run.py`, dead `currentConflicts`, `persist_new_events`,
  unused `conflict_span`, unused `_headline` param, unsafe auto-repair wiring.
- Added `scripts/fetch_gdelt.py` (resumable raw download with progress bar) and local
  ingestion via `python -m app.extract.run --start … --end … --source-dir data/gdelt`.
- Zero-shot filtering now batches inference and dedupes slugs before classification.
- Added `raw_event` storage (all parsed GDELT rows, JSON payload) before extraction;
  `--raw-only` ingests without processing, and a second pass marks outcomes. Processed
  raw rows are pruned after `raw_retention_days` (default 30).
- `ingestion_run` now records `source_day` and `mode` (`full`/`raw_only`/`backfill`)
  plus raw/persisted counts, exposed via `GET /api/ingestion-runs?limit=`. Seven
  retrospective `backfill` rows reconstruct the original week: 717,672 seen / 13,713 new.
- Backfilled 2026-10-29..2026-11-04 from the local GDELT cache:
  13,713 events / 1,680 conflicts. Previous DB backed up in `/tmp/`.
- Full-week raw store: 717,672 rows / 672 files, then all rows processed. Outcomes:
  672,142 not-armed-conflict, 31,817 filtered out, 13,713 duplicate (the existing
  conflict events). `scripts/process_raw.py` and `scripts/backfill_audit.py` added.

## Remaining work (not started)

### UI / product
- [x] Marker clustering for wide time ranges (`leaflet.markercluster` 1.5.3 from unpkg).
  A 30-day range (13,066 geolocated events) renders as ~37 clusters plus a couple of
  individual dots at world zoom; every event is still in the cluster tree.
- [x] Checked-in headless UI smoke: `tests/ui/map-smoke.mjs` (jsdom + real Leaflet
  against a running server). Covers clustering counts, bounded DOM, cluster clicks, and
  the time scrub. Not wired into pytest/CI (needs npm + a server).
- [x] Real-browser smoke via headless Chrome 149 through the `chrome-devtools` MCP
  (attaches to Chrome on `:9222`; setup documented in `tests/ui/README.md`): 13,066
  events → ~37 cluster bubbles + individual dots at world zoom, labels summing to the
  API count, scrub to 3 days re-renders exactly 4,275, cluster click zooms, event popup +
  sidebar detail render, "Pick on map" fills lat/lon, OSM tiles return 200, and no
  console messages. The earlier grey tile gaps were transient fetches, not an app bug.

### Operations / data
- [ ] Decide raw retention: keep the 30-day default or set `raw_retention_days: 0`; take a
  backup of the current ~1.4 GB DB before any pruning or reset.
- [ ] Label the nine legacy `ingestion_run` rows whose `source_day`/`mode` are null, or
  document them as pre-metadata runs.
- [ ] Mark stale `running` `ingestion_run` rows failed on startup.
- [ ] Record whether the zero-shot filter was available/used in run audit metadata.

### Optional
- [ ] Use `num_sources` from `raw_event` for corroboration or confidence.
- [ ] Backfill more history beyond 2026-10-29..2026-11-04.
- [ ] Fetch real article `<title>` instead of URL-slug headlines (previously declined).
- [ ] Pin dependencies and add CI.
- [ ] Split `app/static/app.js` into smaller modules if it grows further.

## Approval state
No pending approvals. Article-title fetching is still declined; raw payload storage is
implemented in `raw_event`.
