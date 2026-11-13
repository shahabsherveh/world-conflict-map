// Headless smoke test for the map UI.
//
// Loads the real index.html + Leaflet + leaflet.markercluster + app.js in jsdom
// and drives it against a running API, so map rendering, clustering and the
// time scrub are exercised without a browser install. It is a complement to the
// manual browser check, not a replacement: jsdom has no layout engine, so the
// viewport is stubbed and CSS/visual regressions are out of scope.
//
// Usage:
//   cd tests/ui && npm install && node map-smoke.mjs
//   BASE_URL=http://localhost:8000 node map-smoke.mjs
//
// Requires Node 18+ (global fetch) and a server started with
// `uvicorn app.main:app --reload --port 8000`.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.resolve(HERE, "../../app/static");
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8000";
const CACHE = path.join(HERE, "node_modules/.cache/ui-smoke");
const CDN = [
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.js",
  "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
];

// jsdom reports every element as 0x0. Without a viewport Leaflet computes empty
// bounds and collapses all markers into one degenerate cluster, which hides
// real layout-dependent behaviour.
const VIEWPORT = { width: 1200, height: 800 };

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures += 1;
}

const isoDate = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86_400_000);

async function fetchRange(start, end) {
  const [eventsRes, conflictsRes] = await Promise.all([
    fetch(`${BASE_URL}/api/events?start=${start}&end=${end}`),
    fetch(`${BASE_URL}/api/conflicts?start=${start}&end=${end}`),
  ]);
  // A 500 on an empty database means the schema was never migrated, not that the
  // UI is broken. Say so instead of failing a map check for the wrong reason.
  if (!eventsRes.ok || !conflictsRes.ok) {
    const status = !eventsRes.ok ? eventsRes.status : conflictsRes.status;
    if (status === 500) {
      throw new Error(
        `API returned 500 for ${BASE_URL} — is the database migrated? ` +
          "Run `alembic upgrade head` against it first.",
      );
    }
    throw new Error(`GET /api/${eventsRes.ok ? "conflicts" : "events"} ${status}`);
  }
  return { events: await eventsRes.json(), conflicts: await conflictsRes.json() };
}

async function expectedMarkers(start, end) {
  const { events } = await fetchRange(start, end);
  return events.filter((e) => e.lat != null && e.lon != null).length;
}

// The "No location" panel's population: conflicts with an event in range but no
// geolocated one. A conflict with no events at all is empty, not unplaceable, and
// belongs in the detail panel's empty state.
function expectedNoLocation({ events, conflicts }) {
  const located = new Set();
  const eventful = new Set();
  for (const e of events) {
    if (e.conflict_id == null) continue;
    eventful.add(e.conflict_id);
    if (e.lat != null && e.lon != null) located.add(e.conflict_id);
  }
  return {
    count: conflicts.filter((c) => eventful.has(c.id) && !located.has(c.id)).length,
    unplacedIds: new Set(
      events
        .filter((e) => (e.lat == null || e.lon == null) && e.conflict_id != null)
        .map((e) => e.conflict_id),
    ),
  };
}

