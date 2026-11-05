# Spec: ui — interactive map + time scrub + manual edit

## Objective
A single-page map UI: conflict markers sized/colored by intensity, time-range controls
that re-query the API, click-for-news, and manual edit/create controls.

## Tech stack
Leaflet + OpenStreetMap tiles, vanilla HTML/CSS/JS, served by FastAPI. No build step.
(Conventions: CAPABILITY-MAP.md)

## Behavior
- Map centered on world; markers per conflict, radius/color by intensity (1–5).
- Time controls (start + end date inputs, or a slider) → `GET /api/conflicts?start&end` → re-render.
- Click marker → side panel: conflict name, country, intensity, status, event timeline
  (each event with event_type, fatalities, and a link to the source article).
- Edit mode: edit conflict (name/intensity/status/end_date), move/add event, create conflict
  → PATCH/POST endpoints.
- Show `auto` vs `manual` provenance subtly, so it's clear what the machine produced.

## Commands
- No build step — served at `/` via uvicorn.
- Manual smoke: open `http://localhost:8000`, scrub time, click, edit.

## Project structure (module)
- `app/static/index.html`, `app/static/app.js`, `app/static/style.css`

## Code style
Conventions: CAPABILITY-MAP.md. Plain ES modules, `fetch()` to `/api/*`.

## Testing strategy
- Manual smoke checklist (primary).
- Optional later: Playwright smoke tests (loads, renders markers, scrub triggers fetch).

## Boundaries
- Always: fetch data from `/api/*` (never hardcode data in JS).
- Ask first: adding a JS framework/build step, adding map providers needing keys.
- Never: embed API keys in static files.

## Success criteria
- Load `/`, see conflict markers for a seeded dataset.
- Changing the time range updates markers without a full reload.
- Clicking a marker shows its news; editing a conflict persists and re-renders.

## Open questions
- Basemap: OSM standard tiles OK? (free, no key)
- Marker style: color = intensity vs size = intensity vs both — pick one to start.
