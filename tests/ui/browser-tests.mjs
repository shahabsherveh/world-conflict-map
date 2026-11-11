// Real-browser UI tests: drives Chrome over CDP against a running API.
//
// map-smoke.mjs covers the map in jsdom — counts, clustering, scrubbing, DOM
// shapes. jsdom has no layout engine or hit-testing, so this file covers what
// only a real browser can: a click lands on the marker drawn at that pixel, the
// popup is anchored above it, badge colours are the computed CSS, basemap tiles
// actually arrive, and Pick-on-map fills the form.
//
// Usage (from the repo root):
//   uvicorn app.main:app --reload --port 8000            # terminal 1
//   chrome/linux-*/chrome-linux64/chrome --headless=new --no-sandbox \
//     --disable-gpu --disable-dev-shm-usage --remote-debugging-port=9222 \
//     --user-data-dir=chrome/profile about:blank &        # terminal 2
//   cd tests/ui && node browser-tests.mjs                 # or: npm run test:browser
//
// Read-only, like map-smoke.mjs: it never saves an edit, and the last check asks
// the API to prove it. Expected entries are read from /api/events, so a seeded
// DB is convenient but not required. Chrome install/layout: README.md.
//
// Not part of pytest or scripts/ci-check.sh: it needs Chrome, a server, and a
// network for the basemap — the same trade-off as the jsdom harness.

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8000";
const CDP_URL = process.env.CDP_URL || "http://127.0.0.1:9222";
const VIEWPORT = { width: 1280, height: 900 };

let failures = 0;
let skipped = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures += 1;
}
function skip(name, why) {
  console.log(`SKIP  ${name} — ${why}`);
  skipped += 1;
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const isoDate = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 86_400_000);

async function api(path) {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.json();
}

// Minimal CDP client: one socket, flattened sessions, promise per command.
// Node 22+ ships WebSocket and fetch, so this needs no npm dependency.
class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener("message", (event) => this.receive(String(event.data)));
    socket.addEventListener("close", () => {
      for (const { reject, method } of this.pending.values()) {
        reject(new Error(`CDP closed while waiting for ${method}`));
      }
      this.pending.clear();
    });
  }

  static async connect(url) {
    let version;
    try {
      version = await (await fetch(`${url}/json/version`)).json();
    } catch {
      throw new Error(
        `No Chrome on ${url}. Start it with the command in tests/ui/README.md.`,
      );
    }
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error("CDP socket error")), {
        once: true,
      });
    });
    return new Cdp(socket);
  }

  receive(raw) {
    let message;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (message.id) {
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new Error(`${entry.method}: ${message.error.message}`));
      else entry.resolve(message.result ?? {});
      return;
    }
    for (const listener of this.listeners.get(message.method) ?? []) {
      listener(message.params ?? {}, message.sessionId);
    }
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
      this.socket.send(JSON.stringify(message));
    });
  }

  on(method, listener) {
    const list = this.listeners.get(method) ?? [];
    list.push(listener);
    this.listeners.set(method, list);
  }

  close() {
    this.socket.close();
  }
}

class Page {
  constructor(cdp, sessionId, targetId) {
    this.cdp = cdp;
    this.sessionId = sessionId;
    this.targetId = targetId;
  }

  send(method, params) {
    return this.cdp.send(method, params, this.sessionId);
  }

  async eval(expression) {
    const { result, exceptionDetails } = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (exceptionDetails) {
      throw new Error(
        exceptionDetails.exception?.description ?? exceptionDetails.text ?? "page exception",
      );
    }
    return result.value;
  }

  async waitFor(label, predicate, timeout = 20_000) {
    const deadline = Date.now() + timeout;
    let last;
    while (Date.now() < deadline) {
      last = await predicate();
      if (last) return last;
      await sleep(200);
    }
    throw new Error(`timed out after ${timeout}ms waiting for ${label} (last: ${last})`);
  }

