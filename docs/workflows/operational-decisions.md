# Durable operational decisions

`clients/<client_id>/operations.json` is the private canonical ledger for an
operator decision that must survive regeneration of `context/generated/` but
does not yet belong to `tasks.json`, evidence, ROPRE or an executed external
action. Its schema is `schemas/operations-ledger.schema.json`.

The ledger records a stable operation id, the proposal/source artifact hash,
human statement, lifecycle status, optional schedule/defer condition, approval
hash, external execution state, evidence IDs and references to durable
receipts. It does not duplicate a full receipt.

Lifecycle is explicit. Scheduled state may become completed, cancelled,
materialized or superseded. Deferred state may become active, cancelled or
superseded. An approved external operation may become executed, revoked or
superseded. A date arriving never changes state by itself.

When a decision becomes a task, `manage-task-ledger` creates the task after its
own approval/validation; the operation is retained as `materialized` with a
`materialized_ref.task_id`. When an external action executes, the approval
payload hash must still match, explicit session authorization is required, and
a durable receipt reference is added. `approved` never means `executed`.

A changed payload makes an earlier approval stale. A new replan does not erase
the old human decision: an explicit supersession links the prior and replacing
operation. The Operator Inbox is rebuilt transiently from this ledger, tasks,
current replanning and relevant evidence.
