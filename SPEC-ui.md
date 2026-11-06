# Spec: ui — interactive map + time scrub + manual edit

## Objective
A single-page map UI: conflict markers sized/colored by intensity, time-range controls
that re-query the API, click-for-news, and manual edit/create controls.

## Tech stack
Leaflet + OpenStreetMap tiles, vanilla HTML/CSS/JS, served by FastAPI. No build step.
(Conventions: CAPABILITY-MAP.md)

## Behavior
- Map centered on world; one marker per event, grouped by Leaflet.markercluster at low
  zoom. Cluster bubbles encode event density twice — colour on a log-scaled heat ramp
  (blue = few, red = many) and size — and print the event count, so hotspots are legible
  at a glance while the DOM stays bounded (a 30-day range is ~13k events). Single events
  are small dots (6–12 px, well under the smallest bubble) on the same ramp, driven by
  intensity so severity still reads once you zoom in. A legend bottom-left explains it.
- Time controls (start + end date inputs) → `GET /api/events` + `GET /api/conflicts` → re-render.
- Click marker → event detail with place/date/type/actors/intensity, provenance, source link,
  raw JSON, and an “Open conflict” action.
- Conflict detail shows the timeline and per-event Edit actions.
- Edit mode: conflict fields, event fields (including lat/lon), add event, create conflict.
  “Pick on map” fills coordinates from a map click; manual lat/lon remains available.
- The conflicts panel lists only conflicts with at least one event inside the current map
  view (pan/zoom re-filter the already-fetched data, no extra API calls), headed
  “Conflicts in view (N of M · E events)”. Membership is decided from the events, not the
  conflict's single summary coordinate: a conflict spans many places, and its summary
  point is just its latest event in range, so testing that one point drops conflicts whose
  incidents are on screen. Clicking a row centres on the in-view event, not the summary
  point. Conflicts whose events are all ungeocoded (GDELT leaves roughly 500 events in a
  30-day window without coordinates) have no location and are
  summarised in one muted note (`X off-screen, Y with no location, Z with no events yet`);
  a newly created conflict opens in the detail panel with an empty state instead of a list
  row.
- Loading, empty, error, and save states are visible; API errors appear in a live notice
  region rather than failing silently.
- Conflict list entries are native buttons and keyboard operable.
- Show `auto` vs `manual` provenance subtly, so it's clear what the machine produced.
- Conflicts with no geocoded event appear in a separate “No location (N)” panel that never
  places them on the map; see the feature spec below for the full contract.

## Commands
- No build step — served at `/` via uvicorn.
- Manual smoke: open `http://localhost:8000`, scrub time, click, edit.

## Project structure (module)
- `app/static/index.html`, `app/static/app.js`, `app/static/style.css`

## Code style
Conventions: CAPABILITY-MAP.md. Plain modern JavaScript, `fetch()` to `/api/*`.

## Testing strategy
- `tests/ui/map-smoke.mjs`: jsdom + real Leaflet/markercluster against a running server —
  marker/cluster counts checked against `/api/events`, bounded DOM, cluster clicks, scrub.
  Run it when touching `app.js`; it is not part of pytest (needs npm + a server).
- Real-browser checks through the `chrome-devtools` MCP (headless Chrome on `:9222`):
  hit-testing, popups, "Pick on map", basemap. Setup: `tests/ui/README.md`.
- A human visual pass (colour/contrast, cluster aesthetics) remains the last word.

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
- A manually created conflict opens in the detail panel before it has events.
- Invalid forms show an understandable error instead of failing silently.

## Feature spec: surfacing no-location conflicts

### Objective
Every conflict in the store should be reachable from the UI — including the ones the
geocoder could not place. In a 30-day window about **493 of 1,670** conflicts are
invisible: GDELT delivered exactly one event for each and left that event without
latitude/longitude, so no marker is drawn and the in-view list (correctly) excludes them.
The map's only trace of them is one muted count.

Goal: make them discoverable and, above all, **fixable by hand** — without ever guessing
coordinates.