function cachePath(url) {
  return path.join(CACHE, url.replace(/^https:\/\//, "").replace(/\//g, "_"));
}

async function fetchLib(url) {
  const file = cachePath(url);
  if (!fs.existsSync(file)) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not download ${url} (${res.status})`);
    fs.mkdirSync(CACHE, { recursive: true });
    fs.writeFileSync(file, await res.text());
  }
  return fs.readFileSync(file, "utf8");
}

function stubLayout(window) {
  for (const [prop, value] of [
    ["clientWidth", VIEWPORT.width],
    ["offsetWidth", VIEWPORT.width],
    ["clientHeight", VIEWPORT.height],
    ["offsetHeight", VIEWPORT.height],
  ]) {
    Object.defineProperty(window.HTMLElement.prototype, prop, {
      configurable: true,
      get: () => value,
    });
  }
  window.Element.prototype.getBoundingClientRect = () => ({
    width: VIEWPORT.width,
    height: VIEWPORT.height,
    left: 0,
    top: 0,
    right: VIEWPORT.width,
    bottom: VIEWPORT.height,
    x: 0,
    y: 0,
  });
}

// Cluster labels are only refreshed when a chunk finishes, so DOM text lags
// behind during loading. The layer tree is the authoritative count of events on
// the map; the DOM node count is only used to prove rendering stays bounded.
function readRendered(window) {
  const doc = window.document;
  return {
    clusters: doc.querySelectorAll(".leaflet-marker-icon.cluster").length,
    dots: doc.querySelectorAll(".leaflet-marker-icon.event-dot").length,
    layers: window.__markers ? window.__markers.getLayers().length : 0,
  };
}

// The list is filled by the same fetch that feeds the map, so it is the signal
// that data has arrived. Polling for it avoids reading an empty map as "stable".
async function waitForData(doc, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (doc.querySelectorAll("#conflict-list .conflict-item").length > 0) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

// For ranges that render nothing: wait for the empty-state message instead.
async function waitForListMessage(doc, pattern, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const text = doc.querySelector("#conflict-list .empty")?.textContent ?? "";
    if (pattern.test(text)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

// Wait for a bit of text the list is expected to gain after a re-fetch.
async function waitForText(doc, selector, pattern, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    last = doc.querySelector(selector)?.textContent ?? "";
    if (pattern.test(last)) return last;
    await new Promise((r) => setTimeout(r, 200));
  }
  return last;
}

// Markers are added in chunks (renderEventMarkers), so wait until the rendered
// total stops growing instead of guessing a fixed delay.
async function waitForStable(window, { timeoutMs = 30_000, quietPolls = 6 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let last = -1;
  let quiet = 0;
  while (Date.now() < deadline && quiet < quietPolls) {
    await new Promise((r) => setTimeout(r, 250));
    const { layers } = readRendered(window);
    quiet = layers === last ? quiet + 1 : 0;
    last = layers;
  }
  return readRendered(window);
}

function setDateInput(window, id, value) {
  const input = window.document.getElementById(id);
  input.value = value;
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
}

async function main() {
  try {
    const health = await fetch(`${BASE_URL}/`);
    if (!health.ok) throw new Error(`GET / ${health.status}`);
  } catch (err) {
    console.error(`Cannot reach ${BASE_URL}: ${err.message}`);
    console.error("Start it first: uvicorn app.main:app --reload --port 8000");
    process.exit(2);
  }

  const dom = new JSDOM(fs.readFileSync(path.join(STATIC, "index.html"), "utf8"), {
    url: `${BASE_URL}/`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const doc = window.document;
  // Optional synthetic conflict for the "no events yet" case below. Injecting it
  // into the payload keeps the harness read-only, which is the rule for the live
  // DB (no test creates or edits records).
  let injectEmptyConflict = false;
  const EMPTY_CONFLICT_ID = 999999;
  window.fetch = async (url, opts) => {
    const response = await fetch(new URL(url, BASE_URL).toString(), opts);
    if (!injectEmptyConflict || !String(url).startsWith("/api/conflicts")) return response;
    const conflicts = await response.json();
    conflicts.push({
      id: EMPTY_CONFLICT_ID,
      name: "Manual conflict with no events yet",
      country: "UA",
      start_date: isoDate(new Date()),
      end_date: null,
      status: "active",
      intensity: 0,
      lat: null,
      lon: null,
      event_count: 0,
      headline: null,
    });
    return new Response(JSON.stringify(conflicts), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  stubLayout(window);

  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.message));

  window.eval(await fetchLib(CDN[0]));
  check("leaflet loaded", typeof window.L === "object" && typeof window.L.map === "function");

  window.eval(await fetchLib(CDN[1]));
  check(
    "markercluster loaded",
    typeof window.L.markerClusterGroup === "function",
    "otherwise every event renders as its own marker",
  );

  // Capture the cluster group so counts can be read from the layer tree, not
  // just from whatever the DOM happens to show.
  const markerClusterGroup = window.L.markerClusterGroup;
  window.L.markerClusterGroup = (...args) => {
    const group = markerClusterGroup(...args);
    window.__markers = group;
    return group;
  };

  // The scripts share one global scope via plain <script> tags in the browser;
  // jsdom's repeated window.eval does not share const/let across calls, so eval
  // the concatenation (same order index.html serves them) as a single script.
  // Script *loading order* fidelity (a real global-scope concern) is covered by
  // browser-tests.mjs against real Chrome; this harness asserts the logic.
  const scriptOrder = ["map.js", "state.js", "list.js", "detail.js", "app.js"];
  window.eval(scriptOrder.map((f) => fs.readFileSync(path.join(STATIC, f), "utf8")).join("\n"));

  // The event popup is a pure function of the payload, so its corroboration badge
  // can be asserted without a browser; only popup *positioning* needs one.
  const eventPopup = window.eval("eventPopup");
  const popup = (overrides) =>
    eventPopup({
      id: 1,
      headline: "Clash",
      place_name: "X",
      country: "SY",
      event_date: "2024-01-01",
      event_type: "battle",
      intensity: 3,
      provenance: "auto",
      source_url: "https://example.com/a",
      sources: null,
      articles: null,
      well_corroborated: false,
      ...overrides,
    });
  const strong = popup({ sources: 4, articles: 12, well_corroborated: true });
  check("popup shows the corroboration counts", /4 outlets · 12 articles/.test(strong));
  check(
    "popup marks a well-corroborated event",
    /class="corroboration strong"/.test(strong),
    "single-outlet events must not be labelled well corroborated",
  );
  check(
    "popup leaves a single-outlet event muted",
    !/corroboration strong/.test(
      popup({ sources: 1, articles: 12, well_corroborated: false }),
    ),
  );
  check(
    "unknown counts render no badge",
    !/corroboration/.test(popup({ sources: null, articles: null })),
  );
  check(
    "corroboration values are escaped",
    !/<img/.test(popup({ sources: "<img>", articles: 1, well_corroborated: false })),
  );

  const expectedDefault = await expectedMarkers(isoDate(daysAgo(30)), isoDate(new Date()));
  check("map data arrived", await waitForData(doc));
  const first = await waitForStable(window);
  const notice = () => doc.getElementById("notice");

  check("no uncaught JS errors", errors.length === 0, errors.join(" | "));
  check(
    "no error notice",
    notice().hidden || !/error/.test(notice().className),
    notice().textContent,
  );
  check(
    "conflict list rendered",
    doc.querySelectorAll("#conflict-list .conflict-item").length > 0,
    `${doc.querySelectorAll("#conflict-list .conflict-item").length} entries`,
  );
  check("clusters rendered", first.clusters > 0, `${first.clusters} clusters`);
  // Density must drive both colour (heat ramp) and size: cool/small → hot/large.
  const heat = [...doc.querySelectorAll(".leaflet-marker-icon.cluster")]
    .map((el) => {
      const style = el.querySelector("span")?.getAttribute("style") || "";
      return {
        count: Number(el.textContent) || 0,
        hue: Number((/hsl\((\d+)/.exec(style) || [])[1]),
        size: Number.parseFloat(el.style.width) || 0,
      };
    })
    .sort((a, b) => a.count - b.count);
  const hueRange = heat.length ? heat[0].hue - heat[heat.length - 1].hue : 0;
  check(
    "cluster colour ramps from cool to hot with density",
    heat.every((c, i) => i === 0 || c.hue <= heat[i - 1].hue) && hueRange > 20,
    `hue ${heat[0]?.hue}° (${heat[0]?.count} events) → ${heat.at(-1)?.hue}° (${heat.at(-1)?.count})`,
  );
  check(
    "cluster size grows with density",
    heat.every((c, i) => i === 0 || c.size >= heat[i - 1].size),
    `${heat[0]?.size}px → ${heat.at(-1)?.size}px`,
  );
  check(
    "density legend is present",
    Boolean(doc.querySelector("#legend .legend-bar")),
    doc.getElementById("legend")?.textContent?.trim() ?? "",
  );
  // "No location" panel: the conflicts GDELT left ungeocoded.
  const rangeData = await fetchRange(isoDate(daysAgo(30)), isoDate(new Date()));
  const expectedNoLoc = expectedNoLocation(rangeData);
  const table = doc.getElementById("nolocation-panel");
  const rows = doc.querySelectorAll("#nolocation-list .nl-row");

  // An empty panel is correct when the data has nothing to place; assert that
  // instead of demanding rows a fixture may legitimately lack.
  check(
    "no-location panel shows the conflicts with no geocoded event",
    expectedNoLoc.count === 0
      ? table.hidden && rows.length === 0
      : !table.hidden && rows.length === Math.min(expectedNoLoc.count, 200),
    expectedNoLoc.count === 0
      ? `hidden=${table.hidden}, 0 rows expected`
      : `${rows.length} rows, expected ${expectedNoLoc.count}`,
  );
  check(
    "every no-location row still has an event in range",
    [...rows].every((r) =>
      expectedNoLoc.unplacedIds.has(Number(r.querySelector("button.conflict-item").dataset.id)),
    ),
    `${rows.length} rows, ${expectedNoLoc.unplacedIds.size} conflicts with an unplaced event`,
  );
  // With nothing unplaced the UI omits the clause rather than printing "0 with
  // no location", so both forms are correct — a false positive would be a
  // non-zero count that the note fails to mention.
  check(
    "panel count and in-view note agree",
    // An empty panel paints no count at all, so only compare when it shows one.
    doc.getElementById("nolocation-count").textContent ===
      (expectedNoLoc.count === 0 ? "" : `(${expectedNoLoc.count})`) &&
      (expectedNoLoc.count === 0 ||
        new RegExp("\\b" + expectedNoLoc.count + " with no location").test(
          doc.querySelector("#conflict-list .list-note")?.textContent ?? "",
        )),
    doc.querySelector("#conflict-list .list-note")?.textContent ?? "(no note)",
  );
  check(
    "the list is capped with a note instead of rendering everything",
    (() => {
      const note = doc.querySelector("#nolocation-list .list-note")?.textContent ?? "";
      return expectedNoLoc.count <= 200 || /showing 200 of \d+/.test(note);
    })(),
    doc.querySelector("#nolocation-list .list-note")?.textContent ?? "(no cap note)",
  );
  check(
    "rows are distinguishable when the conflict has no name",
    [...doc.querySelectorAll("#nolocation-list .ci-name")].every(
      (n) => !/^unnamed conflict$/i.test(n.textContent.trim()),
    ),
    [...doc.querySelectorAll("#nolocation-list .ci-name")].slice(0, 2).map((n) => n.textContent.slice(0, 40)).join(" | "),
  );
  check(
    "every no-location row is a button and keyboard operable",
    [...rows].every((r) => r.querySelector("button.conflict-item")),
    `${rows.length} rows`,
  );

  // Opening a row must not move the map: the in-view list must be unchanged.
  // Only meaningful when there is a row — see the panel check above.
  const inViewBefore = doc.getElementById("conflict-count").textContent;
  const inViewNoteHadRows = Boolean(doc.querySelector("#nolocation-list .conflict-item"));
  doc.querySelector("#nolocation-list .conflict-item")?.click();
  await new Promise((r) => setTimeout(r, 400));
  check(
    "opening a no-location conflict does not move the map",
    doc.getElementById("conflict-count").textContent === inViewBefore,
    `${inViewBefore} → ${doc.getElementById("conflict-count").textContent}`,
  );
  check(
    "opening a no-location conflict fills the detail pane",
    !inViewNoteHadRows || Boolean(doc.querySelector("#detail h2")),
    inViewNoteHadRows ? (doc.querySelector("#detail h2")?.textContent ?? "") : "SKIPPED (nothing unplaced)",
  );

  // "Set location" must arm the existing pick-on-map flow, not invent a position.
  const placeButton = doc.querySelector("#nolocation-list .nl-place");
  placeButton?.click();
  await new Promise((r) => setTimeout(r, 900));
  check(
    "set-location arms pick-on-map on the unplaced event",
    !placeButton ||
      (doc.getElementById("map").classList.contains("picking") &&
        Boolean(doc.getElementById("edit-ev-lat")) &&
        doc.getElementById("edit-ev-lat").value === ""),
    placeButton ? `picking=${doc.getElementById("map").classList.contains("picking")}` : "SKIPPED (nothing unplaced)",
  );
  // Cancel so the rest of the run is unaffected.
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

  check(
    "single dots are smaller than the smallest cluster",
    (() => {
      const dot = doc.querySelector(".leaflet-marker-icon.event-dot");
      const sizes = heat.map((c) => c.size);
      return !dot || Number.parseFloat(dot.style.width) < Math.min(...sizes);
    })(),
    (() => {
      const dot = doc.querySelector(".leaflet-marker-icon.event-dot");
      return dot ? `${dot.style.width} vs cluster ${Math.min(...heat.map((c) => c.size))}px` : "no dots";
    })(),
  );
  check(
    "rendered icons stay bounded",
    first.clusters + first.dots > 0 && first.clusters + first.dots < 400,
    `${first.clusters} clusters + ${first.dots} dots for ${expectedDefault} events`,
  );
  check(
    "every geolocated event is on the map",
    first.layers === expectedDefault,
    `${first.layers} layers vs ${expectedDefault} expected`,
  );

  // Clicking a cluster must zoom/expand without throwing. Kept at world view:
  // a spiderfy would need an SVG/canvas renderer, which jsdom does not have.
  const clusterNode = doc.querySelector(".leaflet-marker-icon.cluster");
  if (clusterNode) {
    clusterNode.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
  }
  check("cluster click raises no errors", errors.length === 0, errors.join(" | "));

  const readList = () => ({
    items: doc.querySelectorAll("#conflict-list .conflict-item").length,
    label: doc.getElementById("conflict-count").textContent,
  });
  const stableList = async () => {
    let last = -1;
    let quiet = 0;
    let state = readList();
    for (let i = 0; i < 40 && quiet < 4; i += 1) {
      await new Promise((r) => setTimeout(r, 150));
      state = readList();
      quiet = state.items === last ? quiet + 1 : 0;
      last = state.items;
    }
    return state;
  };

  // The panel lists what is on screen: drilling into one conflict narrows it,
  // and the summary number must match the rows actually rendered. Return to the
  // world view first — the cluster clicked above is whichever happens to be
  // first in the DOM, and a view holding a single conflict has nothing left to
  // narrow. World view lists every conflict in range on any fixture.
  doc.querySelector(".leaflet-control.reset-view")?.click();
  const before = await stableList();
  // A fixture with only one conflict cannot demonstrate narrowing at any zoom.
  // Skip rather than pass on a 1 -> 0 edge case that proves nothing.
  const canNarrow = before.items > 1;
  let after = before;
  let clickedId = null;
  if (canNarrow) {
    const firstItem = doc.querySelector("#conflict-list .conflict-item");
    clickedId = firstItem.dataset.id;
    firstItem.click();
    after = await stableList();
  }

  check(
    "conflict list follows the map viewport",
    !canNarrow || (after.items > 0 && after.items < before.items),
    canNarrow
      ? `${before.items} rows → ${after.items} after zooming in`
      : `SKIPPED (single-conflict fixture: ${before.items} row)`,
  );
  check(
    "summary count matches the rendered rows",
    Number((after.label.match(/(\d+)/) || [])[1]) === after.items,
    `label "${after.label}" vs ${after.items} rows`,
  );
  check(
    "the remainder note reads as text, not objects",
    (() => {
      const note = doc.querySelector("#conflict-list .list-note")?.textContent ?? "";
      return !note.includes("[object") && /\d+ (off-screen|with no location)/.test(note);
    })(),
    doc.querySelector("#conflict-list .list-note")?.textContent ?? "(no note)",
  );
  check(
    "summary also reports how many events are in view",
    /\(\d+ of \d+ · [\d,]+ events?\)/.test(after.label),
    after.label,
  );
  check(
    "the conflict you clicked stays in the list",
    !canNarrow ||
      Boolean(doc.querySelector(`#conflict-list .conflict-item[data-id="${clickedId}"]`)),
    clickedId === null ? "SKIPPED (single-conflict fixture)" : `id ${clickedId}`,
  );

  // Time scrub: a populated 3-day window must re-query and re-render from scratch.
  // Anchor the window to the newest event, not wall-clock days: a stale or freshly
  // seeded DB can have nothing in the last three calendar days, which silently turns
  // the scrub assertions into 0-vs-0 tautologies.
  const lastEventDay = rangeData.events.reduce(
    (max, e) => (e.event_date > max ? e.event_date : max),
    "",
  );
  const scrubStart = isoDate(
    new Date(new Date(`${lastEventDay}T00:00:00Z`).getTime() - 2 * 86_400_000),
  );
  setDateInput(window, "start-date", scrubStart);
  const expectedNarrow = await expectedMarkers(scrubStart, isoDate(new Date()));
  await waitForData(doc);
  const second = await waitForStable(window);
  check(
    "scrubbing the range re-renders without errors",
    errors.length === 0,
    errors.join(" | "),
  );
  check(
    "scrubbed range draws exactly the events in that range",
    second.layers === expectedNarrow,
    `${second.layers} layers vs ${expectedNarrow} for ${scrubStart}..${isoDate(new Date())}`,
  );
  check(
    "scrubbed range is smaller than the full window",
    second.layers < first.layers || expectedNarrow >= expectedDefault,
    `${second.layers} vs ${first.layers}`,
  );

  // A conflict with no events at all is empty, not unplaceable: it must not be
  // offered for placement, and it counts in the note under its own label so the
  // header numbers still add up. Run it on the full default window (already proven
  // populated above): the note renders next to the in-view list, so an empty window
  // would leave nothing to inspect.
  const fullStart = isoDate(daysAgo(30));
  const fullConflicts = rangeData.conflicts;
  injectEmptyConflict = true;
  setDateInput(window, "start-date", fullStart);
  setDateInput(window, "end-date", isoDate(new Date()));
  const noEventsNote = await waitForText(
    doc,
    "#conflict-list .list-note",
    /\b1 with no events yet\b/,
  );
  check(
    "a conflict with no events is not offered for placement",
    !doc.querySelector(`#nolocation-list .conflict-item[data-id="${EMPTY_CONFLICT_ID}"]`),
    `${doc.querySelectorAll("#nolocation-list .nl-row").length} rows`,
  );
  check(
    "a conflict with no events is counted as such in the note",
    /\b1 with no events yet\b/.test(noEventsNote) &&
      doc
        .getElementById("conflict-count")
        .textContent.includes(`of ${fullConflicts.length + 1} `),
    noEventsNote || "(no note)",
  );
  check(
    "the empty conflict is not on the map",
    !doc.querySelector(`.leaflet-marker-icon[title*="Manual conflict"]`),
    "no marker",
  );
  injectEmptyConflict = false;

  // A range with nothing in it must clear the sidebar, not just the header. The
  // panel used to be painted only after the "nothing in view" return, so the
  // previous range's rows stayed on screen under an empty header.
  setDateInput(window, "start-date", "2001-01-01");
  setDateInput(window, "end-date", "2001-01-02");
  check(
    "an empty range clears the conflict list",
    await waitForListMessage(doc, /No conflicts in this range/),
    doc.querySelector("#conflict-list .empty")?.textContent ?? "(no empty state)",
  );
  check(
    "an empty range clears the No location panel",
    doc.getElementById("nolocation-panel").hidden &&
      doc.querySelectorAll("#nolocation-list .nl-row").length === 0,
    `${doc.querySelectorAll("#nolocation-list .nl-row").length} rows,` +
      ` hidden=${doc.getElementById("nolocation-panel").hidden}`,
  );
  check(
    "an empty range clears the markers",
    readRendered(window).layers === 0,
    `${readRendered(window).layers} layers`,
  );

  console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL CHECKS PASSED");
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error("HARNESS ERROR:", err);
  process.exit(2);
});
