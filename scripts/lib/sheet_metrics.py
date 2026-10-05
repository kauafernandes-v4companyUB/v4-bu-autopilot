"""metrics-sheet: project canonical Quarter metrics onto the client's metrics
sheet (skills/metrics-sheet/SKILL.md). Authority: CANONICAL -> SHEET only.

Field keys (contract `metrics.fields[].field`):
  media.<YYYY-MM>.<channel>.actual_spend | variance_value | attainment_percent  (monitoring.json)
  media.<YYYY-MM>.<channel>.planned_budget                                      (plan.json)
  objective.current_value | progress_percent | status                           (monitoring.json)
  objective.target_value                                                        (plan.json SMART)
  evidence.<evidence_id>.value                                                  (evidence.json)
A field with no canonical value is NOT_AVAILABLE and is never written (never 0).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from scripts.lib import sheet_modules as sh

MODULE = "metrics-sheet"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def canonical_value(client_dir: Path, quarter_id: str, field: str):
    """The canonical value of one field key, or NOT_AVAILABLE."""
    plan = _load(client_dir / "quarters" / quarter_id / "plan.json")
    mon = _load(client_dir / "quarters" / quarter_id / "monitoring.json")
    parts = field.split(".")
    if parts[0] == "media":
        month, channel, attr = parts[1], parts[2], parts[3]
        if attr == "planned_budget":
            rows = [m for m in (plan or {}).get("media_plan", {}).get("monthly", []) if m["month"] == month and m["channel"] == channel]
            return rows[0]["planned_budget"] if len(rows) == 1 else sh.NOT_AVAILABLE
        rows = [m for m in (mon or {}).get("media_monitoring", []) if m["month"] == month and m["channel"] == channel]
        value = rows[0].get(attr) if len(rows) == 1 else None
        return sh.NOT_AVAILABLE if value is None else value
    if parts[0] == "objective":
        if parts[1] == "target_value":
            return (plan or {}).get("smart_objective", {}).get("target", {}).get("value", sh.NOT_AVAILABLE)
        value = (mon or {}).get("objective_progress", {}).get(parts[1])
        return sh.NOT_AVAILABLE if value is None or (parts[1] == "status" and value == "unknown") else value
    evidence_id = field[len("evidence."):-len(".value")]
    ledger = (_load(client_dir / "evidence.json") or {}).get("evidences", [])
    rows = [e for e in ledger if e["evidence_id"] == evidence_id]
    value = rows[0].get("value") if len(rows) == 1 else None
    return sh.NOT_AVAILABLE if value is None else value


def prepare(transport, *, client_dir: Path, client_id: str) -> dict:
    contract, sources_doc, problems = sh.load_contract(client_dir, client_id, MODULE)
    op_id = sh.safe_id("metrics", client_id, (contract or {}).get("metrics", {}).get("quarter_id", "unknown"))
    if problems:
        return sh.business_result(MODULE, client_id, op_id, "CONFIG_REQUIRED", problems=problems)
    cfg = contract["metrics"]
    if not (client_dir / "quarters" / cfg["quarter_id"] / "plan.json").is_file():
        return sh.business_result(MODULE, client_id, op_id, "CONFIG_REQUIRED",
                                  problems=[sh.notice("QUARTER_NOT_FOUND", f"{cfg['quarter_id']} has no plan.json")])
    header_ranges = [e["range"] for e in contract.get("header_expectations", [])]
    cells, read_problems, _tabs = sh.read_cells(transport, client_id=client_id, sources_doc=sources_doc, source_id=contract["source_id"],
                                                ranges=header_ranges + [f["range"] for f in cfg["fields"]])
    conflicts = read_problems + sh.header_conflicts(cells, contract.get("header_expectations", []))
    if conflicts:
        return sh.business_result(MODULE, client_id, op_id, "CONFLICT_REVIEW_REQUIRED", problems=conflicts)
    ops, fields, labels = [], [], {}
    for i, f in enumerate(cfg["fields"], start=1):
        value = canonical_value(client_dir, cfg["quarter_id"], f["field"])
        fields.append({"field": f["field"], "range": f["range"], "canonical_value": value, "sheet_value": cells.get(f["range"]),
                       "written": value != sh.NOT_AVAILABLE})
        if value == sh.NOT_AVAILABLE:
            continue
        labels[f"m{i:03d}"] = f.get("label") or f["field"]
        ops.append({"op_id": f"m{i:03d}", "type": "write_value", "range": f["range"], "values": [[value]], "input_option": "RAW"})
        if f.get("number_format"):
            labels[f"m{i:03d}-fmt"] = f"{labels[f'm{i:03d}']} (format)"
            ops.append({"op_id": f"m{i:03d}-fmt", "type": "set_number_format", "range": f["range"], "number_format": f["number_format"]})
    details = {"fields": fields, "not_available": [f["field"] for f in fields if not f["written"]]}
    if not ops:
        return sh.business_result(MODULE, client_id, op_id, "NO_CHANGE", details=details,
                                  problems=[sh.notice("NOTHING_TO_PROJECT", "no mapped field has a canonical value")])
    patch = sh.build_patch(patch_id=op_id, client_id=client_id, source_id=contract["source_id"], operations=ops, module=MODULE,
                           notes=f"canonical {cfg['quarter_id']} projection")

    def human(sheet_pv: dict) -> list[str]:
        return [f"{labels.get(d['op_id'], d['op_id'])}: {d['before'].get('value')!r} -> {d['after'].get('value', d['after'])!r}"
                for d in sheet_pv["diff"]]

    return sh.preview_via_update_google_sheet(transport, module=MODULE, client_id=client_id, business_operation_id=op_id,
                                              sources_doc=sources_doc, patch=patch, human_lines=human, details=details)
