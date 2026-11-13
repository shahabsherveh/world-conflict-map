# Implementation Plan: Global Conflict Map

## Overview
A personal web app that, on a daily batch, fetches structured armed-conflict events from
GDELT (free, already geolocated + classified), filters and maps them into a local store,
and serves an interactive Leaflet map with time scrub and manual edits.
Build order follows docs/CAPABILITY-MAP.md: `storage` → `ingestion` → `extraction` → `api` → `ui`.

## Architecture Decisions
- **Lean on GDELT, don't reinvent extraction.** GDELT already codes news into geolocated
  conflict events (lat/lon, actors, event type, source URL). Our "extraction" is a thin,
  pure adapter (filter + map + intensity), not a custom NLP pipeline. This is more accurate
  and dramatically less work.
- **Swappable event source.** `BaseSourceAdapter.to_event_draft(raw) -> EventDraft | None`
  isolates GDELT today from a T5 model (`ltg/t5-ucdp-conflict-extraction`) or an LLM later.
- **Batch, not streaming.** A daily job runs `ingest` then `extract`; the API reads the store.
- **Single process.** FastAPI serves both the JSON API and the static UI (same origin, no CORS).
- **SQLite + Alembic.** One file, zero ops; schema changes go through migrations.
- **No-build frontend.** Vanilla JS + Leaflet + OSM tiles.
- **Conflict grouping v2.** Proximity rule (same country + events within 100 km of the
  conflict anchor + overlapping time), isolated behind a helper so it can be replaced. An
  earlier keyword-overlap rule was dropped because the country name alone merged unrelated
  cities. Markers are drawn per event, so grouping never moves a marker.

## Task List

### Phase 1: Foundation
- [x] Task 1: Project scaffolding
- [x] Task 2: Storage — data model + migrations

### Phase 2: Data pipeline
- [x] Task 3: Ingestion — GDELT fetch + dedupe
- [x] Task 4: Extraction — adapter + filter + intensity
- [x] Task 5: Extraction — run pipeline + conflict grouping

### Phase 3: API + UI
- [x] Task 6: API — routes + manual edits
- [x] Task 7: UI — map view + time scrub + click-for-news
- [x] Task 8: UI — manual edit/create controls

### Phase 4: Polish
- [x] Task 9: End-to-end seed + README + cron

### Phase 5: Monetization readiness
- [x] Task 10: Corroboration scoring from `num_sources` + `num_articles`
- [x] Task 11: Corroboration exposed in API + UI badge
- [x] Task 12: Briefing generator (`scripts/briefing.py`)
- [ ] Task 13: Demand test (8 issues) + public case study

Task-by-task acceptance criteria and verification evidence: `tasks/todo.md`.

## Checkpoints
- **After 1–2:** app runs, schema migrates cleanly, storage queries tested.
- **After 3–5:** ingest + extract produce `conflict_event`s from fixture GDELT data;
  armed-conflict filtering works. (Verify the data pipeline early.)
- **After 6–8:** full UI works end-to-end against seeded data (view + edit).
- **After 9:** a fresh clone can be set up and run the full daily flow from the README.
- **After 10–11:** a detail response states how many outlets back an event;
  `./scripts/ci-check.sh` green.
- **After 12–13:** a briefing is produced from the DB in one command, and the go/no-go memo
  is written from real audience numbers rather than a guess.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| GDELT event coding has false positives / duplicates | Med | Dedupe by `GLOBALEVENTID`; filter to armed-conflict codes; manual edits + provenance |
| GDELT file availability / download limits | Med | Retry + skip missing 15-min files; configurable base URL; swappable adapter allows T5/LLM fallback |
| Conflict grouping is fuzzy | High | v1 manual + simple rule; grouping isolated behind a helper |
| GDELT `NumKilled`/`NumWounded` coverage is sparse | Low | Fatalities nullable; intensity derived from event type + tone, not fatalities alone |
| Free OSM tiles rate/attribution | Low | Standard OSM usage policy; Leaflet defaults |
| `num_sources` counts distinct outlets in one 15-min window, not total coverage | Med | Expose both counts; label as corroboration, never as verification |
| Rescoring `confidence` silently changes UI ordering | Med | Ordering regression test; keep the 0.0-for-absent invariant |
| A briefing publishes an unverified claim and burns credibility | High | Every bullet links a source; state corroboration; human read before send |
| Public output from Iran raises personal-security exposure | High | Decide identity/redaction posture before issue 1; no identifying detail |

## Open Questions
- *(Phase 1–4)* None blocking. Defaults approved: intensity 1–5, English-only v1, marker
  size+color, OSM tiles, no pagination, no CORS, no region filtering.
- *(Phase 1–4)* CAMEO armed-conflict code allow-list is tuned during Task 4.
- *(Phase 5)* Briefing language: Persian only, or Persian with an English summary?
- *(Phase 5)* Geography is global (decided in review), so no per-region default is needed.
- *(Phase 5)* Channel is deliberately unspecified; the plan assumes only that the audience
  can be counted per issue.
