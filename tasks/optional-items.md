# Optional items — specs for the two deferred reminders

Both of these are listed under "Optional" in `tasks/todo.md` and exist as *reminders,
not work*. This file turns each into a spec so they can be reopened on a real trigger
without re-deriving the reasoning. Neither is implemented here; both are "Ask first"
per `AGENTS.md`, and neither has fired its trigger yet.

- Item A: fetch real article `<title>` instead of URL-slug headlines.
- Item B: split `app/static/app.js` when it grows further.

---

## Item A — real article `<title>` instead of URL-slug headlines

### Trigger (why it is still deferred)

Headlines are currently derived from the **URL slug** by `slug_to_text` in
`app/extract/classifier.py`, then surfaced by `_headline()` in `app/api/routes.py`
(prefer best-effort slug text, fall back to `event.summary`). Reopen this if and only
if the slug proves unusable in practice — that is the criterion already recorded in
`tasks/todo.md`. Concrete signals that would fire the trigger:

- A briefing (`scripts/briefing.py`) ships more than once with a headline that is a
  bare number, an article id, or a country name (the known bad slugs — see below).
- A subscriber says a headline is unreadable and there is no summary to fall back on.
- The case study or a demo needs a clean headline and the slug path visibly fails.

Until one of these happens, the slug path is close enough and costs nothing.

### The problem with the naive fix

The obvious change — "before persisting, `GET` each `source_url` and parse its
`<title>`" — is a web crawl, and it breaks several invariants the project holds:

1. **The pipeline is offline by design.** `scripts/briefing.py` is "stdlib only, no
   network, read-only". The daily fetch already talks to GDELT; making it also fetch
   ~tens of thousands of arbitrary third-party article pages per day (one per
   `source_event` roughly) turns a fast, retried, resumable download into a slow,
   flaky, unbounded crawl with a different failure mode per publisher (paywalls,
   bot walls, `robots.txt`, TLS, 4xx/5xx, JS-rendered pages with no server `<title>`).
2. **Idempotency and re-filtering depend on raw rows.** `raw_event` retention is
   already a decision (above: keep 30 days). A title fetched today is user-visible
   metadata tied to a *processed* `conflict_event`; adding a crawl step means the
   "re-filter from `raw_event`" story must also re-fetch titles (or accept that
   re-processed rows lose their title), which is a new consistency rule.
3. **`headline` is derived, not stored.** There is no `conflict_event.headline`
   column; `_headline()` recomputes from `source_url`. Real titles are content, not a
   pure function of the row, so they would need a schema migration to persist — which
   is explicitly "Ask first" and "Any schema migration on existing data" is a
   boundary. A title that must be re-fetched on every read is a new N+1 or a cache.

In short: the remembered one-liner hides a schema migration + a crawler + a
retry/robots/ethics story, not a one-file tweak.

### Why slugs are usually fine (and the known costs)

`slug_to_text` already strips a leading `\d{6,}-` article id and a trailing
`\d{5,}` id, drops `.html?`/`.php`/`.aspx?`, and collapses `-_` to spaces. That
handles the common GDELT forms. The residual failures are:

- A slug that is the bare numeric article id (`2087359569-`, `...-2087359569`) →
  `_headline()` returns the id only if it is not all digits (it filters those),
  otherwise falls through to `event.summary`.
- A slug that is a country or place word ("belgium", "belfast-belfast-united-kingdom")
  → a readable but place-derived headline, which the Task 12 briefing already flagged
  as needing a human pass over titles anyway.

The second is a *grouping/naming* signal, not a headline-fetch signal: a real
`<title>` would still read as the cluster's place, because the cluster *is* a place.
So title-fetch does not fix the visible symptom; a human pass over theatre titles
does.

### Spec (if reopened)

Decision to make first: **where** titles come from and **when** they are fetched.

**Chosen shape (recommended), if reopened** — fetch at read time, side-channel, never
blocking the event row:

