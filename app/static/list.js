// Conflict list + "No location" panel. Plain script; global scope.
const NO_LOCATION_CAP = 200;

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
// Called after the list is re-rendered: a reveal requested by a list click only
// lands correctly once the new (shorter) list has claimed its height.
function settlePendingReveal() {
  if (!pendingReveal) return;
  pendingReveal = false;
  clearTimeout(revealTimer);
  revealDetail();
}

function paintConflictList() {
  if (!conflictsLoaded) return;
  const list = document.getElementById("conflict-list");
  const count = document.getElementById("conflict-count");
  const bounds = map.getBounds();

  // A conflict has ONE summary coordinate (its latest event in range), but its
  // events can sit anywhere, so everything here is derived from the events: a
  // conflict is "in view" when any of its events is on screen, and it has a
  // location when any of its events is geolocated. The summary point can answer
  // neither question. One pass fills all three sets, and also yields where to fly
  // to on click.
  const focus = new Map();
  const eventfulIds = new Set();
  const locatedIds = new Set();
  let eventsInView = 0;
  for (const e of rangeEvents) {
    if (e.conflict_id != null) eventfulIds.add(e.conflict_id);
    if (e.lat == null || e.lon == null) continue;
    if (e.conflict_id != null) locatedIds.add(e.conflict_id);
    if (!bounds.contains(L.latLng(e.lat, e.lon))) continue;
    eventsInView += 1;
    if (e.conflict_id != null && !focus.has(e.conflict_id)) focus.set(e.conflict_id, e);
  }

  const inView = rangeConflicts.filter((c) => focus.has(c.id));
  // GDELT leaves ~500 events a window ungeocoded, and those conflicts are eventful
  // but unmappable — that is the panel's population. A conflict with no events at
  // all is not unplaceable, it is empty: it belongs in the detail panel's empty
  // state, never in a list whose whole point is offering to place it.
  const noLocation = rangeConflicts.filter((c) => eventfulIds.has(c.id) && !locatedIds.has(c.id));
  const noEvents = rangeConflicts.filter((c) => !eventfulIds.has(c.id)).length;
  const offScreen = rangeConflicts.length - inView.length - noLocation.length - noEvents;

  // Paint the panel before the empty-viewport return below: a range with nothing in
  // view must clear it, not leave the previous range's rows on screen.
  paintNoLocationList(noLocation);

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
    settlePendingReveal();
    return;
  }

  // The filter narrows the on-screen rows only; the header keeps describing the
  // map view (that is what the numbers are about), and a separate note explains
  // how many of those rows survived the filter.
  const query = conflictQuery.trim().toLowerCase();
  const matching = query
    ? sorted.filter((c) =>
        `${c.name} ${c.country ?? ""} ${c.headline ?? ""}`.toLowerCase().includes(query),
      )
    : sorted;

  if (query && !matching.length) {
    list.innerHTML = `<li class="empty">No conflicts match “${esc(conflictQuery.trim())}”.</li>`;
    settlePendingReveal();
    return;
  }

  // One summary line instead of hundreds of rows: the remainder is off-screen, has
  // no geolocated event, or has no events yet.
  const rest = offScreen + noLocation.length + noEvents;
  const restText = [
    offScreen ? `${offScreen} off-screen` : "",
    noLocation.length ? `${noLocation.length} with no location` : "",
    noEvents ? `${noEvents} with no events yet` : "",
  ]
    .filter(Boolean)
    .join(", ");
  const filterNote = query
    ? `<li class="list-note">${matching.length} of ${sorted.length} in view match “${esc(
        conflictQuery.trim(),
      )}”.</li>`
    : "";

  list.innerHTML =
    filterNote +
    matching.map(conflictItem).join("") +
    (rest ? `<li class="list-note">${restText} (not shown).</li>` : "");

  const byId = new Map(rangeConflicts.map((c) => [String(c.id), c]));
  list.querySelectorAll(".conflict-item").forEach((button) => {
    button.onclick = () => {
      const conflict = byId.get(button.dataset.id);
      if (!conflict) return;
      // Recentring re-filters the list (debounced in the moveend handler). A much
      // shorter list collapses the sidebar and clamps its scroll position, so the
      // detail pane we just revealed can land off-screen. Set this before the map
      // moves so the repaint consumes it; the timer is only a fallback for when
      // the view does not actually change (no moveend, no repaint).
      pendingReveal = true;
      clearTimeout(revealTimer);
      revealTimer = setTimeout(settlePendingReveal, 1500);

      showConflict(conflict.id);
      // Centre on the incident that is on screen, not the conflict's summary
      // point, which may be somewhere else entirely.
      const anchor = focus.get(conflict.id);
      if (anchor) map.setView([anchor.lat, anchor.lon], 6);
      else settlePendingReveal();
    };
  });

  settlePendingReveal();
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
  if (!unplaced.length) {
    // Stale panel: the event gained coordinates since it was painted.
    showNotice("This conflict has no unplaced event in this range.", "info");
    return;
  }
  if (unplaced.length > 1) {
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
