# Task approval

Full contract: `schemas/approval.schema.json`, `scripts/lib/approval.py`,
`operation/task-rules.md` ("Approval, not auto-approval"). This doc is
the operator-facing summary.

## Why this exists

`generate-tasks` produces *proposals*, not tasks. Something has to turn
an approved proposal into a real `manage-task-ledger` operation without
ever letting a skill approve its own output. That something is the
approval record.

## Lifecycle

```
draft (Claude may build this unattended)
  → approved / partially_approved / rejected (ONLY via an explicit operator request)
  → consumed (after a material apply succeeds)
  → superseded (a new replanning makes the source proposal moot)
```

No function in `scripts/lib/approval.py` can produce
`approved`/`partially_approved` without `approved_by`/`approved_at`
supplied by the caller from a real request — there is no default, no
inferred operator identity, no auto-promotion of a draft candidate.

## Hash-locking

Every `approved_item` carries `approved_payload_hash` — SHA-256 of the
exact item payload approved. Before any material action consumes an
approval, it's re-validated against the **current** state of the source
artifact and item:

- source artifact changed (e.g. a new `replan-client` run) → every item
  in that approval is `STALE_APPROVAL`.
- one specific item's payload changed → only that item is stale.

A stale item can never be applied. There's no partial trust — a
downstream action either gets a fresh, exact match or it doesn't
proceed for that item.

## Presenting approvals to the operator

`schemas/operator-inbox.schema.json` groups everything needing a human
decision into one queue instead of scattering questions through an
execution:

```
APROVAÇÕES
A1 — Criar tarefa X
due_at: ...
evidence: ...
impacto: ...

S1 — Precisa definir prazo
...

D1 — Precisa decisão
...

E1 — Ação externa
...
```

Natural commands like "aprova A1", "aprova A1 e A2", "agenda S1 para
20/09", "rejeita D1", "publica as aprovadas" map to
`apply_operator_decision`/downstream workflow calls — no NLP parser is
built; Claude/Codex interprets the sentence and calls the right
function with the right `item_id`s.

## What consumes an approval

- `apply-approved-tasks` (`workflows/registry.json`) — the only thing
  that turns a `ready` approved item into a `manage-task-ledger`
  `create_task` operation (`scripts/lib/task_bridge.py`).
- `publish-ekyte apply` — requires an approval covering exactly the
  task being published; see `docs/workflows/ekyte-publication.md`.
- `close-ropre apply` already had its own `preview_hash` mechanism
  before this mission — conceptually the same idea, kept as-is rather
  than forced into this newer, more general approval model.

## Supersession

A new replanning run can make a previous `task-proposals.json`
obsolete. This never retroactively cancels a task already applied from
the earlier proposal — see `operation/task-rules.md`, "Replanning
supersession".