- **No schema migration.** If a title must be persisted, use `raw_event.payload`
  (already JSON, already retained by the `raw_retention_days` decision) — do not add a
  `conflict_event.headline` column. A title is source metadata, and the payload is the
  source-metadata column. This keeps "re-filter from raw" honest: re-processing
  re-reads the same stored title, no re-fetch.
- **Storage at ingest, best-effort.** In `app/ingest`, after `source_url` is known,
  store a fetched title into `payload["article_title"]`. Strictly offline-safe:
  fetch with a short timeout, respect a `fetch_titles: false` config default, retry the
  same backoff as `GDELTClient._request` (0.5 s doubling, network + 408/425/429/5xx
  only), and on any failure leave the key absent — never fail the run, never block a
  row on a flaky publisher. Record how many fetched/skipped in `ingestion_run`
  metadata if it is cheap, else leave it out (the audit already has `degraded_reason`);
  do not add a column for a count that has no consumer.
- **Render path.** `_headline()` becomes: `payload["article_title"]` →
  `slug_to_text(source_url)` → `event.summary` → `None`. The existing precedence
  ("prefer the article headline, fall back to the summary") is unchanged; the only new
  first branch is the fetched title.
- **Constraints (acceptance):**
  1. No network in the read path (`_headline` stays pure; the fetch happened at
     ingest). Add a test that `_headline` with a populated payload never performs
     I/O (it cannot, by construction, but assert the fallback order).
  2. `fetch_titles: false` (default) keeps byte-for-byte current behaviour — a test
     fixture with no `article_title` key renders exactly the slug path.
  3. A missing/failed fetch leaves the key absent and the row still ingests.
     (Mutation test: drop the "on failure keep going" branch → the ingest test
     fails.) A 4xx/5xx/timeout/malformed-HTML page all → absent key, no error row.
  4. `<title>` is stripped of publisher boilerplate and HTML entities, length-capped
     (e.g. 200 chars), and every interpolated render goes through `esc()` (it already
     does in `app.js`, but the cap must be enforced server-side too — it is now
     arbitrary external text, not a slug we control).
  5. `robots.txt` / rate politeness: the recommended shape still fetch-once-per-event
     at ingest, which is the same volume as the downstream consumer; document a per-host
     throttle if it is ever turned on for a backfill (thousands of pages).

**Alternative shape (rejected unless the human-pass idea is also rejected):** fetch
real titles only for a *curated* briefing pass, by hand or a small separate script
(`scripts/enrich_titles.py`), never in the daily pipeline. This is the cheapest way to
get real titles for the eight demand-test issues while the headline-fetch machinery
stays out of the data path entirely. Prefer this if the goal is "the briefing reads
well" rather than "every event has a real title".

### Risk / decision record

- Do **not** store the fetched title in `conflict_event.summary` or a new column —
  that is the schema-migration boundary.
- A title is user-visible but **not** a truth claim or a verification signal; never
  display it as corroboration (same rule as Task 10/11: counts are counts, titles are
  decoration).
- A mis-fetched title (a paywall "Subscribe to continue", a bot-check page) is
  *worse* than the slug. That is the strongest argument for the curated/briefing-only
  alternative: a human sees the garbage; the pipeline does not.

---

## Item B — split `app/static/app.js`

### Trigger (why it is still deferred)

`TODO.md` says "no trigger yet; not actionable now". The concrete trigger, to be
recorded: **`app.js` exceeds ~1,500 lines, or a single conceptual unit (see the seam
list below) needs a second maintainer's attention in one review.** At 1,120 lines it
has not fired. Reopen when either happens, not before — a split for its own sake is a
refactor with no behavioural change and a real risk of breaking the no-build-step
assumption (see "Constraint").

### Constraint (the reason it is not a free win)

The frontend is **vanilla ES modules, no build step** (`README`/`AGENTS.md`). Splitting
into multiple `.js` files must stay that way: `index.html` loads them as `<script
type="module">` with their `import`/`export` edges, served as-is. No bundler, no
minifier, no `package.json` build. Any split that introduces one is rejected on
principle.