  async box(selector) {
    return this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height,
               left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    })()`);
  }

  // A real mouse event at page coordinates. Leaflet listens on the document and
  // hit-tests the marker icon, so this exercises the drawn pixel, not the DOM node.
  async clickAt(x, y) {
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    for (const type of ["mousePressed", "mouseReleased"]) {
      await this.send("Input.dispatchMouseEvent", {
        type,
        x,
        y,
        button: "left",
        buttons: 1,
        clickCount: 1,
      });
    }
  }

  async clickSelector(selector) {
    // Scroll first: the sidebar can put a row below the viewport, and a click at
    // its un-scrolled coordinates would land on the map instead.
    const box = await this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      el.scrollIntoView({ block: "center", inline: "center" });
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    })()`);
    if (!box) throw new Error(`no element: ${selector}`);
    await this.clickAt(box.x, box.y);
  }

  close() {
    return this.cdp.send("Target.closeTarget", { targetId: this.targetId });
  }
}

// The map is a top-level `const` in a classic script, so indirect eval reaches it.
// Reading zoom/view is setup; every interaction below is a real mouse event.
const MAP = "window.eval(\"map\")";

async function mapZoom(page) {
  return page.eval(`${MAP}.getZoom()`);
}

async function openEventAt(page, event) {
  // Let a previous cluster zoom finish first: markercluster drops the moveend
  // that adds the new view's markers while its zoom animation is running, so a
  // view change issued mid-animation leaves the previous event's dot on screen.
  await page.waitFor("map animation to settle", async () => !(await page.eval(
    `document.querySelector(".leaflet-map-pane")?.classList.contains("leaflet-cluster-anim")`,
  )));
  // `animate: false` matters: with a pan animation the previous event's dot is
  // still at the centre when a click would land, so the popup would belong to
  // the wrong event. Jumping makes the centre deterministic.
  await page.eval(`(() => {
    const m = ${MAP};
    m.closePopup();
    m.setView([${event.lat}, ${event.lon}], m.getMaxZoom(), { animate: false });
  })()`);
  // Leaflet removes the popup node on the map's fade timer, so a click issued
  // immediately after closePopup still hits the previous event's anchored popup
  // (and reads its content). Wait for the DOM, not for `map._popup`: Leaflet
  // 1.9's closePopup does not clear that reference.
  await page.waitFor("previous popup closed", async () => (await page.eval(
    `document.querySelectorAll(".leaflet-popup").length`,
  )) === 0);
  await page.waitFor("map at max zoom", async () => (await mapZoom(page)) === (await page.eval(
    `${MAP}.getMaxZoom()`,
  )));
  await page.waitFor("event dots", async () => (await page.eval(
    `document.querySelectorAll(".leaflet-marker-icon.event-dot").length`,
  )) > 0);
  // setView centred this event, so its dot must be the one at the container
  // centre (at max zoom only coincident events cluster, and these are chosen to
  // be alone). Clicking that pixel is the test.
  const mapBox = await page.box("#map");
  const centre = { x: mapBox.x + mapBox.width / 2, y: mapBox.y + mapBox.height / 2 };
  await page.waitFor("this event's dot at the centre", async () => {
    const dot = await nearestDot(page);
    return Boolean(dot) && Math.hypot(dot.x - centre.x, dot.y - centre.y) < 4;
  });
  await page.clickAt(centre.x, centre.y);
  await page.waitFor("popup", async () => await page.eval(
    `Boolean(document.querySelector(".leaflet-popup-content"))`,
  ));
}

