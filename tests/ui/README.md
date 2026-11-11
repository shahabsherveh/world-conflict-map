# UI tests (headless)

Two harnesses, both read-only and both opt-in:

- `map-smoke.mjs` loads the real `index.html` + Leaflet + `leaflet.markercluster` +
  `app.js` in [jsdom](https://github.com/jsdom/jsdom) and drives them against a running
  API. It covers the JavaScript regressions — cluster loading, marker counts, time
  scrubbing, DOM shapes — without a browser install.
- `browser-tests.mjs` drives a real Chrome over CDP: hit-testing, popup anchoring,
  computed CSS, basemap tiles, Pick-on-map. Setup is in “Browser tests” below.

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
`docker compose run --rm web python scripts/seed.py` for the Docker stack) or the real
DB. Unfiltered GDELT events often share country-centroid coordinates; clustering keeps
those events in a bubble at every zoom, so the harness passes on the real 13k-event DB.
Spiderfy still needs a browser, so the coincident-event check lives in the browser suite.

The harness is independent of how *dense* the fixture is, not of whether there is one at
all: an empty database has no event to anchor the time-scrub window to, so seed first.
A single-conflict fixture is handled too — the viewport check reports `SKIPPED` rather
than passing on a 1 → 0 edge case. Panels whose population is empty ("No location" when
every event is geocoded) assert that they are hidden, not that they have rows.

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

## What jsdom cannot assert

jsdom has no layout engine or CSS. The viewport is stubbed (1200x800) so Leaflet
computes usable bounds, but **visual** regressions — marker colours, cluster bubble
styling, popup positioning — need a real browser. That is what the next harness is for.

## Browser tests (`browser-tests.mjs`)

Drives the real Chrome already running on `:9222` over CDP, with no npm dependency
(Node 22+ has global `fetch` and `WebSocket`). Expectations are read from `/api/events`,
so it works against a seeded DB or the real GDELT data.

```bash
# terminal 1: API on a seeded DB
uvicorn app.main:app --reload --port 8000

# terminal 2: Chrome started as below, then
cd tests/ui
node browser-tests.mjs        # or: npm run test:browser
```

Defaults to the API on `:8000` and Chrome on `:9222`. Override with `BASE_URL`/`CDP_URL`
— useful to keep the dev server on `:8000` while the tests hit a throwaway seeded DB:

```bash
BASE_URL=http://127.0.0.1:8011 node browser-tests.mjs
```

It never saves an edit, and proves it: the Pick-on-map check asks `/api/events/{id}`
afterwards and fails if a coordinate was written.

### What it asserts

- Conflicts and markers render; no uncaught JS errors or `console.error` calls.
- At least one OpenStreetMap tile response is 200 — the basemap is really there.
- A real mouse click on a drawn cluster bubble zooms the map.
- Coincident events are individually reachable at max zoom: GDELT puts hundreds of events
  on one country centroid, so the test jumps to the most crowded coordinate, clicks its
  bubble, and requires the event dots to land on distinct pixels instead of stacking on
  one. (A coordinate with no duplicate skips.)
- Clicking the pixel at the map centre opens the popup of *that* event: the map is
  centred on the event, so the test knows which dot should be under the cursor. The popup
  checks pick an event that is alone at its coordinate; shared ones belong to the stack
  check above.
- The popup is anchored above the clicked marker (centre within 40 px; 0 px offset and
  a 7 px gap on the seeded DB).
- The corroboration badge prints the API's counts; the `strong` variant computes to
  `rgb(209, 231, 221)` / `rgb(15, 81, 50)`; a one-outlet event stays `rgb(227, 227, 227)`;
  an event with null counts shows no badge.
- The detail pane mirrors the popup's heading and badge.
- "Set location" on a no-location row arms picking, a map click fills both coordinate
  inputs and ends picking mode — and the API still reports the event unplaced.

A missing example skips rather than fails (no cluster, no one-outlet event, no unplaced
row — e.g. an old DB), so the suite can run anywhere. Like the jsdom harness it is not
part of `pytest` or `scripts/ci-check.sh`: it needs Chrome, a server, and network for
tiles.

## Chrome setup (`browser-tests.mjs` and the chrome-devtools MCP)

Chrome cannot be launched by the MCP in this container (no binary at
`/opt/google/chrome`, and `chrome-devtools-mcp` refuses to launch as root), so start it
yourself and let both the test script and the MCP attach over CDP. Chrome for Testing
installs into the repo's gitignored `chrome/` directory, which lives on the workspace
volume, so it survives a container rebuild:

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
`evaluate_script`, `take_screenshot`, `list_console_messages`, …) for exploratory checks.
`browser-tests.mjs` is the reproducible version; the MCP is for looking around. Gotchas:
`new_page` waits for the `load` event and can time out while map tiles are still
fetching — the page is loaded, so carry on with it; `evaluate_script` returns prose plus
a fenced `json` block; cluster labels only count events inside the current viewport, so
compare totals to `/api/events` at the initial world view, not after zooming.

What a real browser adds over the jsdom harness: real hit-testing (a click lands on the
marker drawn at that pixel), popup positioning, computed CSS, "Pick on map", and the
basemap.

Verified in headless Chrome 157 (and 149 before the rebuild): 13,066 geolocated events
render as ~37 cluster bubbles plus individual dots at world view (labels summing to
13,066), scrubbing to 3 days re-renders exactly 4,275, cluster clicks zoom, the 398 events
at one Israeli centroid spiderfy to 398 distinct pixels at max zoom, event clicks open
popup + detail, "Pick on map" fills lat/lon, OSM tiles 200, and no console messages.
The automated suite passes all checks on the seeded DB, including the three badge states
(green counts, muted single outlet, no badge for null counts).
On the seeded demo DB the corroboration badge was checked in the same browser: a
multi-outlet event shows `4 outlets · 12 articles` in green, a single outlet shows the
muted counts, and an event with no stored raw row shows no badge at all.

A true visual pass (colours, contrast, cluster aesthetics) still belongs to a human eye.
Neither harness is wired into `pytest` or the CI gates (`docs/ci-cd.md`): the jsdom one
needs npm and a running server, and it cannot render markercluster's spiderfy layer, so
the coincident-event check lives in the browser suite; the browser one additionally needs
Chrome and network for tiles. `scripts/seed.py` seeds one conflict with a single unplaced
event, so the "No location" panel and its set-location flow are exercisable from demo
data. The viewport-narrowing checks still assume a populated database (with five demo
conflicts, the cluster click has already zoomed the list down to one row).
