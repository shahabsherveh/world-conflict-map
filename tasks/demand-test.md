# Demand test — eight weekly briefings

Task 13 of `tasks/todo.md`. Eight issues, each generated with `scripts/briefing.py`
(README: "Weekly briefing"), each read by a human before it ships. Then a go/no-go memo
citing the counts.

**Kill criteria (decided before issue 1, so the decision is not made by mood):**
if after eight issues the median issue gains fewer than 5 engaged readers and almost no
direct replies, stop publishing — the skill is demonstrated by the case study instead of
sold as a subscription. Narrow the scope instead if growth is double-digit anyway, and
continue if there is repeat readership plus at least one request for more.

## Decisions to record before issue 1

- [x] Public identity: a pseudonym (the running name goes in the briefing masthead and
      the case-study footer; the map's operator is not identified under a real name).
- [x] Hosting posture: the briefings are the only public surface. This map's host is
      **not** named and must not be advertised as a service — the app is loopback-only
      and has no auth by design (AGENTS.md).
- [x] Distribution channel: a newsletter, using its built-in open/click analytics for
      the per-issue counts.
- [x] Past issues are archived publicly (each issue linked from the case study / a
      public archive page), not mailed-only.
- [x] "Engaged reader" = the full set, each counted separately every issue: opens,
      clicks, replies, and reshares. The go/no-go memo compares them, not a single
      blended number.

## Issue log

Fill one row per issue immediately after publication, not from memory a week later.
Counts are read from the channel's analytics on day 7, not estimated.

| # | Period | Published | Readers | Engaged | Replies | Reshares | Growth | Notes |
|---|--------|-----------|---------|---------|---------|----------|--------|-------|
| 1 |         |           |         |         |         |          |        |       |
| 2 |         |           |         |         |         |          |        |       |
| 3 |         |           |         |         |         |          |        |       |
| 4 |         |           |         |         |         |          |        |       |
| 5 |         |           |           |         |         |          |        |       |
| 6 |         |           |         |         |         |          |        |       |
| 7 |         |           |         |         |         |          |        |       |
| 8 |         |           |         |         |         |          |        |       |

## Go / no-go memo

Written after issue 8. Answer these with numbers, then state the decision.

- [ ] Median engaged readers per issue, and the trend from issue 1 to issue 8.
- [ ] Replies that asked for more, versus replies that pushed back.
- [ ] Issues where the briefing was visibly wrong (mis-titled theatre, stale window,
      a link that did not support its line) — count them; two or more means the
      pipeline is not subscriber-ready regardless of demand.
- [ ] Decision: continue / narrow scope / stop — and the evidence line for each clause.
