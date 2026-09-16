# Task rules

Consolidated from CLAUDE.md sections 19 and 27, and
`skills/manage-task-ledger/SKILL.md`. Read the SKILL.md for the full
contract (hashing, evidence union rules, batch atomicity) — this is the
summary.

## Tasks are longitudinal — Quarter is origin metadata, not location

`quarter_id` on a task records *where it was raised*, never where it
currently "lives". A task raised in Q3 and still open in Q4 stays
`quarter_id: "2026-Q3"` forever — it is never migrated, copied, or
relabelled to the current Quarter just because time passed.

## No fields beyond `schemas/task-ledger.schema.json`

No `owner`, `priority`, `sprint`, `story_points`, `complexity`, or any
other field outside the schema. If a future need requires one, extend
the schema deliberately — don't smuggle it into `description`.

## `overdue` is always derived, never persisted

A task's `status` is one of `pending` / `completed` / `cancelled` —
never `overdue`. "Overdue" is computed at read time: `status == pending
and due_at < today (real system date)`. `manage-task-ledger`'s
`task_summary` may expose it as a transient view; it never writes it
back to `tasks.json`, never creates a flag or ROPRE item just because a
task is overdue.

## Every material operation is evidence-backed

`create_task`, `complete_task`, `cancel_task`, `reschedule_task` each
require resolvable `evidence_ids` (from that client's
`evidence.json`) for the material change, with one narrow exception:
an explicitly manual origin may have empty evidence when the schema
permits it. `link_ekyte` is the one operation that only sets a URL and
needs no new evidence beyond the task already existing.

## Never invent a task from a pending item

A `pending`/`request`/`commitment`/ROPRE next-step existing somewhere
(WhatsApp, Account x GT, current-state.json, a ROPRE draft) does **not**
automatically become a task. CLAUDE.md section 5: never auto-convert
`PENDING` into a task. A task is created only by an explicit
`create_task` operation with its own evidence and origin.
`skills/generate-tasks/` produces *proposals* from a replanning's
actions (never directly from a raw pending item) — turning a proposal
into a real `create_task` operation still requires an explicit operator
approval (`schemas/approval.schema.json`, see "Approval, not
auto-approval" below) before `manage-task-ledger` ever sees it.

## Stable task identity — never a timestamp

A task's `task_id` is always derived deterministically from
`(client_id, quarter_id, origin_action_id)` via
`scripts/lib/task_identity.py::compute_task_id` — never from a
timestamp or the order it was discovered. This is what stops
"Criar criativos Semana do Cliente" from being proposed as three
different tasks across three separate `replan-client` runs: the same
action, in the same Quarter, for the same client, always produces the
same `task_id`, and `manage-task-ledger`'s own `duplicate_task_id`
protection does the real deduplication at `create_task` time.

## Approval, not auto-approval (`schemas/approval.schema.json`)

No skill may set an approval's `status` to `approved`/`partially_approved`
on its own — `scripts/lib/approval.py::apply_operator_decision` is the
only path that produces one of those statuses, and it always requires
`approved_by`/`approved_at` supplied by the caller from a real,
explicit operator request. A skill may build a `status: "draft"`
candidate unattended; it may never promote its own candidate to
approved.

Every approved item is hash-locked to the exact payload it approved
(`approved_payload_hash`, canonical JSON SHA-256). If the source
artifact (typically `task-proposals.json`) changes afterward — e.g. a
new `replan-client` run supersedes it — the approval is **stale** for
that item, and no material operation (`apply-approved-tasks`,
`publish-ekyte apply`) may consume it. This is checked every time, not
just once at approval creation.

## Replanning supersession — never cancel in-flight work silently

A new `replan-client` run may produce a new `task-proposals.json` that
effectively supersedes a previous one. This never retroactively
invalidates a task that was already applied to `tasks.json` from the
earlier proposal — an applied task is real operational state, and
changing course on it is a new, explicit decision (e.g. `cancel_task`),
never an automatic side effect of replanning again. Transient
replanning artifacts are not deleted for this — historical proposals
remain on disk for audit, only their *approval* (if unconsumed) goes
stale.

## Task Completion Authority (formerly an open architectural question)

Resolved policy, adopted here:

- The local task ledger (`clients/<client_id>/tasks.json`) is the
  canonical operational memory for task status. It is always the
  reference an operator/skill trusts by default.
- eKyte (when actually used) is an external system of *execution*, not
  of *authority* — work may happen there, but it does not by itself
  change what this repository considers true.
- An externally observed status (via `reconcile-ekyte`) **never**
  changes the local task automatically — `reconcile-ekyte` is read-only
  by construction (no `apply` mode exists for it).
- A divergence found by `reconcile-ekyte` is a *proposal for the
  operator to look at*, nothing more. If the operator decides the
  remote status should win, that becomes an explicit
  `manage-task-ledger` operation (`complete_task`/`cancel_task`/
  `reschedule_task`) with its own evidence — the same bar as any other
  material change to the ledger, never a bulk auto-sync.

This means `reconcile-ekyte` will, by design, sometimes report the same
`STATUS_MISMATCH` repeatedly across runs until a human acts on it —
that is intended, not a bug to "fix" by making the sync automatic.

## eKyte is optional, external, and never required

The local task ledger (`clients/<client_id>/tasks.json`) is always the
operational reference. `link_ekyte` records a URL (and, additively,
`external.*` — `schemas/task-ledger.schema.json`) — it makes no API
call, publishes nothing, and never interprets remote status by itself.
Publishing to eKyte for real (`publish-ekyte`) is an EXTERNAL action
requiring an explicit approval per this file and CLAUDE.md section 20.
Its honest capability status is `IMPLEMENTED_DRY_RUN`: no real eKyte
API/connector is documented or available today (audit trail:
`docs/workflows/ekyte-publication.md`), so real-world publication is
currently a manual-export packet, not a programmatic call — the
contract, payload mapping, approval gating and idempotency are real and
tested regardless.
