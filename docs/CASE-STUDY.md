# Case study: mapping armed conflict from the news

A personal web app that shows where armed conflicts are happening, lets you scrub time
to see how they started and escalated, and refreshes itself daily from public news
metadata. Built and operated by one person, with no paid data feed, no GPU, and no
frontend build step.

This is a walkthrough of the data pipeline for a reader who does not write software:
what goes in, what the machine does, what comes out, and where the honest limits are.
Numbers are measured from the project's own database unless they say otherwise.

## The problem

Thousands of news reports a day mention a battle, an airstrike or a village shelling.
Each arrives as a separate story, usually without telling you that it belongs to a
larger conflict you have been following for months. The result is a picture that is
simultaneously overwhelming and fragmented: plenty of incidents, no shape.

The question the app answers is deliberately narrow: **which armed conflicts are
active, where, and how has that changed?** Not why they started, not who is right, and
not everything that is happening — armed conflict only.

## Constraints that shaped every decision

- One person, part-time, and no recurring bill. A paid event database or a hosted NLP
  service would do the job better and cost more than the whole project is worth.
- A daily refresh, not real time. A map that updates once a day is enough to watch a
  conflict evolve and cheap enough to run on one machine.
- Personal first, but not a dead end. Where a decision was cheap either way, it was made
  in the shape a product would need (a replaceable extraction step, an API the UI does
  not bypass, audit trails on manual edits).
- No accounts, and no exposure. It is a personal tool: it binds to the machine's
  loopback interface and is deliberately not reachable from a network.

## The pipeline, stage by stage

### 1. Fetch: start with the raw material, not with a conclusion

