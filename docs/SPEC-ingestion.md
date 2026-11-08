# Spec: ingestion — daily GDELT file fetch

## Objective
Fetch structured conflict events from GDELT's free 2.0 raw event files on a daily basis,
normalize them into our raw-event shape, dedupe by `GLOBALEVENTID`, and record each run
in `ingestion_run`.

## Tech stack
`httpx` + `pyyaml` + stdlib `zipfile`. (Conventions: CAPABILITY-MAP.md)

Parsing is a plain `line.split("\t")` against the 61-column list, not the `csv` module:
the export is tab-separated with no quoting or embedded newlines, and `csv` would only
add a parser we then have to configure back to that shape.

## Data source
GDELT 2.0 15-minute event exports, one zipped TSV per 15-min slot:
`https://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip`
- Free, no API key.
- 96 files per day (000000 … 234500).
- Each file is tab-separated, **no header row**; columns are positional (61 columns,
  defined in `app/ingest/normalizer.COLUMNS`).

## Behavior
- Read config from `config/gdelt.yaml` (base URL, lookback window in days).
- Enumerate the 96 15-minute timestamps for the target day.
- Download each `*.export.CSV.zip`, unzip, parse the TSV into raw event dicts (positional columns).
- Dedupe by `global_event_id` (`GLOBALEVENTID`).
- Persist parsed rows into `raw_event` **before** extraction/filtering, then mark each row
  with its outcome once processing completes.
- Tolerate a missing 15-min file (HTTP 404 → skip that slot); any other HTTP failure
  propagates and fails the run loudly, because a 5xx or a timeout means the day is
  incomplete rather than absent. Cached local files that are missing or corrupt
  (`read_day_from_dir`) are skipped so a partial download can be retried next run.
- Prune processed raw rows after `raw_retention_days` (default 30); unprocessed rows are kept.
- This module is a library only; the runnable entrypoint is `app.extract.run`, which calls it.

## Commands
- `python -m app.extract.run` (fetch → filter → persist → group)
- `python scripts/process_raw.py` (process pending `raw_event` rows only)
- `python scripts/backfill_audit.py` (reconstruct `ingestion_run` rows from completed raw data)

## Project structure (module)
- `app/ingest/gdelt.py` — download client (15-min stamps, zip fetch, TSV parse)
- `app/ingest/normalizer.py` — `COLUMNS` + `parse_export_tsv` + `dedupe_new`
- `app/ingest/raw_store.py` — raw-row persistence, pending queue, outcome marking, pruning
- `config/gdelt.yaml`

## Code style
Conventions: CAPABILITY-MAP.md

## Testing strategy
- Inline TSV rows built from `COLUMNS` (`make_row` in `tests/test_ingestion.py`) → assert
  positional column mapping and malformed-row skipping. There are no GDELT fixtures on
  disk; the eval sample under `tests/fixtures/` belongs to extraction.
- Test 15-min stamp enumeration (96 stamps, correct boundaries).
- Test 404 skipping via a mocked transport, and missing/corrupt local files via `tmp_path`.
- Test raw-row dedupe, pending selection, outcome marking, and retention pruning.

## Boundaries
- Always: dedupe by `GLOBALEVENTID`; log per-run outcomes.
- Ask first: switching source (e.g. GDELT Cloud API), changing lookback policy.
- Never: write source columns into `conflict_event`. Raw rows belong in `raw_event`, and
  there only as the JSON of non-empty columns (`payload`) so a row can be replayed through
  a changed adapter; `conflict_event` carries the mapped, typed fields alone.

## Success criteria
- One command downloads and normalizes the target day's GDELT events without duplicates.
- A missing/empty 15-min file is skipped and the run still completes.

## Open questions
- None blocking. Settled: classic GDELT 2.0 `.export.CSV.zip` files (free, no key).
  GDELT Cloud's REST API exists but requires an API key; we can switch later via the adapter.
