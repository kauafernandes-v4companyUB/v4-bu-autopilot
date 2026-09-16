# Replanning rules (forward-looking — not implemented yet)

Consolidated from CLAUDE.md section 18. Unlike the other four files in
`operation/`, this one describes a flow whose INTELLIGENCE/ACTION skills
are **not implemented yet** — `diagnose-client`, `calculate-gap`,
`identify-priorities`, `replan-client`, `audit-plan`, `generate-tasks`
are all `status: planned` in `skills/registry.json`. This doc exists so
the *policy* is written down once, before those skills land, instead of
being re-derived from scratch (or, worse, assumed to already exist —
see `skills/registry.json`'s `implemented` flag before ever claiming one
of these can be run).

## Replanning is not "make a task list"

Before generating a single task, the conceptual sequence (CLAUDE.md
section 18) is:

1. identify the client;
2. load its canonical memory;
3. identify which sources are needed;
4. obtain current context;
5. check freshness of sources;
6. surface current goals;
7. analyze results;
8. identify recent decisions;
9. identify pending items;
10. identify gaps;
11. diagnose bottlenecks;
12. establish priorities;
13. produce the replanning;
14. audit the plan;
15. **only then** generate tasks.

Every generated task must trace back to an operational reason — not
"because the quarter needs more tasks."

## Category boundaries this flow must respect (CLAUDE.md section 2)

- SOURCE skills (`read-*`) observe; they never decide.
- INTELLIGENCE skills (`diagnose-client`, `calculate-gap`,
  `identify-priorities`, `replan-client`, `audit-plan`) reason; they
  never write canonical state or call external systems.
- ACTION skills (`generate-tasks`, `publish-ekyte`, and the
  already-implemented `promote-client-memory` / `monitor-quarter` /
  `manage-task-ledger` / `close-ropre`) materialize already-validated
  decisions; they never silently reinterpret the strategy/diagnosis they
  were handed.

## Context Pack precedes intelligence work (CLAUDE.md section 17)

Before any non-trivial INTELLIGENCE workflow, assemble a Context Pack:
client, timestamp, available sources, missing sources, freshness per
source, known conflicts, and an overall confidence read. The point is to
be able to answer "do I have enough context to do this work?" — a
missing source informs impact/confidence, it does not necessarily block
everything.

## `operation/task-rules.md` governs the last step

Once `generate-tasks` exists, every task it creates still goes through
the same evidence-backed, no-invented-fields, Quarter-is-origin-only
rules in `operation/task-rules.md` — this file does not relax those.

## Until these skills exist

Do not simulate `diagnose-client`/`calculate-gap`/`identify-priorities`/
`replan-client`/`audit-plan`/`generate-tasks` by hand inside another
skill's execution, and do not claim a replanning was produced by "the
system" when it was actually produced ad hoc. If a real replanning is
needed before these skills are implemented, that work is a manual,
clearly-labeled exception — not a precedent for skipping this sequence
once the skills exist.
