# UI smoke test (headless)

`map-smoke.mjs` loads the real `index.html` + Leaflet + `leaflet.markercluster` +
`app.js` in [jsdom](https://github.com/jsdom/jsdom) and drives them against a running
API. It exists because the interesting regressions here are JavaScript ones — cluster
loading, marker counts, time scrubbing — and this environment has no browser.

```bash
# terminal 1
uvicorn app.main:app --reload --port 8000

# terminal 2
cd tests/ui
npm install
node map-smoke.mjs          # or: BASE_URL=http://localhost:8000 node map-smoke.mjs
```

Requires Node 18+ (global `fetch`). The library files are downloaded from unpkg once and
cached under `node_modules/.cache/ui-smoke/`.

## What it asserts

- Leaflet and markercluster load; `app.js` throws no uncaught errors.
- The conflict list renders and no error notice is shown.
- Every geolocated event in the default 30-day window is in the cluster layer tree
  (counts are checked against `/api/events`, not hardcoded).
- The DOM stays bounded: ~13k events render as a few dozen cluster icons.
- Clicking a cluster raises no errors.
- Changing the "From" date re-queries and re-renders the exact set for the new range.

## What it cannot assert

jsdom has no layout engine or CSS. The viewport is stubbed (1200x800) so Leaflet
computes usable bounds, but **visual** regressions — marker colours, cluster bubble
styling, popup positioning — still need a real browser:

```bash
# manual: open http://localhost:8000, scrub the range, click a marker, edit an event
```

This harness is deliberately not wired into `pytest`/CI: it needs npm and a running
server, and `AGENTS.md` treats new dependencies as a decision, not a default.
