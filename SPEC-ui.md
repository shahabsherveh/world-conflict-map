# Spec: ui — interactive map + time scrub + manual edit

## Objective
A single-page map UI: conflict markers sized/colored by intensity, time-range controls
that re-query the API, click-for-news, and manual edit/create controls.

## Tech stack
Leaflet + OpenStreetMap tiles, vanilla HTML/CSS/JS, served by FastAPI. No build step.
(Conventions: CAPABILITY-MAP.md)

## Behavior
- Map centered on world; one marker per event, size/colour by intensity (1–5), grouped by
  Leaflet.markercluster at low zoom. Cluster bubbles show their event count and the worst
  intensity inside them, so escalation stays visible while the DOM stays bounded (a 30-day
  range is ~13k events).
- Time controls (start + end date inputs) → `GET /api/events` + `GET /api/conflicts` → re-render.
- Click marker → event detail with place/date/type/actors/intensity, provenance, source link,
  raw JSON, and an “Open conflict” action.
- Conflict detail shows the timeline and per-event Edit actions.
- Edit mode: conflict fields, event fields (including lat/lon), add event, create conflict.
  “Pick on map” fills coordinates from a map click; manual lat/lon remains available.
- Newly created conflicts without events appear in the list and show an empty state.
- Loading, empty, error, and save states are visible; API errors appear in a live notice
  region rather than failing silently.
- Conflict list entries are native buttons and keyboard operable.
- Show `auto` vs `manual` provenance subtly, so it's clear what the machine produced.

## Commands
- No build step — served at `/` via uvicorn.
- Manual smoke: open `http://localhost:8000`, scrub time, click, edit.

## Project structure (module)
- `app/static/index.html`, `app/static/app.js`, `app/static/style.css`

## Code style
Conventions: CAPABILITY-MAP.md. Plain modern JavaScript, `fetch()` to `/api/*`.

## Testing strategy
- Manual smoke checklist (primary).
- Optional later: Playwright smoke tests (loads, renders markers, scrub triggers fetch).

## Boundaries
- Always: fetch data from `/api/*` (never hardcode data in JS).
- Ask first: adding a JS framework/build step, adding map providers needing keys.
- Never: embed API keys in static files.

## Success criteria
- Load `/`, see conflict markers for a seeded dataset.
- A 30-day range renders clustered markers without freezing the map; every event with
  coordinates is present (grouped, not dropped).
- Changing the time range updates markers without a full reload.
- Clicking a marker shows its news; editing a conflict or event persists and re-renders.
- Editing an event’s coordinates moves its marker after save.
- A manually created conflict is visible before it has events.
- Invalid forms show an understandable error instead of failing silently.

## Open questions
- Basemap: OSM standard tiles OK? (free, no key) — yes.
- Marker style: colour = intensity vs size = intensity vs both — both, size scaled 9–21 px.
- Clustering library: `leaflet.markercluster` 1.5.3 from unpkg (no build step, no key).
  Approved; it is the only added frontend dependency.
