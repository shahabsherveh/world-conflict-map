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

**Open, and why** — the table below is the full remaining surface: thirteen rows, of
which two are now *decided* (identity/posture recorded; raw retention = keep 30 days),
and the rest are blocked on the deploy host, eight weeks of publishing, or are
non-actionable optional reminders:

| Item | Blocker |
|---|---|
| Demand test: 8 issues + per-issue counts (Task 13) | ~8 weeks of publishing; not code |
| Go/no-go memo written from those counts | needs the eight issues |
| Read each issue before it ships (verification) | per issue, at publish time |
| Public identity + hosting posture for issue 1 | decided & recorded (pseudonym, host unnamed) |
| Host: daemon `dns` (runbook §1) | deploy host (Docker daemon config) |
| Host: install the health timer + pipeline cron (runbook §5) | deploy host (systemd/cron) |
| Host: `production` environment required reviewers (runbook §6) | GitHub repo setting |
| Host: real cutover, if a legacy DB exists (runbook §3–4) | deploy host, only when one exists |
| Raw retention: ended | decided — keep 30 days; host backup is the only step left |
| Housekeeping: prune images + build cache (runbook §8) | deploy host |
| Backfill before 2026-10-29 (runbook §9) | optional; host time, ~30 min/day of data |
| Fetch real article `<title>` for headlines | declined earlier; spec in `tasks/optional-items.md` (Item A); reopen only if slugs prove unusable |
| Split `app/static/app.js` if it grows further | no trigger yet; spec in `tasks/optional-items.md` (Item B) — splits at ~1,500 lines |

The last two rows are the only entries under "Optional"; each now has a written spec
in `tasks/optional-items.md` (reopen trigger, design, constraints, acceptance) so a
future session executes against it instead of re-deriving the reasoning. They are
reminders, not work: neither trigger has fired. Host steps are specified command by
command in `docs/host-runbook.md`.

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

## Session history

Append-only per-pass handoff notes (status, verification baselines, environment quirks)
previously lived below this point. They are superseded by the "Status at a glance" table
at the top and by the commit history, so they were removed from the read path — recover
any pass with `git log -- tasks/todo.md`. Open items are the table at the top and the
two active checkboxes above (Task 13 / `tasks/demand-test.md`).
