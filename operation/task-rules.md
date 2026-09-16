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
`create_task` operation with its own evidence and origin — generating
tasks from upstream signals is the job of a future INTELLIGENCE/ACTION
skill (`generate-tasks`, currently `planned`, not `implemented` — see
`skills/registry.json`), not something any current skill does
implicitly.

## eKyte is optional, external, and never required

The local task ledger (`clients/<client_id>/tasks.json`) is always the
operational reference. `link_ekyte` only records a URL — it makes no
API call, publishes nothing, and never interprets remote status.
Publishing to eKyte for real (`publish-ekyte`, `planned`, not
implemented) is an EXTERNAL action requiring explicit authorization
per CLAUDE.md section 20, same as any other external system write.
