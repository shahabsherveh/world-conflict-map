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

Use a freshly seeded DB (from the repo root: `python scripts/seed.py`, or
`docker compose run --rm web python scripts/seed.py` for the Docker stack) or a
model-filtered DB. Unfiltered GDELT events often share country-centroid coordinates;
Leaflet spiderfies duplicate points, and jsdom cannot render that layer, so the
cluster-click and scrub checks fail for harness reasons rather than app reasons.

## What it asserts

- Leaflet and markercluster load; `app.js` throws no uncaught errors.
- The conflict list renders and no error notice is shown.
- Every geolocated event in the default 30-day window is in the cluster layer tree
  (counts are checked against `/api/events`, not hardcoded).
- The DOM stays bounded: ~13k events render as a few dozen cluster icons.
- Cluster bubbles encode density: hue is monotone cooler→hotter and size grows as the
  event count rises; the density legend exists.
- Clicking a cluster raises no errors.
- Changing the "From" date re-queries and re-renders the exact set for the new range.
- The conflicts panel follows the viewport: drilling into a conflict narrows the list, the
  "N of M · E events" summary matches the rendered rows, the clicked conflict stays listed,
  and the remainder note is real text (not `[object Object]`).
- Single-event dots are smaller than the smallest cluster bubble.
- The event popup's corroboration badge: counts are printed, the `strong` variant appears
  only when the API sets `well_corroborated`, unknown counts render nothing, and values are
  escaped. (The popup is a pure function of the payload, so this needs no layout.)
- The "No location" panel counts the conflicts with no geocoded event (checked against the
  API), caps its rows with a note, opens detail without moving the map, and arms
  Pick-on-map from a row. It never saves a coordinate — that stays a human action.
- A conflict with no events at all (injected into the payload, never written to the DB) is
  counted as "no events yet" instead of being offered for placement.
- Changing to a range with no conflicts clears the conflict list, the markers and the
  "No location" panel — no stale rows from the previous range.

## What it cannot assert

jsdom has no layout engine or CSS. The viewport is stubbed (1200x800) so Leaflet
computes usable bounds, but **visual** regressions — marker colours, cluster bubble
styling, popup positioning — still need a real browser.

## Real-browser checks (`chrome-devtools` MCP)

Chrome cannot be launched by the MCP in this container (no binary at
`/opt/google/chrome`, and `chrome-devtools-mcp` refuses to launch as root), so start it
yourself and let the MCP attach over CDP. Chrome for Testing installs into the repo's
gitignored `chrome/` directory, which lives on the workspace volume, so it survives a
container rebuild:

```bash
# once per checkout
npx -y @puppeteer/browsers install chrome@stable

# every session
chrome/linux-*/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --remote-debugging-port=9222 \
  --user-data-dir=chrome/profile about:blank &

pi mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest \
  --browserUrl http://127.0.0.1:9222
```

On a bare Debian image Chrome needs shared libraries the app itself does not. A missing
`libglib-2.0.so.0` is the tell:

```bash
apt-get update && apt-get install -y --no-install-recommends \
  libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
  libpango-1.0-0 libcairo2 libasound2
```

Then drive it with the codemode tools (`mcp__chrome_devtools__list_pages`,
`evaluate_script`, `take_screenshot`, `list_console_messages`, …). Gotchas: `new_page`
waits for the `load` event and can time out while map tiles are still fetching — the page
is loaded, so carry on with it; `evaluate_script` returns prose plus a fenced `json`
block; cluster labels only count events inside the current viewport, so compare totals to
`/api/events` at the initial world view, not after zooming.

What a real browser adds over the jsdom harness: real hit-testing (clicking a cluster or a
marker dot), popup/sidebar rendering, "Pick on map", and the basemap.

Verified in headless Chrome 157 (and 149 before the rebuild): 13,066 geolocated events
render as ~37 cluster bubbles plus individual dots at world view (labels summing to
13,066), scrubbing to 3 days re-renders exactly 4,275, cluster clicks zoom, event clicks
open popup + detail, "Pick on map" fills lat/lon, OSM tiles 200, and no console messages.
On the seeded demo DB the corroboration badge was checked in the same browser: a
multi-outlet event shows `4 outlets · 12 articles` in green, a single outlet shows the
muted counts, and an event with no stored raw row shows no badge at all.

A true visual pass (colours, contrast, cluster aesthetics) still belongs to a human eye.
This harness is deliberately not wired into `pytest` or the CI gates (`docs/ci-cd.md`):
it needs npm and a running server, and at world zoom its cluster-click check spiderfies,
which jsdom cannot render without an SVG/canvas layer — it would fail for harness
reasons, not app reasons. `scripts/seed.py` seeds one conflict with a single unplaced
event, so the "No location" panel and its set-location flow are exercisable from demo
data. The viewport-narrowing checks still assume a populated database (with five demo
conflicts, the cluster click has already zoomed the list down to one row).
