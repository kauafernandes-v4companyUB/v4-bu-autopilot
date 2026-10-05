# Metrics sheet

Projects canonical Quarter metrics onto the client's metrics sheet.
Authority is one-way: **canonical → sheet**. A value typed in the sheet is
never read back into memory.

**Input.** `clients/<client-id>/sheet-contracts/metrics-sheet.json`
(`schemas/sheet-module-contract.schema.json`): the writable `google_sheet`
`source_id`, `header_expectations`, `metrics.quarter_id` and one entry per
cell: `field` → `range` (e.g. `media.2026-10.meta_ads.actual_spend` →
`'Indicadores'!B3`). Fields: `media.<YYYY-MM>.<channel>.{actual_spend,
planned_budget, variance_value, attainment_percent}`,
`objective.{current_value, target_value, progress_percent, status}`,
`evidence.<evidence_id>.value`. Nothing is hardcoded in the engine.

**Preview.** "atualize a planilha de métricas da <cliente>" →
`scripts/lib/sheet_metrics.py::prepare`. It reads through `read-google-sheet`,
checks headers, builds the patch and asks `update-google-sheet` for a
hash-bound preview. Result: `PATCH_READY` with lines like
`Meta spend Oct: 400 -> 1069.07`, `NO_CHANGE`, `CONFIG_REQUIRED` (no contract
or invalid mapping) or `CONFLICT_REVIEW_REQUIRED` (header changed, tab
missing, formula in a target cell). Fields without a canonical value are
listed in `details.not_available` and never written (never 0).

**Approval.** You approve that exact `update-google-sheet` preview
(`sheet_modules.build_approval`).

**Apply + verification.** `sheet_modules.execute` → `update-google-sheet`
apply: it re-reads the sheet (any human edit since the preview →
`CONFLICT_REVIEW_REQUIRED`, zero writes), writes content only, verifies
targets, formulas and structure, and its receipt is stored in
`clients/<client-id>/receipts/`. Re-running is `NO_CHANGE`.
