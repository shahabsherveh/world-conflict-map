# Capability Map: Global Conflict Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `storage` | Data model + persistence: conflict events, conflicts, manual edits, ingestion runs, time-series state | — |
| `ingestion` | Daily fetch of structured conflict events from GDELT → normalized, deduped raw rows persisted before extraction | `storage` |
| `extraction` | Event-source adapter: filter to armed conflicts, map fields, derive intensity. **Swappable source boundary (GDELT now, T5/LLM later).** | `ingestion`, `storage` |
| `api` | HTTP API: query conflicts/events by time frame; manual edit/create | `storage` |
| `ui` | Interactive map, time scrub, click-for-news, manual edit | `api` |

Build order: `storage` → `ingestion` → `extraction` → `api` → `ui`

Cross-cutting conventions, commands, and gotchas live in [`AGENTS.md`](../AGENTS.md);
each module's contract is in its `SPEC-<module>.md`.

Diagrams of these boundaries, the daily pipeline, and the schema live in
[`diagrams/`](diagrams/README.md) as Mermaid blocks. A non-specialist walkthrough of the
same pipeline (what goes in, what each stage decides, what the numbers and limits are)
is [`CASE-STUDY.md`](CASE-STUDY.md).
