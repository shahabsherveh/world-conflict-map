# Tasks: Global Conflict Map

Build order: storage → ingestion → extraction → api → ui. Full plan: `tasks/plan.md`.

## Status at a glance

Read this first; the rest of the file is the record of how each item was decided.

**Done** — all of Phase 1–5 except Task 13, and every in-repo follow-up from the
code-review and CI/CD passes: data integrity (download retries, WAL + `busy_timeout`,
the minor review findings, stale-run settling), the three grouping-rule changes (bounded
window and deterministic selection in `43d4a89`, the anchorless fallback in `98ef12b`),
the UI work (clustering, heat ramp, in-view list, no-location panel), the CI/CD gaps that
were code (config source, cutover rehearsal, watcher scripts, dependency pinning +
audit, UI smoke made fixture-independent), the API documentation surface (`4cebde5`),
and the case study (`4ce2362`).

**Open, and why** — thirteen unchecked boxes, and no others:

| Item | Blocker |
|---|---|
| Demand test: 8 issues + per-issue counts (Task 13) | ~8 weeks of publishing; not code |
| Go/no-go memo written from those counts | needs the eight issues |
| Read each issue before it ships (verification) | per issue, at publish time |
| Public identity + hosting posture for issue 1 | your decision, before issue 1 |
| Host: daemon `dns` (runbook §1) | deploy host (Docker daemon config) |
| Host: install the health timer + pipeline cron (runbook §5) | deploy host (systemd/cron) |
| Host: `production` environment required reviewers (runbook §6) | GitHub repo setting |
| Host: real cutover, if a legacy DB exists (runbook §3–4) | deploy host, only when one exists |
| Raw retention: 30 days or 0 (runbook §7) | your decision, after a backup on the host |
| Housekeeping: prune images + build cache (runbook §8) | deploy host |
| Backfill before 2026-10-29 (runbook §9) | optional; host time, ~30 min/day of data |
| Fetch real article `<title>` for headlines | declined earlier; reopen only if slugs prove unusable |
| Split `app/static/app.js` if it grows further | no trigger yet; not actionable now |

The last two rows are the only entries under "Optional" and exist as reminders, not work.
Host steps are specified command by command in `docs/host-runbook.md`.

---

## Phase 1: Foundation

### Task 1: Project scaffolding
**Description:** Initialize the Python project: venv, `requirements.txt`, the `app`
package, a minimal FastAPI app with a `/health` endpoint, pytest/ruff/black config, `.gitignore`.

**Acceptance criteria:**
- [x] `pip install -r requirements.lock` succeeds in a fresh venv (the lock was
  introduced later; `requirements.txt` carries the constraints)
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
- [x] Visual browser smoke: open `http://localhost:8000`, scrub time, click a marker — done
  in headless Chrome through the `chrome-devtools` MCP (see "UI / product" below), and
  since then continuously by `tests/ui/browser-tests.mjs`, which drives real Chrome over CDP

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
- [x] Visual browser smoke: edit a conflict and confirm it persists after reload — done the
  same way; persistence is also asserted by the API tests and the jsdom harness

**Dependencies:** Task 7

**Files likely touched:**
- `app/static/app.js`, `app/static/index.html`, `app/static/style.css`

**Estimated scope:** Small (1–2 files)

## Checkpoint: API + UI
- [x] Full UI wired end-to-end against seeded data (view, scrub, click, edit)
- [x] Visual browser smoke done in headless Chrome (details under "UI / product")

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
- [x] Visual browser smoke (headless Chrome; see "UI / product")

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
- [x] Manual browser check: Chrome for Testing 157 (installed via `@puppeteer/browsers` into
  the gitignored `chrome/`, so it persists) against the seeded DB — Ukraine popup and detail
  show `4 outlets · 12 articles` in `corroboration strong` (green), Yemen shows the muted
  `1 outlet · 9 articles`, Sudan (no raw row) shows no badge, OSM tiles loaded
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
- [x] `python scripts/briefing.py --days 7` prints Markdown to stdout; no network calls
  (`sqlite3` + stdlib only, opened `mode=ro`, so it cannot write either)
- [x] Every event line carries its source URL; an event without one is omitted, not shown
  unlinked — and non-`http(s)` URLs are refused too
