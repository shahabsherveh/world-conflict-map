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

async function expectedMarkers(start, end) {
  const res = await fetch(`${BASE_URL}/api/events?start=${start}&end=${end}`);
  if (!res.ok) throw new Error(`GET /api/events ${res.status}`);
  const events = await res.json();
  return events.filter((e) => e.lat != null && e.lon != null).length;
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

// chunkedLoading adds events progressively, so wait until the rendered total
// stops growing instead of guessing a fixed delay.
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
  window.fetch = (url, opts) => fetch(new URL(url, BASE_URL).toString(), opts);
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

  window.eval(fs.readFileSync(path.join(STATIC, "app.js"), "utf8"));

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

  // Clicking a cluster must zoom/expand without throwing.
  const clusterNode = doc.querySelector(".leaflet-marker-icon.cluster");
  if (clusterNode) {
    clusterNode.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
  }
  check("cluster click raises no errors", errors.length === 0, errors.join(" | "));

  // Time scrub: a 3-day window must re-query and re-render from scratch.
  setDateInput(window, "start-date", isoDate(daysAgo(3)));
  const expectedNarrow = await expectedMarkers(isoDate(daysAgo(3)), isoDate(new Date()));
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
    `${second.layers} layers vs ${expectedNarrow} for ${isoDate(daysAgo(3))}..${isoDate(new Date())}`,
  );
  check(
    "scrubbed range is smaller than the full window",
    second.layers < first.layers || expectedNarrow >= expectedDefault,
    `${second.layers} vs ${first.layers}`,
  );

  console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL CHECKS PASSED");
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error("HARNESS ERROR:", err);
  process.exit(2);
});
