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
- [ ] Visual browser smoke test by user (open <http://localhost:8000>)

---

## Phase 5: Monetization readiness

Two strands: make the data defensible enough to sell, then test demand with a free global
briefing before spending on infrastructure or a foreign entity. Rationale and kill criteria:
the go/no-go memo in Task 13.

Constraint for this phase: no schema migration. `confidence` and `provenance` already exist;
a real multi-article provenance table would need one and is deferred (AGENTS.md "Ask first").

### Task 10: Corroboration scoring from `num_sources` + `num_articles`
**Description:** `_confidence` currently uses `num_articles` alone (articles/10, capped at
1.0). `num_sources` — distinct outlets — is retained in `raw_event.payload` but never read,
so twelve articles from one outlet score the same as twelve from twelve outlets. Blend both
into one corroboration score, keeping the documented invariant that absent or unparsable
counts give exactly 0.0.

**Acceptance criteria:**
- [x] 12 articles / 4 outlets scores strictly higher than 12 articles / 1 outlet
- [x] Missing or unparsable counts still return 0.0 — the existing invariant holds
- [x] Extreme input (e.g. 9999/9999) stays within 0.0–1.0
- [x] A mutation that drops `num_sources` from the blend makes a test fail
- [x] Field is documented as corroboration; it must not be described as verification

**Verification:**
- [x] Tests pass: `pytest tests/test_extraction.py -k confidence` (3 passed)
- [x] Mutation check: dropping the `num_sources` term failed 2 tests; restored, 3 pass
- [x] Full gates: `./scripts/ci-check.sh` — 104 tests, ty and markdown clean
- [x] Calibrated on 717k stored rows: articles p50=4/p90=10/p99=15, sources=1 for ~90%

**Dependencies:** None

**Files likely touched:**
- `app/extract/gdelt_adapter.py`
- `tests/test_extraction.py`
- `docs/SPEC-extraction.md`

**Estimated scope:** Small (1–2 files)

### Task 11: Corroboration exposed in API + UI badge
**Description:** A reader cannot currently tell whether an event rests on one article or
forty. Surface the outlet and article counts on the event response, read in one batched
query keyed by `source_event_id` (never per-row — see gotcha #5), plus a small trust badge in
the event popup.

**Acceptance criteria:**
- [x] Event response includes `sources` and `articles`, parsed from `raw_event.payload`
- [x] Any "well corroborated" label is a counts predicate (`sources >= 2 and articles >= 3`),
  never a `confidence` threshold — the score is ordinal and its scale is unvalidated
- [x] Manual events (`provenance="manual"`) return null counts, not 0 and not an error
- [x] Detail-endpoint query count stays bounded (extend the existing query-count test)
- [x] UI shows e.g. "4 outlets" and every interpolated value passes through `esc()`
- [x] `?v=N` bumped for `app.js`

**Verification:**
- [x] Tests pass: `pytest tests/test_api.py -k "corroboration or query_count"` (4 passed)
- [x] Mutation checks: per-event lookup → 12 queries for 12 events (failed); unknown→0 (failed);
  dropping the outlet term made the 1-outlet case "well corroborated" (failed); all restored
- [x] UI: `cd tests/ui && node map-smoke.mjs` against a freshly seeded DB — all checks passed,
  including the new popup-badge assertions (counts shown, strong variant only when flagged,
  no badge for unknown counts, values escaped)
- [ ] Manual browser check: no Chrome in this container (gotcha #12: the `/tmp` install was
  deleted on rebuild); popup *content* is covered by jsdom, popup *positioning* is not
- [x] Lists and conflict detail carry the counts too, not just the single-event endpoint
- [x] Full gates: `./scripts/ci-check.sh` — 109 tests, ty/ruff/markdown/shellcheck clean

**Dependencies:** Task 10

**Files likely touched:**
- `app/queries.py`
- `app/api/schemas.py`, `app/api/routes.py`
- `app/static/app.js`, `app/static/index.html`
- `scripts/seed.py`, `tests/test_api.py`, `tests/ui/map-smoke.mjs`
- `docs/SPEC-api.md`, `docs/SPEC-ui.md`, `docs/SPEC-extraction.md`

**Estimated scope:** Medium (3–5 files)

### Task 12: Briefing generator (`scripts/briefing.py`)
**Description:** Render a dated Markdown digest from the DB: conflicts ranked by recent
activity, events since the previous issue, corroboration counts, one source link each. Stdlib
only, no network, no writes to the DB. This is the demand-test engine and doubles as the
case-study artefact.

**Acceptance criteria:**
- [ ] `python scripts/briefing.py --days 7` prints Markdown to stdout; no network calls
- [ ] Every event line carries its source URL; an event without one is omitted, not shown
  unlinked
- [ ] Output is deterministic for a fixed DB (same input, same order and content)
- [ ] Runs against `scripts/seed.py` data with no model file present (degraded mode)
- [ ] `--region <country>` filters without changing the format

**Verification:**
- [ ] Tests pass: `pytest tests/test_briefing.py`
- [ ] Manual check: run on a seeded DB and read the output as a subscriber would
- [ ] Markdown gate: `pymarkdown scan -r docs tasks`

**Dependencies:** Task 11

**Files likely touched:**
- `scripts/briefing.py`
- `tests/test_briefing.py`
- `README.md`

**Estimated scope:** Medium (3–4 files)

### Task 13: Demand test (8 issues) + public case study
**Description:** Publish eight weekly global briefings, count engagement after each, then
decide with numbers instead of opinion. In parallel, write the case study the "sell the
skill" strand needs.

**Acceptance criteria:**
- [ ] Eight issues published, each at most one page, every claim linked
- [ ] Per-issue count recorded: replies, reshares, audience growth
- [ ] Written go/no-go memo: continue, narrow scope, or stop — citing the counts
- [ ] `docs/CASE-STUDY.md` explains the pipeline for a non-specialist (fetch → filter →
  group → serve) with no personal or location identifiers
- [ ] Public identity and hosting posture decided and recorded before issue 1

**Verification:**
- [ ] Human review: you read each issue before it ships
- [ ] Markdown gate: `pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks`

**Dependencies:** Task 12

**Files likely touched:**
- `docs/CASE-STUDY.md`
- `tasks/demand-test.md` (issue log and counts)

**Estimated scope:** Small (2 files, spread over 8 weeks)

## Checkpoint: Data quality
- [ ] An event detail states its corroboration and links its source
- [ ] `./scripts/ci-check.sh` green (all non-docker gates)

## Checkpoint: Demand recorded
- [ ] A briefing is one command from the DB
- [ ] Eight issues published and counted
- [ ] Go/no-go memo written; next phase chosen from evidence

---

## Session handoff state

Updated after the code-review pass and context setup.

### Status
All original plan tasks complete. Raw GDELT storage, two-phase processing, audit
backfill, batched zero-shot filtering, API hardening, containerization, and the
CI/CD pipeline are applied — the pipeline has deployed to this host successfully and
serves the real dataset. The working tree is clean on `main`; `conflicts.db`,
`data/`, and `.venv/` are untracked via `.gitignore`. Open follow-ups are listed
below under "Remaining work"; the first two to pick up are the daemon `dns` setting
(runtime model download) and deploy gating for schema changes.

### Verification baseline (re-run these first)

```bash
source .venv/bin/activate
./scripts/ci-check.sh   # tool pins, ruff, format, shellcheck, ty, pytest (102), alembic
```

The same gates run in `.github/workflows/ci.yml` on every push and PR; a green
`./scripts/ci-check.sh` is the closest local proxy. `pytest`, `ruff`, `ty`,
`shellcheck`, and `alembic` all run normally in this environment.

Host-only verification (not part of ci-check): `./scripts/install-runner.sh --dry-run
--url https://github.com/OWNER/REPO` downloads and hash-checks the runner archive
without registering anything.

### Changes since the original plan
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
- Pipeline observability: `ingestion_run` now records `error` (`ExcType: message`,
  truncated to 2000 chars), `degraded_reason` (zero-shot filter unavailable, or a
  partly corrupt `--source-dir` cache), and `phase` for the whole-invocation steps
  (`retry_stranded_raw_days`, `group_events`, `prune_raw_events`). Each step gets its
  own row, created `running` and settled in place, so a healthy grouping keeps its
  duration and a crash keeps the reason — previously a failure there left only day rows
  that had already committed `success`, and a healthy grouping left no trace at all.
  Verified against a real DB + `uvicorn`: forced fetch failure →
  `error='RuntimeError: …'`; forced grouping failure → `phase='group_events',
  status='failed'`; classifier unavailable → `degraded_reason` set while `status` stays
  `success`; corrupt cached zip → `1 corrupt cached export file(s) skipped`.
- `GET /api/pipeline-health` reports the last successful day row, its age in hours, and a
  `stale` flag against `config/gdelt.yaml → pipeline_stale_hours` (default 48). Day rows
  only: a `raw_only` run never reaches the map and a phase row spans no day, so neither
  can say which day's data is current. `scripts/check-pipeline.sh` exits non-zero, so a
  host-cron `MAILTO` catches a frozen map instead of it going unnoticed (gotcha #9).
  Verified: empty DB → `stale=true`, exit 1; fresh success → exit 0; unreachable app →
  exit 1.
- Migrated formatting from black to `ruff format` (one tool for lint and format, no
  separate dependency). Output was nearly identical — exactly one file changed, where
  ruff joins an implicit f-string concat black left split. The Alembic exclusion was
  verified to still protect the three auto-generated revisions (stripping it makes ruff
  want to reformat all three). `black` dropped from `requirements.txt` and confirmed
  absent from the rebuilt image. Earlier entries above still say black; that is accurate
  for when they were written and is left as-is deliberately.
- Containerized the app and the daily pipeline (`Dockerfile`, `docker-compose.yml`,
  `docker/pipeline-entrypoint.sh`, `scripts/docker-daily.sh`). No apt layer: torch's
  CPU wheel bundles its own `libgomp.so.1`. Verified a clean build, migrations from an
  empty DB, and the same 1,437 conflicts served as on the host.
- Added a `ty` dev dependency group with `uv.lock`, pinned to the Dockerfile's Python
  so uv does not lock for the host interpreter. `ty check app` surfaced three DML
  `.rowcount` type errors,
  fixed by routing the calls through one `CursorResult`-casting helper.
- Added CI (`.github/workflows/ci.yml`): lint, format, `ty check`, pytest, fresh
  `alembic upgrade head` + `alembic check`, app-import check, tracked-artifact
  guard, compose-file validation, and a docker image that must serve `/health` **and**
  answer a real `/api/conflicts` query. Gate tools pinned in `requirements-ci.txt`;
  `ruff` gained the `I`/`B` rule sets. 16 pre-existing `ty` diagnostics fixed at the
  source rather than suppressed (protocols for the classifier/geocoder seams, explicit
  `zip(strict=…)`).
- Added CD (`.github/workflows/deploy.yml` + `scripts/deploy.sh`): on a green `main` run,
  builds `web` **and** `pipeline`, force-recreates the web container, requires `/health`
  plus a DB query to pass, and on failure restores the previous image (tagged
  `:rollback` *before* the build — the build otherwise prunes it) while still failing the
  job. Compose now pins `name: global-conflict-map` and `image: gcm-web:…`, and the data
  path is defined once in `scripts/_data-dir.sh` (shared by deploy and the daily
  pipeline; they previously drifted onto different databases).
- `scripts/docker-daily.sh` now forwards arguments (it silently dropped `--days 7`),
  creates the data dir as the invoking user, and the README's backfill commands use it
  instead of a bare `docker compose run` that bypasses the deployed database.
- `scripts/seed.py` offsets demo event coordinates (Leaflet spiderfies exactly coincident
  points, which jsdom cannot render) and gives the no-location demo a single unplaced
  event so the "Set location" flow is exercisable.
- Added `scripts/install-runner.sh`: pinned runner v2.338.2 with per-arch sha256,
  `--dry-run` (no token needed), root/already-registered guards, docker-group warning,
  systemd service install with a `./run.sh` fallback. `--allow-root` works on hosts
  where root is the only account (service install no longer assumes `sudo`). Registration
  itself still needs a token minted from the repo settings.
- Replaced `actions/setup-python` with a pinned-uv composite action
  (`.github/actions/uv-python`): setup-python has no Debian builds and the runner is
  Debian, so every job failed with a "version ... was not found for debian 12" error.
  uv provisions CPython for any glibc distro and caches it across runs; gates install
  with `uv pip`. Rehearsed locally in the 3.12 venv: 102 tests, ruff,
  ty, pymarkdown, migrations and app imports all pass.
- CI builds its venv at `$GITHUB_WORKSPACE/.venv` (was `$RUNNER_TEMP/venv`), the
  same relative path `scripts/_venv.sh` defaults to, so CI and a developer no longer
  look like different environments. Verified a build-local, untracked `.venv` does
  not trip the tracked-artifact guard.
- CI and the local scripts now resolve every interpreter and tool by absolute path:
  CI uses `$RUNNER_TEMP/venv/bin/{ruff,ty,pytest,...}` (UV_BIN/SHELLCHECK_BIN from
  `$GITHUB_ENV`), the scripts source `scripts/_venv.sh` (`GCM_VENV`, default
  `.venv`). A new "Verify tools resolve" step prints each tool's version first, so a
  `command not found` can no longer be mistaken for a lint failure. Motivated by a
  Shellcheck step that failed in 0.37s with no output on the runner while passing
  locally.
- Fixed a runner-only CI failure: downloaded tools were added to `$GITHUB_PATH`,
  which outlives `$RUNNER_TEMP`, so a later job resolved `shellcheck` to a removed
  directory and the step failed in 0.4s with no output. Tools now go through
  `$GITHUB_ENV` (`UV_BIN`, `SHELLCHECK_BIN`) and are called by absolute path; the
  shellcheck step prints `--version` first. `scripts/ci-check.sh` no longer skips
  shellcheck silently when the binary and docker are both missing.
- Added shellcheck to the gates for `scripts/*.sh` and
  `docker/pipeline-entrypoint.sh`: CI downloads v0.11.0 into `$RUNNER_TEMP` and verifies a
  pinned per-arch sha256 (actionlint only shellchecks the workflow `run:` blocks);
  `scripts/ci-check.sh` uses a local binary or the official image. All scripts clean.
- Added `scripts/cutover-data.sh` for the first deploy: SQLite backup API (WAL-safe),
  integrity + row-count verification, `.bak` instead of overwrite, container-mount guard,
  optional `hf-cache` copy. Rehearsed against a synthetic DB (including an uncheckpointed
  WAL writer); the real cutover is a one-command human step (`docs/ci-cd.md`).
- Code-review pass over the data path: 14 failure modes identified, 5 fixed (four
  directly, one as a side effect; each reproduced by a test that failed first). Grouping
  now upgrades a conflict's cached anchor
  anchor as soon as a linked event brings coordinates — the `None` cached for a conflict
  whose oldest event was ungeocoded was never replaced, so every later event in that
  theatre had to match the city name exactly. The detail view now lists every linked
  event instead of re-scoping to the conflict's own span (it showed fewer events than the
  list counted, and hid anything dated after `today` when `end_date` was null), keeping
  the in-span headline preference plus a stable `(event_date, id)` tie-break. A full run
  now drains pending `raw_event` rows for days it is not fetching: a failure between the
  raw commit and processing used to strand that day permanently, because the daily run
  only targets recent days and pruning deletes only processed rows. Event coordinates
  must now be both-or-neither, validated against the merged record on PATCH so
  single-field edits still work — a half coordinate made the marker vanish from the map
  with no error. 83 → 88 tests. The unfixed findings are below under
  "Data integrity (from the code review)".

### Remaining work (not started)

#### Data integrity (from the code review)
- [ ] **Retry GDELT downloads instead of aborting the run.** Why: `fetch_day` tolerates
  only 404s, so one `ReadTimeout`/`ConnectError`/5xx in any of the 96 daily slots
  propagates out of `run()` and the remaining days of a multi-day backfill never run; there
  is no retry or backoff. `parse_export_zip` also raises `IndexError` on an empty archive
  on the live path (`read_day_from_dir` catches it, `fetch_day` does not). How: bounded
  retries with backoff around `download_export`, treat an empty/invalid zip like a 404,
  and keep the `ingestion_run.status = failed` record for the day that really fails. Done
  when a simulated timeout on one slot still stores the other 95.
- [ ] **Enable WAL and a `busy_timeout` on the SQLite engine.** Why: `make_engine` sets only
  `PRAGMA foreign_keys`; the API writes from the threadpool while the daily pipeline
  writes through the same file, so a concurrent `PATCH` can raise `database is locked`
  (500). `scripts/cutover-data.sh` is deliberately WAL-safe, which implies WAL was assumed
  but never enabled. How: set `journal_mode=WAL` (and `busy_timeout`, e.g. 5000 ms) in the
  connect listener; WAL is persistent per database file, so confirm it after the cutover.
  Done when two writers can interleave without a lock error.
- [ ] **Bound the grouping time window.** Why: grouping never sets `Conflict.end_date` and
  `_time_overlaps` only checks the existing span, so two events in the same 100 km and
  country merge even five years apart, resurrecting dormant theatres as active. How: cap
  the gap since the conflict's last event (or set `end_date` when creating/joining) — this
  changes the grouping rule, so get approval first. Done when a multi-year gap produces
  two conflicts and an adjacent-day event still merges.
- [ ] **Make grouping's candidate selection explicit.** Why: the candidate query filters
  on `Conflict.country` with no `ORDER BY`, so the first match wins by rowid order, and
  `country IS NULL` matches every null-country conflict, letting two events in different
  countries merge if within 100 km. How: order candidates deterministically (e.g. earliest
  anchor/`id`) and decide what an absent country code may match — grouping rule, so get
  approval first. Done when the merge target for a null-country event is specified by a
  test rather than by rowid.
- [ ] **Residual anchorless case in grouping.** Why: fixing the never-upgraded anchor still
  leaves one gap — when the *first* geolocated event in a theatre has a different city name
  than the conflict's oldest (ungeocoded) event, it cannot be measured against a missing
  anchor and opens a second conflict. How: match on the stored place strings for
  anchorless conflicts, or defer anchoring to the first located event and merge the
  unplaced remainder afterwards — grouping rule, so get approval first.
- [ ] **Clear the minor review findings.** Why: each is small but silently loses
  information. `load_config` returns the `lru_cache`d dict itself (a caller mutating it
  poisons every later read) and never re-reads the YAML; the engine is built at import
  time, so `GCM_DATABASE_URL` must be set before any `app.*` import; `_apply_patch` logs
  `None` and `""` identically, so `edit_log` cannot distinguish cleared from empty;
  `slug_to_text` returns `""` for a URL with no slug, so the zero-shot filter drops an
  event it has no evidence against; `regroup_all` re-links manual events that have no
  `conflict_id` and never logs the change. How: return a copy from `load_config` (or memoise
  on the file mtime), build the engine lazily, log a sentinel for `None`, keep slug-less
  URLs like drafts without a URL, and skip/report manual events in `regroup_all`. Done
  when each has a regression test.

#### UI / product
- [x] Marker clustering for wide time ranges (`leaflet.markercluster` 1.5.3 from unpkg).
  A 30-day range (13,066 geolocated events) renders as ~37 clusters plus a couple of
  individual dots at world zoom; every event is still in the cluster tree.
- [x] Map reading aids: single-event dots shrunk to 6–12 px and moved onto the same
  heat ramp (severity fixes their shade, so they stay meaningful), and the conflicts
  panel now lists only what is inside the current map view ("Conflicts in view
  (N of M · E events)", refiltered on pan/zoom from already-fetched data) with one muted
  line for the off-screen/coordinate-less remainder.
- [x] Fixed in-view membership: it was tested against each conflict's single summary
  coordinate (its latest event in range), so conflicts whose incidents were on screen but
  whose summary point was not got dropped, and the header undercounted. Membership now
  comes from the events themselves (any event in bounds puts the conflict in the list),
  the header reports events in view, and clicking a row centres on the in-view event.
  Checked in jsdom (rows vs summary label, note text) and in headless Chrome: 1,177
  conflicts / 13,066 events at world view, 134 / 2,601 after zooming into a hot cluster,
  matching the cluster labels on screen. Follow-up from explaining "1177": the note said
  those conflicts were "without events in this range", but all 493 have exactly one event
  — GDELT just left it ungeocoded. "No location" is now derived from the events, and the
  note says so.
- [x] Cluster density heatmap: bubble colour on a log-scaled cool→hot ramp (hue 210°→0°,
  30→52 px) plus the event count, with a legend bottom-left. Checked in the jsdom
  harness (hue/size monotone in count) and in headless Chrome (2 events = hsl(189°)
  30 px, 2,161 events = hsl(0°) 52 px).
- [x] Checked-in headless UI smoke: `tests/ui/map-smoke.mjs` (jsdom + real Leaflet
  against a running server). Covers clustering counts, bounded DOM, cluster clicks, and
  the time scrub. Not wired into pytest/CI (needs npm + a server).
- [x] Real-browser smoke via headless Chrome 149 through the `chrome-devtools` MCP
  (attaches to Chrome on `:9222`; setup documented in `tests/ui/README.md`): 13,066
  events → ~37 cluster heat bubbles + individual dots at world zoom, labels summing to the
  API count, scrub to 3 days re-renders exactly 4,275, cluster click zooms, event popup +
  sidebar detail render, "Pick on map" fills lat/lon, OSM tiles return 200, and no
  console messages. The earlier grey tile gaps were transient fetches, not an app bug.

- [x] No-location panel (`docs/SPEC-ui.md` § Feature spec: surfacing no-location conflicts):
  sidebar section listing the 493 conflicts per 30-day window that have no geocoded event,
  capped at 200 rows, leading with the headline because every one of them is named
  "Unnamed conflict", with a "Set location →" action that arms the existing Pick-on-map
  flow. No API or schema change. Verified end-to-end in the browser: placing one event took
  493 → 492 unplaced, 13,064 → 13,066 markers, 1,177 → 1,178 in view, then reverted.

#### CI/CD follow-ups
The pipeline is in place and has run green end to end (see "Run the CI/CD pipeline on
the runner once"). These are the gaps deliberately left open. Each says what to change
and how to know it worked.

- [ ] **Gate deploys of schema changes behind review.** Why: `web` runs
  `alembic upgrade head` on every deploy, and rollback restores the image only — an old
  app on a new schema cannot be undone automatically. How: Settings → Environments →
  `production` → Required reviewers (the workflow already targets that environment);
  and/or `paths-ignore` for docs-only pushes in `deploy.yml` so a README commit does not
  redeploy. Done when a schema-changing push waits for approval and a docs-only push
  does not deploy.
- [ ] **Give the config a single source, like the data dir.** Why: the deployed stack
  mounts `config/gdelt.yaml` from the deploy checkout, so the README's "edit config and
  restart web" only holds for a bare local stack. How: add `GCM_CONFIG_DIR` next to
  `GCM_DATA_DIR` in `scripts/_data-dir.sh` (default `./config`), reference it in
  `docker-compose.yml` for both services, and state that deployed config edits go
  through git. Done when `deploy.sh` and `docker-daily.sh` mount the same file.
- [x] **Write and rehearse the first-deploy cutover.** `scripts/cutover-data.sh` is the
  runbook: dry-run by default, `--apply` to copy, `--force` to replace (the old target is
  renamed `.bak-<timestamp>`, nothing is deleted). Rehearsed against a synthetic schema:
  dry run writes nothing; copy verifies `integrity=ok` and equal `conflict`/
  `conflict_event` counts; re-apply refuses without `--force`; an uncheckpointed WAL
  writer's row survives the copy (a plain `cp` would lose it); a wrong/empty SQLite file
  is rejected before writing; a container mounting the target aborts the run; `--owner`
  chowns the result; `hf-cache` is copied when present. Still a human step on the real
  host: `docker compose -p workspace down`, then
  `./scripts/cutover-data.sh --apply --owner "$USER"`, then confirm `/api/conflicts`
  returns the counted rows.
- [x] **Venv was created but empty.** `Verify tools resolve` failed with "no ruff
  in .../.venv" seconds after uv exited 0. Cause: tool installation lived in the
  *next* step, and GitHub skips every later step once one has failed, so the check
  ran against a venv that only had `python`. Fixed by making installation part of
  the `uv-python` action (`requirements:` input, torch redirected to the CPU index),
  which then prints ruff/ty/pytest versions — so "the tools are missing" can only
  be reported after an honest attempt to install them.
- [x] **Image build failed on DNS the runner does not use.** `docker build` ran on the
  default bridge where Docker supplies its own nameservers (8.8.8.8/8.8.4.4, unreachable
  here), so pip timed out on PyPI while the gates job installed the same wheels fine.
  The Build step now uses `--network=host`; recorded in AGENTS gotcha #11 and
  docs/ci-cd.md.
- [x] **Deploy hit the same resolver.** The deploy step failed after exactly 2m00s on
  `pip install` in the image build: `scripts/deploy.sh` called `docker compose build`,
  which (unlike the CI job's `docker build --network=host`) got the daemon's fallback
  resolvers. `docker-compose.yml` now sets `network: host` on both services' `build:`,
  with an explicit `--network=host` fallback in deploy.sh. Verified: a fresh
  `docker compose build web` succeeds, and a control compose build *without* the key
  fails in ~12s on this host; a full `./scripts/deploy.sh` run reports ready.
- [ ] **Set `"dns"` in the deploy host's `daemon.json`.** The `--network=host` build flag
  is a workaround for CI only: `docker compose run pipeline` (model download) and the
  deploy container also get the broken resolver defaults.
- [x] **Get the Shellcheck step's actual output.** No longer needed: the step passes
  now that the tools are installed by the venv action before any gate runs, and the
  shellcheck download publishes `SHELLCHECK_BIN` by absolute path. The earlier
  no-output failures were the skip-after-failure pattern, not shellcheck itself.
  Keep `ACTIONS_STEP_DEBUG` in mind for the next silent step rather than re-guessing.
- [x] **Run the CI/CD pipeline on the runner once.** Green end to end
  2026-11-09: `gates` 97s, `image` 25s, `deploy to this host` 23s (all Succeeded on
  commit `224750b`), and the deployed stack serves the real data —
  `/api/conflicts` 1443 conflicts / 13,713 events, matching the DB. `workflow_run`
  firing, the `head_sha` checkout, uv's cache, `docker compose config --images web`
  and the readiness probe all behaved as designed. Four defects surfaced and were
  fixed getting here: setup-python has no Debian build (→ uv action), a `$GITHUB_PATH`
  entry outliving `$RUNNER_TEMP`, tools installed in a later step that a failure skips
  (→ install inside the venv step), and the daemon's fallback resolvers on build
  containers (→ `network: host` on every build path).
- [ ] **Make the UI smoke data-density-independent, then gate it.** Why: with the
  five-conflict demo seed it passes except "conflict list follows the map viewport" —
  the preceding cluster click has already zoomed the list to one row, so narrowing is
  unobservable. How: reset the map to world view before the viewport check (or seed a
  fixture DB dense enough), then add a `ui` job to `ci.yml` that starts `uvicorn` on a
  temp DB, seeds it, and runs `tests/ui/map-smoke.mjs`. Keep the seed coordinate offsets:
  jsdom cannot render Leaflet's spiderfy for coincident points. Done when the harness is
  green from demo data in CI.
- [ ] **Pin `requirements.txt`, then add `pip-audit` and Dependabot for pip.** Why: CI
  installs whatever the resolver picks, so an audit reports guesses, and
  `.github/dependabot.yml` has no pip ecosystem for the same reason. How: `uv pip compile
  requirements.txt -o requirements.lock` (keep torch on the CPU index), install the lock
  in CI and the Dockerfile, add `pip-audit -r requirements.lock` to the `gates` job, and
  re-enable the pip ecosystem weekly. Done when two consecutive CI runs install identical
  versions and the audit runs.
- [ ] **Notice post-deploy failure.** Why: the deploy job checks readiness once; nothing
  watches a container that starts crash-looping an hour later. How: a systemd timer or
  host cron that curls `/health` and a `/api/conflicts` query and logs/notifies on
  failure (same readiness definition as `scripts/deploy.sh`). Done when a stopped
  container is visible without inspecting `docker ps`.
- [ ] **Housekeeping.** Why: image layers and buildkit cache accumulate and nothing prunes
  them. How: monthly `docker image prune -f --filter until=168h` and `docker builder
  prune -f --filter until=168h`; delete local validation artefacts (`gcm-web:ci`,
  `rhysd/actionlint`) if unused. Done when disk usage is stable across deploys.

#### Operations / data
- [x] **Upgrade the host database past `b7da7a666155`.** Done by the container:
  `docker compose exec web alembic current` reports `3eaf800e3086 (head)`. A *host*
  run still has to migrate first if it is pointed at a database the container has not
  touched yet (the `web` service migrates on start).
- [ ] Decide raw retention: keep the 30-day default or set `raw_retention_days: 0`; take a
  backup of the current ~1.4 GB DB before any pruning or reset.
- [ ] Label the nine legacy `ingestion_run` rows whose `source_day`/`mode` are null, or
  document them as pre-metadata runs. `source_day IS NULL` now also means "phase row",
  but the two are distinguishable (`phase` is null for the legacy rows), and
  `/api/pipeline-health` ignores both because it reads day rows only.
- [ ] Mark stale `running` `ingestion_run` rows failed on startup. This matters slightly
  more now that every invocation adds three `running` phase rows for the length of
  `retry_stranded_raw_days`/`group_events`/`prune_raw_events`; a kill leaves them
  `running` on purpose (it shows where the process died), but nothing ever settles them.
- [x] Record whether the zero-shot filter was available/used in run audit metadata:
  `ingestion_run.degraded_reason` carries `zero-shot filter unavailable (ExcType: msg);
  ran unfiltered` while the run stays `status='success'` (unfiltered events are real,
  just country-centroid-placed). Surfaced by `GET /api/ingestion-runs`.

#### Tooling
- [x] Raised the runtime to Python 3.12: Dockerfile base image, `pyproject.toml`
  (`requires-python >=3.12` and the ty target), CI (one `gates` job; the separate
  "compat" job is gone because it duplicated the shipped version), and the docs.
- [x] Add `scripts/install-runner.sh` for the self-hosted runner: pinned v2.338.2 with
  per-arch sha256, `--dry-run` without a token, root and already-registered guards,
  docker-group warning, systemd install with a `./run.sh` fallback. Registering still
  needs a token from the repo settings; the first hosted run is tracked under
  "CI/CD follow-ups".
- [x] Migrate formatting from black to `ruff format` (one tool for lint + format, drops
  a dependency). Only one file differed — ruff joins an implicit f-string concat that
  black kept split. Verified the Alembic exclusion still protects the three
  auto-generated revisions: with it stripped, ruff would reformat all three. `black`
  removed from `requirements.txt` and confirmed absent from the rebuilt image. Historical
  entries earlier in this file still reference black — accurate for when they were run,
  left untouched on purpose.

- [x] Add shellcheck for the shell scripts (deploy, rollback, cutover, cron). Pinned
  v0.11.0 with per-arch tarball hashes in `ci.yml`; local fallback in
  `scripts/ci-check.sh`. Clean on all six `scripts/*.sh` files plus the container entrypoint.

#### Optional
- [x] Use `num_sources` from `raw_event` for corroboration — moved to Task 10 (Phase 5).
- [ ] Backfill more history beyond 2026-10-29..2026-11-04.
- [ ] Fetch real article `<title>` instead of URL-slug headlines (previously declined).
- [x] Add CI/CD — see `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, and
  `docs/ci-cd.md`. Remaining dependency work is tracked under "CI/CD follow-ups".
- [ ] Pin dependencies (see "CI/CD follow-ups").
- [ ] Split `app/static/app.js` into smaller modules if it grows further.

### Approval state
Pending approvals (both are grouping-rule changes): bound the conflict time window so a
multi-year gap starts a new conflict, and make candidate selection deterministic instead
of rowid-ordered with `country IS NULL` matching worldwide. Also awaiting a decision on
the residual anchorless case above. Article-title fetching is still declined; raw payload
storage is implemented in `raw_event`.
