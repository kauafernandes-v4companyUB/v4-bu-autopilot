# ACTION contract (V1)

Every ACTION that mutates canonical state follows

```
PREVIEW -> preview_hash (+ base_state_hash) -> approval bound to that preview
        -> APPLY (re-derive; STALE on any drift; zero writes on failure)
        -> atomic write -> receipt (clients/<client_id>/receipts/)
```

Shared helpers: `scripts/lib/canonical_action.py` (semantic hashing,
base state, approval gate, all-or-nothing multi-file write, receipt).

## Matrix

| ACTION | preview | preview_hash | base_state_hash | approval binding | stale detection | atomic apply | receipt | idempotency |
|---|---|---|---|---|---|---|---|---|
| `promote-client-memory` 1.1.0 | yes | yes | yes (all bound targets) | approval record (`memory_promotion`) | yes | yes (multi-file) | yes | yes |
| `manage-quarter` 1.0.0 | yes | yes | yes (`quarters/`, ledgers, `client.json`) | approval record (`quarter_lifecycle`) | yes | yes (multi-file) | yes | yes |
| `monitor-quarter` 1.2.0 | yes | yes | yes (plan + monitoring) | approved `preview_hash` + explicit request | yes (`stale_preview`) | yes | yes | yes |
| `manage-task-ledger` 1.2.0 | yes | yes | yes | approved `preview_hash`; approval record via `apply-approved-tasks` | yes | yes | yes | yes |
| `close-ropre` 1.1.0 | yes | yes | yes | approved `preview_hash` + explicit request | yes | yes | yes | yes |
| `update-google-sheet` 1.0.0 | yes | yes | yes (live sheet state) | approval record (`google_sheet_patch`) | yes (`STALE_PREVIEW`) | n/a — see below | yes | yes |
| `publish-ekyte` 1.0.0 | yes | n/a — see below | n/a — see below | approval bound to the canonical task | yes (task payload hash) | n/a — external | yes | yes (idempotency key) |
| `manage-operations-ledger` 1.1.0 | yes | yes | yes (`operations.json`, `tasks.json`) | approval record (`operations_ledger_change`) | yes | yes | yes | yes |
| `generate-tasks` 1.1.0 | preview only | n/a | n/a | n/a | n/a | n/a | n/a | yes (deterministic `task_id`) |

## Justified exceptions

- `generate-tasks` never writes: its proposals are applied by
  `manage-task-ledger` through `apply-approved-tasks`, which carries the
  approval, stale check and receipt.
- `update-google-sheet` writes to an external system: one Sheets API call
  cannot be made atomic with others, so it re-reads and aborts on drift
  before writing, stops at the first failed request and verifies after
  writing (`skills/update-google-sheet/SKILL.md`).
- `publish-ekyte` has no readable remote base state (no real transport);
  its approval is bound to the canonical task payload, and real apply is
  `MANUAL_EXPORT` (`docs/workflows/ekyte-publication.md`).

## Reference implementations

Code applies: `promote-client-memory`, `manage-quarter`,
`manage-operations-ledger`, `update-google-sheet`, `publish-ekyte` (fake
transport). `monitor-quarter`, `manage-task-ledger` and `close-ropre` are
applied by the agent following their SKILL.md on this same contract, with
pure reference logic in `scripts/lib/` (`media_monitoring.py`,
`task_bridge.py`).