The source is [GDELT](https://www.gdeltproject.org/), a public project that publishes,
every 15 minutes, a file of news events coded into a structured form: what kind of
event it was, which actors, where it was reported, which article it came from. No API
key, no licence fee.

Two decisions matter more than they look:

- **Store the raw rows before interpreting them.** All 61 columns of the source format
  are kept, unparsed, in a `raw_event` table, and only then is anything filtered. A week
  of files is about 718,000 rows. When the interpretation turns out to be wrong — and it
  did, repeatedly — the facts are still there to redo it without re-downloading.
- **Make a download day restartable.** Downloads retry transport errors and rate limits
  with exponential backoff; a single missing 15-minute file is skipped and named in the
  run record, while a day where nothing arrived is a failure, not a silent zero. Each
  run stores what it fetched, what it kept, how long it took, and any degraded reason,
  so "the map stopped updating" is a query (`GET /api/pipeline-health`) rather than a
  log hunt.

### 2. Filter: two gates, because one was not accurate enough

GDELT codes every kind of political event, so most of a day's rows are not armed
conflict. Filtering happens in two passes:

1. **A cheap structural gate.** Only event types that describe material conflict pass:
   battles, airstrikes, armed clashes, artillery. This removes the majority of rows at
   no cost.
2. **A semantic gate.** The structural gate is fast but blunt: it happily passes a story
   about a *football* clash or a court battle if the coding is loose. A small
   open-source language model reads the headline-like text (derived from the article's
   web address) and scores whether it is about armed conflict. On a hand-labelled set of
   25 articles this raised precision from 32% to 80% at 100% recall. The model runs on
   an ordinary CPU at roughly 0.03 seconds per event, which is why a full day takes
   about half an hour rather than minutes.
3. **Failure is explicit.** If the model is not available, the pipeline still runs and
   says so in its run record (`degraded_reason`) instead of quietly publishing
   unfiltered noise or silently storing nothing.

Each surviving event keeps its article link, date, location, intensity (a 1–5 score
derived from event type, not from casualty counts — see limits below) and a
corroboration count: how many distinct outlets and articles reported it. The counts are
shown as counts, never as a verified/not-verified badge, because the underlying score
is ordinal and its scale has not been validated.

### 3. Group: incidents are points, conflicts are theatres

This is the part that looks trivial and is not. Each event is a dot with a date. A
"conflict" is a grouping of dots that belong together — the same fight continuing, not
two unrelated fights that happen to share a country.

The first attempt matched shared words (including the country name) and was a failure
worth keeping in the repository's notes: every event tagged "Yemen" merged into a single
conflict spanning the country, which then never ended because every new event extended
it. The rule that replaced it is geographic:

- same country,
- within 100 km of the conflict's anchor point (its first located event),
- and no more than 14 days since the conflict's last event.

The time window is a **gap since the last event**, not a total duration: a theatre that
sees an event every ten days stays one conflict for a year, while two events a year
apart start two conflicts instead of resurrecting a dormant one.

Markers are always drawn per event, never from the grouping. That separation is a
product decision as much as a technical one: grouping can only change how conflicts are
*presented*, so a grouping mistake never silently moves a dot on the map. Events the
source could not locate (roughly 500 in any 30-day window) are listed separately, with a
"set location" action that uses a human's judgement rather than guessing. Re-geocoding
them automatically was tried, made correct records worse, and was turned off for good.

### 4. Serve: a map, an API, and a way to correct it

A small web service answers three kinds of question — which conflicts were active in a
date range, what happened in this one, and where did this event come from — and the map
is a plain web page drawn on top of those answers, with no framework and no build step.
A time scrub re-queries the API instead of reloading the page. Clustering keeps a
30-day view (13,000 events) responsive.

Because the machine is never right about everything, the fields that matter can be
corrected by hand — place, coordinates, date, type, intensity, source link, and a
conflict's name and span — and every correction is recorded with its old and new value.
A corrected record is marked as manual, and automated grouping never claims it back. The
distinction between
"the machine inferred this" and "a person said so" is visible in the interface.

## What the numbers look like

Measured on one week of source files and the resulting database:

| Measure | Value |
|---|---|
| Raw source rows in one week | ~718,000 |
| Rows retained as armed conflict | 13,713 |
| Conflicts they group into | ~1,500 |
| Filtering cost per day of data | ~30 minutes, CPU only |
| Database size for that week | ~1.4 GB |
| Time to render a 7-day written briefing | 2.6 seconds |

Those 13,713 events are about 1.9% of what the source publishes. That ratio is the
honest headline of the filtering work: the feed is mostly not about armed conflict.

## The limits, stated plainly

A reader should be able to tell what this data cannot do:

- **No casualty figures.** The free feed has no usable casualty fields, so the app
  shows intensity derived from event type, never a death toll. A blank is a blank.
- **Locations are only as precise as the source.** GDELT sometimes falls back to a
  country's centre point when it cannot name a town, which can put a dot in the middle
  of a country rather than where the fighting was. The app keeps the location it was
  given (and the place name beside it) rather than inventing one, lets a human move it,
  and lists events with no location at all separately instead of guessing.
- **One report is not a fact.** Corroboration counts are exposed so a single-outlet
  event looks different from one carried by twelve, but counts are not verification.
  Written output links every claim to its source, and a human reads it before it ships.
- **Grouping can name a theatre oddly.** A cluster is named after a place inside it, so
  a country-wide cluster can read as a city name. That is a naming decision left open
  on purpose rather than papered over.
- **The map is not a live feed.** It updates daily. An event from this morning can be
  missing until tomorrow's run.

## What this demonstrates

Not that a small language model can classify news — many can, and better ones exist.
What this project demonstrates is the discipline around that model:

- every failure mode found in review ended as a regression test, not a memory;
- performance limits are asserted (the conflict list is one bounded query, checked by a
  query-count test) rather than assumed;
- data-quality rules — do not re-geocode verified points, never merge conflicts by
  keyword, never rewrite a human's correction — are written down with the reason they
  exist;
- honesty is structural: missing data is null rather than zero, unknown corroboration
  says "unknown", and the pipeline records when it ran degraded.

The extraction step sits behind a single interface, so a stronger model (or a large
language model, later) can replace it without touching storage, the API or the map. That
is the swap the architecture was built to allow, and the reason the current model choice
is not a dead end.

## Where the detail lives

- Pipeline stages and their boundaries: `docs/CAPABILITY-MAP.md` and
  `docs/SPEC-*.md`.
- The failures that shaped the code, each with the symptom to recognise:
  `AGENTS.md` (Gotchas).
- The written briefing this pipeline produces, and the demand test it feeds:
  `README.md` ("Weekly briefing") and `tasks/demand-test.md`.
