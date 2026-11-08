# Spec: extraction — event-source adapter (swappable)

## Objective
Turn raw GDELT events into `conflict_event` candidates and group them into conflicts:
filter to armed-conflict events (a root-code gate plus a zero-shot semantic gate), map
fields into our schema, and derive intensity (1–5). Expose a swappable source adapter so
a T5 model or an LLM can replace/augment GDELT later without touching other modules.

## Tech stack
Python + `transformers`/`torch` (zero-shot armed-conflict filter, CPU; degrades gracefully
when the model is unavailable). (Conventions: CAPABILITY-MAP.md)

## Interface (the swappable boundary)
- `app/extract/base.py`: `BaseSourceAdapter` with `to_event_draft(raw) -> EventDraft | None`
- `app/extract/gdelt_adapter.py`: default implementation
- `app/extract/t5_adapter.py` / `llm_adapter.py`: later upgrades (same interface)
- `EventDraft`: source_event_id, place_name, country, lat, lon, event_date, event_type,
  actor_a, actor_b, fatalities, intensity, summary, source_url, confidence

## Filtering + mapping
1. Keep only armed-conflict event codes (GDELT CAMEO `EventRootCode` in {18 assault, 19 fight,
   20 unconventional mass violence}); drop protests (14), diplomacy, etc.
2. Map GDELT fields: `ActionGeo_*` → place/country/lat/lon; `Actor1Name`/`Actor2Name` → actors;
   `EventBaseCode` → `event_type`; `SQLDATE` → `event_date`; `SOURCEURL` → `source_url`;
   `GLOBALEVENTID` → `source_event_id`.
3. `fatalities` stays null: the free GDELT 2.0 export carries no casualty columns, so the
   adapter has nothing to map. Intensity is derived from event type + Goldstein scale
   instead; manual edits may still set a count.
4. `derive_intensity(event_type, fatalities, goldstein) -> 1..5` — a small pure, unit-tested
   function (severity by event type + fatality/tone adjustment, clamped to 1–5).
5. `confidence` from `NumArticles` (more coverage → higher, capped at 1.0). A missing or
   unparsable count is the same absence and gives `0.0`, not a second default.
6. Zero-shot gate: `filter_by_zero_shot` drops drafts whose source URL slug doesn't
   classify as armed conflict (NLI model, threshold from config). Drafts without a
   source URL are kept — the adapter's root-code filter has already run. If the model
   is unavailable the pipeline skips this gate rather than failing.

## Commands
- `pytest tests/test_extraction.py`

## Project structure (module)
- `app/extract/base.py` — `BaseSourceAdapter` + `EventDraft`
- `app/extract/gdelt_adapter.py` — GDELT 2.0 → `EventDraft` (root-code filter, field map)
- `app/extract/intensity.py` — `derive_intensity`
- `app/extract/classifier.py` — zero-shot NLI classifier (batched)
- `app/extract/filter.py` — `filter_by_zero_shot` semantic gate
- `app/extract/grouping.py` — link events to conflicts (proximity + time window)
- `app/extract/location.py` — `haversine_km` + optional coordinate repair (off by default)
- `app/extract/run.py` — pipeline entrypoint (fetch → adapt → filter → persist → group)

## Code style
Conventions: CAPABILITY-MAP.md. Adapter returns dataclasses; no DB/HTTP access inside it.

## Testing strategy
- Fixture GDELT records → assert armed-conflict filter, field mapping, intensity bounds.
- Unit-test `derive_intensity` across representative cases.
- Unit-test the zero-shot gate with a stub classifier.
- Interface test: an adapter conforms to `to_event_draft(raw) -> EventDraft | None`
  (currently only GDELT).

## Boundaries
- Always: keep adapter free of DB/HTTP deps; keep filtering/mapping pure.
- Ask first: changing `EventDraft` shape, adding a new adapter/model.
- Never: hardcode source-specific parsing outside the adapter.

## Success criteria
- A GDELT "battle" record yields an event with plausible country/lat/lon and intensity.
- A protest/diplomacy record is dropped.
- Swapping `BaseSourceAdapter` implementations requires changes only in `app/extract/`.

## Open questions
- None blocking. Settled: root-code allow-list is {18 assault, 19 fight, 20 mass violence};
  sub-codes are not distinguished yet.