- [x] Output is deterministic for a fixed DB (same input, same order and content; total
  ordering ends on `conflict.id`)
- [x] Runs against `scripts/seed.py` data with no model file present (degraded mode)
- [x] `--region <country>` filters without changing the format
- [x] Ranking uses corroboration counts, never a `confidence` threshold (same reasoning as
  Task 11: the score is ordinal and unvalidated)
- [x] Output is bounded: `--top` (default 10 theatres) and `--events-per-theatre` (default
  3), each with a "…N more, not shown" line; `--top 0` prints everything

**Verification:**
- [x] Tests pass: `pytest tests/test_briefing.py` (17 tests). Mutation-checked: removing
  the no-source guard failed 2 tests; summing per-event counts instead of taking the
  strongest failed the corroboration test
- [x] Manual check: run on the seeded DB and on the real 1.4 GB `conflicts.db` (2.6 s, 96
  lines for a 7-day issue). Reading it changed four things the spec did not anticipate:
  (1) uncapped output was ~13k lines for 1,436 theatres, so the issue is now capped;
  (2) one article produced up to three identical lines (GDELT emits one row per actor
  pair), so duplicate reports fold into "… N related reports" while the heading still
  counts stored rows; (3) the header's event total now counts stored rows, not folded
  lines; (4) **content caveat, not a bug to fix silently** — theatre titles are
  place-derived, so a country-centroid cluster reads as a place name ("## Belgium",
  "## Belfast, Belfast, United Kingdom") and GDELT's own noise comes with it. A
  subscriber-facing issue needs a human pass over the titles or the grouping changes
  already awaiting approval below.
- [x] Markdown gate: `pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks`

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

**Plan and log:** `tasks/demand-test.md` — kill criteria chosen in advance, the
pre-issue-1 decisions to record (identity, hosting, channel, what "engaged" counts), a
per-issue table, and the memo skeleton. Nothing in this task can be done from a code
session; it needs eight weeks of publishing.

**Acceptance criteria:**
- [ ] Eight issues published, each at most one page, every claim linked
- [ ] Per-issue count recorded: replies, reshares, audience growth
- [ ] Written go/no-go memo: continue, narrow scope, or stop — citing the counts
- [x] `docs/CASE-STUDY.md` explains the pipeline for a non-specialist (fetch → filter →
  group → serve) with no personal or location identifiers. Written; every number comes
  from the project's own database or a measured run, and the limits section states what
  the data cannot do (no casualties, centroid locations, counts are not verification).
  Linked from `README.md` and `docs/CAPABILITY-MAP.md`; markdown gate clean.
- [ ] Public identity and hosting posture decided and recorded before issue 1

**Verification:**
- [ ] Human review: you read each issue before it ships
- [x] Markdown gate: `pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks`

**Dependencies:** Task 12

**Files likely touched:**
- `docs/CASE-STUDY.md`
- `tasks/demand-test.md` (issue log and counts)

**Estimated scope:** Small (2 files, spread over 8 weeks)

## Checkpoint: Data quality
- [x] An event detail states its corroboration and links its source
- [x] `./scripts/ci-check.sh` green (all non-docker gates) — 142 tests, ruff, format,
  shellcheck (v0.11.0), pymarkdown, ty, alembic apply + drift

## Checkpoint: Demand recorded
- [x] A briefing is one command from the DB
- [ ] Eight issues published and counted — log started in `tasks/demand-test.md`
- [ ] Go/no-go memo written; next phase chosen from evidence

---

## Session handoff state (earlier passes — historical, see the Phase 5 handoff below)

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
./scripts/ci-check.sh   # tool pins, ruff, format, shellcheck, ty, pytest (142), alembic
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

Superseded in part: what is still open is the table at the top of this file. Ticked
entries below are kept because each records *how* it was verified.

