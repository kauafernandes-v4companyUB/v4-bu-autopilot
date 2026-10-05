# Creative performance export

Exports one `document-winning-creative` report as a row of the client's
creative sheet. No creative analysis happens here.

**Input.** A report valid against
`skills/document-winning-creative/output.schema.json`, and
`clients/<client-id>/sheet-contracts/creative-performance-export.json`:
`tab`, `first_row`, `last_row` and `columns` (export field → column letter;
`row_key` is required). Exportable fields: `row_key`, `client`,
`creative_id`, `platform`, `period`, `winner_status`, `technical_metadata`,
`observed_pattern`, `replication_hypothesis`, `do_not_generalize`,
`report_revision` and `metric.<metric_key>`. Missing values are
`NOT_AVAILABLE`, never 0.

**Preview.** "exporte o criativo campeão da <cliente> para a planilha" →
`sheet_creative_export.prepare`. Row identity is
`<client-id>:<creative-id>`:

- key absent → `insert: row N` (first empty key row);
- key present → `update existing: row N` (same row; `report_revision`
  changes when the report changes semantically);
- identical → `NO_CHANGE`;
- duplicated key or no free row → `CONFLICT_REVIEW_REQUIRED`.

**Approval / apply / verification.** Approve the exact `update-google-sheet`
preview; `sheet_modules.execute` applies, verifies and stores the receipt in
`clients/<client-id>/receipts/`. Re-running the same report is `NO_CHANGE` and
never adds a second row.
