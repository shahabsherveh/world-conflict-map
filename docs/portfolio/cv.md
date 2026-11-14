# CV

Global Conflict Map demonstrates a production-shaped stack — ETL, ML filtering,
persistence, API, interactive UI, and operations — which is rare in a personal project.
Present it as *engineered*, not *coded together*.

## Placement

Put it under a **Projects** section: above work experience if you are early-career,
below it if you are senior. Each entry should carry:

- **Name** — Global Conflict Map
- **Link** — the GitHub repo (and the live app, if deployed)
- **Tech line** — Python · FastAPI · SQLAlchemy · Alembic · SQLite · PyTorch/Transformers
  · Leaflet · Docker · CI/CD
- 3–5 bullets, chosen below

## Bullets

### Anchor bullet (always include)

> Built a self-updating web app that ingests GDELT 2.0 news-event data (~57k rows/day),
> filters it to armed-conflict events with a zero-shot semantic classifier, and groups
> them into browsable conflicts on an interactive Leaflet map.

### Backend / data engineering

- Designed a one-way dependency architecture (storage → ingestion → extraction → API →
  UI) with swappable adapters, keeping the extraction layer pure of DB/HTTP side effects.
- Wrote a daily ETL pipeline with graceful degradation — it still stores unfiltered
  events when the ML model is unavailable.
- Reduced N+1 query risk and enforced a ≤5-query bound on the main listing endpoint with
  a regression test.
- Modeled data with SQLAlchemy 2.0 + Alembic migrations and validated every endpoint
  with Pydantic response schemas.

### ML / data science

- Applied a batched zero-shot classifier (~0.03 s/event on CPU) to cut false positives
  from noisy news data, combined with a CAMEO code + Goldstein scale intensity heuristic.

### Full-stack / product

- Shipped a map UI with cluster heatmaps, spiderfied overlapping markers, time-scrubbing,
  and manual conflict/event editing — in dependency-free vanilla ES modules.
- Designed deliberately so it could become a product without a rewrite, including
  data-quality safeguards (never auto-repositioning coordinates from unreliable
  re-geocoding).

### Engineering rigor / operations (the differentiator)

- Automated quality gates in CI: pinned+hashed dependencies, `ruff` lint/format, `ty`
  type-checking, `shellcheck`, `pymarkdown`, `pytest`, and `pip-audit`.
- Containerized the stack (Docker Compose) with a cron pipeline plus a freshness health
  check that alerts when the map silently stops updating.
- Tested the UI both headlessly (jsdom) and in a real browser over Chrome DevTools
  Protocol, plus explicit performance-invariant tests.

## Two things that move the needle most

1. **The "silent failure" alert.** The pipeline-health check is a one-line interview
   story: it shows you think about failure modes, not just happy paths.
2. **The README and docs are the portfolio.** Link the repo directly and let the
   reviewer skim `README.md`, `docs/CAPABILITY-MAP.md`, and `docs/CASE-STUDY.md`. They
   sell better than any bullet.

## Tailoring by role

| Target role | Lead with | Drop |
|---|---|---|
| Backend / Data Engineer | Pipeline, architecture, N+1, migrations | UI detail |
| ML Engineer | Zero-shot filter, batching, degradation | Frontend |
| Full-stack / Product | Map UI, clustering, "product-ready" design | Shell/CI detail |

## Caveat

Be ready to explain what is hand-built versus scaffolded. The project is genuinely
hand-built, so this is easy — just know which pieces you would defend in depth if an
interviewer pushes on them.
