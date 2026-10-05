# Operational playbook

Projects approved actions onto the period's playbook tab.

**Input.** Canonical tasks, operations and active decisions of the Quarter,
plus optional seasonal-plan items (`sheet_playbook.collect_items`). Sections:

| Section | From |
|---|---|
| CONFIRMED_ACTION | pending/completed tasks, scheduled/approved operations, active decisions, seasonal recommendations you explicitly approved |
| RECOMMENDATION | seasonal recommendations not approved |
| CLIENT_CONFIRMATION_REQUIRED | seasonal items needing client confirmation |
| DEPENDENCY | deferred operations |
| DECISION_REQUIRED | decision_pending operations |

A recommendation never becomes an action or a task silently. Dates only come
from a task `due_at`, an operation `scheduled_for` or an explicit ISO date —
"última semana do mês" stays without a date.

Contract `clients/<client-id>/sheet-contracts/operational-playbook.json`:
`template_tab`, a stable `target_tab` (e.g. `Playbook 2026-10`) and one
4-column block (statement, date, reference, status) per section.

**Preview.** "atualize o playbook da <cliente>" → `sheet_playbook.prepare`,
in two approved steps:

1. `create sheet: YES` — `duplicate_sheet` of the template into the target
   tab, once. Its receipt is the tab's identity.
2. `create sheet: NO` + the actions per section — content patch (empty
   cells are explicit clears).

`CONFLICT_REVIEW_REQUIRED` when the target tab exists without this module's
receipt, a suffixed copy exists (`… (2)`), the target was removed, or headers
changed; `CONFIG_REQUIRED` when a section has more items than rows (never
truncated).

**Approval / apply / verification.** Same as every Sheets module: approve the
exact `update-google-sheet` preview, `sheet_modules.execute` applies, verifies
and stores the receipt. Re-running is `NO_CHANGE`; the tab is never
duplicated twice.
