# Replanning rules

Consolidated from CLAUDE.md section 18 and the Intelligence MVP
(`build-context-pack`, `diagnose-client`, `calculate-gap`,
`identify-priorities`, `replan-client`, `audit-plan`, `generate-tasks`
— see `skills/registry.json` for `implemented` status before ever
assuming one of these can be run; `publish-ekyte` remains `planned`).
Every SKILL.md in this pipeline points back here instead of restating
these rules — if a SKILL.md and this doc ever disagree, the SKILL.md
wins for that skill's own behavior; update this doc to match.

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

## Artifact chain and where things live

```
build-context-pack -> context-pack.json
diagnose-client     -> diagnosis.json     (input: context-pack.json)
calculate-gap        -> gaps.json          (input: context-pack.json, diagnosis.json)
identify-priorities  -> priorities.json    (input: context-pack.json, diagnosis.json, gaps.json)
replan-client         -> replanning.json    (input: all of the above)
audit-plan            -> audit.json         (input: replanning.json + everything upstream)
generate-tasks (ACTION, preview only) -> task-proposals.json (input: replanning.json + audit.json, only if audit_status != fail)
```

Transient path convention: `<workspace>/context/generated/<client_id>/replanning/{context-pack,diagnosis,gaps,priorities,replanning,audit,task-proposals}.json`, plus a human-readable `replanning-brief.md`. Gitignored, never canonical.

