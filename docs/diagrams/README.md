# Diagrams

Mermaid sources for the architecture. Each block renders inline on GitHub and in any
Mermaid renderer (mermaid.live, or `mmdc -i in.mmd -o out.svg`). They are plain text, so
they diff and review like code.

| Diagram | Shows | Derived from |
|---|---|---|
| Architecture | Module boundaries and the runtime data flow between them | `../CAPABILITY-MAP.md` |
| Daily pipeline | The daily run: fetch → filter → persist → group, with both gates | `../SPEC-ingestion.md`, `../SPEC-extraction.md`, `app/extract/run.py` |
| Schema | The five tables, their keys, and the one real foreign key | `app/models.py`, `../SPEC-storage.md` |
| Classes | The adapter and classifier seams, the ORM models, and the API schema hierarchy | `app/extract/base.py`, `app/extract/classifier.py`, `app/models.py`, `app/api/schemas.py` |
| Request flow | What one page load, date scrub, marker click, or edit actually does | `app/api/routes.py`, `app/queries.py`, `app/static/app.js` |

## Architecture

```mermaid
flowchart LR
  model["Zero-shot NLI model<br/>transformers + torch (CPU)<br/>degrades gracefully if absent"]
  gdelt[("GDELT 2.0<br/>15-min .export.CSV.zip<br/>61-col TSV, no header")]
  ingestion["ingestion<br/>app/ingest/ gdelt.py · normalizer.py · raw_store.py<br/>download → normalize → dedupe"]
  extraction["extraction<br/>app/extract/<br/>BaseSourceAdapter (swappable)<br/>filter · map · intensity · group"]
  storage[("storage<br/>SQLite · SQLAlchemy 2.0<br/>models.py · queries.py · db.py<br/>5 tables + read helpers")]
  api["api<br/>app/api/ routes.py · schemas.py<br/>FastAPI /api/* · manual edit/create"]
  ui["ui<br/>app/static/ index.html · map.js/state.js/list.js/detail.js · app.js wiring<br/>Leaflet map + time scrub"]
  browser["Browser<br/>Leaflet + OSM tiles<br/>no build step"]

  gdelt -->|download| ingestion
  ingestion -->|raw rows| extraction
  extraction -->|drafts| storage
  storage -->|queries| api
  api -->|JSON| ui
  ui -->|static| browser
  model -.->|filter_by_zero_shot (degradable)| extraction
  browser -.->|manual edits (PATCH/POST)| api
```

Dependency direction is one-way (build order): `storage → ingestion → extraction → api → ui`.
Extraction is the swappable source boundary — GDELT now, T5/LLM later via `BaseSourceAdapter`.
Adapters stay pure: no DB or HTTP inside `gdelt_adapter.py` / `base.py`.

## Daily pipeline

```mermaid
flowchart TD
  s1["run() — resolve target days (lookback_days)"]
  s2["[phase] retry_stranded_raw_days<br/>process pending raw rows from prior crashed days"]
  s3["per target day: enumerate 96 × 15-min timestamps"]
  s4["download .export.CSV.zip (404 → skip, 5xx → fail)"]
  s5["parse 61-col TSV (positional, no header)<br/>dedupe by GLOBALEVENTID"]
  s6["store_raw_events → raw_event<br/>(persisted BEFORE extraction/filtering)"]
  s7["GDELTAdapter.to_event_draft — map into EventDraft"]
  d1{"EventRootCode in 18/19/20?"}
  d1no["drop: outcome = not_armed_conflict"]
  s8["filter_by_zero_shot — NLI classifies source URL slug"]
  d2{"passes? (skipped if model unavailable)"}
  d2no["drop: outcome = filtered_out"]
  s9["persist_drafts → conflict_event"]
  s10["mark_raw_events outcome"]
  s11["[phase] group_events — proximity 100 km + time window"]
  s12["[phase] prune_raw_events — raw_retention_days (30)"]
  s13["audit: ingestion_run row per day + per phase"]

  s1 --> s2 --> s3 --> s4 --> s5 --> s6 --> s7 --> d1
  d1 -- no --> d1no
  d1 -- yes --> s8 --> d2
  d2 -- no --> d2no
  d2 -- yes --> s9 --> s10 --> s11 --> s12 --> s13
```

## Schema

```mermaid
erDiagram
  conflict ||--o{ conflict_event : "1 to 0..N"
  conflict {
    int id PK
    string name
    string country
    date start_date
    date end_date
    string status
    datetime created_at
    datetime updated_at
  }
  conflict_event {
    int id PK
    string source_event_id UK
    int conflict_id FK
    string place_name
    string country
    float lat
    float lon
    date event_date
    string event_type
    string actor_a
    string actor_b
    int fatalities
    int intensity
    text summary
    string source_url
    float confidence
    string provenance
    datetime created_at
    datetime updated_at
  }
  raw_event {
    int id PK
    string source_event_id UK
    date source_day
    date event_date
    string event_root_code
    string source_file
    text payload
    datetime ingested_at
    datetime processed_at
    string outcome
  }
  edit_log {
    int id PK
    string target_type
    int target_id
    string field
    text old_value
    text new_value
    datetime edited_at
  }
  ingestion_run {
    int id PK
    date source_day
    string mode
    string phase
    datetime started_at
    datetime finished_at
    string status
    int items_seen
    int items_new
    text error
    text degraded_reason
  }
```

## Classes

