# README sections

Copy-and-paste sections for `README.md`. They are written to slot in under the
`# Global Conflict Map` heading. The existing README is already good; these front-load
the pitch.

## TL;DR

Paste directly under the title, above the existing "What it does" section:

```markdown
**Global Conflict Map** turns the GDELT 2.0 news stream — ~57k geolocated events a day —
into a browsable, self-updating map of armed conflicts. A zero-shot semantic filter
separates real conflict events from noise, a proximity-based grouping algorithm links
them into conflicts, and a Leaflet map lets you scrub through time, zoom into clusters,
and edit the results by hand. It runs as a daily cron/containerized pipeline with a
freshness health check, so the map stays current — and tells you when it isn't.
```

## How it works

Paste after the TL;DR, before (or instead of) the existing "What it does" list:

```markdown
## How it works

Every day, the pipeline follows the same four steps:

1. **Fetch** — download the latest GDELT 2.0 raw event files (free, no API key), each
   already coded as a geolocated event with an actor type and an intensity score.
2. **Filter** — keep only candidate conflict events (CAMEO root codes 18/19/20), then
   run a zero-shot semantic classifier to drop false positives like podcasts and plane
   crashes.
3. **Group** — link events into *conflicts* by geographic proximity (not keywords), so
   scattered news reports become one browsable conflict with a timeline.
4. **Serve** — store the results in SQLite and expose them through a FastAPI backend to
   a Leaflet map with time-scrubbing, clustering, and manual editing.

The whole thing runs on a schedule (cron or Docker), and a freshness check alerts you if
the map has stopped updating — because a pipeline that silently fails is worse than one
that visibly fails.
```

> The ASCII flow diagram was dropped here because it wraps awkwardly on mobile. If you
> want it, add this inside the "How it works" section, after the numbered list:

```text
GDELT 2.0 ──▶ fetch ──▶ filter (rules + zero-shot) ──▶ group by proximity ──▶ SQLite ──▶ FastAPI ──▶ Leaflet map
                                            ▲                                                        │
                                            └──────────────── daily cron + health check ──────────────┘
```

## Why I built this

A draft plus guidance, because the strongest version of this section is personal. Paste
the draft, then replace the motivation with your own answer to one or two of these:

- **What started it?** A news event you wanted to follow? Frustration with an existing
  tool? Curiosity about GDELT?
- **What was the hard part you cared about?** For most people it is the false-positive
  filtering or the grouping logic — say which one you obsessed over.
- **What did you learn that surprised you?** (GDELT codes Yemen as `YM`; country
  centroids masquerade as precise cities; re-geocoding corrupts good data.)

```markdown
## Why I built this

I wanted to understand armed conflict as *data* — not as headlines, but as a stream of
geolocated events that could be filtered, grouped, and browsed over time. Existing tools
either show static maps or rely on curated, one-off reports; none let you watch the
underlying news stream turn into a map that updates itself.

So I built the pipeline end to end: ingest the raw feed, filter the signal from the
noise, group scattered reports into coherent conflicts, and make the result editable
where automation gets it wrong. Along the way it became an exercise in the unglamorous
parts of real software — dependency pinning, type checking, migration drift, and the
failure mode where a cron job keeps "succeeding" while the map quietly stops updating.

It's a personal tool first, but it's architected as if it might one day be a product.
```

Example of a personalized rewrite:

> I started this after following the war in Ukraine and realizing every map I found was
> either a static snapshot or a manually curated list. I wanted a map that *grew itself*
> from the raw news stream — and I wanted to find out whether that was actually possible
> with free, public data.

## Why include it

The "Why I built this" section does two jobs: it tells a recruiter you can explain *why*
something exists (product thinking), and it gives an interviewer a natural entry point
("so why did you pick GDELT?"). Without it, reviewers read the project as a technical
exercise; with it, they read it as a person solving a real problem.
