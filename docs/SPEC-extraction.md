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
5. `confidence` is an **ordinal** corroboration score, 0.0–1.0, blending `NumArticles`
   (coverage volume) with `NumSources` (a distinct-outlet bonus; ten articles from one outlet
   is usually one wire story reprinted). Denominators are observed percentiles from the
   armed-conflict subset (articles p50=4/p90=10/p99=15; sources = 1 for 94.9% of events), so a
   single-outlet event cannot exceed 0.55. The 0.4/0.6 weight is a **convention, not a fitted
   parameter**: ranking is insensitive to it (Spearman ≥0.99 for any weight in 0.2–0.8). The
   absolute scale is unvalidated — do not threshold it as though 0.7 meant something; gate
   decisions on the counts (`sources >= 2 and articles >= 3`) instead. Zero or negative counts
   contribute nothing, so an absent or unparsable count gives `0.0` rather than a second
   default. It is a coverage signal, not a truth claim. Rows persisted before this change keep
   their articles-only score, because processing only touches `processed_at IS NULL` rows, so
   the column is mixed-scale until something explicitly re-derives it. The API exposes the
   raw counts for the badge by reading `raw_event.payload` (one batched query per page), not
   by reversing the score; counts are null once retention has pruned the raw row.
6. Zero-shot gate: `filter_by_zero_shot` drops drafts whose source URL slug doesn't
   classify as armed conflict (NLI model, threshold from config). Drafts without a
   source URL are kept — the adapter's root-code filter has already run. If the model
   is unavailable the pipeline skips this gate rather than failing, and records
   `ingestion_run.degraded_reason` so the skip is visible in the audit trail instead of
   only on stderr. The run stays `status='success'`: unfiltered events are still real
   events, they just keep GDELT's country-centroid coordinates.
7. A failed day stores `ingestion_run.error` (`ExcType: message`, truncated) before the
   exception propagates, so "why did yesterday fail?" is a query, not a lost log line.
   Steps outside the per-day loop — the stranded-row retry, grouping, pruning — get
   their own `ingestion_run` row (`source_day` null, `phase` set) created as `running`
   and settled in place, so a healthy step keeps its duration and a crash keeps the
   reason. The day rows have already committed `success` by then, so a failure there
   would otherwise leave the run looking clean.
8. `read_day_from_dir` (the `--source-dir` path) skips unreadable cached exports. Missing
   15-minute slots are normal and unreported; corrupt files are counted onto the day's
   `degraded_reason`, because a silently short day looks identical to a full one.

## Commands
- `pytest tests/test_extraction.py`

## Project structure (module)
- `app/extract/base.py` — `BaseSourceAdapter` + `EventDraft`
- `app/extract/gdelt_adapter.py` — GDELT 2.0 → `EventDraft` (root-code filter, field map)
- `app/extract/intensity.py` — `derive_intensity`
- `app/extract/classifier.py` — zero-shot NLI classifier (batched)
- `app/extract/filter.py` — `filter_by_zero_shot` semantic gate
- `app/extract/grouping.py` — link events to conflicts (100 km anchor + gap window)
- `app/extract/location.py` — `haversine_km` + optional coordinate repair (off by default)
- `app/extract/run.py` — pipeline entrypoint (fetch → adapt → filter → persist → group)

## Code style
Conventions: CAPABILITY-MAP.md. Adapter returns dataclasses; no DB/HTTP access inside it.

## Grouping rule

An unlinked event joins a conflict when the country matches, the event is within
`radius_km` (100 km) of the conflict's anchor — the coordinates of its earliest
geolocated event — and its date falls between the conflict's `start_date` and
`gap_days` (14) after the conflict's most recent event. Otherwise a new conflict is
created. An explicit `end_date` (a human ending it) wins over the gap.

The window exists because nothing ever set `end_date`: the span only widened, so one
stale event bridged onto the current window and resurrected a dormant theatre (365 days
for 63 of 1,443 conflicts on the first real DB). It is a *gap*, not a duration, so an
event every 10 days chains indefinitely.

Events with no coordinates fall back to comparing the first component of the place
string (GDELT's `City, Admin1, Country`). The comparison is against the cities named by
the conflict's *events*, not against `Conflict.name`: the name is editable, and a
renamed conflict became unmatchable — with no anchor there is no distance to measure, so
the next event opened a second conflict for the same theatre. A conflict with no stored
place strings (seeded or manually created) still compares its name, the only evidence it
has. Place evidence is updated as events link, so the fallback also sees a town
introduced earlier in the same run (the session runs with `autoflush` off).

The fallback matches nothing for a placeless event (`city_of(None)` is `None`), so the
unlocated tail stays one conflict per event rather than collapsing into one. It also
splits on a *different* city: without an anchor nothing can measure the distance, so a
name is evidence of the same theatre only when it is the same name.

Candidate selection is ordered by `(start_date, id)`. Without an `ORDER BY` the winner
was whatever rowid order returned, so identical data grouped differently after a
re-import.

Known limitation: a conflict is *named* after whichever event arrived first, and GDELT
dates have day granularity. In 137 of 1,517 conflicts more than one place string shares
the earliest date, so the name — which is what the briefing and UI show — is decided by
import order. Dense theatres are legitimately one cluster (Hebron is within 100 km of
Gaza, Jerusalem and Tel Aviv), which is why a 7-day briefing can be titled
`## Hebron, Israel (general), Israel`.

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