#### Data integrity (from the code review)
- [x] **Retry GDELT downloads instead of aborting the run.** `GDELTClient._request` retries
  transport errors and 408/425/429/5xx three times with exponential backoff (0.5 s
  doubling, `sleep` injected for tests); a slot that exhausts them is skipped and named in
  `fetch_day(failed_slots=…)`, which `run()` records as
  `degraded_reason = "N download(s) skipped after retries"`. An empty or invalid archive
  is now "no data" (like a 404) instead of an `IndexError` on the live path. A day where
  no slot produced anything still raises, so the day really shows `status = failed`
  instead of a silent zero-event success. Tests: one timeout then success (asserts the
  backoff sleeps), 5xx then success, empty archive, 95-of-96 slots survive one dead slot,
  all-slots-dead raises, and a `run()` test asserting the degraded reason.
- [x] **Enable WAL and a `busy_timeout` on the SQLite engine.** `make_engine` now sets
  `journal_mode=WAL` and `busy_timeout=5000` alongside `foreign_keys`. One non-obvious
  detail: pysqlite already installs its own 5 s busy handler, which made the pragma look
  decorative — a mutation test removing it still passed. The engine therefore connects
  with `timeout=0` so the pragma is the single source of the wait, and the mutation is
  caught. Tests: WAL + 5000 reported on connect, and two real writers where the second
  blocks (rather than raising "database is locked") and commits once the first releases.
  Not yet observed on the deployed file — WAL is persistent per database, so confirm with
  `PRAGMA journal_mode` against `/data/db/conflicts.db` after the next deploy.
- [x] **Bound the grouping time window.** Done in `43d4a89`: the window is now a gap
  since the conflict's most recent event (`DEFAULT_GAP_DAYS = 14`), not a total
  duration, and an explicit `end_date` still wins. Tests:
  `test_group_events_starts_a_new_conflict_after_a_dormant_gap`,
  `..._keeps_a_quiet_week_inside_one_conflict`,
  `..._gap_is_measured_from_the_last_event_not_the_start`,
  `..._never_lets_an_explicit_end_date_absorb_later_events`. Measured on the real DB:
  1,443 → 1,517 conflicts, no event unlinked.
- [x] **Make grouping's candidate selection explicit.** Done in `43d4a89`: candidates
  are ordered oldest-first, so the same data groups the same way after a re-import
  (`test_group_events_picks_the_same_conflict_regardless_of_row_order`), and an absent
  country matches only another absent country rather than every null-country conflict
  (`test_group_events_links_events_that_have_no_country`, which deliberately gives the
  two events different place strings so the city fallback cannot mask the country path).
- [x] **Residual anchorless case in grouping.** Fixed: the no-coordinate fallback now
  compares the event's city with the cities named by the conflict's **events** (cached
  per conflict, updated as events link) instead of with `Conflict.name`. The name is
  editable, so a manual rename made an anchorless conflict unmatchable and the next
  event opened a second conflict for the same theatre; with `autoflush` off, a town
  introduced earlier in the same run was also invisible to the fallback. A conflict with
  no stored places (seeded/manual) still compares its name; a *different* city still
  splits, because without an anchor there is no distance to measure. Tests:
  `test_group_events_matches_anchorless_conflict_by_stored_places_not_its_name`,
  `..._ungeocoded_event_sees_places_linked_earlier_in_the_run`,
  and `..._keeps_an_anchorless_conflict_to_its_own_place` as the must-still-split guard.
  Mutation-checked: reverting to the name-only comparison failed 2 tests, returning
  `True` for any stored place failed the split test, and dropping the cache update on
  link failed the same-run test.
- [x] **Clear the minor review findings.** All five fixed, each with a regression test that
  fails without the fix. `load_config()` returns a fresh copy of a privately cached dict,
  so a caller mutating the result can no longer poison later reads. The engine is built
  lazily on first `get_session()` from `database_url()` (read at call time), so
  `GCM_DATABASE_URL` no longer has to be set before importing `app.*` — Alembic's
  `env.py` uses the same accessor. `_apply_patch` stores SQL `NULL` for `None`, so
  `edit_log` distinguishes "cleared" from "set to empty". `filter_by_zero_shot` keeps
  drafts whose URL yields no slug (an empty text is no evidence either way) instead of
  silently dropping them. `group_events` and `regroup_all` no longer claim manual events:
  a hand-assigned `conflict_id` is a human decision, and since ids restart from 1 on
  regroup, re-linking one would have attached it to an unrelated conflict. (The
  "never re-reads the YAML" half is left as-is: config is read once per process by
  design, and the web app restarts on deploy.)

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

