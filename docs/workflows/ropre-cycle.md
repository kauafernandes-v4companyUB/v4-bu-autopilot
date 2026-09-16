# Workflow: ROPRE cycle

Fully implemented (`prepare-ropre`, `close-ropre`). See
`operation/ropre-rules.md` for the policy summary and the two skills'
`SKILL.md` for the full contract.

```mermaid
flowchart LR
    A["Quarter plan + monitoring\n+ evidence + prior check-ins"] -->|prepare-ropre\nINTELLIGENCE, read-only| B["ropre draft\ncontext/generated/<id>/ropre-draft.json\n(transient, not memory)"]
    B -->|close-ropre\nsave_draft| C["check-ins/current.json\nstatus: draft"]
    C -->|close-ropre\nmark_ready| D["status: ready"]
    D -->|close-ropre\ncomplete_check_in\nreal clock -> completed_at| E["status: completed\n+ history/<check_in_id>.json\n(immutable copy)"]
```

## State machine (only forward)

```
absent -> draft -> ready -> completed
```

Any reverse or skipped transition is a conflict, never a write. See
`operation/ropre-rules.md` for why `absent` is a legitimate, intentional
state for a client/Quarter that hasn't had its first real check-in yet —
`scheduled_for` must come from a real meeting, never invented.

## Where next steps go

A `next_step` in a completed check-in can seed a task
(`manage-task-ledger`, `origin.type: "check_in"`) — but only via an
explicit `create_task` call referencing that evidence, never
automatically just because the check-in mentions it.
