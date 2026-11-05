# Spec: extraction — event-source adapter (swappable)

## Objective
Turn raw GDELT events into `conflict_event` candidates: keep only armed-conflict event
types, map fields into our schema, and derive intensity (1–5). Expose a swappable source
adapter so a T5 model or an LLM can replace/augment GDELT later without touching other modules.

## Tech stack
Pure Python (no ML deps). (Conventions: CAPABILITY-MAP.md)

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
3. `fatalities` from GDELT `NumKilled`/`NumWounded` where present, else null.
4. `derive_intensity(event_type, fatalities, goldstein) -> 1..5` — a small pure, unit-tested
   function (severity by event type + fatality/tone adjustment, clamped to 1–5).
5. `confidence` from `NumArticles`/`NumSources` (more coverage → higher), else default.

## Commands
- `pytest tests/test_extraction.py`

## Project structure (module)
- `app/extract/base.py`, `app/extract/gdelt_adapter.py`, `app/extract/intensity.py`

## Code style
Conventions: CAPABILITY-MAP.md. Adapter returns dataclasses; no DB/HTTP access inside it.

## Testing strategy
- Fixture GDELT records → assert armed-conflict filter, field mapping, intensity bounds.
- Unit-test `derive_intensity` across representative cases.
- Interface test: both adapters conform to `to_event_draft(raw) -> EventDraft | None`.

## Boundaries
- Always: keep adapter free of DB/HTTP deps; keep filtering/mapping pure.
- Ask first: changing `EventDraft` shape, adding a new adapter/model.
- Never: hardcode source-specific parsing outside the adapter.

## Success criteria
- A GDELT "battle" record yields an event with plausible country/lat/lon and intensity.
- A protest/diplomacy record is dropped.
- Swapping `BaseSourceAdapter` implementations requires changes only in `app/extract/`.

## Open questions
- Exact CAMEO code allow-list to confirm (18/19/20 root codes, plus sub-codes as we tune).
