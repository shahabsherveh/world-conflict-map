// Map setup, shared helpers, and the per-event marker layer.
// Loaded as a plain script before app.js; everything stays on the global scope
// so the other scripts (and the jsdom smoke test) can reach it without a bundler.
const HOME_VIEW = { center: [25, 15], zoom: 2 };
const map = L.map("map").setView(HOME_VIEW.center, HOME_VIEW.zoom);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

// Cluster per-event markers: a 30-day range holds >13k events here, and one
// Leaflet marker per event made the map unusably slow. Clustering keeps every
// event in the client (no data loss) while bounding the rendered DOM.
// One ramp shared by cluster bubbles (event density) and single dots (severity),
// so colour means the same thing across the map: cool → hot.
function heatColor(t) {
  return `hsl(${Math.round(210 - 210 * t)}, 78%, ${Math.round(52 - 10 * t)}%)`;
}

// Cluster bubbles encode event density twice: colour on the ramp and size.
// Log scale: 1 event → 0, 1000+ → 1. Linear would make everything except the
// handful of huge clusters look identically cool.
function clusterHeat(count) {
  const t = Math.min(1, Math.log10(Math.max(1, count)) / 3);
  return {
    size: Math.round(28 + 24 * t),
    background: heatColor(t),
    // Mid-ramp colours (green/yellow) need dark text to stay readable.
    color: t > 0.32 && t < 0.8 ? "#1b1b1b" : "#fff",
  };
}

const markers = L.markerClusterGroup({
  // Chunking is done in renderEventMarkers(), not by chunkedLoading: the
  // library's loader lives in a closure that clearLayers() cannot cancel, so a
  // new range could be drawn while the previous one was still trickling in.
  maxClusterRadius: 55,
  // Clustering stays on at every zoom. Disabling it at 13 used to dissolve the
  // bubble for the hundreds of events GDELT geocodes to one country centroid,
  // stacking every dot on a single pixel where only the topmost was clickable.
  // Keeping the bubble lets a click at max zoom spiderfy the stack instead.
  showCoverageOnHover: false,
  iconCreateFunction(cluster) {
    const count = cluster.getChildCount();
    const heat = clusterHeat(count);
    const label = `${count} event${count === 1 ? "" : "s"}`;
    return L.divIcon({
      className: "cluster",
      iconSize: L.point(heat.size, heat.size),
      html: `<span title="${label}" style="background:${heat.background};color:${heat.color}">${count}</span>`,
    });
  },
});
// addTo() after the assignment keeps `markers` usable from any option callback.
markers.addTo(map);

// A way back to the world view: after drilling into a cluster there was no
// obvious route out short of dragging the map.
const ResetViewControl = L.Control.extend({
  options: { position: "topright" },
  onAdd() {
    const button = L.DomUtil.create("button", "reset-view");
    button.type = "button";
    button.textContent = "Reset view";
    button.title = "Zoom back out to the world";
    L.DomEvent.disableClickPropagation(button);
    L.DomEvent.on(button, "click", () => map.setView(HOME_VIEW.center, HOME_VIEW.zoom));
    return button;
  },
});
new ResetViewControl().addTo(map);

// Shared across the list/marker/detail scripts; hoisted so order does not matter.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayISO() {
  return fmtDate(new Date());
}

function parseDateInput(value) {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function numberOrNull(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function intOrNull(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : NaN;
}

// Chunk size chosen so one slice stays well under a frame's budget at world
// zoom; a full 30-day window (~13k events) lands in a handful of ticks.
const MARKER_CHUNK_SIZE = 1000;
// Bumped on every render; a chunk loop from an older render sees the mismatch
// and stops instead of adding markers for a range the user already left.
let markerGeneration = 0;

function intensityClass(intensity) {
  return Math.max(1, Math.min(5, Math.round(intensity || 1)));
}

// One marker per EVENT: a conflict can span several cities, so plotting one
// point per conflict would misplace the others.
function renderEventMarkers(events) {
  const generation = ++markerGeneration;
  markers.clearLayers();
  const points = [];
  for (const e of events) {
    if (e.lat == null || e.lon == null) continue;
    points.push(eventMarker(e));
  }
  let index = 0;
  const addChunk = () => {
    if (generation !== markerGeneration) return;
    markers.addLayers(points.slice(index, index + MARKER_CHUNK_SIZE));
    index += MARKER_CHUNK_SIZE;
    if (index < points.length) setTimeout(addChunk, 0);
  };
  addChunk();
}

function eventMarker(e) {
  const intensity = intensityClass(e.intensity);
  // Same ramp as the clusters, driven by severity: intensity 1 is cool, 5 is hot.
  // Dots stay well under the smallest bubble so they read as single events.
  const t = (intensity - 1) / 4;
  const dotSize = Math.round(6 + 6 * t);
  const text = e.headline || e.place_name || "event";
  const marker = L.marker([e.lat, e.lon], {
    icon: L.divIcon({
      className: "event-dot",
      iconSize: L.point(dotSize, dotSize),
      html: `<span style="background:${heatColor(t)}"></span>`,
      popupAnchor: [0, -dotSize / 2],
    }),
    title: text,
    keyboard: true,
    riseOnHover: true,
  });
  // Bind the tooltip on first hover instead of eagerly: `bindTooltip` allocates
  // a Tooltip object per marker, and only one is ever shown at a time.
  marker.on("mouseover", () => {
    if (!marker.getTooltip()) marker.bindTooltip(esc(text), { direction: "top" });
    marker.openTooltip();
  });
  marker.on("click", () => {
    showEvent(e);
    L.popup({ maxWidth: 300 })
      .setLatLng(marker.getLatLng())
      .setContent(eventPopup(e))
      .openOn(map);
  });
  return marker;
}
