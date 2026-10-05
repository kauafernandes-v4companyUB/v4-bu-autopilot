"""creative-performance-export: export ONE document-winning-creative report as a
normalized row of the client's creative sheet
(skills/creative-performance-export/SKILL.md). No creative reasoning here —
the report is the input, validated against its own schema.

Row identity: row_key = "<client_id>:<creative_id>" in the contract's
row_key column. Absent -> INSERT in the first empty key row; present ->
UPDATE_EXISTING (same row, report_revision = report content hash);
identical -> NO_CHANGE. Two rows with the same key -> CONFLICT_REVIEW_REQUIRED.
Absent values are NOT_AVAILABLE, never 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib import canonical_action as ca
from scripts.lib import sheet_modules as sh
from scripts.lib.artifact_hash import content_sha256

MODULE = "creative-performance-export"
REPORT_SCHEMA = "skills/document-winning-creative/output.schema.json"


def normalize_row(report: dict) -> dict:
    def text(v):
        return sh.NOT_AVAILABLE if v in (None, "", []) else v

    period = report.get("period") or {}
    metrics = {m["metric_key"]: m for m in report.get("provided_metrics", [])}
    asset = next((a for a in report.get("asset_metadata", []) if a.get("status") == "loaded"), {})
    tech = [f"{k}={asset[k]}" for k in ("kind", "width", "height", "aspect_ratio", "duration_seconds") if asset.get(k) not in (None, "")]
    observed = [f"{e['dimension']}: {e['description']}" for e in report.get("observed_elements", []) if e.get("status") == "OBSERVED" and e.get("description")]
    row = {
        "row_key": f"{report['client_id']}:{report['creative_id']}",
        "client": report["client_id"], "creative_id": report["creative_id"],
        "platform": text((report.get("campaign_context") or {}).get("channel")),
        "period": f"{period.get('start_date') or sh.NOT_AVAILABLE}..{period.get('end_date') or sh.NOT_AVAILABLE}",
        "winner_status": report["winner_status"]["source"],
        "technical_metadata": "; ".join(tech) or sh.NOT_AVAILABLE,
        "observed_pattern": " | ".join(observed) or sh.NOT_AVAILABLE,
        "replication_hypothesis": " | ".join(h["statement"] for h in report.get("replication_hypotheses", [])) or sh.NOT_AVAILABLE,
        "do_not_generalize": " | ".join(n["statement"] for n in report.get("do_not_generalize", [])) or sh.NOT_AVAILABLE,
        "report_revision": content_sha256(ca.semantic(report))[:12],
    }
    for key, m in metrics.items():
        row[f"metric.{key}"] = m["value"] if m.get("status") == "PROVIDED" and m.get("value") is not None else sh.NOT_AVAILABLE
    return row


def prepare(transport, *, client_dir: Path, client_id: str, report: dict) -> dict:
    contract, sources_doc, problems = sh.load_contract(client_dir, client_id, MODULE)
    errs = ca.schema_errors(report, REPORT_SCHEMA)
    op_id = sh.safe_id("creative", client_id, str(report.get("creative_id", "unknown")))
    if errs or report.get("client_id") != client_id:
        problems = problems + [sh.notice("INVALID_REPORT", "; ".join(errs[:3]) or "report belongs to another client")]
    if problems:
        return sh.business_result(MODULE, client_id, op_id, "CONFIG_REQUIRED", problems=problems)
    cfg = contract["creative"]
    cols = cfg["columns"]
    row = normalize_row(report)
    key_col = cols["row_key"]
    key_range = f"'{cfg['tab']}'!{key_col}{cfg['first_row']}:{key_col}{cfg['last_row']}"
    header_ranges = [e["range"] for e in contract.get("header_expectations", [])]
    cells, read_problems, _ = sh.read_cells(transport, client_id=client_id, sources_doc=sources_doc, source_id=contract["source_id"],
                                            ranges=header_ranges + [key_range])
    conflicts = read_problems + sh.header_conflicts(cells, contract.get("header_expectations", []))
    if conflicts:
        return sh.business_result(MODULE, client_id, op_id, "CONFLICT_REVIEW_REQUIRED", problems=conflicts)
    keys = {r: cells.get(sh.cell_ref(cfg["tab"], r, sh.letters_to_col(key_col))) for r in range(cfg["first_row"], cfg["last_row"] + 1)}
    matches = [r for r, v in keys.items() if v == row["row_key"]]
    if len(matches) > 1:
        return sh.business_result(MODULE, client_id, op_id, "CONFLICT_REVIEW_REQUIRED",
                                  problems=[sh.notice("DUPLICATE_ROW_KEY", f"{row['row_key']!r} appears in rows {matches}")])
    if matches:
        target_row, action = matches[0], "UPDATE_EXISTING"
    else:
        free = [r for r, v in keys.items() if v in (None, "")]
        if not free:
            return sh.business_result(MODULE, client_id, op_id, "CONFLICT_REVIEW_REQUIRED",
                                      problems=[sh.notice("NO_FREE_ROW", f"no empty row between {cfg['first_row']} and {cfg['last_row']}")])
        target_row, action = free[0], "INSERT"
    unmapped = sorted(k for k in row if k not in cols)
    ops = [{"op_id": sh.safe_id("col", field), "type": "write_value",
            "range": sh.cell_ref(cfg["tab"], target_row, sh.letters_to_col(letter)), "values": [[row.get(field, sh.NOT_AVAILABLE)]], "input_option": "RAW"}
           for field, letter in sorted(cols.items())]
    patch = sh.build_patch(patch_id=op_id, client_id=client_id, source_id=contract["source_id"], operations=ops, module=MODULE)

    def human(_pv: dict) -> list[str]:
        return [f"{action.lower().replace('_', ' ')}: row {target_row} ({row['row_key']})"] + \
               [f"{k}: {v}" for k, v in sorted(row.items()) if k.startswith("metric.") and k in cols]

    result = sh.preview_via_update_google_sheet(transport, module=MODULE, client_id=client_id, business_operation_id=op_id,
                                                sources_doc=sources_doc, patch=patch, human_lines=human,
                                                details={"row_action": action, "row": target_row, "normalized_row": row,
                                                         "fields_not_in_contract": unmapped})
    return result