### Why they are not placed on the map
- **Country centroid** — that is GDELT's own failure mode (Gotcha #2) and the practice that
  corrupted records before (Gotcha #3). A marker must never claim a place the source did
  not state.
- **Edge “bucket” markers** — invent a position and add permanent noise to the basemap.
- **Automatic re-geocoding** — forbidden (AGENTS.md: *never* rewrite coordinates).

So these conflicts get a home in the sidebar, not on the basemap.

### Behavior
- A second collapsible in the sidebar, sibling to “Conflicts in view”, titled
  **“No location (N)”**; hidden when `N = 0`; collapsed by default.
- `N` = conflicts in the selected range that **have an event in range but no geolocated
  one** — the same number the in-view note reports, computed in the same pass so the two
  can never disagree.
- A conflict with no events yet is **not** listed here: it is empty rather than
  unplaceable, and the detail panel already gives it an empty state. It is counted
  separately in the note (`Z with no events yet`).
- Rows, newest event first: name — or the headline when the name is the grouping
  placeholder — event date, place, and a muted “no coordinates” badge. Native `<button>`s,
  keyboard operable, escaped like every other list.
- Clicking a row opens its conflict detail; the map does **not** move (there is nowhere to
  move to).
- Each row carries **“Set location →”**: opens the conflict, expands its event's edit form
  and arms the existing “Pick on map” mode. The user clicks the map, saves, the event gains
  coordinates, `loadConflicts()` refreshes markers and lists, and the conflict leaves this
  section. If a conflict has several unplaced events, the action opens the conflict detail
  rather than guessing which one was meant.
- At most 200 rows, with a trailing note “showing 200 of N — narrow the date range to see
  the rest”.
- Grouping names a conflict after its place, and these have none, so all 493 arrive as
  “Unnamed conflict”. A row therefore leads with the headline when the name is empty or
  that placeholder, clamped to two lines; the placeholder name is not shown.
- Nothing is ever written without a user click on the map (or typed lat/lon).

### Data and API
No schema or API change. `GET /api/events` already returns the ungeocoded events (13,559 in
range here, 493 without coordinates) and `GET /api/conflicts` already returns the conflicts
with `lat = null`. The section is derived client-side from the payloads already fetched,
from the same `rangeEvents` array that feeds the header and the in-view list.

### Interaction with existing rules
- “Conflicts in view” keeps its event-based membership; unplaced conflicts never match it.
- The header denominator `M` stays “conflicts active in the range”, so the books balance:
  **in-view + off-screen + no-location + with-no-events = M**.
- A conflict with no events is never offered a “Set location” action; if a row is ever
  clicked after its event gained coordinates, the handler says so instead of pretending
  there are several candidates.
- Manual placement reuses `PATCH /api/events/{id}` and its `edit_log` row; provenance stays
  `auto` unless the user changes it — the edit log is the audit trail.

### Testing strategy
- jsdom harness: section appears with the expected count, hides at zero, rows are buttons,
  every row still has an unplaced event (so an empty conflict can never appear there),
  clicking a row leaves the map view unchanged, “Set location” arms picking mode, and
  header / note / section counts agree. Changing to a range with nothing in it clears the
  panel instead of leaving the previous range's rows on screen.
- Never save a coordinate from an automated test against the live DB; assert up to the
  point where the user would click the map.
- Real browser (chrome-devtools MCP): one full placement on a throwaway conflict, then
  revert it, plus a screenshot for the visual record.

### Boundaries
- Always: derive the list from the same payloads as the rest of the UI.
- Ask first: adding an API filter (e.g. `has_coords=false`), any bulk-placement tool.
- Never: infer coordinates from `place_name`/`country`; write coordinates without explicit
  user action; auto-geocode during ingestion.

### Success criteria
- With 493 no-location conflicts in range, the section shows 493 and the note in
  “Conflicts in view” shows the same number.
- Every row is keyboard reachable, opens the right conflict, and never moves the map.
- “Set location” ends in a saved coordinate in ≤3 interactions (row → map click → save) for
  a single-event conflict; the marker then appears and the row disappears.
- Nothing is silently hidden: in-view + off-screen + no-location = range total.

### Decisions (resolved)
1. Cap at 200 rows with a note — 493 rows of a collapsed panel is not worth rendering.
2. Do not auto-open the section; the header count is the signal.
3. No “next unplaced” queue for now — placement is a rare, deliberate act.

## Open questions
- Basemap: OSM standard tiles OK? (free, no key) — yes.
- Marker style: colour = intensity vs size = intensity vs both — both: single dots 6–12 px,
  cluster bubbles 30–52 px on the shared heat ramp.
- Clustering library: `leaflet.markercluster` 1.5.3 from unpkg (no build step, no key).
  Approved; it is the only added frontend dependency.