async function readPopup(page) {
  return page.eval(`(() => {
    const content = document.querySelector(".leaflet-popup-content");
    const badge = content?.querySelector(".corroboration");
    const popup = content?.closest(".leaflet-popup");
    const r = popup?.getBoundingClientRect();
    return {
      text: content ? content.textContent.replace(/\\s+/g, " ").trim() : null,
      badge: badge?.textContent ?? null,
      badgeClass: badge?.className ?? null,
      background: badge ? getComputedStyle(badge).backgroundColor : null,
      color: badge ? getComputedStyle(badge).color : null,
      rect: r ? { left: r.left, right: r.right, top: r.top, bottom: r.bottom } : null,
    };
  })()`);
}

async function nearestDot(page) {
  return page.eval(`(() => {
    const map = document.getElementById("map").getBoundingClientRect();
    const cx = map.x + map.width / 2;
    const cy = map.y + map.height / 2;
    const dots = [...document.querySelectorAll(".leaflet-marker-icon.event-dot")].map((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2,
               left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    });
    dots.sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy));
    return dots[0] ?? null;
  })()`);
}

function countsLabel(sources, articles) {
  return `${sources} outlet${sources === 1 ? "" : "s"} · ${articles} article${
    articles === 1 ? "" : "s"
  }`;
}

// Console/exception collection: only app errors, not network noise from tiles.
const jsErrors = [];
const tiles = [];
let cdp;
let page;

