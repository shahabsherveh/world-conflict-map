// Entry point: event wiring and bootstrap. The feature logic lives in map.js,
// state.js, list.js, and detail.js, loaded before this and sharing the global
// scope (plain scripts, no build step — see index.html).
//
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

document.getElementById("conflict-search").addEventListener("input", (event) => {
  conflictQuery = event.target.value;
  paintConflictList();
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
