# Statement of Intent — Global Conflict Map

## Outcome
A personal web app: an interactive world map of armed conflicts, browsable across time,
that updates itself daily by reading news.

## User
One person (personal use), for now — but architected so it could become a product
without a rewrite.

## Why now
Global conflict feels like it is escalating, and headlines give a fragmented,
sensationalized view. The user wants an honest, at-a-glance picture of where things
are actually bad and how that has changed over time.

## Success
The user opens the app and sees armed conflicts (past and present) sized/colored by
intensity, scrubs the time frame to see how conflicts started, escalated, or ended,
clicks a conflict for the underlying news, and manually corrects anything the machine
got wrong.

## Constraint
- Free/open-source NLP extraction to start (zero recurring cost).
- LLMs are a later, swappable upgrade — the extraction step must stay behind a clean interface.
- Daily refresh cadence.
- Personal-first, product-ready architecture (no single-user dead-ends where cheap to avoid).

## Out of scope
- Non-armed unrest (protests, coups, disasters).
- Hourly/real-time updates.
- Multi-user accounts.
- Public accuracy/reliability guarantees.

## Decision log (from interview)
- Data source: live news ingestion (automatic).
- Scope: armed conflicts only.
- Ingestion: fully automatic, with manual edit capability.
- Time: browsable across time frames, not just "now."
- Extraction: free/open-source NLP first; LLMs later.
- Cadence: daily.