```mermaid
classDiagram
  class BaseSourceAdapter {
    <<abstract>>
    +to_event_draft(raw: dict) EventDraft | None
  }
  class EventDraft {
    <<dataclass>>
    +source_event_id
    +place_name / country
    +lat / lon
    +event_date
    +event_type / actor_a / actor_b
    +fatalities
    +intensity
    +summary / source_url
    +confidence
  }
  class GDELTAdapter {
    -ARMED_CONFLICT_ROOT_CODES = 18, 19, 20
    +to_event_draft(raw) EventDraft | None
  }
  class BinaryClassifier {
    <<Protocol>>
    +classify_many(texts, threshold) list[(bool, float)]
  }
  class SingleTextClassifier {
    <<Protocol>>
    +classify(text, threshold) (bool, float)
  }
  class ZeroShotConflictClassifier {
    -_pipeline (transformers, CPU)
    -_labels
    +classify(text, threshold)
    +classify_many(texts, threshold)
  }
  class Geocoder {
    <<Protocol>>
    +lookup(query) (lat, lon, country) | None
  }
  class NominatimGeocoder {
    -min_interval = 1.1s (rate limit)
    +lookup(query)
  }
  class GDELTClient {
    +fifteen_minute_stamps(day)
    +download_export(ts)
    +fetch_day(day)
  }
  class Conflict
  class ConflictEvent
  class RawEvent
  class EditLog
  class IngestionRun
  class ConflictOut
  class ConflictSummary
  class ConflictDetail
  class ConflictEventOut
  class EventCreate

  GDELTAdapter --|> BaseSourceAdapter : implements
  GDELTAdapter ..> EventDraft : returns
  ZeroShotConflictClassifier ..|> BinaryClassifier : implements
  ZeroShotConflictClassifier ..|> SingleTextClassifier : implements
  NominatimGeocoder ..|> Geocoder : implements
  GDELTClient ..> GDELTAdapter : raw dicts
  Conflict "1" --> "0..*" ConflictEvent
  ConflictDetail --|> ConflictSummary
  ConflictSummary --|> ConflictOut
  ConflictEventOut ..> ConflictEvent : serialises
  EventCreate ..> ConflictEvent : creates
```

## Request flow

```mermaid
flowchart TD
  load["[UI] open / — index.html + split scripts, Leaflet + OSM tiles, no build step"]
  http_get["[HTTP] GET /api/conflicts?start+end · GET /api/events?start+end"]
  validate["[route] _validate_range — start > end → 422, never 500"]
  queries["[queries.py] conflicts_active_in_range, events_in_range<br/>one events query for all conflicts (N+1 guard ≤5)"]
  sqlite[("SQLite — conflict, conflict_event, raw_event, edit_log, ingestion_run")]
  summarize["[route] _summarize per conflict<br/>intensity = max(event) · coordinate = latest event<br/>headline = slug_to_text(source_url), else summary"]
  render["[UI] renderEventMarkers()<br/>clusters + 'Conflicts in view' + 'No location'<br/>membership from events, never the summary point"]
  d_scrub{"changed the date range?"}
  d_marker{"clicked a marker?"}
  d_edit{"edited an event or conflict?"}
  notice["[UI] error → live notice region<br/>every API failure surfaces here"]
  event_detail["[HTTP] GET /api/events/{id} · [route] _event_out"]
  popup["[UI] detail popup: place, date, type, actors,<br/>intensity, provenance, source link, raw JSON"]
  patch["[HTTP] PATCH /api/events/{id}<br/>PATCH/POST /api/conflicts, POST /api/events"]
  apply["[route] merged-record checks, then _apply_patch<br/>lat/lon both-or-neither; one edit_log row per changed field"]
  commit["[route] commit → refresh → response<br/>provenance stays auto unless user set it"]

  load --> http_get --> validate --> queries --> sqlite --> summarize --> render
  render --> d_scrub
  d_scrub -- no --> d_marker
  d_scrub -- re-query --> http_get
  d_marker -- no --> d_edit
  d_marker -- yes --> event_detail --> popup
  d_edit -- yes --> patch --> apply --> commit
  commit -. reload .-> http_get
  validate -. 4xx/5xx .-> notice
  apply -. 4xx/5xx .-> notice
```

## What the diagrams assert

- **Architecture** — dependency runs one way, `storage → ingestion → extraction →
  api → ui`, so build follows the same order. Extraction is a swappable boundary: the
  zero-shot gate hangs off it as a dashed (degradable) dependency, and manual edits run
  back from the browser to the API.
- **Daily pipeline** — `raw_event` is written *before* extraction and filtering, so a
  failed run leaves replayable rows. The two gates are the CAMEO root-code allow-list
  (`{18, 19, 20}`) and the zero-shot semantic filter, which is skipped — not failed — when
  the model is unavailable. `group_events` and `prune_raw_events` run after the per-day
  loop; each gets its own `ingestion_run` row.
- **Schema** — `conflict_event → conflict` is the only foreign key. `edit_log`
  points at its target by `target_type` + `target_id` with no FK, and `raw_event` /
  `ingestion_run` stand alone.
- **Classes** — `BaseSourceAdapter.to_event_draft` is the one method a replacement
  source must implement, and it may not touch the DB or HTTP. The classifier and geocoder
  seams are `Protocol`s rather than abstract classes, because typing against the concrete
  class made every test stub a type error. The schema chain `ConflictOut → ConflictSummary
  → ConflictDetail` is inheritance, not duplication: detail adds only `events`.
- **Request flow** — the map is drawn from *events*, and `_summarize` decides each
  conflict's single summary point as its latest event in range. That is why the sidebar
  tests membership against the events rather than that point. `_apply_patch` writes one
  `edit_log` row per field that actually changed, and lat/lon are validated on the merged
  record (both or neither), never on the partial payload alone.

## Keeping them honest

The diagrams restate the specs, so a spec change that isn't mirrored here leaves a
diagram that lies. When `EventDraft`, the grouping rule, the schema, or an endpoint
changes, update the matching block in the same change.