Every artifact after the first cites `artifact-ref`s (`schemas/artifact-ref.schema.json`: `artifact_id` + `content_sha256` of the upstream artifact's canonical JSON) to the artifacts it was actually computed from. `scripts/lib/artifact_hash.py` computes/verifies these. A downstream artifact computed against a stale/mismatched upstream (e.g. `gaps.json` referencing a `context-pack.json` hash that no longer matches the file on disk) is a broken chain — `scripts/run_replanning_checks.py` and `scripts/lib/replanning_lint.py` catch this, and the skill re-running with fresh inputs is the fix, never patching the hash.

## Evidence traceability backbone

`context-pack.evidence_index` is the one place every downstream `evidence_id` must resolve to. Each entry is tagged `kind: canonical` (resolvable in `clients/<client_id>/evidence.json`, strongest) or `kind: source_observation` (a normalized SOURCE output not yet promoted — usable for reasoning, weaker provenance, should be flagged when it's the sole support for something material). `diagnose-client` through `generate-tasks` never invent a new `evidence_id` — they only ever cite what's already in `evidence_index`.

## Diagnosis vs observation (`diagnose-client`)

Every `finding` declares a `finding_class`, and the classes are not interchangeable:

- **OBSERVED_ISSUE** — a problem directly evidenced (e.g. "spend MTD is below the planned monthly budget"). Requires `evidence_ids`.
- **OBSERVATION** — a neutral evidenced fact, not framed as a problem. Requires `evidence_ids`.
- **HYPOTHESIS** — a plausible, unproven explanation (e.g. "creative fatigue may be limiting results"). Never presented as fact; `hypothesis_when_applicable.would_be_confirmed_by` must say what would turn it into an observation.
- **MISSING_DATA** — absence of data blocks or limits a conclusion (e.g. "no sales evidence exists, so SMART progress can't be measured"). Absence is not itself a problem to "fix" operationally — it's a data-quality signal.
- **RISK** — a potential negative outcome, evidenced or structurally implied by the measurement/operational setup (e.g. "lead-to-sale attribution gap may limit how well the SMART can be read").

`impact` is always qualitative (`unknown`/`low`/`medium`/`high`) with a mandatory `impact_rationale` — never a numeric/composite health score. A single metric being below plan is never, by itself, sufficient to declare "media is bad" — see the Walmaq example in `docs/workflows/replan-client.md`: period, absence of a pacing model, presence/absence of sales evidence, recent decisions, and measurement limitations all matter before any conclusion is drawn.

## Gap invariant (`calculate-gap`)

`calculable: false` implies `current: null` and `delta: null` — **never** invent `current = 0` when the current value is simply unknown (e.g. sales progress with no sales evidence: `target: 15`, `current: null`, `calculable: false`, `delta: null`). A gap that *can* be computed arithmetically (e.g. media spend vs. plan) still only states the arithmetic fact (`interpretation`) — it never editorializes into a pacing/quality judgment; that belongs to `diagnose-client`, not here, and only when a pacing model actually exists.

## Prioritization (`identify-priorities`)

No arbitrary numeric score, ever. Every `priority.order` must be justifiable from `rationale_dimensions` (impact on the active SMART, factual urgency, dependency/blocking, evidence strength, reversibility, effort — only when actually known, never guessed to justify a rank — client request/decision, operational obligation). `excluded_candidates` records what was weighed and rejected, so the ranking is auditable, not just its winners.

## Replanning (`replan-client`)

Actions are **proposals**, never tasks yet — `generate-tasks` (ACTION) is the only thing that turns an approved action into a task-shaped operation, and only in `preview`. `deadline_requirement` is one of `explicit` / `derived_from_existing_commitment` / `needs_operator_decision` / `none` — a due date is never invented to fill the field; `needs_operator_decision` is a legitimate, expected value, not a failure.

**`replan-client` never mutates the Quarter plan.** SMART, target, baseline and `planned_budget` in `plan.json` stay exactly as `monitor-quarter`/the current plan define them (`operation/quarter-rules.md`). "Revisar o budget" is a recommendation inside an action's `statement`, never a write — a real plan change is a separate, explicit future workflow, not something this pipeline does implicitly.

## Audit (`audit-plan`)

`audit_status` is derived, not asserted independently: any `severity: high` issue makes it `fail`; only `low`/`medium` issues makes it `pass_with_warnings`; zero issues makes it `pass`. **No plan with `audit_status: fail` may feed `generate-tasks`.** Audit actively tries to break the plan — unsupported claims, missing evidence, contradictions, duplicate/unrelated-to-SMART actions, invented deadlines/responsibles, an action needing a dependency that doesn't exist, an unapproved external action, a hypothesis dressed as fact, a budget change disguised as execution, a task-shaped item that isn't actually operationally ready, stale/ambiguous evidence, a client decision the plan contradicts, and semantic elevation (a `hypothesis`/`risk`/`request` treated as settled fact anywhere in the chain).

## Task readiness (`generate-tasks`)

Classify every action proposal — not every action becomes a task:

- `task_candidate` — can plausibly become an internal task ("analisar campanha").
- `decision_required` — needs an operator/client decision first ("budget deveria aumentar" is a recommendation, not an execution task).
- `external_action` — requires touching a system/party outside this repo (CLAUDE.md section 20 approval boundary).
- `information_request` — waiting on the client to provide something ("cliente precisa definir estoque") — a dependency, not an internally-owned task.
- `monitoring_item` — something to watch, not to execute.
- `not_task` — doesn't warrant a task at all.

Readiness (`ready` / `needs_scheduling` / `needs_decision` / `dependency` / `external` / `not_task`) governs whether `manage_task_operation` is populated: only `ready` gets one, and only when `due_at` can be sustained by an explicit deadline, an existing commitment, an explicit operational rule, or an operator decision — never invented (`operation/task-rules.md`). Everything else carries `reason_if_blocked` instead, and stays a proposal an operator reviews before it ever reaches `manage-task-ledger`'s own `apply`.

`generate-tasks` never writes `tasks.json` itself — that would duplicate `manage-task-ledger`'s own responsibility (`operation/task-rules.md`). Its output is `mode: "preview"` always; the operator-approved `manage_task_operation`s are what `manage-task-ledger` later previews/applies for real.

## Unknown handling and decision boundaries (applies to the whole chain)

- Unknown current value -> `null`, never `0`. Unknown deadline -> `needs_operator_decision`/`needs_scheduling`, never a guessed date. Unknown responsible -> never populated (tasks have no `responsible` field at all — `operation/task-rules.md`).
- A `hypothesis`/`request`/`pending`/`risk` is never silently elevated to `fact`/`commitment`/`task`/certainty anywhere in this chain (CLAUDE.md section 5) — `audit-plan`'s `semantic_elevation` code exists specifically to catch this if it slips through.
- No skill in this chain writes canonical memory, Quarter plan/monitoring, evidence, or tasks.json. `build-context-pack` through `audit-plan` are read-only by construction (no `apply` mode at all). `generate-tasks` is ACTION but preview-only in this MVP.
- If a genuinely ambiguous business decision blocks progress (not a missing-data situation, an actual either/or a human must decide), the skill states `DECISION_REQUIRED` explicitly and continues with the rest of what it can produce — it never guesses.
