const map = L.map("map").setView([25, 15], 2);
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
  chunkedLoading: true,
  // Default chunkSize=200 with a 200 ms interval means ~13k events take 15 s
  // to appear; 1000 brings a full 30-day load down to a few seconds.
  chunkSize: 1000,
  maxClusterRadius: 55,
  disableClusteringAtZoom: 13,
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

let currentStart = null;
let currentEnd = null;
let currentConflictId = null;
let coordinateTarget = null;
let noticeTimer = null;
let conflictsRequestId = 0;
let rangeConflicts = [];
let rangeEvents = [];
let conflictsLoaded = false;
let listRepaintTimer = null;
let detailRequestId = 0;

// Rendering 500 rows of a collapsed panel costs more than it is worth.
const NO_LOCATION_CAP = 200;

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

function formatApiDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

const api = {
  async request(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        if (body && body.detail !== undefined) detail = formatApiDetail(body.detail);
      } catch (_err) {
        // Non-JSON error response; keep the status text.
      }
      throw new Error(detail);
    }
    return response.json();
  },
  get(url) {
    return this.request(url);
  },
  post(url, body) {
    return this.request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  patch(url, body) {
    return this.request(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
};

function showNotice(message, kind = "info") {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.setAttribute("aria-live", kind === "error" ? "assertive" : "polite");
  notice.hidden = false;
  clearTimeout(noticeTimer);
  if (kind !== "error") {
    noticeTimer = setTimeout(() => {
      notice.hidden = true;
    }, 5000);
  }
}

function setBusy(button, busy) {
  if (!button) return;
  if (busy) {
    button.dataset.idleText = button.textContent;
    button.textContent = "Saving…";
    button.disabled = true;
  } else {
    if (button.dataset.idleText) button.textContent = button.dataset.idleText;
    button.disabled = false;
    delete button.dataset.idleText;
  }
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return [start, end];
}

function setDateInputs() {
  if (!currentStart) {
    const [start, end] = defaultDates();
    currentStart = start;
    currentEnd = end;
    document.getElementById("start-date").value = fmtDate(start);
    document.getElementById("end-date").value = fmtDate(end);
  }
}

async function loadConflicts() {
  setDateInputs();
  const requestId = ++conflictsRequestId;
  const list = document.getElementById("conflict-list");
  const range = `start=${fmtDate(currentStart)}&end=${fmtDate(currentEnd)}`;
  conflictsLoaded = false;
  list.setAttribute("aria-busy", "true");
  list.innerHTML = `<li class="empty">Loading conflicts…</li>`;
  try {
    const [events, conflicts] = await Promise.all([
      api.get(`/api/events?${range}`),
      api.get(`/api/conflicts?${range}`),
    ]);
    if (requestId !== conflictsRequestId) return;
    rangeEvents = events;
    renderConflictList(conflicts);
    renderEventMarkers(events);
  } catch (err) {
    if (requestId !== conflictsRequestId) return;
    markers.clearLayers();
    list.innerHTML = `<li class="empty error" role="alert">Could not load conflicts: ${esc(
      err.message,
    )}</li>`;
    showNotice(`Could not load conflicts: ${err.message}`, "error");
  } finally {
    if (requestId === conflictsRequestId) list.removeAttribute("aria-busy");
  }
}

function updateRange() {
  if (!currentStart || !currentEnd) {
    showNotice("Choose both the From and To dates.", "error");
    return;
  }
  if (currentStart > currentEnd) {
    showNotice("The From date must be on or before the To date.", "error");
    return;
  }
  loadConflicts();
}

function renderConflictList(conflicts) {
  rangeConflicts = conflicts;
  conflictsLoaded = true;
  paintConflictList();
}

// The panel lists what is on screen, not the whole time range: with 1,600+
// conflicts in a 30-day window the full list was mostly off-map noise. The map's
// own bounds decide, so pan and zoom re-filter the same fetched data (no extra
// API calls).
function paintConflictList() {
  if (!conflictsLoaded) return;
  const list = document.getElementById("conflict-list");
  const count = document.getElementById("conflict-count");
  const bounds = map.getBounds();

  // A conflict has ONE summary coordinate (its latest event in range), but its
  // events can sit anywhere. Deciding visibility from that single point drops
  // conflicts whose incidents are on screen — and counts events that are not.
  // So membership comes from the events themselves: a conflict is "in view" when
  // at least one of its events is. The same pass yields where to fly to on click.
  const focus = new Map();
  let eventsInView = 0;
  for (const e of rangeEvents) {
    if (e.lat == null || e.lon == null) continue;
    if (!bounds.contains(L.latLng(e.lat, e.lon))) continue;
    eventsInView += 1;
    if (e.conflict_id != null && !focus.has(e.conflict_id)) focus.set(e.conflict_id, e);
  }

  // "No location" means no geolocated event in the range at all — not "no events":
  // GDELT leaves ~500 events here ungeocoded, and each of those conflicts is
  // eventful but unmappable. Derive it from the events, not from the conflict's
  // summary coordinate, which only reflects its latest event.
  const locatedIds = new Set();
  for (const e of rangeEvents) {
    if (e.conflict_id != null && e.lat != null && e.lon != null) locatedIds.add(e.conflict_id);
  }
  const inView = rangeConflicts.filter((c) => focus.has(c.id));
  const noLocationCount = rangeConflicts.filter((c) => !locatedIds.has(c.id)).length;
  const offScreen = rangeConflicts.length - inView.length - noLocationCount;

  count.textContent =
    `(${inView.length} of ${rangeConflicts.length} · ${eventsInView.toLocaleString()} ${
      eventsInView === 1 ? "event" : "events"
    })`;

  const sorted = [...inView].sort(
    (a, b) => b.intensity - a.intensity || a.name.localeCompare(b.name),
  );

  if (!sorted.length) {
    list.innerHTML = `<li class="empty">${
      rangeConflicts.length ? "No conflicts in this view." : "No conflicts in this range."
    }</li>`;
    return;
  }

  // One summary line instead of hundreds of rows: the remainder is either
  // off-screen or has no geolocated event at all.
  const rest = offScreen + noLocationCount;
  const restText = [
    offScreen ? `${offScreen} off-screen` : "",
    noLocationCount ? `${noLocationCount} with no location` : "",
  ]
    .filter(Boolean)
    .join(", ");
  list.innerHTML =
    sorted.map(conflictItem).join("") +
    (rest ? `<li class="list-note">${restText} (not shown).</li>` : "");

  paintNoLocationList(rangeConflicts.filter((c) => !locatedIds.has(c.id)));

  const byId = new Map(rangeConflicts.map((c) => [String(c.id), c]));
  list.querySelectorAll(".conflict-item").forEach((button) => {
    button.onclick = () => {
      const conflict = byId.get(button.dataset.id);
      if (!conflict) return;
      showConflict(conflict.id);
      // Centre on the incident that is on screen, not the conflict's summary
      // point, which may be somewhere else entirely.
      const anchor = focus.get(conflict.id);
      if (anchor) map.setView([anchor.lat, anchor.lon], 6);
    };
  });
}

// Conflicts the geocoder could not place get a home in the sidebar: they can never be
// "in view", and inventing a position (country centroid, map edge) would put a marker
// where the source never said anything happened. The point of the panel is the
// "Set location" action, which feeds the human-supplied coordinate into the normal
// edit path (PATCH + edit_log) — no automatic geocoding anywhere.
function paintNoLocationList(conflicts) {
  const panel = document.getElementById("nolocation-panel");
  const count = document.getElementById("nolocation-count");
  const list = document.getElementById("nolocation-list");

  if (!conflicts.length) {
    panel.hidden = true;
    list.innerHTML = "";
    count.textContent = "";
    return;
  }

  // Newest first: an unplaced conflict is usually the freshest story, and the one
  // most worth fixing while the place is still in the headline.
  const unplacedEvent = new Map();
  for (const e of rangeEvents) {
    if (e.lat != null && e.lon != null) continue;
    const previous = unplacedEvent.get(e.conflict_id);
    if (!previous || e.event_date > previous.event_date) unplacedEvent.set(e.conflict_id, e);
  }
  const sorted = [...conflicts].sort((a, b) => {
    const da = unplacedEvent.get(a.id)?.event_date || a.start_date;
    const db = unplacedEvent.get(b.id)?.event_date || b.start_date;
    return db.localeCompare(da) || a.name.localeCompare(b.name);
  });

  const shown = sorted.slice(0, NO_LOCATION_CAP);
  count.textContent = `(${conflicts.length})`;
  panel.hidden = false;

  const row = (c) => {
    const lost = unplacedEvent.get(c.id);
    const when = lost?.event_date || c.start_date;
    const where = lost?.place_name ? ` · ${lost.place_name}` : "";
    // Grouping names a conflict after its place, and these have none, so they all
    // arrive as "Unnamed conflict". Lead with the headline instead of showing 200
    // identical rows; the placeholder name carries no information.
    const genericName = !c.name || /^unnamed conflict$/i.test(c.name.trim());
    const title = genericName ? c.headline || "Untitled conflict" : c.name;
    return `
      <li class="nl-row">
        <button type="button" class="conflict-item" data-id="${c.id}">
          <span class="dot nl-dot"></span>
          <span class="ci-body">
            <span class="ci-name">${esc(title)}</span>
            <span class="ci-meta">${esc(when)}${esc(where)} · no coordinates</span>
            ${!genericName && c.headline ? `<span class="ci-headline">${esc(c.headline)}</span>` : ""}
          </span>
        </button>
        <button type="button" class="nl-place" data-id="${c.id}">Set location →</button>
      </li>`;
  };

  list.innerHTML =
    shown.map(row).join("") +
    (sorted.length > shown.length
      ? `<li class="list-note">showing ${shown.length} of ${sorted.length} — narrow the date range to see the rest.</li>`
      : "");

  list.querySelectorAll(".conflict-item").forEach((button) => {
    button.onclick = () => showConflict(Number(button.dataset.id));
  });
  list.querySelectorAll(".nl-place").forEach((button) => {
    button.onclick = () => setLocationFor(Number(button.dataset.id));
  });
}

// Opens the conflict, then arms the existing pick-on-map flow on its single
// unplaced event. Several unplaced events means the caller must choose, so we
// stop at the conflict detail rather than guessing.
async function setLocationFor(conflictId) {
  const unplaced = rangeEvents.filter(
    (e) => e.conflict_id === conflictId && (e.lat == null || e.lon == null),
  );
  await showConflict(conflictId);
  if (unplaced.length !== 1) {
    showNotice("Several events here lack a location — open the one to place it.", "info");
    return;
  }
  showEvent(unplaced[0]);
  const editBlock = document.querySelector("#detail details.event-edit");
  if (editBlock) editBlock.open = true;
  startCoordinatePick("edit-ev-lat", "edit-ev-lon");
  showNotice("Click the map to place this event, then save it.", "info");
}

function conflictItem(c) {
  const hasEvents = c.event_count > 0;
  const countLabel = hasEvents
    ? `${c.event_count} event${c.event_count === 1 ? "" : "s"}`
    : "no events yet";
  const intensityLabel = hasEvents ? c.intensity : "—";
  // Same ramp as the map markers, so the list reads like the legend.
  const dotColor = hasEvents ? heatColor((c.intensity - 1) / 4) : "#b8b8b8";
  return `
      <li>
        <button type="button" class="conflict-item" data-id="${c.id}">
          <span class="dot" style="background:${dotColor}"></span>
          <span class="ci-body">
            <span class="ci-name">${esc(c.name)}</span>
            <span class="ci-meta">${esc(countLabel)} · ${esc(c.status)}${
              c.end_date ? ` · ended ${esc(c.end_date)}` : ""
            }</span>
            ${c.headline ? `<span class="ci-headline">${esc(c.headline)}</span>` : ""}
          </span>
          <span class="ci-intensity">${esc(String(intensityLabel))}</span>
        </button>
      </li>`;
}

function intensityClass(intensity) {
  return Math.max(1, Math.min(5, Math.round(intensity || 1)));
}

// One marker per EVENT: a conflict can span several cities, so plotting one
// point per conflict would misplace the others.
function renderEventMarkers(events) {
  markers.clearLayers();
  const points = [];
  for (const e of events) {
    if (e.lat == null || e.lon == null) continue;
    points.push(eventMarker(e));
  }
  // addLayers() (not addLayer() in a loop) is what enables chunkedLoading.
  markers.addLayers(points);
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

function eventPopup(e) {
  const actors = [e.actor_a, e.actor_b].filter(Boolean).join(" vs ");
  return `
    <div class="popup">
      <div class="popup-headline">${esc(e.headline || "(no headline)")}</div>
      <div class="popup-meta">${esc(e.place_name || e.country || "?")} · ${esc(e.event_date)}</div>
      <div class="popup-meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
        e.fatalities ? ` · ${e.fatalities} killed` : ""
      }</div>
      ${actors ? `<div class="popup-meta">${esc(actors)}</div>` : ""}
      ${
        e.source_url
          ? `<a href="${esc(e.source_url)}" target="_blank" rel="noopener noreferrer">source ↗</a>`
          : ""
      }
    </div>`;
}

function showEvent(e) {
  stopCoordinatePick();
  detailRequestId += 1;
  currentConflictId = e.conflict_id ?? null;
  document.getElementById("edit-panel").innerHTML = "";
  const actors = [e.actor_a, e.actor_b].filter(Boolean).join(" vs ");
  const raw = JSON.stringify(e, null, 2);
  document.getElementById("detail").innerHTML = `
    <h2 id="detail-heading" tabindex="-1">${esc(e.headline || e.place_name || "Event")}</h2>
    <div class="meta">${esc(e.place_name || e.country || "?")} · ${esc(e.event_date)}</div>
    <div class="meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
      e.fatalities ? ` · ${e.fatalities} killed` : ""
    } <span class="prov ${esc(e.provenance)}">${esc(e.provenance)}</span></div>
    ${actors ? `<div class="meta">${esc(actors)}</div>` : ""}
    ${
      e.source_url
        ? `<p><a href="${esc(e.source_url)}" target="_blank" rel="noopener noreferrer">Read source ↗</a></p>`
        : ""
    }
    ${e.conflict_id ? `<p><button id="open-conflict" type="button">Open conflict</button></p>` : ""}
    ${renderEventEditForm(e)}
    <details class="raw">
      <summary>Raw data</summary>
      <pre>${esc(raw)}</pre>
    </details>`;
  document.getElementById("detail-heading").focus();

  const openButton = document.getElementById("open-conflict");
  if (openButton) openButton.onclick = () => showConflict(e.conflict_id);

  const form = document.getElementById("event-edit-form");
  if (form) form.onsubmit = (event) => saveEvent(event, e);
  const pick = document.getElementById("edit-ev-pick");
  if (pick) pick.onclick = () => startCoordinatePick("edit-ev-lat", "edit-ev-lon");
}

function renderEventEditForm(e) {
  return `
    <details class="event-edit">
      <summary>Edit event</summary>
      <form id="event-edit-form">
        <label>Date <input type="date" id="edit-ev-date" value="${esc(e.event_date)}" required></label>
        <label>Type <input id="edit-ev-type" value="${esc(e.event_type || "")}" placeholder="battle / assault / …"></label>
        <label>Place <input id="edit-ev-place" value="${esc(e.place_name || "")}" placeholder="City, Region, Country"></label>
        <label>Country <input id="edit-ev-country" value="${esc(e.country || "")}" maxlength="2"></label>
        <div class="form-row">
          <label>Latitude <input id="edit-ev-lat" type="number" step="any" min="-90" max="90" value="${e.lat ?? ""}"></label>
          <label>Longitude <input id="edit-ev-lon" type="number" step="any" min="-180" max="180" value="${e.lon ?? ""}"></label>
        </div>
        <button id="edit-ev-pick" type="button">Pick on map</button>
        <p class="hint">Coordinates are optional. Use the map picker or enter lat/lon manually.</p>
        <label>Intensity <input id="edit-ev-intensity" type="number" min="1" max="5" value="${e.intensity ?? 3}" required></label>
        <label>Fatalities <input id="edit-ev-fatalities" type="number" min="0" value="${e.fatalities ?? ""}"></label>
        <label>Summary <textarea id="edit-ev-summary" rows="3">${esc(e.summary || "")}</textarea></label>
        <label>Source URL <input id="edit-ev-source" type="url" value="${esc(e.source_url || "")}" placeholder="https://…"></label>
        <button type="submit">Save event</button>
      </form>
    </details>`;
}

async function saveEvent(event, original) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const eventDate = document.getElementById("edit-ev-date").value;
  if (!eventDate) {
    showNotice("Event date is required.", "error");
    return;
  }

  const intensity = intOrNull(document.getElementById("edit-ev-intensity").value);
  if (Number.isNaN(intensity) || intensity === null || intensity < 1 || intensity > 5) {
    showNotice("Intensity must be a whole number between 1 and 5.", "error");
    return;
  }
  const fatalities = intOrNull(document.getElementById("edit-ev-fatalities").value);
  if (Number.isNaN(fatalities) || (fatalities !== null && fatalities < 0)) {
    showNotice("Fatalities must be a whole number of 0 or more.", "error");
    return;
  }
  const lat = numberOrNull(document.getElementById("edit-ev-lat").value);
  const lon = numberOrNull(document.getElementById("edit-ev-lon").value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    showNotice("Latitude and longitude must be numbers.", "error");
    return;
  }
  if ((lat === null) !== (lon === null)) {
    showNotice("Enter both latitude and longitude, or leave both blank.", "error");
    return;
  }
  if (lat !== null && (lat < -90 || lat > 90)) {
    showNotice("Latitude must be between -90 and 90.", "error");
    return;
  }
  if (lon !== null && (lon < -180 || lon > 180)) {
    showNotice("Longitude must be between -180 and 180.", "error");
    return;
  }
  const sourceUrl = document.getElementById("edit-ev-source").value.trim();
  if (sourceUrl && !/^https?:\/\//i.test(sourceUrl)) {
    showNotice("Source URL must start with http:// or https://.", "error");
    return;
  }

  const body = {
    event_date: eventDate,
    event_type: document.getElementById("edit-ev-type").value.trim() || null,
    place_name: document.getElementById("edit-ev-place").value.trim() || null,
    country: document.getElementById("edit-ev-country").value.trim() || null,
    lat,
    lon,
    intensity,
    fatalities,
    summary: document.getElementById("edit-ev-summary").value.trim() || null,
    source_url: sourceUrl || null,
  };

  setBusy(button, true);
  try {
    const updated = await api.patch(`/api/events/${original.id}`, body);
    showNotice("Event saved.", "success");
    showEvent(updated);
    await loadConflicts();
  } catch (err) {
    showNotice(`Could not save event: ${err.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function showConflict(id) {
  stopCoordinatePick();
  currentConflictId = id;
  const requestId = ++detailRequestId;
  const detail = document.getElementById("detail");
  document.getElementById("edit-panel").innerHTML = "";
  detail.innerHTML = `<p class="muted">Loading conflict…</p>`;
  try {
    const conflict = await api.get(`/api/conflicts/${id}`);
    if (requestId !== detailRequestId) return;
    renderConflictDetail(conflict);
  } catch (err) {
    if (requestId !== detailRequestId) return;
    detail.innerHTML = `<p class="empty error" role="alert">Could not load conflict: ${esc(
      err.message,
    )}</p>`;
    showNotice(`Could not load conflict: ${err.message}`, "error");
  }
}

function renderConflictDetail(c) {
  const eventsHtml = c.events.length
    ? c.events
        .map(
          (e) => `
      <li>
        <div class="ev-date">${esc(e.headline || "(no headline)")}</div>
        <div class="ev-meta">${esc(e.event_date)} · ${esc(e.event_type || "?")} · intensity ${
          e.intensity
        }${e.fatalities ? ` · ${e.fatalities} killed` : ""} <span class="prov ${esc(
          e.provenance,
        )}">${esc(e.provenance)}</span></div>
        <div class="ev-place">${esc(e.place_name || "")}</div>
        <div class="ev-actions">
          ${
            e.source_url
              ? `<a class="ev-src" href="${esc(
                  e.source_url,
                )}" target="_blank" rel="noopener noreferrer">source ↗</a>`
              : ""
          }
          <button class="ev-edit-btn" type="button" data-event-id="${e.id}">Edit</button>
        </div>
      </li>`,
        )
        .join("")
    : `<li class="empty">No events yet. Add the first event below.</li>`;

  const intensityLabel = c.event_count ? `intensity ${c.intensity} · ${c.event_count} events` : "no events yet";
  document.getElementById("detail").innerHTML = `
    <h2 id="detail-heading" tabindex="-1">${esc(c.name)}</h2>
    <div class="meta">${esc(c.country || "")} · ${esc(c.status)} · ${esc(intensityLabel)}</div>
    <div class="meta">${esc(c.start_date)} → ${esc(c.end_date || "ongoing")}</div>
    <ul class="events">${eventsHtml}</ul>`;
  document.getElementById("detail-heading").focus();

  const byId = new Map(c.events.map((event) => [String(event.id), event]));
  document.querySelectorAll("#detail .ev-edit-btn").forEach((button) => {
    button.onclick = () => {
      const event = byId.get(button.dataset.eventId);
      if (event) showEvent(event);
    };
  });

  renderEditPanel(c);
}

function renderEditPanel(c) {
  document.getElementById("edit-panel").innerHTML = `
    <h3>Edit conflict</h3>
    <form id="conflict-form">
      <label>Name <input id="edit-name" value="${esc(c.name)}" required></label>
      <label>Country <input id="edit-country" value="${esc(c.country || "")}" maxlength="2"></label>
      <div class="form-row">
        <label>Start <input type="date" id="edit-start" value="${esc(c.start_date)}" required></label>
        <label>End <input type="date" id="edit-end" value="${esc(c.end_date || "")}"></label>
      </div>
      <label>Status
        <select id="edit-status">
          <option value="active" ${c.status === "active" ? "selected" : ""}>active</option>
          <option value="ended" ${c.status === "ended" ? "selected" : ""}>ended</option>
        </select>
      </label>
      <button id="save-edit" type="submit">Save conflict</button>
    </form>
    <hr>
    <h3>Add event</h3>
    <form id="add-event-form" data-start="${esc(c.start_date)}" data-end="${esc(c.end_date || "")}">
      <label>Date <input type="date" id="ev-date" value="${todayISO()}" required></label>
      <label>Type <input id="ev-type" placeholder="battle / assault / …"></label>
      <label>Place <input id="ev-place" placeholder="City, Country"></label>
      <label>Country <input id="ev-country" maxlength="2" placeholder="SY"></label>
      <div class="form-row">
        <label>Latitude <input id="ev-lat" type="number" step="any" min="-90" max="90"></label>
        <label>Longitude <input id="ev-lon" type="number" step="any" min="-180" max="180"></label>
      </div>
      <button id="ev-pick" type="button">Pick on map</button>
      <p class="hint">Coordinates are optional; events without them will not get a map marker.</p>
      <label>Intensity <input id="ev-intensity" type="number" min="1" max="5" value="3" required></label>
      <label>Source URL <input id="ev-source" type="url" placeholder="https://…"></label>
      <button id="add-event" type="submit">Add event</button>
    </form>
    <hr>
    <h3>New conflict</h3>
    <form id="new-conflict-form">
      <label>Name <input id="new-name" placeholder="Conflict name" required></label>
      <label>Country <input id="new-country" maxlength="2" placeholder="SY"></label>
      <div class="form-row">
        <label>Start <input type="date" id="new-start" value="${todayISO()}" required></label>
        <label>End <input type="date" id="new-end"></label>
      </div>
      <button id="new-conflict" type="submit">Create conflict</button>
    </form>`;

  document.getElementById("conflict-form").onsubmit = saveEdit;
  document.getElementById("add-event-form").onsubmit = addEvent;
  document.getElementById("new-conflict-form").onsubmit = newConflict;
  document.getElementById("ev-pick").onclick = () => startCoordinatePick("ev-lat", "ev-lon");
}

async function saveEdit(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const name = document.getElementById("edit-name").value.trim();
  const startDate = document.getElementById("edit-start").value;
  const endDate = document.getElementById("edit-end").value;
  if (!name) {
    showNotice("Conflict name is required.", "error");
    return;
  }
  if (!startDate) {
    showNotice("Conflict start date is required.", "error");
    return;
  }
  if (endDate && endDate < startDate) {
    showNotice("End date must be on or after the start date.", "error");
    return;
  }

  const body = {
    name,
    country: document.getElementById("edit-country").value.trim() || null,
    start_date: startDate,
    end_date: endDate || null,
    status: document.getElementById("edit-status").value,
  };

  setBusy(button, true);
  try {
    await api.patch(`/api/conflicts/${currentConflictId}`, body);
    showNotice("Conflict saved.", "success");
    await showConflict(currentConflictId);
    await loadConflicts();
  } catch (err) {
    showNotice(`Could not save conflict: ${err.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function addEvent(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const eventDate = document.getElementById("ev-date").value;
  if (!eventDate) {
    showNotice("Event date is required.", "error");
    return;
  }
  if (form.dataset.start && eventDate < form.dataset.start) {
    showNotice("Event date is before the conflict start date.", "error");
    return;
  }
  if (form.dataset.end && eventDate > form.dataset.end) {
    showNotice("Event date is after the conflict end date.", "error");
    return;
  }

  const intensity = intOrNull(document.getElementById("ev-intensity").value);
  if (Number.isNaN(intensity) || intensity === null || intensity < 1 || intensity > 5) {
    showNotice("Intensity must be a whole number between 1 and 5.", "error");
    return;
  }
  const lat = numberOrNull(document.getElementById("ev-lat").value);
  const lon = numberOrNull(document.getElementById("ev-lon").value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    showNotice("Latitude and longitude must be numbers.", "error");
    return;
  }
  if ((lat === null) !== (lon === null)) {
    showNotice("Enter both latitude and longitude, or leave both blank.", "error");
    return;
  }
  if (lat !== null && (lat < -90 || lat > 90)) {
    showNotice("Latitude must be between -90 and 90.", "error");
    return;
  }
  if (lon !== null && (lon < -180 || lon > 180)) {
    showNotice("Longitude must be between -180 and 180.", "error");
    return;
  }
  const sourceUrl = document.getElementById("ev-source").value.trim();
  if (sourceUrl && !/^https?:\/\//i.test(sourceUrl)) {
    showNotice("Source URL must start with http:// or https://.", "error");
    return;
  }

  const body = {
    event_date: eventDate,
    event_type: document.getElementById("ev-type").value.trim() || null,
    place_name: document.getElementById("ev-place").value.trim() || null,
    country: document.getElementById("ev-country").value.trim() || null,
    lat,
    lon,
    intensity,
    source_url: sourceUrl || null,
    conflict_id: currentConflictId,
  };

  setBusy(button, true);
  try {
    await api.post("/api/events", body);
    showNotice("Event added.", "success");
    await showConflict(currentConflictId);
    await loadConflicts();
  } catch (err) {
    showNotice(`Could not add event: ${err.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

async function newConflict(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const name = document.getElementById("new-name").value.trim();
  const startDate = document.getElementById("new-start").value;
  const endDate = document.getElementById("new-end").value;
  if (!name) {
    showNotice("Conflict name is required.", "error");
    return;
  }
  if (!startDate) {
    showNotice("Conflict start date is required.", "error");
    return;
  }
  if (endDate && endDate < startDate) {
    showNotice("End date must be on or after the start date.", "error");
    return;
  }

  const body = {
    name,
    country: document.getElementById("new-country").value.trim() || null,
    start_date: startDate,
    end_date: endDate || null,
    status: "active",
  };

  setBusy(button, true);
  try {
    const created = await api.post("/api/conflicts", body);
    showNotice("Conflict created. Add its first event below.", "success");
    await showConflict(created.id);
    await loadConflicts();
  } catch (err) {
    showNotice(`Could not create conflict: ${err.message}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function startCoordinatePick(latId, lonId) {
  if (!document.getElementById(latId) || !document.getElementById(lonId)) return;
  coordinateTarget = { latId, lonId };
  map.getContainer().classList.add("picking");
  showNotice("Click the map to set the event coordinates.", "info");
}

function stopCoordinatePick() {
  coordinateTarget = null;
  map.getContainer().classList.remove("picking");
}

// Repaint the panel when the viewport changes (zoom, pan, or a conflict click
// that recentres). Debounced because a zoom fires several events at once.
map.on("moveend zoomend", () => {
  clearTimeout(listRepaintTimer);
  listRepaintTimer = setTimeout(paintConflictList, 120);
});

map.on("click", (event) => {
  if (!coordinateTarget) return;
  const latInput = document.getElementById(coordinateTarget.latId);
  const lonInput = document.getElementById(coordinateTarget.lonId);
  if (!latInput || !lonInput) {
    stopCoordinatePick();
    return;
  }
  latInput.value = event.latlng.lat.toFixed(5);
  lonInput.value = event.latlng.lng.toFixed(5);
  stopCoordinatePick();
  showNotice("Coordinates set. Save the event to apply.", "success");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && coordinateTarget) {
    stopCoordinatePick();
    showNotice("Coordinate picking cancelled.", "info");
  }
});

document.getElementById("start-date").onchange = (event) => {
  const parsed = parseDateInput(event.target.value);
  if (!parsed) {
    event.target.value = fmtDate(currentStart);
    showNotice("Choose a valid From date.", "error");
    return;
  }
  currentStart = parsed;
  updateRange();
};

document.getElementById("end-date").onchange = (event) => {
  const parsed = parseDateInput(event.target.value);
  if (!parsed) {
    event.target.value = fmtDate(currentEnd);
    showNotice("Choose a valid To date.", "error");
    return;
  }
  currentEnd = parsed;
  updateRange();
};

loadConflicts();
