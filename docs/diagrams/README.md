# Diagrams

Draw.io sources for the architecture. Each file is a single-page `.drawio` that opens
directly in the [draw.io editor](https://app.diagrams.net), the desktop app, or VS Code
(with the Draw.io Integration extension).

| File | Shows | Derived from |
|---|---|---|
| `architecture.drawio` | Module boundaries and the runtime data flow between them | `../CAPABILITY-MAP.md` |
| `pipeline.drawio` | The daily run: fetch → filter → persist → group, with both gates | `../SPEC-ingestion.md`, `../SPEC-extraction.md`, `app/extract/run.py` |
| `schema.drawio` | The five tables, their keys, and the one real foreign key | `app/models.py`, `../SPEC-storage.md` |
| `classes.drawio` | The adapter and classifier seams, the ORM models, and the API schema hierarchy | `app/extract/base.py`, `app/extract/classifier.py`, `app/models.py`, `app/api/schemas.py` |
| `request-flow.drawio` | What one page load, date scrub, marker click, or edit actually does | `app/api/routes.py`, `app/queries.py`, `app/static/app.js` |

## What the diagrams assert

- **`architecture.drawio`** — dependency runs one way, `storage → ingestion → extraction →
  api → ui`, so build follows the same order. Extraction is a swappable boundary: the
  zero-shot gate hangs off it as a dashed (degradable) dependency, and manual edits run
  back from the browser to the API.
- **`pipeline.drawio`** — `raw_event` is written *before* extraction and filtering, so a
  failed run leaves replayable rows. The two gates are the CAMEO root-code allow-list
  (`{18, 19, 20}`) and the zero-shot semantic filter, which is skipped — not failed — when
  the model is unavailable. `group_events` and `prune_raw_events` run after the per-day
  loop; each gets its own `ingestion_run` row.
- **`schema.drawio`** — `conflict_event → conflict` is the only foreign key. `edit_log`
  points at its target by `target_type` + `target_id` with no FK, and `raw_event` /
  `ingestion_run` stand alone.
- **`classes.drawio`** — `BaseSourceAdapter.to_event_draft` is the one method a replacement
  source must implement, and it may not touch the DB or HTTP. The classifier and geocoder
  seams are `Protocol`s rather than abstract classes, because typing against the concrete
  class made every test stub a type error. The schema chain `ConflictOut → ConflictSummary
  → ConflictDetail` is inheritance, not duplication: detail adds only `events`.
- **`request-flow.drawio`** — the map is drawn from *events*, and `_summarize` decides each
  conflict's single summary point as its latest event in range. That is why the sidebar
  tests membership against the events rather than that point. `_apply_patch` writes one
  `edit_log` row per field that actually changed, and lat/lon are validated on the merged
  record (both or neither), never on the partial payload alone.

## Keeping them honest

The diagrams restate the specs, so a spec change that isn't mirrored here leaves a diagram
that lies. When `EventDraft`, the grouping rule, the schema, or an endpoint changes, update
the matching file in the same change.

Geometry is hand-placed (grid of 10) rather than auto-laid-out, except that edges are
routed on open. Keep edge labels to one or two words: the 60–130 px gaps between boxes hold
nothing longer without colliding with a box, which is how `download .export.CSV.zip`
previously overlapped the GDELT and ingestion boxes.
