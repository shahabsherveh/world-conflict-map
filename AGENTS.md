# Global Conflict Map — agent rules

Personal web app that maps armed conflicts worldwide, browsable across time, refreshed
daily from news data. Read this file before working in the repo.

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, SQLite
- `httpx` (GDELT downloads), `pyyaml` (config)
- `transformers` + `torch` (zero-shot filter, CPU)
- Vanilla ES modules + Leaflet + OpenStreetMap tiles — **no frontend build step**
- Tests: pytest · Lint: ruff check · Format: ruff format (line length 100)
  · Shell: shellcheck · Markdown: pymarkdown

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.lock         # runtime, pinned + hashed (torch is the +cpu wheel)
pip install -r requirements-ci.txt       # pinned pytest, ruff, ty, pymarkdown, pip-audit

pytest                                   # full suite
pytest tests/test_api.py -k conflicts    # focused
ruff check .                             # lint
ruff format app tests scripts            # format
shellcheck scripts/*.sh scripts/git-hooks/pre-commit docker/pipeline-entrypoint.sh  # .shellcheckrc
pymarkdown scan -r README.md AGENTS.md docs tests/ui/README.md tasks  # markdown
ty check                                 # types (targets 3.12)
./scripts/ci-check.sh                    # every non-docker CI gate, in order
./scripts/install-hooks.sh               # run those gates as a pre-commit hook
./scripts/lock-deps.sh                    # regenerate requirements.lock after editing requirements.txt
./scripts/check-deps.sh                   # pip-audit the installed runtime (needs network)
./scripts/ci-check.sh --docker           # …plus the image build + import check
cd tests/ui && node map-smoke.mjs        # headless UI smoke (needs npm install + serve)
cd tests/ui && node browser-tests.mjs    # real Chrome over CDP (needs Chrome on :9222 + serve)

# Chrome for the chrome-devtools MCP (see Gotchas #12); CDP on :9222
npx -y @puppeteer/browsers install chrome@stable   # once; ./chrome/ is gitignored
chrome/linux-*/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --remote-debugging-port=9222 \
  --user-data-dir=chrome/profile about:blank &
alembic upgrade head                     # apply migrations
alembic revision --autogenerate -m "…"   # new migration

python -m app.extract.run                # daily pipeline: fetch → filter → persist → group
./scripts/check-pipeline.sh              # non-zero when no run succeeded recently (cron alert)
uvicorn app.main:app --reload --port 8000 # serve (always use --reload)

