---
name: operator-brief
description: Read-only daily operational briefing built from canonical client records.
---

# Operator brief

- **Class:** INTELLIGENCE
- **Version:** 1.0.0
- **Canonical side effects:** NONE

Build `RESUMO`, `PRIORIDADES`, `PENDÊNCIAS`, `DECISÕES`, `PRÓXIMOS MARCOS`,
`RISCOS/FLAGS`, approved-but-not-executed actions and missing data from the
selected client's canonical task and operations ledgers, Quarter and evidence.
It is transient only. `approved` is never reported as executed or executable
without a real current transport capability. Future dates are never overdue.
