# Operating loop demo — `acme-demo`

Continues `../intelligence/` (the replan chain) into the full operating
loop: **replan → approval → local task materialization → external
publication → reconciliation → midweek/week-close**. 100% synthetic,
generated from `examples/demo-client/acme-demo/intelligence/task-proposals.json`
via the real `scripts/lib/{approval,task_bridge,ekyte_publish,ekyte_transport,
reconciliation,task_ledger_views}.py` modules (not hand-typed) — see
`tests/operating_loop/test_demo_artifacts.py`.

| File | What it shows |
|---|---|
| `operator-inbox.json` | The queue presented before any decision: A1 (approval needed), S1 (scheduling needed), D1 (decision needed). |
| `approval.json` | The operator approves A1 only (defers S1/D1) — hash-locked to `task-proposals.json`. |
| `task-ledger-preview.json` | `manage-task-ledger`-shaped preview of the resulting `create_task` operation. |
| `ekyte-preview.json` | `publish-ekyte` preview — payload mapped, zero external call. |
| `ekyte-apply-fake.json` | `publish-ekyte` apply using `FakeEkyteTransport` — a real (fake) remote create, never a real network call. |
| `reconciliation.json` | `reconcile-ekyte` comparing the now-bound task against the fake remote — `MATCHED`. |
| `midweek-preview.json` / `week-close-preview.json` | Read-only weekly snapshots over the same task set. |
| `workflow-report.json` | Audit trail for the `replan-client` workflow execution that produced the chain in `../intelligence/`. |

No real eKyte call happened anywhere here — see
`docs/workflows/ekyte-publication.md` for why (`FakeEkyteTransport` is
the only transport that exists today for programmatic testing; real
operation is `MANUAL_EXPORT`).