python scripts/seed.py                   # demo data (no network)
python scripts/briefing.py --days 7      # Markdown digest of the DB (stdlib only, read-only)
./scripts/check-health.sh                # is the deployed app answering? (cron/timer)
./scripts/install-health-watch.sh --dry-run  # the 15-minute systemd timer that runs it
./scripts/install-runner.sh --url …     # register the CI runner (RUNNER_TOKEN=…)
./scripts/cutover-data.sh                # dry-run: move existing DB into GCM_DATA_DIR
./scripts/cutover-data.sh --apply        # ...and copy (WAL-safe, verified, keeps a .bak)
python scripts/evaluate.py               # filter precision/recall (needs model)
python scripts/repair_locations.py       # dry-run coordinate inspection only
python scripts/regroup.py                # dry-run conflict rebuild (--apply to write)
python scripts/fetch_gdelt.py --days 7   # raw GDELT download to data/gdelt/
python scripts/process_raw.py            # process pending raw_event rows
python scripts/backfill_audit.py         # reconstruct ingestion_run rows
```

## Architecture

Dependency direction is one-way: `storage → ingestion → extraction → api → ui`.
`docs/CAPABILITY-MAP.md` is the index; each module has a `docs/SPEC-<module>.md`.

| Area | Path | Notes |
|---|---|---|
| Models, migrations | `app/models.py`, `app/migrations/` | SQLite; never hand-edit the DB |
| Shared queries | `app/queries.py` | cross-module read helpers live here, not in routes |
| Config | `app/config.py` | path-independent, cached; defaults in `DEFAULTS` |
| GDELT download | `app/ingest/gdelt.py`, `normalizer.py` | 61-column positional TSV, no header |
| Extraction | `app/extract/` | `base.py` = swappable adapter seam; `grouping.py` links events to conflicts (proximity, not keywords) |
| API | `app/api/routes.py`, `schemas.py` | Pydantic models for every endpoint |
| UI | `app/static/` | `app.js`, `index.html`, `style.css` |

## Conventions

- Type hints everywhere; `from __future__ import annotations`.
- Accessors/tests query through `app/queries.py` helpers — don't duplicate SQL in routes.
- Adapters stay pure: no DB or HTTP inside `app/extract/gdelt_adapter.py` or `base.py`.
- Every endpoint has a Pydantic response model; validate inputs with `Field` bounds.
- Frontend: `esc()` every interpolated string in `app.js` (values come from external news).
- Assets in `index.html` carry a `?v=N` query; bump it when changing `app.js`/`style.css`.
- Comments explain *why*, especially where a naive approach was rejected.

## Testing

- `tests/` mirrors modules: `test_storage`, `test_ingestion`, `test_extraction`,
  `test_api`, `test_location`, `test_config`, `test_raw_store`, `test_download_model`,
  and `test_briefing` (the script, not a module).
- Test **behaviour**, and make fixtures complete enough that a mutation is actually caught —
  a test that passes for the wrong reason is worse than none.
- Regression tests for every bug fix (see `test_group_events_does_not_merge_distant_cities_in_one_country`).
- Guard performance invariants explicitly (see `test_conflict_list_query_count_is_bounded`).
- `tests/ui/map-smoke.mjs` covers the map JavaScript (clustering, counts, time scrub) in
  jsdom against a running server. `tests/ui/browser-tests.mjs` covers what jsdom cannot
  (hit-testing, popup anchoring, computed CSS, tiles, Pick-on-map) by driving a real
  Chrome over CDP. Neither is part of pytest or the CI gates; run them when touching
  `app/static/app.js` (`tests/ui/README.md`).
- CI (`.github/workflows/ci.yml`) runs lint, format, shellcheck, `ty check`, `pytest`, a fresh
  `alembic upgrade head` + `alembic check`, an app-import check, an artifact guard, and a
  docker build that serves `/health`. `docs/ci-cd.md` explains each gate and the deploy
  rollback. Run `./scripts/ci-check.sh` before pushing so the pipeline has nothing to find.
- `./scripts/install-hooks.sh` points `core.hooksPath` at the tracked
  `scripts/git-hooks/`, so `git commit` runs `scripts/ci-check.sh` and a red gate stops
  the commit. It is opt-in per clone (git never auto-enables hooks) and
  `git commit --no-verify` bypasses it for deliberately dirty WIP.
- Visual/CSS checks need a real browser. Use the `chrome-devtools` MCP (codemode tools
  `mcp__chrome_devtools__*`), which attaches to the headless Chrome on `:9222`; see
  `tests/ui/README.md` for the workflow and what each layer covers.

## Boundaries

**Always**
- Run `./scripts/ci-check.sh` before calling work done: tool pins, ruff check + format,
  shellcheck, pymarkdown, `ty check`, pytest, and migration apply/drift — the same gates as CI.
- Use Alembic for schema changes, and keep `alembic check` clean: it runs in CI.
- Keep markers per-event; never re-position a marker from aggregated conflict data.
- Assert on measured behaviour (query counts, HTTP status) rather than assuming.

**Ask first**
- Adding a dependency (each one is a liability).
- Changing `EventDraft` or `BaseSourceAdapter` shape.
- Changing the grouping rule or its 100 km radius.
- Any schema migration on existing data.

**Never**
- Do not make shellcheck quiet by ignoring SC1091 in a script; fix the cause (a
  `# shellcheck source=` pragma or `.shellcheckrc`), or the gate stops meaning anything.
- Commit `conflicts.db`, `.venv/`, or secrets.
- Automatically rewrite coordinates from re-geocoding — verified to corrupt correct records.
- Enable `repair_locations` by default (see gotchas).
- Expose the app publicly: no auth by design, personal tool.

## Gotchas (each cost real debugging time)

1. **GDELT country codes are FIPS, not ISO** — Yemen is `YM`, Germany `GM`, Ukraine `UP`.
2. **GDELT geocodes country-centroid when it can't pin a city** — Iran is `32,53`. Not a bug.
3. **Place strings can be self-contradictory** (`"Qeshm, Kordestan, Iran"` — Qeshm is an island).
   Re-geocoding "city, country" fixed some records and moved Dnipro/Komyshuvakha/Kagera
   hundreds of km. Repair stays off; fix such points by hand.
4. **Grouping once matched the country word**, merging every Yemen event into one conflict.
   It is now proximity-based (100 km anchor + a 14-day gap window). Do not reintroduce
   keyword matching. The window is a *gap since the last event*, not a total duration, and
   an explicit `end_date` overrides it — see `docs/SPEC-extraction.md#grouping-rule`.
   The no-coordinate fallback compares place strings of the conflict's *events*, not
   `Conflict.name` (a human can rename it), and it never compares names when the presence
   of any stored place makes distance the only honest test.
5. **N+1 is easy to reintroduce** in `list_conflicts`; the query-count test enforces ≤5.
6. **Nominal `uvicorn` without `--reload` serves stale Python**; browsers cache `index.html`
   (mitigated by `no-store` middleware + `?v=N`).
