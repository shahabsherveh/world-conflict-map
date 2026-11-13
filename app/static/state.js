// API client, notices, and shared app state. Plain script; global scope.
// Shared across list/marker/detail scripts; hoisted so order does not matter.
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

// The detail pane lives below the (long) conflict list, so on a narrow layout a
// click used to fill it off-screen — and the sticky header then clipped the
// heading. Bring the pane into view, leaving room for the header.
function revealDetail() {
  const sidebar = document.getElementById("sidebar");
  const detail = document.getElementById("detail");
  if (!sidebar || !detail || typeof sidebar.scrollTo !== "function") return;
  const header = sidebar.querySelector("header");
  const sidebarBox = sidebar.getBoundingClientRect();
  const detailBox = detail.getBoundingClientRect();
  const headerBottom = header ? header.getBoundingClientRect().bottom : sidebarBox.top;
  // Already fully visible below the header: do not fight the user's scroll.
  if (detailBox.top >= headerBottom - 2 && detailBox.bottom <= sidebarBox.bottom) return;
  // Instant, not smooth: the browser's own focus-scroll runs on the same frame
  // and the two animations fought, leaving the pane parked under the header.
  sidebar.scrollTop = Math.max(0, sidebar.scrollTop + detailBox.top - headerBottom - 8);
}

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

// App state shared across the three scripts. Hoisted `let` so `app.js` can read
// and write them regardless of script order.
let currentStart = null;
let currentEnd = null;
let currentConflictId = null;
let coordinateTarget = null;
let noticeTimer = null;
let conflictsRequestId = 0;
let conflictQuery = "";
let rangeConflicts = [];
let rangeEvents = [];
let conflictsLoaded = false;
let listRepaintTimer = null;
let revealTimer = null;
let pendingReveal = false;
let detailRequestId = 0;

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
