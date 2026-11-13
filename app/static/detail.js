// Event popup, conflict/event detail panes, and the edit forms. Plain script.
// Corroboration badge: outlet + article counts, not a confidence score. The
// "well corroborated" variant is the API's counts predicate (2+ outlets and 3+
// articles), so the UI never invents its own cut-off from `confidence`, whose
// scale has never been validated. Null counts mean unknown (a manual event, or
// one whose raw GDELT row has aged out), and show nothing: "0 outlets" would be
// a claim the data cannot support.
function corroborationBadge(e) {
  if (e.sources == null || e.articles == null) return "";
  const outlets = `${e.sources} outlet${e.sources === 1 ? "" : "s"}`;
  const articles = `${e.articles} article${e.articles === 1 ? "" : "s"}`;
  const strong = e.well_corroborated ? " strong" : "";
  return `<span class="corroboration${strong}" title="Outlets that carried this event and the article count GDELT recorded">${esc(
    `${outlets} · ${articles}`,
  )}</span>`;
}

function eventPopup(e) {
  const actors = [e.actor_a, e.actor_b].filter(Boolean).join(" vs ");
  const corroboration = corroborationBadge(e);
  return `
    <div class="popup">
      <div class="popup-headline">${esc(e.headline || "(no headline)")}</div>
      <div class="popup-meta">${esc(e.place_name || e.country || "?")} · ${esc(e.event_date)}</div>
      <div class="popup-meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
        e.fatalities ? ` · ${e.fatalities} killed` : ""
      }</div>
      ${actors ? `<div class="popup-meta">${esc(actors)}</div>` : ""}
      ${corroboration ? `<div class="popup-meta">${corroboration}</div>` : ""}
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
  const detailPane = document.getElementById("detail");
  detailPane.removeAttribute("aria-busy");
  document.getElementById("edit-panel").innerHTML = "";
  const actors = [e.actor_a, e.actor_b].filter(Boolean).join(" vs ");
  const corroboration = corroborationBadge(e);
  const raw = JSON.stringify(e, null, 2);
  document.getElementById("detail").innerHTML = `
    <h2 id="detail-heading" tabindex="-1">${esc(e.headline || e.place_name || "Event")}</h2>
    <div class="meta">${esc(e.place_name || e.country || "?")} · ${esc(e.event_date)}</div>
    <div class="meta">${esc(e.event_type || "?")} · intensity ${e.intensity}${
      e.fatalities ? ` · ${e.fatalities} killed` : ""
    } <span class="prov ${esc(e.provenance)}">${esc(e.provenance)}</span></div>
    ${corroboration ? `<div class="meta">${corroboration}</div>` : ""}
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
  // After the forms are in the DOM, so the pane is measured in its final place.
  revealDetail();
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
        <label>Summary <textarea id="edit-ev-summary" rows="5">${esc(e.summary || "")}</textarea></label>
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
  // A skeleton shaped like the content that is coming: the fetch replaces the
  // previous detail anyway, so a spinner or a bare "Loading…" just flashes.
  detail.setAttribute("aria-busy", "true");
  detail.innerHTML = `
    <div class="skeleton" role="status" aria-label="Loading conflict details">
      <span class="sk-line sk-title"></span>
      <span class="sk-line short"></span>
      <span class="sk-line"></span>
      <span class="sk-line"></span>
      <span class="sk-line short"></span>
    </div>`;
  try {
    const conflict = await api.get(`/api/conflicts/${id}`);
    if (requestId !== detailRequestId) return;
    detail.removeAttribute("aria-busy");
    renderConflictDetail(conflict);
  } catch (err) {
    if (requestId !== detailRequestId) return;
    detail.removeAttribute("aria-busy");
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
  // Last, so the edit forms below the list do not change where it lands.
  revealDetail();
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
