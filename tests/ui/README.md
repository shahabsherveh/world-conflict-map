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
styling, popup positioning — still need a real browser.

## Real-browser checks (`chrome-devtools` MCP)

Chrome cannot be launched by the MCP in this container (no binary at
`/opt/google/chrome`, and `chrome-devtools-mcp` refuses to launch as root), so start it
yourself and let the MCP attach over CDP:

```bash
/tmp/chrome-dl/chrome-linux64/chrome --headless=new --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-profile about:blank &

pi mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest \
  --browserUrl http://127.0.0.1:9222
```

Then drive it with the codemode tools (`mcp__chrome_devtools__list_pages`,
`evaluate_script`, `take_screenshot`, `list_console_messages`, …). Gotchas: `new_page`
waits for the `load` event and can time out while map tiles are still fetching — the page
is loaded, so carry on with it; `evaluate_script` returns prose plus a fenced `json`
block; cluster labels only count events inside the current viewport, so compare totals to
`/api/events` at the initial world view, not after zooming.

What a real browser adds over the jsdom harness: real hit-testing (clicking a cluster or a
marker dot), popup/sidebar rendering, "Pick on map", and the basemap.

Verified in headless Chrome 149: 13,066 geolocated events render as ~37 cluster bubbles
plus individual dots at world view (labels summing to 13,066), scrubbing to 3 days
re-renders exactly 4,275, cluster clicks zoom, event clicks open popup + detail, "Pick on
map" fills lat/lon, OSM tiles 200, and no console messages.

A true visual pass (colours, contrast, cluster aesthetics) still belongs to a human eye.
This harness is deliberately not wired into `pytest`/CI: it needs npm and a running
server, and `AGENTS.md` treats new dependencies as a decision, not a default.
