const map = L.map("map").setView([25, 15], 2);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const markers = L.layerGroup().addTo(map);
let currentStart = null;
let currentEnd = null;
let currentConflictId = null;

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

function intensityColor(intensity) {
  return COLORS[Math.max(0, Math.min(4, (intensity || 1) - 1))];
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return [start, end];
}

function setDateInputs() {
  if (!currentStart) {
    const [s, e] = defaultDates();
    currentStart = s;
    currentEnd = e;
    document.getElementById("start-date").value = fmtDate(s);
    document.getElementById("end-date").value = fmtDate(e);
  }
}

async function loadConflicts() {
  setDateInputs();
  const range = `start=${fmtDate(currentStart)}&end=${fmtDate(currentEnd)}`;
  const [events, conflicts] = await Promise.all([
    fetch(`/api/events?${range}`).then((r) => r.json()),
    fetch(`/api/conflicts?${range}`).then((r) => r.json()),
  ]);
  renderConflictList(conflicts);
  renderEventMarkers(events);
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
    .map(
      (c) => `
      <li class="conflict-item" data-id="${c.id}">
        <span class="dot" style="background:${intensityColor(c.intensity)}"></span>
        <div class="ci-body">
          <div class="ci-name">${esc(c.name)}</div>
          <div class="ci-meta">${c.event_count} event${c.event_count === 1 ? "" : "s"} · ${esc(
            c.status,
          )}${c.end_date ? ` · ended ${c.end_date}` : ""}</div>
          ${c.headline ? `<div class="ci-headline">${esc(c.headline)}</div>` : ""}
        </div>
        <span class="ci-intensity">${c.intensity}</span>
      </li>`,
    )
    .join("");

  list.querySelectorAll(".conflict-item").forEach((li) => {
    li.onclick = () => {
      const conflict = sorted.find((x) => String(x.id) === li.dataset.id);
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
      <div class="popup-meta">${esc(e.place_name || e.country || "?")} · ${e.event_date}</div>
      <div class="popup-meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
        e.fatalities ? ` · ${e.fatalities} killed` : ""
      }</div>
      ${actors ? `<div class="popup-meta">${esc(actors)}</div>` : ""}
      ${e.source_url ? `<a href="${esc(e.source_url)}" target="_blank">source ↗</a>` : ""}
    </div>`;
}

function showEvent(e) {
  const actors = [e.actor_a, e.actor_b].filter(Boolean).join(" vs ");
  const raw = JSON.stringify(e, null, 2);
  document.getElementById("detail").innerHTML = `
    <h2>${esc(e.headline || e.place_name || "Event")}</h2>
    <div class="meta">${esc(e.place_name || e.country || "?")} · ${e.event_date}</div>
    <div class="meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
      e.fatalities ? ` · ${e.fatalities} killed` : ""
    } <span class="prov ${e.provenance}">${e.provenance}</span></div>
    ${actors ? `<div class="meta">${esc(actors)}</div>` : ""}
    ${e.source_url ? `<p><a href="${esc(e.source_url)}" target="_blank">Read source ↗</a></p>` : ""}
    ${e.conflict_id ? `<p><button id="open-conflict">Open conflict</button></p>` : ""}
    <details class="raw">
      <summary>Raw data</summary>
      <pre>${esc(raw)}</pre>
    </details>`;
  const btn = document.getElementById("open-conflict");
  if (btn) btn.onclick = () => showConflict(e.conflict_id);
}

async function showConflict(id) {
  currentConflictId = id;
  const res = await fetch(`/api/conflicts/${id}`);
  const c = await res.json();
  const eventsHtml = c.events
    .map(
      (e) => `
      <li>
        <div class="ev-date">${esc(e.headline || "(no headline)")}</div>
        <div class="ev-meta">${e.event_date} · ${esc(e.event_type || "?")} · intensity ${e.intensity}${
          e.fatalities ? ` · ${e.fatalities} killed` : ""
        } <span class="prov ${e.provenance}">${e.provenance}</span></div>
        <div class="ev-place">${esc(e.place_name || "")}</div>
        ${e.source_url ? `<a class="ev-src" href="${esc(e.source_url)}" target="_blank">source ↗</a>` : ""}
      </li>`,
    )
    .join("");
  document.getElementById("detail").innerHTML = `
    <h2>${esc(c.name)}</h2>
    <div class="meta">${esc(c.country || "")} · ${esc(c.status)} · intensity ${c.intensity} · ${c.event_count} events</div>
    <div class="meta">${c.start_date} → ${c.end_date || "ongoing"}</div>
    <ul class="events">${eventsHtml || "<li>no events</li>"}</ul>`;
  renderEditPanel(c);
}

function renderEditPanel(c) {
  const panel = document.getElementById("edit-panel");
  panel.innerHTML = `
    <h3>Edit conflict</h3>
    <label>Name <input id="edit-name" value="${esc(c.name)}"></label>
    <label>Status
      <select id="edit-status">
        <option value="active" ${c.status === "active" ? "selected" : ""}>active</option>
        <option value="ended" ${c.status === "ended" ? "selected" : ""}>ended</option>
      </select>
    </label>
    <label>End date <input type="date" id="edit-end" value="${c.end_date || ""}"></label>
    <button id="save-edit">Save changes</button>
    <hr>
    <h3>Add event</h3>
    <label>Date <input type="date" id="ev-date"></label>
    <label>Type <input id="ev-type" placeholder="battle / assault / …"></label>
    <label>Place <input id="ev-place" placeholder="City, Country"></label>
    <label>Country <input id="ev-country" maxlength="2" placeholder="SY"></label>
    <label>Intensity <input id="ev-intensity" type="number" min="1" max="5" value="3"></label>
    <button id="add-event">Add event</button>
    <hr>
    <h3>New conflict</h3>
    <label>Name <input id="new-name" placeholder="Conflict name"></label>
    <label>Country <input id="new-country" maxlength="2" placeholder="SY"></label>
    <label>Start <input type="date" id="new-start"></label>
    <button id="new-conflict">Create conflict</button>`;
  document.getElementById("save-edit").onclick = saveEdit;
  document.getElementById("add-event").onclick = addEvent;
  document.getElementById("new-conflict").onclick = newConflict;
}

async function saveEdit() {
  const body = {
    name: document.getElementById("edit-name").value,
    status: document.getElementById("edit-status").value,
    end_date: document.getElementById("edit-end").value || null,
  };
  const res = await fetch(`/api/conflicts/${currentConflictId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    showConflict(currentConflictId);
    loadConflicts();
  }
}

async function addEvent() {
  const body = {
    event_date: document.getElementById("ev-date").value,
    event_type: document.getElementById("ev-type").value || null,
    place_name: document.getElementById("ev-place").value || null,
    country: document.getElementById("ev-country").value || null,
    intensity: parseInt(document.getElementById("ev-intensity").value, 10) || 3,
    conflict_id: currentConflictId,
  };
  const res = await fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    showConflict(currentConflictId);
    loadConflicts();
  }
}

async function newConflict() {
  const body = {
    name: document.getElementById("new-name").value,
    country: document.getElementById("new-country").value || null,
    start_date: document.getElementById("new-start").value,
  };
  const res = await fetch("/api/conflicts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    loadConflicts();
  }
}

document.getElementById("start-date").onchange = (e) => {
  currentStart = new Date(e.target.value + "T00:00:00");
  loadConflicts();
};
document.getElementById("end-date").onchange = (e) => {
  currentEnd = new Date(e.target.value + "T00:00:00");
  loadConflicts();
};

loadConflicts();