- [~] **Gate deploys of schema changes behind review.** Half done, and the remaining half
  is not a code change. The deploy job now diffs `HEAD^..HEAD` and skips the build when
  every changed file is a `*.md` under `docs/`, `tasks/` or `.agents/`, so a README push no
  longer force-recreates the container (`paths-ignore` cannot be used here: `workflow_run`
  evaluates it against the CI run's event). Verified locally against a scratch repo:
  docs-only → `deploy=false`, code → `true`, mixed → `true`, shallow clone → deploys.
  Still open: **Approval on the `production` environment** — Settings → Environments →
  `production` → Required reviewers (`docs/host-runbook.md` §6). That is a repo setting
  with no local check, and it is deliberately *after* "Run the CI/CD pipeline on the
  runner once", which is green.
- [x] **Give the config a single source, like the data dir.** `scripts/_data-dir.sh` now
  exports `GCM_CONFIG_DIR` (default `./config`) next to `GCM_DATA_DIR`, and both compose
  services mount `$GCM_CONFIG_DIR/gdelt.yaml`. `deploy.sh` and `docker-daily.sh` already
  source that file, so they cannot drift again; `docs/ci-cd.md` states that deployed
  config edits go through git because the deploy checkout is wiped by `git clean -ffdx`.
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
  returns the counted rows (`docs/host-runbook.md` §3).
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
- [ ] **Set `"dns"` in the deploy host's `daemon.json`** (`docs/host-runbook.md` §1). The
  `--network=host` build flag is a workaround for CI only: `docker compose run pipeline`
  (model download) and the deploy container also get the broken resolver defaults.
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
- [x] **Make the UI smoke data-density-independent.** Done, with one deliberate exception:
  the "gate it in CI" half is **not** being done, by the later decision in `cf226c5` that
  the UI harnesses must stay out of the gates (the runner has no npm or Chrome and may be
  rebuilt). Changes: the viewport check always resets to world view first and reports
  `SKIPPED` on a single-conflict fixture instead of passing on a 1 → 0 edge case; panels
  whose population is empty (e.g. "No location" when everything is geocoded) assert the
  *hidden* state rather than demanding rows; and a 500 from the API now says "is the
  database migrated?" instead of failing a map assertion. Verified green against three
  fixtures: the demo seed, a 200-conflict / 8,000-event DB of GDELT-style centroid stacks
  (also exercises clustering through thousands of coincident points), and the real 13k-event
  DB in the browser suite. An *empty* database still fails — there is no event to anchor
  the time-scrub window to — so "populated fixture" remains a prerequisite, now documented.
- [x] **Pin `requirements.txt`, then add `pip-audit` and Dependabot for pip.** Done:
  `requirements.lock` is a hashed `uv pip compile` of `requirements.txt`, generated by
  `scripts/lock-deps.sh`, which also embeds PyTorch's CPU index so the `+cpu` wheel is
  the only torch the install can resolve (the Dockerfile's old "install torch, then strip
  the line and install the rest" is gone — one `pip install -r requirements.lock`).
  The Dockerfile and the CI `uv-python` action install the lock; CI needs
  `--index-strategy unsafe-best-match` because the CPU index mirrors torch's deps at
  older versions before PyPI is consulted. `pytest`/`ruff` left `requirements.txt` for
  `requirements-ci.txt`, so a lock bump cannot change the tools that decide pass/fail.
  Audit: `scripts/check-deps.sh` runs `pip-audit` on the *installed venv* (re-resolving a
  hashed lock took 10 minutes; CI has just installed that lock) and accepts exactly one
  named skip — torch's `+cpu` build has no PyPI release to map to. `pip-audit==2.10.1`
  is pinned in `requirements-ci.txt`; the gate runs in CI and `ci-check` (13 s).
  Dependabot pip is re-enabled for `requirements.txt`, with the gate tools ignored so
  they stay hand-pinned. `tests/test_lockfile.py` (4 tests, offline) fails if the lock is
  unpinned, unhashed, missing a top-level requirement, out of step with a bumped
  constraint, drops the CPU index, or gains a gate tool. Verified end to end: rebuilt
  `gcm-web` installs torch 2.15.0+cpu / transformers 5.23.0 and has no pytest;
  mutation-checked the lock tests (dropped index, `+cpu` removed, bumped constraint);
  `./scripts/ci-check.sh` green.
- [x] **Notice post-deploy failure.** `scripts/check-health.sh` uses the same readiness
  definition as `deploy.sh` (`/health` 200 **and** `/api/conflicts` returns a JSON array)
  and exits non-zero with a one-line reason. `scripts/install-health-watch.sh` installs a
  15-minute systemd timer (`--dry-run` / `--remove` supported, runs as the invoking user).
  Verified: healthy stack → exit 0; nothing listening → exit 1 with `DOWN: …`. Adversarial
  check that caught a false negative in the *test*, not the script: deleting the SQLite
  *main* file while the server holds its WAL leaves reads working (all pages in the WAL),
  so the API still answers `[]` — a real database outage that empties the file is caught,
  a WAL-only deletion is not, and no HTTP probe can see the difference.
- [ ] **Install the two watchers on the host** (`docs/host-runbook.md` §5). The scripts
  exist but the timer and the `check-pipeline.sh` cron line are host state: run
  `sudo ./scripts/install-health-watch.sh` and add
  `0 8 * * * /path/to/repo/scripts/check-pipeline.sh` to the crontab. Done when a stopped
  container and a stale pipeline each produce a non-zero exit without inspecting
  `docker ps`.
- [ ] **Housekeeping** (`docs/host-runbook.md` §8). Why: image layers and buildkit cache
  accumulate and nothing prunes them. How: monthly `docker image prune -f --filter
  until=168h` and `docker builder prune -f --filter until=168h`; delete local validation
  artefacts (`gcm-web:ci`, `rhysd/actionlint`) if unused. Done when disk usage is stable
  across deploys. Needs the deploy host, so it waits on the same session as the watcher
  install above.

#### Operations / data
- [x] **Upgrade the host database past `b7da7a666155`.** Done by the container:
  `docker compose exec web alembic current` reports `3eaf800e3086 (head)`. A *host*
  run still has to migrate first if it is pointed at a database the container has not
  touched yet (the `web` service migrates on start).
- [ ] Decide raw retention (`docs/host-runbook.md` §7): keep the 30-day default or set
  `raw_retention_days: 0`; take a backup of the current ~1.4 GB DB before any pruning or
  reset.
- [x] Label the nine legacy `ingestion_run` rows whose `source_day`/`mode` are null, or
  document them as pre-metadata runs. `source_day IS NULL` now also means "phase row",
  but the two are distinguishable (`phase` is null for the legacy rows), and
  `/api/pipeline-health` ignores both because it reads day rows only.
- [x] Mark stale `running` `ingestion_run` rows failed. `app/ingest/audit.py` settles any
  `running` row older than `stale_run_hours` (config, default 12) to `failed` with
  `error = "settled as failed: the run never finished (process died or was killed)"`, and
  `run()` calls it first — before adding rows of its own — so an eternal "running" from
  last week stops looking like live progress. Deliberately *not* done on web-app startup:
  the pipeline is the only writer, and a web restart would otherwise declare a live
  backfill dead. Raise `stale_run_hours` for a backfill longer than half a day. Tests: the
  selector touches only abandoned rows (not a live run, not a settled success), and a
  `run()` leaves the abandoned row `failed` with that error.
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
- [ ] Backfill more history beyond 2026-10-29..2026-11-04 (`docs/host-runbook.md` §9).
- [ ] Fetch real article `<title>` instead of URL-slug headlines (previously declined).
- [x] Add CI/CD — see `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, and
  `docs/ci-cd.md`. Remaining dependency work is tracked under "CI/CD follow-ups".
- [x] Pin dependencies (see "CI/CD follow-ups").
- [ ] Split `app/static/app.js` into smaller modules if it grows further.

### Approval state
No grouping-rule change is pending. The three items that waited on approval are done:
bounded time window and deterministic candidate selection (with `43d4a89`) and the
residual anchorless case (this pass). **Evidence that remains**: the Task 12 briefing run
showed broad clusters titled `## Belgium` and `## Belfast, Belfast, United Kingdom` —
place-derived titles, not a window bug, so it is a naming/content decision rather than
something the three items above fix.

Also open for a decision: pinning the runtime dependencies (see "CI/CD follow-ups").
Article-title fetching is still declined; raw payload storage is implemented in
`raw_event`.

## Session handoff state (Phase 5 pass)

### Status
The `pi update --extensions` run that preceded this session touched only the agent
extensions (`pi-subagents` 0.87.0 → 0.88.0 and the `agent-skills` git checkout); nothing
in this repo changed for it. This pass closed every `tasks/todo.md` item that is both
in-repo and implementable without a product decision:

- Data integrity: GDELT retry/backoff + slot skipping, WAL + `busy_timeout`, the five
  minor review findings, stale `running` rows settled by the pipeline.
- CI/CD: `GCM_CONFIG_DIR`, docs-only deploys skipped, post-deploy health watcher
  (systemd timer + `check-health.sh`), UI smoke made fixture-density-independent, the
  "gate the UI smoke" half explicitly declined (see `cf226c5`).
- Phase 5: Task 12 briefing generator with 17 tests, plus `tasks/demand-test.md`.

Still blocked, and why: the three grouping-rule changes (need approval), the case study
and the eight-issue demand test (weeks of publishing, not code), the `production`
environment approval + two host watcher installs + housekeeping (host settings), runtime
dependency pinning (a dependency decision), and the ops-only retention/backfill choices.

### Verification baseline (re-run these first)

```bash
source .venv/bin/activate
./scripts/ci-check.sh   # tool pins, ruff, format, shellcheck, ty, pytest (142), alembic
```

Environment notes for the next session: docker cannot reach a registry from this
container, so the shellcheck gate must run with a local v0.11.0 binary on `PATH`
(`koalaman/shellcheck:v0.11.0` image pull fails with an auth EOF); CI itself downloads
the pinned tarball and is unaffected. UI harnesses: `tests/ui/map-smoke.mjs` passes on
the demo seed, on a 200-conflict centroid-stack fixture, and on the real DB; it needs a
*populated* DB (an empty one cannot anchor its scrub window) and a server
(`BASE_URL=http://127.0.0.1:PORT node map-smoke.mjs`).

### Working tree
Clean. The two sets of changes that were mixed together on entry are now separate
commits on `main`: `4cebde5` (API documentation surface + its invariant test),
`8156462` + the follow-up commit (state directory layout: one `/data` mount, database
at `/data/db/conflicts.db`), and `1b8548b` (this task log). The in-flight UI
clustering work had already landed in `870560e`/`cf226c5`.

## Session handoff state (this session — read the "Status at a glance" table above)

Eight commits on `main`, tree clean, `./scripts/ci-check.sh` green (169 tests, ruff,
format, shellcheck, pymarkdown, ty, dependency audit, alembic apply + drift).

| Commit | What |
|---|---|
| `4cebde5` | API documented at `/docs` (tags, summaries, parameter docs) + `test_openapi_document_names_every_operation` |
| `8156462` | Model cache mounted where `HF_HOME` points, instead of landing inside the data volume |
| `1b8548b` | Task log for the two above |
| `9e30ff0` | Closed the two grouping items that had shipped in `43d4a89` but were still listed open |
| `57d98a7` | One `${GCM_DATA_ROOT}:/data` mount, so the database is `/data/db/conflicts.db` in host and container |
| `98ef12b` | Anchorless grouping matches the conflict's events' places, not its (editable) name |
| `84dcb90` | `requirements.lock` (hashed, CPU torch index), `pip-audit` gate, Dependabot pip re-enabled |
| `4ce2362` | `docs/CASE-STUDY.md` — the pipeline for a non-specialist, with its limits |
| `7f6a0fd` | `docs/host-runbook.md` — the host-only steps, command by command |

This log pass (the commit after `7f6a0fd`) only edits this file: a status table at the
top, so the open set is readable without scrolling 900 lines, three stale "visual
browser smoke by user pending" boxes ticked (the headless-Chrome checks and
`tests/ui/browser-tests.mjs` cover them), and the note that the runtime now installs
from `requirements.lock`.

Verification baseline for the next session — unchanged, and the fastest way to know the
tree is healthy:

```bash
source .venv/bin/activate
pip install -r requirements.lock -r requirements-ci.txt   # once per venv
./scripts/ci-check.sh
```

Environment notes: docker cannot pull the `koalaman/shellcheck` image here, so the
shellcheck gate needs a local v0.11.0 binary on `PATH` (CI downloads the pinned tarball
and is unaffected); `pypi.org/simple/` (the index root) times out on this network while
per-package pages work, so `uv pip compile` and `lock-deps.sh --check` need
`UV_HTTP_TIMEOUT=60` or more. UI harnesses need a *populated* DB and a server; see
`tests/ui/README.md`.

## Session handoff state (API docs + state-dir split pass)

Two independent pieces were sitting uncommitted on `main`, both now finished and
separated into their own commits.

### API documentation surface (new)
The JSON API had response models but no readable `/docs`: every endpoint was an
unlabelled operation with no parameter descriptions, so Swagger UI showed nine bare
`GET`/`PATCH` lines. `app/main.py` now carries a title summary, description, version and
`openapi_tags` (conflicts, events, pipeline, sources, system); `app/api/routes.py` tags,
summarises and describes every endpoint plus each query/path parameter; and
`app/api/schemas.py` documents the corroboration fields (`sources`, `articles`,
`well_corroborated`) where a reader looks for them. `/health` keeps its trivial
behaviour — CI and deploy curl it — and only gained a docstring and a tag.

No test asserts prose (that would be a change-detector), but the invariants are
enforced by `test_openapi_document_names_every_operation`: the document must build,
every operation must carry a summary, and every tag used must be declared in
`openapi_tags` (an undeclared tag is silently unstyled in Swagger UI).

### State directories: one `/data` mount, database at `/data/db/conflicts.db` (new)
`scripts/_data-dir.sh` had been edited to default `GCM_DATA_DIR=/data/db` and
`HF_HOME=/data/hf-cache` while compose still mounted `${GCM_DATA_DIR}:/data`, so the
database landed at `/data/conflicts.db` and the container's `HF_HOME` resolved to
`/data/db/hf-cache` — both the wrong location and the host/container cache divergence
gotcha #7 exists to prevent.

Resolved by mounting the *root* instead of the db directory, so host and container use
identical paths:

- `docker-compose.yml` mounts `${GCM_DATA_ROOT:-./data}:/data` in both services and
  sets `GCM_DATABASE_URL=sqlite:////data/db/conflicts.db`. The database lives in the
  `db/` subdirectory, not at the mount root; the model cache is a sibling at
  `/data/hf-cache`, which keeps the unrecoverable directory separable for backups.
- `scripts/_data-dir.sh` defines `GCM_DATA_ROOT` (default `/data`) and derives
  `GCM_DATA_DIR=$root/db` and `GCM_HF_HOME=$root/hf-cache`.
  `gcm_ensure_data_dir` became `gcm_ensure_dirs`: it creates the db *and* cache
  directories as the invoking user, since Docker creates missing bind targets
  root-owned and later writes then fail.
- `scripts/cutover-data.sh` copies the model cache to `$GCM_HF_HOME` (was
  `$dst_dir/hf-cache`) and copies *into* an existing empty directory (`cp -a src/. dst/`
  — `cp -a src dst` would have nested it); `--owner` now chowns the cache too.
- Every user-facing hint that named an old path was corrected: the
  `download_model.py` warning/docstring, the `classifier.py` warning, the deploy
  workflow comment, `README.md`, `docs/ci-cd.md`, and gotchas #7/#9 in `AGENTS.md`.

Verified: `docker compose config` renders `source: /data` → `target: /data` with the
deployed defaults and `./data` with none set, and both services carry
`sqlite:////data/db/conflicts.db`; `source scripts/_data-dir.sh` exports
`GCM_DATA_ROOT=/data`, `GCM_DATA_DIR=/data/db`, `HF_HOME=/data/hf-cache` and
`gcm_ensure_dirs` succeeds. Gates:
`./scripts/ci-check.sh` green (161 tests, ruff, format, shellcheck v0.11.0 via the
pinned image, pymarkdown, ty, alembic apply + drift).
