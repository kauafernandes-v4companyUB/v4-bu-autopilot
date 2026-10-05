---
name: operator-brief
description: Read-only daily operational briefing built from canonical client records.
---

# Operator brief

- **Class:** INTELLIGENCE
- **Version:** 1.1.0
- **Canonical side effects:** NONE

Build `RESUMO`, `PRIORIDADES`, `PENDÊNCIAS`, `DECISÕES`, `PRÓXIMOS MARCOS`,
`RISCOS/FLAGS`, approved-but-not-executed actions and missing data from the
selected client's canonical task and operations ledgers, Quarter and evidence.
It is transient only. `approved` is never reported as executed or executable
without a real current transport capability. Future dates are never overdue.

Since 1.1.0: `overdue_operations` lists operations whose canonical status is
`scheduled` and whose `scheduled_for` is before today (derived for the view
only — the ledger is never rewritten); they also appear in `PRIORIDADES`.
`external_action_review` lists every external operation with its projected
state (`APPROVAL_REQUIRED`, `APPROVED_WAITING_CAPABILITY`, `EXECUTION_READY`,
`EXECUTED`, `STALE`, `REVOKED`, `BLOCKED`). It is a review only: nothing in this
skill executes Meta, eKyte, Sheets or any other external system.
