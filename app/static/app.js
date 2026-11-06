const map = L.map("map").setView([25, 15], 2);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const markers = L.layerGroup().addTo(map);
let currentStart = null;
let currentEnd = null;
let currentConflictId = null;
let coordinateTarget = null;
let noticeTimer = null;
let conflictsRequestId = 0;
let detailRequestId = 0;

const COLORS = ["#2c7bb6", "#abd9e9", "#fdae61", "#f46d43", "#d73027"];

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

function intensityColor(intensity) {
  return COLORS[Math.max(0, Math.min(4, (intensity || 1) - 1))];
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
  list.setAttribute("aria-busy", "true");
  list.innerHTML = `<li class="empty">Loading conflicts…</li>`;
  try {
    const [events, conflicts] = await Promise.all([
      api.get(`/api/events?${range}`),
      api.get(`/api/conflicts?${range}`),
    ]);
    if (requestId !== conflictsRequestId) return;
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
  const list = document.getElementById("conflict-list");
  const count = document.getElementById("conflict-count");
  count.textContent = `(${conflicts.length})`;

  if (!conflicts.length) {
    list.innerHTML = `<li class="empty">No conflicts in this range.</li>`;
    return;
  }

  const sorted = [...conflicts].sort(
    (a, b) => b.intensity - a.intensity || a.name.localeCompare(b.name),
  );
  list.innerHTML = sorted
    .map((c) => {
      const hasEvents = c.event_count > 0;
      const countLabel = hasEvents
        ? `${c.event_count} event${c.event_count === 1 ? "" : "s"}`
        : "no events yet";
      const intensityLabel = hasEvents ? c.intensity : "—";
      const dotColor = hasEvents ? intensityColor(c.intensity) : "#b8b8b8";
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
    })
    .join("");

  list.querySelectorAll(".conflict-item").forEach((button) => {
    button.onclick = () => {
      const conflict = sorted.find((x) => String(x.id) === button.dataset.id);
      if (!conflict) return;
      showConflict(conflict.id);
      if (conflict.lat != null && conflict.lon != null) {
        map.setView([conflict.lat, conflict.lon], 6);
      }
    };
  });
}

// One marker per EVENT: a conflict can span several cities, so plotting one
// point per conflict would misplace the others.
function renderEventMarkers(events) {
  markers.clearLayers();
  for (const e of events) {
    if (e.lat == null || e.lon == null) continue;
    const circle = L.circleMarker([e.lat, e.lon], {
      radius: 4 + (e.intensity || 1) * 2,
      color: intensityColor(e.intensity),
      fillColor: intensityColor(e.intensity),
      fillOpacity: 0.7,
    });
    circle.bindTooltip(`${esc(e.headline || e.place_name || "event")}`, { direction: "top" });
    circle.bindPopup(eventPopup(e));
    circle.on("click", () => showEvent(e));
    circle.addTo(markers);
  }
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
