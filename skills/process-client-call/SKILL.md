---
name: process-client-call
description: Preview-only normalization and canonical diff for client-call notes.
---

# Process client call

- **Class:** SOURCE
- **Version:** 1.0.0
- **Canonical side effects:** NONE

Default mode is preview. Normalize only grounded `FACT`, `METRIC`, `DECISION`,
`REQUEST`, `COMMITMENT`, `PENDING`, `RISK`, `HYPOTHESIS`, `IDEA`, and
`DEPENDENCY`; compare with canonical state and propose changes. It never applies
evidence, tasks, operations, or any external action. Fictitious/test sources are
quarantined and cannot be persisted.
