---
name: prepare-ropre
description: Assemble a read-only, evidence-traceable weekly ROPRE draft for one resolved Quarter without changing canonical client memory.
---

# Prepare ROPRE

## 1. Identity and boundary

- **Class:** INTELLIGENCE
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/prepare-ropre/output.schema.json`
- **Transient artifact (optional):** `context/generated/<client_id>/ropre-draft.json`

This skill organizes a weekly ROPRE draft using only the project meanings of
Resultados, Objetivos, Premissas, Riscos, Próximos Passos and Visão de Longo
Prazo. It does not expand or invent a meaning for the acronym.

It never writes `current.json`, check-in history, plans, monitoring, tasks,
flags or evidence; does not call eKyte or any external system; and does not
create, complete, cancel or schedule a task. A future ACTION owns persistence
and closure of a check-in.

## 2. Inputs, sources and Quarter

Require `client_id`; accept optional `quarter_id`, a valid read-quarter output,
and an explicitly supplied `scheduled_for` only when a valid draft is desired.
Use the validated read-quarter output as tactical authority for the plan, SMART,
monitoring, media and flag summaries, coverage, warnings and missing data.
Never recalculate its planned/actual/remaining/attainment/variance values or
month-channel ambiguities.

If it must resolve directly, use exactly read-quarter's order: explicit ID;
exactly one valid active plan; otherwise current `YYYY-QN` from the real system
clock only if it exists; multiple active or missing current Quarter is an error.
The selected plan must validate and match client and Quarter identity. Never
create a Quarter.

Read only the selected client's `tasks.json`, `evidence.json`, `strategy.md`,
and `quarters/<quarter_id>/check-ins/current.json` and `history/` entries needed
for continuity. Validate used tasks, plans, monitoring and check-ins against
their canonical schemas. Check `tasks.json.client_id == client_id` and every
`task.client_id == client_id`; a violation is `client_isolation_violation` and
blocks the draft. Validate referenced evidence IDs against the same client's
ledger whenever it exists; an orphan is `unresolved_evidence`, never invented.

## 3. Check-in selection and continuity

From valid check-ins in the resolved Quarter, select the most recent
`status: completed` by its valid `completed_at` timestamp. Do not use filename
order. Before selection, deduplicate logical check-ins: `current.json` and a
history entry with the same check_in_id, client_id, quarter_id and semantically
identical canonical JSON represent one check-in. Use sorted-key compact UTF-8
JSON comparison (not file bytes or whitespace) and prefer history as the
longitudinal source; current completed is its canonical mirror. `previous_check_in.temporal_reference` is exactly the selected
`completed_at`. Equal greatest timestamps are `previous_check_in_ambiguity`:
return `conflict`, `blocked`, and `ropre_draft: null`. With none, set
`continuity_summary.first_known_check_in: true`; this is not an error and never
means the client or project is new.

The deduplication exception is narrow. Equal check_in_id with divergent semantic
content is `check_in_id_collision`, conflict and blocked. Different IDs with
the same greatest completed_at remain `previous_check_in_ambiguity`; never
collapse distinct meetings merely by timestamp.

Every current or historical check-in considered must have `client_id` equal to
the input and `quarter_id` equal to the resolved Quarter. Any mismatch is
`check_in_identity_conflict`: return `conflict`, `blocked`, and no draft. In
particular, a Q3 check-in is never Q4 weekly continuity.

If a valid `current.json` has `draft` or `ready`, set
`previous_check_in.existing_open_check_in: true`, add
`existing_open_check_in` to warnings or missing data, return `partial` /
`partial`, and set `ropre_draft: null`. It may provide alert context only: do
not merge, revise, overwrite, or emit a second check-in draft. It is not the
previous completed check-in.

Extract prior results, objective reference, premises, risks, next steps and
long-term view only from the selected completed object. Cross a prior next step
with tasks only through its explicit `task_id`, never text similarity: pending,
pending+overdue, completed and cancelled become respectively
`promised_pending`, `promised_overdue`, `promised_completed` and
`promised_cancelled`. A missing ID is `unresolved_task_reference`; duplicate
matching IDs are `ambiguous_task_reference` conflict. No `task_id` is simply an
unlinked prior next step.

Classify every previous next step in exactly one bucket:
`promised_completed`, `promised_pending`, `promised_overdue`,
`promised_cancelled`, `unresolved_task_references`,
`ambiguous_task_references`, or `unlinked_next_steps`. A pending overdue task
belongs only to `promised_overdue`, never also pending. The total of these seven
lists must equal `previous_next_steps_total`.

## 4. Draft construction

**Results** contain only canonically observed/sustained SMART progress, media
values already derived by read-quarter, relevant resolved flags after the
previous completed timestamp, and relevant completed-task execution progress.
Preserve evidence IDs. A completed task is execution progress, not automatic
commercial performance or causal business result. Do not promote hypotheses,
ideas, pending items or risks to factual results, and do not resolve source
conflicts.

**Objectives** references exactly `quarter_plan.smart_objective`, retaining the
current Quarter statement, metric, baseline (including `null`), target and
deadline. Include observed current value/progress/status only when supplied by
monitoring. Never alter the target or use a prior Quarter's SMART. Expose an
objective gap only when current and target are present, units match and the
mathematical direction is unambiguous; otherwise it is `null`.

**Premises** are only open flags of type `premise`; **Risks** are only open flags
of type `risk`. Retain their IDs, statements, timestamps and evidence in the
summary; do not convert other flag types, overdue tasks, media variance,
objective progress or missing data into risks. Resolved flags after the prior
check-in are changes, not current risks. A source-supported possible new item
may be a transient `candidate_observation`; it never mutates flags.

**Next steps** come from unresolved prior next steps, relevant pending tasks,
explicit commitments, or directly recorded plan/monitoring needs. Existing
tasks retain their task_id and Quarter of origin. Legitimate steps without a
task keep `task_id: null` and may appear in transient `task_candidates` with
statement, suggested Quarter, evidence IDs, reason and source—never a task ID,
status, owner or invented due date.

For every non-null draft, `task_ids` is exactly the de-duplicated set of its
non-null `next_steps[].task_id`; each must resolve uniquely in the client task
ledger. Do not include candidates or unresolved IDs. Top-level `evidence_ids`
is the de-duplicated closure of every evidence ID used in draft results,
objectives, next steps, and displayed premise/risk flags. Every ID must resolve
to the same client; no item may cite evidence omitted from that closure.

**Long-term view** comes preferentially from `strategy.md`; it remains distinct
from the tactical SMART and weekly execution. If strategy is unavailable or
insufficient, use the selected previous completed check-in's explicit
`long_term_view` unchanged when available, while reporting strategy missing or
insufficient and capping readiness at `partial`. Without either source, record
`long_term_view_missing` and emit no draft. Never derive strategy from weekly
metrics.

`scheduled_for` must be explicitly supported input; absent input is
`scheduled_for_missing`, `partial` / `partial`, and no draft. Never use
`generated_at` as a meeting time. A valid draft uses real-system UTC
`generated_at`, `status: draft`, `completed_at: null`, and a deterministic ID:
canonicalize `{client_id, quarter_id, scheduled_for}` as sorted-key compact
UTF-8 JSON; take the first 12 lowercase hex characters of its SHA-256; then
form `ropre-<client_id>-<quarter_id lowercase>-<real-system YYYYMMDD>-<digest>`.
Before emitting it, compare all known current/history IDs: an ID assigned to a
different object or meeting is `check_in_id_collision`, `conflict` / `blocked`,
and no draft. Never use a UUID, random value, raw uppercase Quarter in the ID,
or a prior ID.

## 5. Tasks, media and readiness

Tasks are longitudinal: include relevant tasks regardless of origin Quarter;
derive `overdue` only when pending and `due_at` precedes the real system date.
Derive `due_today` with that same date. Never persist either, relabel a task's
Quarter, or turn overdue into a risk. Missing tasks is non-blocking but is
recorded; duplicate task IDs are material ambiguity.

Use read-quarter media summaries verbatim. Missing monitoring or actuals remain
missing, never zero; partial coverage stays explicit. Do not classify budget or
pacing as good, bad, on track or at risk.

`readiness` is `ready` for enough validated context to present an honest draft,
`partial` for a useful draft/context with declared gaps, and `blocked` for
unresolved Quarter, invalid plan/schema, client isolation violation, or an
identity/continuity ambiguity that prevents reliable synthesis. `success` means
`ready` plus a non-null draft; `partial` means `partial` readiness and permits a
null or valid draft; `error` and `conflict` require `blocked` and a null draft.
If a conflict does not block presentation, surface it as warning/partial
instead of status conflict.

## 6. Quality and conformance

All execution timestamps use the real UTC RFC3339 system clock; source dates
remain source dates. Before returning, validate the output with Draft 2020-12
and external canonical references via `referencing.Registry`, validate any
non-null ROPRE draft in full, preserve client isolation and provenance, and
perform no canonical write.

Test in memory, without synthetic client persistence, cases A-BD: complete and
first-known context; all prior-step task states and unlinked/missing/duplicate
references; cross-Quarter tasks and SMART isolation; absent monitoring/actuals;
baseline, premise, risk and resolved-flag handling; no automatic risk creation;
strategy/evidence/current-draft/previous-check-in ambiguity/isolation/Quarter
and plan failures; canonical draft validity and draft state; candidates without
invented due dates; results versus execution; read-quarter media authority;
current SMART; candidate non-mutation; no canonical writes; and schema refs;
open-current suppression; check-in identity and temporal selection; deterministic
lowercase ID and collision; missing schedule; long-term fallback; read-quarter
media rejection; task/evidence closure; exclusive continuity categories; status
coherence; and monitoring-status enumeration.
