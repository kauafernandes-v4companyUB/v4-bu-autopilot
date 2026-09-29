# Operator commands

`scripts.lib.operator_router.route_command` recognizes a deliberately finite
set of natural triggers and returns only routing metadata. It never runs a
workflow. The runtime resolves a human client name to its private `client_id`
before calling it.

| Intent | Workflow | Mutation |
| --- | --- | --- |
| daily brief / pending decisions / overdue | `operator-brief` | no |
| prepare call | `prepare-client-call` | no |
| process call | `process-client-call` | preview only |
| source intake | `source-intake` | no |
| what changed, midweek, week close, ROPRE, replan | matching registered workflow | no |

An ACTION is always a subsequent explicit operator request. Approval is not
execution; a real, compatible, currently authorized capability is also needed.
The external projection vocabulary is `APPROVAL_REQUIRED`,
`APPROVED_WAITING_CAPABILITY`, `EXECUTION_READY`, `EXECUTED`, `STALE`,
`REVOKED`, and `BLOCKED`.
