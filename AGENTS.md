# Global Conflict Map — agent rules

Personal web app that maps armed conflicts worldwide, browsable across time, refreshed
daily from news data. Read this file before working in the repo.

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, SQLite
- `httpx` (GDELT downloads), `pyyaml` (config)
- `transformers` + `torch` (zero-shot filter, CPU)
- Vanilla ES modules + Leaflet + OpenStreetMap tiles — **no frontend build step**
- Tests: pytest · Lint: ruff · Format: black (line length 100)

## Commands

```bash
source .venv/bin/activate

pytest                                   # full suite
pytest tests/test_api.py -k conflicts    # focused
ruff check .                             # lint
black app tests scripts                  # format
cd tests/ui && node map-smoke.mjs        # headless UI smoke (needs npm install + serve)

# Chrome for the chrome-devtools MCP (see Gotchas #9); CDP on :9222
/tmp/chrome-dl/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-profile about:blank &
alembic upgrade head                     # apply migrations
alembic revision --autogenerate -m "…"   # new migration

python -m app.extract.run                # daily pipeline: fetch → filter → persist → group
uvicorn app.main:app --reload --port 8000 # serve (always use --reload)

python scripts/seed.py                   # demo data (no network)
python scripts/evaluate.py               # filter precision/recall (needs model)
python scripts/repair_locations.py       # dry-run coordinate inspection only
python scripts/fetch_gdelt.py --days 7   # raw GDELT download to data/gdelt/
python scripts/process_raw.py            # process pending raw_event rows
python scripts/backfill_audit.py         # reconstruct ingestion_run rows
```

## Architecture

Dependency direction is one-way: `storage → ingestion → extraction → api → ui`.
`CAPABILITY-MAP.md` is the index; each module has a `SPEC-<module>.md`.

| Area | Path | Notes |
|---|---|---|
| Models, migrations | `app/models.py`, `app/migrations/` | SQLite; never hand-edit the DB |
| Shared queries | `app/queries.py` | cross-module read helpers live here, not in routes |
| Config | `app/config.py` | path-independent, cached; defaults in `DEFAULTS` |
| GDELT download | `app/ingest/gdelt.py`, `normalizer.py` | 61-column positional TSV, no header |
| Extraction | `app/extract/` | `base.py` = swappable adapter seam |
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

- `tests/` mirrors modules: `test_storage`, `test_ingestion`, `test_extraction`, `test_api`, `test_location`, `test_config`.
- Test **behaviour**, and make fixtures complete enough that a mutation is actually caught —
  a test that passes for the wrong reason is worse than none.
- Regression tests for every bug fix (see `test_group_events_does_not_merge_distant_cities_in_one_country`).
- Guard performance invariants explicitly (see `test_conflict_list_query_count_is_bounded`).
- `tests/ui/map-smoke.mjs` covers the map JavaScript (clustering, counts, time scrub) in
  jsdom against a running server. It is **not** part of pytest and has its own npm
  dependency; run it when touching `app/static/app.js`.
- Visual/CSS checks need a real browser. Use the `chrome-devtools` MCP (codemode tools
  `mcp__chrome_devtools__*`), which attaches to the headless Chrome on `:9222`; see
  `tests/ui/README.md` for the workflow and what each layer covers.

## Boundaries

**Always**
- Run `pytest`, `ruff check .`, `black app tests scripts` before calling work done.
- Use Alembic for schema changes.
- Keep markers per-event; never re-position a marker from aggregated conflict data.
- Assert on measured behaviour (query counts, HTTP status) rather than assuming.

**Ask first**
- Adding a dependency (each one is a liability).
- Changing `EventDraft` or `BaseSourceAdapter` shape.
- Changing the grouping rule or its 100 km radius.
- Any schema migration on existing data.

**Never**
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
   It is now proximity-based (100 km + time window). Do not reintroduce keyword matching.
5. **N+1 is easy to reintroduce** in `list_conflicts`; the query-count test enforces ≤5.
6. **Nominal `uvicorn` without `--reload` serves stale Python**; browsers cache `index.html`
   (mitigated by `no-store` middleware + `?v=N`).
7. **The zero-shot model downloads once** via `python scripts/download_model.py`; the pipeline
   degrades gracefully (skips the filter) if unavailable.
8. **Auto-generated Alembic revisions are excluded** from ruff/black — don't reformat them.
9. **`chrome-devtools-mcp` cannot launch Chrome here** (no binary at `/opt/google/chrome`,
   and Chrome refuses to run as root). Run Chrome yourself with
   `--remote-debugging-port=9222 --no-sandbox` and configure the MCP with
   `--browserUrl http://127.0.0.1:9222` so it attaches instead of launching. Two rough
   edges: `new_page` waits for `load` and times out while map tiles are still fetching
   (the page is fine — keep using it), and `evaluate_script` replies with prose plus a
   fenced JSON block, so parse the fence. The Chrome install lives in `/tmp`, so a
   container rebuild deletes it.

## Known limitations

- Headlines are derived from URL slugs (lowercase, occasionally truncated).
- `fatalities` is always null: the free GDELT export has no casualty fields; intensity is
  derived from event type + Goldstein scale.
- The extraction adapter uses a subset of GDELT's 61 columns. `raw_event` now retains
  all non-empty columns, so `num_sources` is available but not yet used for corroboration.
- Zero-shot is batched (~0.03 s/event on CPU here), but it is still the dominant cost of
  a multi-day backfill.
