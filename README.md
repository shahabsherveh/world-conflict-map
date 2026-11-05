# Global Conflict Map

A personal web app that maps armed conflicts worldwide, browsable across time, and
updates itself daily from news data. Built personal-first but architected so it could
become a product without a rewrite.

## What it does

1. Fetches **GDELT 2.0 raw event files** (free, no API key) — news already coded into
   geolocated events.
2. Filters to **armed conflicts** (CAMEO root codes 18/19/20) and applies a
   **zero-shot semantic filter** to drop false positives (podcasts, jet crashes, etc.).
3. Groups events into **conflicts** and stores them in SQLite.
4. Serves an interactive **Leaflet map** with time-scrub and manual editing.

## Requirements

- Python 3.11+
- Network access (for GDELT + the one-time model download)

## Setup

```bash
cd global-conflict-map
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/download_model.py   # one-time; downloads the zero-shot model (~130 MB)
```

## Run

```bash
# 1. Fetch + extract (the daily pipeline)
python -m app.extract.run

# 2. Serve the app
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000**.

- Markers are sized and colored by intensity (1–5).
- Change the **From / To** dates to see conflicts active in that window.
- Click a marker to see its events and the underlying news source.
- Use the side panel to **edit** a conflict, **add** an event, or **create** a new conflict.

## Daily cron

```bash
crontab -e
# fetch + extract every day at 06:00
0 6 * * * /absolute/path/to/global-conflict-map/scripts/daily.sh
```

`scripts/daily.sh` runs the fetch→extract pipeline. `config/gdelt.yaml` controls the
source URL, lookback window, and zero-shot threshold.

## Seed demo data (optional)

To see the map immediately without hitting GDELT:

```bash
python scripts/seed.py
```

## Data source & filtering

- **Source:** GDELT 2.0 `.export.CSV.zip` files — free, no key, 15-minute granularity.
- **Filter pipeline:** `app/extract/` — root-code filter → field mapping → zero-shot
  gate (`cross-encoder/nli-deberta-v3-small`, threshold `0.7`).
- Measured on a labeled sample: **~83% precision / 63% recall** (vs ~32% precision
  before filtering).

## Architecture

`storage → ingestion → extraction → api → ui` — see `CAPABILITY-MAP.md` and `SPEC-*.md`.

Contributing with an AI agent? Read **`AGENTS.md`** first — it carries the commands,
conventions, boundaries, and the gotchas that cost real debugging time.

- `app/ingest/` — GDELT download + TSV parsing
- `app/extract/` — adapter + filter + grouping (`BaseSourceAdapter` is the swappable boundary)
- `app/api/` — FastAPI routes + Pydantic schemas
- `app/static/` — Leaflet frontend (no build step)

## Future: swap NLP → LLM

The extraction boundary is `app/extract/base.py: BaseSourceAdapter`. To use a T5 model
or an LLM later, add a new adapter implementing `to_event_draft(raw) -> EventDraft | None`
and select it in `app/extract/run.py`. No other module changes.

## Tests & evaluation

```bash
pytest                      # unit + integration tests
python scripts/evaluate.py  # precision/recall of the zero-shot filter (needs model)
```
