# Interview prep

The five questions an interviewer will most likely ask about Global Conflict Map, with
answers grounded in what the project actually does. Keep each answer to one or two
minutes spoken.

## 1. "Walk me through the architecture."

> It's a one-way pipeline: **storage → ingestion → extraction → API → UI**. Each layer
> only depends on the layer below it, so the extraction logic is pure — no DB or HTTP
> inside it — which makes it testable in isolation. Every day it fetches GDELT's raw
> event files, filters to candidate conflict events, runs a zero-shot model to drop false
> positives, groups events into conflicts by proximity, persists to SQLite via
> SQLAlchemy/Alembic, and serves them through FastAPI to a Leaflet map. The whole thing
> runs on cron or Docker with a health check that alerts if the map stops updating.

## 2. "How do you group thousands of events into conflicts?"

> Proximity, not keywords — and that's a lesson I learned the hard way. My first version
> matched on country *names*, and every event in Yemen collapsed into one giant conflict.
> Now I use a spatial anchor: a new event joins a conflict if it is within 100 km of the
> conflict's anchor, with a 14-day gap window since the last event. It also has a
> fallback for events with no coordinates, which compares place strings of the conflict's
> events — not the human-editable name. The key rule I enforce is that markers stay tied
> to individual events; I never reposition a marker from aggregated conflict data.

## 3. "How do you know an event is actually a conflict and not noise?"

> Two stages — deterministic, then semantic. GDELT codes events with CAMEO root codes,
> so I first keep only the conflict-related codes (18/19/20). But that still includes
> podcasts and plane crashes, so I run a zero-shot classifier — batched at about
> 0.03 seconds per event on CPU — to separate real conflict from noise. The important
> design choice is that the pipeline degrades gracefully: if the model is missing or
> fails, it warns and stores unfiltered events rather than crashing the whole run.

## 4. "What was the hardest problem you hit?"

Pick one of these two. Both are concrete and memorable.

### The silent failure (operations angle)

> The most expensive bug wasn't a crash — it was a cron job that exited 0 while the map
> stopped updating. Two data paths had diverged and the pipeline was writing to a
> different database than the web app was reading, so everything "succeeded" but the map
> froze. The fix was a `/api/pipeline-health` endpoint that reports the age of the last
> successful run, and a cron check that alerts when it goes stale. It taught me that
> success signals need to verify the *outcome*, not just the exit code.

### The grouping bug (algorithm angle)

> My first grouping rule matched events by country name, which merged every event in one
> country into a single conflict. It looked right at a glance and took a while to catch
> because the data *seemed* correct. It pushed me to design the proximity-based rule
> carefully and write a regression test named specifically for that failure mode.

## 5. "How would you scale this, or what would you change?"

> Three things. First, swap SQLite for Postgres + PostGIS — right now proximity grouping
> is done in Python, but a spatial index would let it scale to far more events. Second,
> replace the zero-shot model with a small fine-tuned classifier once I had enough
> labeled data — it is the dominant cost of a backfill. Third, I already retain
> `num_sources` from the raw feed but don't use it; I'd add source corroboration to
> weight events that multiple outlets report. The zero-shot filter was the right 80/20
> choice for a personal tool, but those are the levers for production.

## Delivery tips

1. **Say the numbers:** ~57k events/day, 0.03 s/event, 100 km, 14 days, ≤5 queries.
   Specific numbers make you sound like you measured, not guessed.
2. **Name the failure:** every strong answer above has a "I got this wrong and here's
   what I learned" beat. That is what separates a real project from a tutorial.
3. **Rehearse once out loud.** These answers are written to be spoken; reading them
   silently is not the same as saying them.
