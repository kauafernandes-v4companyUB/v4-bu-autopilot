---
name: manage-task-ledger
description: Safely preview and atomically apply explicit, evidence-backed changes to one client's longitudinal task ledger.
---

# Manage Task Ledger

## 1. Identity

- Class: ACTION
- Canonical Side Effects: TASK_LEDGER
- Version: 1.0.0
- Canonical target: clients/<client_id>/tasks.json
- Output contract: skills/manage-task-ledger/output.schema.json

## 2. Purpose and boundaries

Maintain only the local, longitudinal task ledger of one client. It records when
an explicitly requested task was raised, its due date and status, completion
date, Quarter of origin, provenance and optional ekyte_url. It does not replace
or call eKyte.

It never creates a task from a pending item, flag, message or ROPRE next step
without an explicit operation. It never adds owner, priority, sprint, story
points, complexity or any field outside task-ledger.schema.json. It never moves
tasks to a Quarter directory, rewrites the Quarter of origin because time has
passed, changes plans, changes evidence.json, diagnoses, creates flags or calls
an external system.

## 3. Inputs, sources and preconditions

Required input is client_id. mode is preview by default or explicit apply. The
only supported operations are create_task, complete_task, cancel_task,
reschedule_task and link_ekyte. Every operation has a unique operation_id in
its batch; duplicate IDs are error/conflict and cause zero mutations.

Read only the selected client's tasks.json, evidence.json, and only the plan.json
files needed to validate create_task origin quarters. Validate tasks against
schemas/task-ledger.schema.json and origin plans against
schemas/quarter-plan.schema.json. evidence.json is read only: every material
provided evidence ID must resolve there and belong to the selected client.
Otherwise return error/missing_data with unresolved_evidence and make no write.

Before planning, enforce client isolation: `tasks.json.client_id` must equal the
input `client_id`, and every canonical task's `client_id` must equal both of
them. A divergence is `error` or `conflict` with
`client_isolation_violation`, and causes zero writes. Never accept a task
`client_id` from `create_task`: populate it exclusively from the input client
context. Recheck the same invariant for every task in the proposed `after`.

An explicitly manual create may have empty origin.evidence_ids and task
evidence_ids when task-ledger.schema.json permits it. All other create origins,
and every material non-manual observation, require resolvable evidence. This
skill never creates evidence. source_files reports tasks, evidence and each
relevant quarter_plan.

## 4. Quarter origin

quarter_id is origin metadata, not task location. A Q3 task remains Q3 while
open in Q4; it is never copied, migrated or relabelled.

create_task validates the given quarter by reading
clients/<client_id>/quarters/<quarter_id>/plan.json. The plan must exist, be
valid and have the selected client and quarter identity; otherwise return
error/unknown_origin_quarter. If create_task omits quarter_id, resolve it by
the read-quarter rules: exactly one active valid plan; otherwise the current
real-system YYYY-QN only if it exists; multiple active is error and a missing
current Quarter is error. Persist the resolved quarter_id.
The normalized `create_task` in `mutation_plan` and in the preview hash always
contains that resolved `quarter_id`, even when the input omitted it. Apply uses
the approved normalized Quarter; it never resolves a different Quarter.

## 5. Preview, hashes and apply

Preview reads and validates dependencies, normalizes operations, calculates
before, after, mutation_plan and preview_hash, and never writes canonical state.
If tasks.json is absent, it may propose a valid empty ledger with the correct
client_id, tasks: [], and updated_at from the real UTC execution clock. Absence
does not imply any task or status.

base_state_hash is SHA-256 of canonical JSON (sorted keys, UTF-8, compact
separators) of:
{ "tasks": <tasks.json or null>, "evidence": <relevant canonical evidence state>,
  "quarter_plans": <relevant validated plans> }.
The relevant evidence and plans are the exact dependencies of normalized
material operations; their stable identifiers and full values, or another
deterministic representation that changes whenever a required dependency
changes, must be included. preview_hash is SHA-256 of client_id,
base_state_hash, normalized operations and the logical proposed after.

Apply is never implicit. It requires explicit approval, the approved preview
plan and preview_hash. Reread all dependencies, recompute base_state_hash and
verify preview_hash before any write. Any difference is conflict/stale_preview
with zero writes. Validate after as a complete task-ledger object first, then
write only tasks.json atomically through a temporary file in the same directory,
fsync and rename. A batch is all-or-nothing: invalid operation, dependency,
hash or validation means no canonical mutation.

A material apply replaces only after.updated_at with the real UTC RFC3339 apply
timestamp; every other after field equals the approved logical plan. Preview may
use its real timestamp only to form a valid proposal. No-op does not rewrite the
file and preserves updated_at.

## 6. Operation rules

### create_task