7. **The zero-shot model downloads once** via `python scripts/download_model.py`; the pipeline
   degrades gracefully (skips the filter) if unavailable. It is cached in
   `GCM_HF_HOME` (default `/data/hf-cache`, a sibling of the `db/` directory under the
   one `/data` mount) and shared by the host run and the container
   (`scripts/_data-dir.sh` exports `HF_HOME`, the Dockerfile sets
   `HF_HOME=/data/hf-cache`, and both compose services mount the same directory at the
   same path); don't let them diverge into two copies. `HF_HOME` is set by that
   script, not by the code — `python scripts/download_model.py`
   or `python -m app.extract.run` run straight from a shell use `~/.cache/huggingface` instead, so
   either source `scripts/_data-dir.sh` first or pass `HF_HOME=` explicitly; both warn on stderr
   when the default cache is in use. On a network that can't reach `cdn-lfs.huggingface.co`, large
   downloads stall as `*.incomplete` blobs and never finish — copy a complete cache in from another
   machine instead and confirm with `python scripts/download_model.py --check`.
8. **Auto-generated Alembic revisions are excluded** from ruff lint/format — don't reformat them.
   `ty check` excludes them too.
9. **The containerized stack's state lives under one mount, `GCM_DATA_ROOT`, defined only
   in `scripts/_data-dir.sh`** (default `/data`; `GCM_DATA_DIR=$root/db` holds
   `conflicts.db`, `GCM_HF_HOME=$root/hf-cache` holds the model cache; bare
   `docker compose up` uses `./data`). Host and container paths are identical, so
   `/data/db/conflicts.db` means the same file on both sides. Both `deploy.sh` and
   `docker-daily.sh` source it. Setting it in one place only is how the web app and the daily pipeline
   ended up on different databases — the map simply stopped updating. Use
   `scripts/docker-daily.sh` for backfills: it forwards args (a bare
   `docker compose run --rm pipeline --days 7` uses `./data`). `GET
   /api/pipeline-health` (and `scripts/check-pipeline.sh` from cron) is the symptom
   check for exactly this: it reports the last *successful* run's age, so a
   pipeline that writes to the wrong DB shows up as stale instead of silent. The UI smoke test
   now passes against the real DB because coincident events stay clustered at every zoom;
   spiderfy still needs a browser, so `browser-tests.mjs` owns that check. `scripts/seed.py`
   offsets its demo coordinates, keeping a fresh seed the fast fixture.
10. **Scripts must not assume the venv is at `.venv` or that they run from the repo
   root.** `scripts/_venv.sh` owns the location (`GCM_VENV` overrides it) and every
   caller uses `"$(gcm_venv_python)"` / `"$(gcm_venv_tool ruff)"`; the cron entry
   point (`scripts/daily.sh`) runs under whatever PATH cron provides. CI builds
   its venv at `$GITHUB_WORKSPACE/.venv` (same path, gitignored) so CI and a
   developer see the same layout. Related: the
   tracked `conflicts.db` is at schema `b7da7a666155` while `alembic head` is ahead
   of it, so anything reading it — the host run, the UI smoke against a hand-started
   server — must `alembic upgrade head` first.
11. **Docker builds use a different resolver than the runner, and it is broken here.**
   `docker build` steps run on the default bridge, where Docker substitutes its own
   nameservers (`8.8.8.8`/`8.8.4.4`) instead of the host's; pip then times out on PyPI
   while every non-container step works. Build with `--network=host` (CI does), or set
   `"dns": [...]` in the daemon config. Symptom to recognise: `ReadTimeoutError` on
   `files.pythonhosted.org`, only inside image builds.
12. **`chrome-devtools-mcp` cannot launch Chrome here** (no binary at `/opt/google/chrome`,
   and Chrome refuses to run as root). Run Chrome yourself with
   `--remote-debugging-port=9222 --no-sandbox` and configure the MCP with
   `--browserUrl http://127.0.0.1:9222` so it attaches instead of launching. Install Chrome
   for Testing with `npx -y @puppeteer/browsers install chrome@stable`; it lands in the
   gitignored `chrome/` at the repo root, so it survives a container rebuild. Its shared
   libraries are image packages, not repo files: `libglib-2.0.so.0: cannot open shared
   object file` means re-install them (command in `tests/ui/README.md`). Two rough edges:
   `new_page` waits for `load` and times out while map tiles are still fetching (the page is
   fine — keep using it), and `evaluate_script` replies with prose plus a fenced JSON block,
   so parse the fence.

## Known limitations

- Headlines are derived from URL slugs (lowercase, occasionally truncated).
- `fatalities` is always null: the free GDELT export has no casualty fields; intensity is
  derived from event type + Goldstein scale.
- The extraction adapter uses a subset of GDELT's 61 columns. `raw_event` now retains
  all non-empty columns, so `num_sources` is available but not yet used for corroboration.
- Zero-shot is batched (~0.03 s/event on CPU here), but it is still the dominant cost of
  a multi-day backfill.