try {
  cdp = await Cdp.connect(CDP_URL);
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  page = new Page(cdp, sessionId, targetId);

  cdp.on("Runtime.exceptionThrown", (params, sid) => {
    if (sid !== sessionId) return;
    jsErrors.push(
      params.exceptionDetails?.exception?.description ?? params.exceptionDetails?.text,
    );
  });
  cdp.on("Runtime.consoleAPICalled", (params, sid) => {
    if (sid !== sessionId || params.type !== "error") return;
    jsErrors.push(params.args.map((arg) => arg.value ?? arg.description ?? "?").join(" "));
  });
  cdp.on("Network.responseReceived", (params, sid) => {
    if (sid !== sessionId || params.type !== "Image") return;
    if (/tile\.openstreetmap\.org/.test(params.response.url) && params.response.status === 200) {
      tiles.push(params.response.url);
    }
  });

  await page.send("Page.enable");
  await page.send("Runtime.enable");
  await page.send("Network.enable");
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: VIEWPORT.width,
    height: VIEWPORT.height,
    deviceScaleFactor: 1,
    mobile: false,
  });

  await page.send("Page.navigate", { url: `${BASE_URL}/` });
  await page.waitFor("conflict list", async () => (await page.eval(
    `document.querySelectorAll("#conflict-list .conflict-item").length`,
  )) > 0, 30_000);
  await page.waitFor("markers", async () => (await page.eval(
    `document.querySelectorAll(".cluster, .event-dot").length`,
  )) > 0);
  await page.waitFor("basemap", async () => tiles.length > 0, 15_000).catch(() => null);

  check("page renders conflicts and markers", true);
  check("no uncaught JS errors", jsErrors.length === 0, jsErrors.join(" | "));
  check("basemap tiles load", tiles.length > 0, `${tiles.length} OSM tiles`);

  // Cluster click: a real click on the drawn bubble must zoom the map.
  const beforeZoom = await mapZoom(page);
  const cluster = await page.box(".leaflet-marker-icon.cluster");
  if (!cluster) {
    skip("clicking a cluster zooms in", "no cluster at the current view");
  } else {
    await page.clickAt(cluster.x + cluster.width / 2, cluster.y + cluster.height / 2);
    await page
      .waitFor("zoom after cluster click", async () => (await mapZoom(page)) > beforeZoom, 8_000)
      .catch(() => null);
    const afterZoom = await mapZoom(page);
    check(
      "clicking a cluster zooms in",
      afterZoom > beforeZoom,
      `zoom ${beforeZoom} → ${afterZoom}`,
    );
  }

  // Expectations come from the API, so this works on a seeded or a real DB.
  const events = await api(`/api/events?start=${isoDate(daysAgo(30))}&end=${isoDate(new Date())}`);
  const mappable = events.filter((event) => event.lat != null && event.lon != null);

  // GDELT geocodes many events to the same country centroid, so a real DB has
  // coordinates shared by hundreds of events. The popup checks below need an
  // event that is alone at its pixel; the shared ones are covered by the stack
  // check, which is the only place a popup can belong to the wrong event.
  const coordCounts = new Map();
  for (const event of mappable) {
    const key = `${event.lat},${event.lon}`;
    coordCounts.set(key, (coordCounts.get(key) ?? 0) + 1);
  }
  // Clustering stays on at max zoom, where markercluster still groups anything
  // within ~55 px (well under 0.001° here), so "alone" must mean no neighbour in
  // the surrounding 0.001° cells, not just no exact duplicate.
  const cell = (event) => `${Math.round(event.lat * 1000)},${Math.round(event.lon * 1000)}`;
  const cells = new Map();
  for (const event of mappable) cells.set(cell(event), (cells.get(cell(event)) ?? 0) + 1);
  const alone = (event) => {
    const [lat, lon] = cell(event).split(",").map(Number);
    if (cells.get(cell(event)) !== 1) return false;
    for (let dLat = -1; dLat <= 1; dLat += 1) {
      for (let dLon = -1; dLon <= 1; dLon += 1) {
        if ((dLat || dLon) && cells.has(`${lat + dLat},${lon + dLon}`)) return false;
      }
    }
    return true;
  };
  const strong = mappable.find((event) => event.well_corroborated && alone(event));
  const muted = mappable.find(
    (event) =>
      event.sources === 1 && event.articles != null && !event.well_corroborated && alone(event),
  );
  const unknown = mappable.find(
    (event) => event.sources == null && event.articles == null && alone(event),
  );

  // Coincident events: clustering used to be disabled at zoom 13, so the events
  // that share GDELT's country-centroid all rendered on one pixel and only the
  // topmost could be clicked. At max zoom the stack must now be resolved (a
  // bubble click spiderfies it) — otherwise most events are unreachable.
  const [stackLat, stackLon, stackCount] =
    [...coordCounts.entries()]
      .map(([key, count]) => [...key.split(",").map(Number), count])
      .sort((a, b) => b[2] - a[2])[0] ?? [];
  if (!stackCount || stackCount < 2) {
    skip(
      "coincident events are individually reachable at max zoom",
      "no coordinate is shared by two events",
    );
  } else {
    await page.eval(`(() => {
      const m = ${MAP};
      m.closePopup();
      m.setView([${stackLat}, ${stackLon}], m.getMaxZoom(), { animate: false });
    })()`);
    await page.waitFor("markers at the shared coordinate", async () => (await page.eval(
      `document.querySelectorAll(".cluster, .event-dot").length`,
    )) > 0);
    // Zooming re-runs the cluster tree; wait until either a bubble or the stack's
    // dots exist, so a still-trickling render cannot be read as "no stack".
    await page.waitFor("the shared coordinate's markers", async () => (await page.eval(
      `document.querySelectorAll(".leaflet-marker-icon.cluster").length > 0 ||` +
        ` document.querySelectorAll(".leaflet-marker-icon.event-dot").length >= 2`,
    )));
    const stackBox = await page.box("#map");
    const stackCentre = {
      x: stackBox.x + stackBox.width / 2,
      y: stackBox.y + stackBox.height / 2,
    };
    // A fix may keep the coordinate clustered at max zoom; clicking the bubble
    // is then what spreads the events out.
    const hasClusterAtCentre = await page.eval(`(() => {
      const map = document.getElementById("map").getBoundingClientRect();
      const cx = map.x + map.width / 2;
      const cy = map.y + map.height / 2;
      return [...document.querySelectorAll(".leaflet-marker-icon.cluster")].some((el) => {
        const r = el.getBoundingClientRect();
        return Math.hypot(r.x + r.width / 2 - cx, r.y + r.height / 2 - cy) < 2;
      });
    })()`);
    // Compare the pixel positions of the dots that belong to this coordinate,
    // matched by the marker titles (headline/place) rather than by geometry, so
    // unrelated dots nearby cannot make a stack look resolved. The spiderfy
    // animation moves the dots after they are added, so wait for the spread
    // rather than reading the centre the animation starts from.
    const stackTitles = mappable
      .filter((event) => event.lat === stackLat && event.lon === stackLon)
      .map((event) => event.headline || event.place_name || "event");
    const readSpread = () => page.eval(`(() => {
      const titles = new Set(${JSON.stringify(stackTitles)});
      const dots = [...document.querySelectorAll(".leaflet-marker-icon.event-dot")]
        .filter((el) => titles.has(el.getAttribute("title")));
      const positions = new Set(dots.map((el) => {
        const r = el.getBoundingClientRect();
        return Math.round(r.x + r.width / 2) + "," + Math.round(r.y + r.height / 2);
      }));
      return { dots: dots.length, positions: positions.size };
    })()`);
    if (hasClusterAtCentre) {
      await page.clickAt(stackCentre.x, stackCentre.y);
      await page.waitFor(
        "the stack to spiderfy",
        async () => (await readSpread()).positions > 1,
        8_000,
      ).catch(() => null);
    }
    const spread = await readSpread();
    check(
      "coincident events are individually reachable at max zoom",
      spread.positions > 1,
      `${stackCount} events share ${stackLat},${stackLon}; ` +
        `${spread.dots} dots at ${spread.positions} distinct pixel(s)` +
        (hasClusterAtCentre ? " after clicking the bubble" : ""),
    );
    // Leave the map clustered for the popup checks that follow.
    await page.eval(`window.eval("markers").unspiderfy()`).catch(() => null);
  }

  if (!strong) {
    skip("popup shows corroboration counts", "no well-corroborated event in range");
  } else {
    await openEventAt(page, strong);
    const popup = await readPopup(page);
    const dot = await nearestDot(page);
    check(
      "clicking an event dot opens its popup",
      popup.text?.includes(strong.event_date ?? "") && popup.text?.includes(strong.place_name ?? strong.country ?? ""),
      popup.text,
    );
    const dx = dot && popup.rect
      ? Math.abs((popup.rect.left + popup.rect.right) / 2 - (dot.left + dot.right) / 2)
      : Infinity;
    const gapAbove = dot && popup.rect ? dot.top - popup.rect.bottom : Infinity;
    check(
      "popup is anchored above the clicked marker",
      dx <= 40 && gapAbove >= -12 && gapAbove <= 80,
      `dx ${Number.isFinite(dx) ? dx.toFixed(1) : "?"}px, gap ${Number.isFinite(gapAbove) ? gapAbove.toFixed(1) : "?"}px`,
    );
    const label = countsLabel(strong.sources, strong.articles);
    check("popup shows the corroboration counts", popup.badge === label, popup.badge);
    // The green in style.css; a visual contract, updated with the CSS.
    check(
      "well-corroborated badge uses the strong style",
      popup.badgeClass === "corroboration strong" &&
        popup.background === "rgb(209, 231, 221)" &&
        popup.color === "rgb(15, 81, 50)",
      `${popup.badgeClass} ${popup.background} / ${popup.color}`,
    );
    const detail = await page.eval(`(() => ({
      heading: document.getElementById("detail-heading")?.textContent?.trim() ?? null,
      badge: document.querySelector("#detail .corroboration")?.textContent ?? null,
    }))()`);
    check(
      "detail pane mirrors the popup",
      detail.badge === label &&
        detail.heading === (strong.headline || strong.place_name || "Event"),
      `heading=${detail.heading ?? "?"} badge=${detail.badge ?? "?"}`,
    );
  }

  if (!muted) {
    skip("single-outlet badge stays muted", "no one-outlet event in range");
  } else {
    await openEventAt(page, muted);
    const popup = await readPopup(page);
    check(
      "single-outlet badge stays muted",
      popup.badge === countsLabel(muted.sources, muted.articles) &&
        popup.badgeClass === "corroboration" &&
        popup.background === "rgb(227, 227, 227)",
      `${popup.badge ?? "no badge"} ${popup.badgeClass ?? ""} ${popup.background ?? ""}`,
    );
  }

  if (!unknown) {
    skip("event without counts shows no badge", "no event with unknown counts is mappable");
  } else {
    await openEventAt(page, unknown);
    const popup = await readPopup(page);
    check(
      "event without counts shows no badge",
      Boolean(popup.text) && popup.badge === null,
      popup.badge ?? "no badge",
    );
  }

  // Pick-on-map: the form fills, and the API still says the event is unplaced.
  const unplaced = events.find((event) => event.lat == null && event.conflict_id != null);
  if (!unplaced) {
    skip("pick-on-map fills both coordinates", "no unplaced event in range");
  } else {
    const selector = `#nolocation-list .nl-place[data-id="${unplaced.conflict_id}"]`;
    const rowExists = await page.eval(`Boolean(document.querySelector(${JSON.stringify(selector)}))`);
    if (!rowExists) {
      skip("pick-on-map fills both coordinates", "no-location row is not visible in this range");
    } else {
      const before = await api(`/api/events/${unplaced.id}`);
      // The panel is a collapsed <details> by design, so a real mouse cannot hit
      // the row until the summary is clicked open. Toggle only when closed:
      // clicking an open summary would collapse it again.
      if (!(await page.eval(`document.getElementById("nolocation-panel").open`))) {
        await page.clickSelector("#nolocation-panel > summary");
      }
      await page.waitFor("no-location panel open", async () => await page.eval(
        `document.getElementById("nolocation-panel").open === true`,
      ));
      await page.clickSelector(selector);
      await page.waitFor("picking mode", async () => await page.eval(
        `document.getElementById("map").classList.contains("picking")`,
      ));
      const mapBox = await page.box("#map");
      await page.clickAt(mapBox.x + mapBox.width / 2, mapBox.y + mapBox.height / 2);
      await page.waitFor("coordinates filled", async () => await page.eval(
        `Boolean(document.getElementById("edit-ev-lat")?.value && document.getElementById("edit-ev-lon")?.value)`,
      ));
      const coords = await page.eval(`({
        lat: document.getElementById("edit-ev-lat").value,
        lon: document.getElementById("edit-ev-lon").value,
      })`);
      const after = await api(`/api/events/${unplaced.id}`);
      check(
        "pick-on-map fills both coordinates",
        Number.isFinite(Number(coords.lat)) && Number.isFinite(Number(coords.lon)),
        `${coords.lat}, ${coords.lon}`,
      );
      check(
        "picking mode ends after the map click",
        await page.eval(`!document.getElementById("map").classList.contains("picking")`),
      );
      check(
        "pick-on-map does not write until saved",
        after.lat === before.lat && after.lon === before.lon,
        `API still says ${after.lat}, ${after.lon}`,
      );
    }
  }

  check("no uncaught JS errors after interactions", jsErrors.length === 0, jsErrors.join(" | "));
} catch (err) {
  // A thrown setup/assertion helper is a failure, not a crash: report it in the
  // same format and keep the exit code meaningful for a shell gate.
  failures += 1;
  console.error(`FAIL  ${err instanceof Error ? err.message : err}`);
} finally {
  if (page) await page.close().catch(() => {});
  cdp?.close();
}

console.log(
  failures
    ? `\n${failures} FAILED${skipped ? `, ${skipped} skipped` : ""}`
    : `\nALL CHECKS PASSED${skipped ? ` (${skipped} skipped)` : ""}`,
);
process.exitCode = failures ? 1 : 0;