Require task_id, quarter_id (explicit or resolved), title, description,
raised_at, due_at, origin and evidence_ids. raised_at and due_at are YYYY-MM-DD;
status is pending, completed_at is null, and ekyte_url is optional/null.
task_id must have zero canonical occurrences; an existing ID is
conflict/duplicate_task_id and is never overwritten. origin.type is limited to
whatsapp, account_gt, check_in, replanning, manual or other. origin.evidence_ids
are the provenance that raised the task; task.evidence_ids is the accumulated
provenance over its life. Validate every supplied ID before planning and set
the final task evidence deterministically to
`union(input.evidence_ids, origin.evidence_ids)` without duplicates. Thus every
origin evidence ID is retained in task.evidence_ids. For an explicitly manual
origin both lists may be empty when the canonical schema permits it.

Check task_id uniqueness in canonical `before`, after every operation against
the evolving logical state, and again in final `after`. Any duplicate,
including two creates for the same task_id in one batch, is
`conflict/duplicate_task_id` and aborts the entire batch.

### complete_task

Require an existing, uniquely identified pending task and an explicit,
evidence-backed operation. Set status to completed and completed_at to the real
system date YYYY-MM-DD. Union new evidence IDs without duplicates. Never alter
task_id, client_id, quarter_id, raised_at or origin. A completed task with no
new material information is no_change and preserves its original completed_at;
with new valid evidence, union only that provenance while retaining status and
the original completed_at. A cancelled task conflicts. Completion is never
inferred. For a pending task this is material and requires at least one
resolvable evidence ID; an empty list is valid only for the already-completed
no-op.

### cancel_task

For a uniquely identified pending task, set status to cancelled and keep
completed_at null; union any new resolved evidence IDs. Completed conflicts.
Cancelled without new material information is no_change; with new valid
evidence, union provenance while retaining cancelled and completed_at null.
Cancelling a pending task is material and requires at least one resolvable
evidence ID; an empty list is valid only for the already-cancelled no-op. Never
delete a task.

### reschedule_task

Require task_id, new due_at in YYYY-MM-DD and evidence IDs. Only pending tasks
can change due_at. Preserve raised_at, quarter_id and all other task identity.
The same due_at with no new provenance is no_change; it is never a new task.
For a pending task, a changed due_at or provenance change is material and
requires at least one resolvable evidence ID. An empty list is permitted only
for the already-reflected same-date no-op. The same due_at with new valid
evidence changes only provenance; raised_at, quarter_id and origin remain
unchanged.

### link_ekyte

Require task_id and a URI valid under the canonical schema. It may target
pending, completed or cancelled and changes only ekyte_url. The same URL is
no_change. It does not require eKyte to operate and performs no eKyte API call,
publication, remote update or remote-status interpretation.

Before every non-create operation, count matching task_id values: zero is
error/missing, one may proceed, and more than one is
conflict/duplicate_canonical_task_id with zero writes. Evidence IDs are unioned
without duplication for complete, cancel and reschedule.

## 7. Derived overdue summary

Overdue is runtime-only: status is never overdue. At the real system date, a
task is overdue only when status is pending and due_at is earlier than today.
task_summary may expose total, pending, completed, cancelled, overdue,
due_today and an overdue task list with is_overdue and overdue_days. It is
transient output only: it never changes tasks.json, creates a flag, ROPRE or
owner. A task due today is not overdue.

## 8. Status, output and quality

The output may be stored transiently under context/generated/<client_id>/ and
must validate against this skill's schema. before and after are null or the
full canonical task ledger by external reference.

In preview, success means a complete material proposal; no_change means state
already matches; partial is only useful informational context with a
non-essential absence and never authorizes partial application; conflict/error
block apply. Apply returns only success, no_change, conflict or error.

Before completion verify client isolation, task and operation uniqueness,
evidence resolution, origin plans, real timestamps, full after validation,
atomicity, idempotency, absence of persisted overdue and git diff --check.
Never commit or push.

## 9. In-memory conformance cases

Use the configured Python environment, Draft 2020-12 and referencing.Registry
without persisting a synthetic client. Test A-AF: absent-ledger preview and
non-mutation; valid creation; duplicate task ID; completion/cancellation and
their no-ops/conflicts; rescheduling; eKyte linking; Q3 origin retention;
derived overdue and due-today; canonical duplicate task IDs; duplicate
operation IDs; valid, missing and cross-client evidence; explicit manual
origin versus WhatsApp without evidence; missing origin Quarter; stale tasks,
evidence and relevant plan; invalid after; invalid batch atomicity; deduplicated
evidence union; no-op timestamp/file preservation; and canonical before/after
references. Also test AG-AR: pending complete/cancel without evidence;
origin-to-task evidence union; top-level and internal client isolation;
duplicate creates in one batch; terminal-state provenance preservation;
same-date reschedule provenance; normalized resolved Quarter; apply/partial
schema rejection; and final task_id/client-isolation invariants.