### Current shape (the facts a split must respect)

- ~1,120 lines, one file. State lives in module-scope `let`s near the top
  (`currentStart`, `rangeConflicts`, `conflictsLoaded`, timers, etc.).
- Two globals the UI hard-depends on: `map` (Leaflet) is constructed at load and used
  by every feature; `markers` (the `L.markerClusterGroup`) is assigned then `.addTo(map)`.
- Functions cluster around clear seams (see below). `esc()`, `fmtDate()`,
  `numberOrNull()` and the `api` object are the shared leaf utilities everyone calls.

### Seam map (the proposed cut points, for when it fires)

A split should follow these boundaries, each module exporting only what the others
need and importing `map`/`esc`/`api` from the shared core:

1. **`core.js`** — `HOME_VIEW`, `map`, tile layer, `heatColor`/`clusterHeat`,
   the `markers` cluster group, `ResetViewControl`, `esc`, `fmtDate`,
   `parseDateInput`, `numberOrNull`, `intOrNull`, `formatApiDetail`, and the `api`
   object (the four HTTP verbs). This is the thing every other module imports.
2. **`state.js`** — the module-scope `let` declarations and their accessors, moved
   here so no module holds mutable module-globals; the other modules import a
   `state` object or accessor functions. (This is the hard part: today those `let`s
   are free module-scope names used directly everywhere — that is exactly the
   coupling a split exists to remove.)
3. **`conflicts.js`** — `loadConflicts`, `updateRange`, `defaultDates`,
   `setDateInputs`, `renderConflictList`, `paintConflictList`, `conflictItem`,
   `intensityClass`, the in-view membership and no-location list
   (`paintNoLocationList`, `setLocationFor`).
4. **`events.js`** — `renderEventMarkers`, `eventMarker`, `corroborationBadge`,
   `eventPopup`, `showEvent`, `renderEventEditForm`, `saveEvent`, and the
   coordinate-pick flow (`startCoordinatePick`/`stopCoordinatePick`).
5. **`detail.js`** — `showConflict`, `renderConflictDetail`, `renderEditPanel`,
   `revealDetail`, the reveal/pending-reveal timers.
6. **`controls.js`** — `showNotice`, `setBusy`, and any remaining pure-UI helpers.

`index.html` loads them in dependency order (`core` → `state` → the rest). The
`?v=N` asset-busting query in `index.html` is bumped once for the split (it already
busts `app.js`; a multi-file split must bump the version for every file it serves, or
a cached old file breaks the module graph).

### Acceptance (for when it is actually done)

1. `node --check` on each file, and the module graph loads with no console errors
   (jsdom `map-smoke.mjs` already runs real Leaflet against a server — it is the
   natural regression gate; no new harness).
2. Every existing check in `tests/ui/map-smoke.mjs` and `tests/ui/browser-tests.mjs`
   passes unchanged — the split is a no-behaviour refactor, so it must not change a
   single visible outcome (clustering counts, popup anchoring, notice region,
   Pick-on-map, no-location panel).
3. No shared mutable globals left in any feature module: state access goes through
   `state.js`. (A lint-ish test can assert the only top-level `let` in feature
   modules are the re-export of imported names — keep this as a review checklist,
   not a new tool.)
4. `esc()` is still applied to every interpolated external value in the files that
   move — a mechanical move must not drop the calls (this is why a split is riskier
   than it looks; grep the diff for `esc(` before/after).

### Why not now

At 1,120 lines the file is readable in one sitting and the seams are already clean —
the functions are small and single-purpose, and the module-scope state is the only
real entanglement. A split now is a large, untestable-in-isolation diff (the UI
harnesses are not in CI, so regressions there are invisible to the gates) that buys
no new capability. Wait for the line count or a real second-maintainer event.

---

## Status

Both items remain deferred. This file is the spec to execute against when a trigger
fires; it does not change any shipped code. `tasks/todo.md`'s two "Optional" rows now
point here.
