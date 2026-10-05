"""Reference preview/apply for skills/monitor-quarter/SKILL.md on the V1
ACTION contract (scripts/lib/canonical_action.py). Semantics follow the
SKILL.md: plan.json is read-only; every material operation needs canonical
evidence (evidence_overlay is preview-only and never reaches apply);
base_state_hash = sha256(canonical {"plan", "monitoring"}) (section 9).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.evidence_resolution import resolve_evidence_id
from scripts.lib.exec_clock import utc_now_rfc3339
from scripts.lib.media_monitoring import AmbiguousMediaKey, find_media_records, upsert_media_actual

ACTION = "monitor-quarter"
APPROVAL_ITEM_TYPE = "monitoring_change"
APPROVAL_SOURCE_TYPE = "monitoring_preview"
OP_FIELDS = {
    "update_objective_progress": {"operation_id", "type", "evidence_ids", "status", "current_value", "target_value", "progress_percent", "observed_at"},
    "upsert_media_actual": {"operation_id", "type", "month", "channel", "actual_spend", "evidence_ids", "pacing_percent", "observed_at"},
    "create_flag": {"operation_id", "type", "flag_id", "flag_type", "statement", "evidence_ids"},
    "validate_flag": {"operation_id", "type", "flag_id", "evidence_ids"},
    "resolve_flag": {"operation_id", "type", "flag_id", "evidence_ids"},
}


class _Stop(Exception):
    def __init__(self, kind: str, code: str, message: str, op_id: Optional[str] = None):
        super().__init__(message)
        self.kind, self.code, self.op_id = kind, code, op_id


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _resolve_quarter(client_dir: Path, quarter_id: Optional[str], now: str) -> str:
    if quarter_id:
        return quarter_id
    qdir = client_dir / "quarters"
    active = [p.parent.name for p in sorted(qdir.glob("*/plan.json")) if (_load(p) or {}).get("status") == "active"] if qdir.is_dir() else []
    if len(active) > 1:
        raise _Stop("error", "multiple_active_quarters", f"more than one active Quarter: {active}")
    if active:
        return active[0]
    d = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").date()
    current = f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if (qdir / current / "plan.json").is_file():
        return current
    raise _Stop("error", "quarter_not_found", "no active Quarter and the current calendar Quarter does not exist; never created here")


def base_state_hash(plan: Optional[dict], monitoring: Optional[dict]) -> str:
    return content_sha256({"plan": plan, "monitoring": monitoring})


def _plan(client_dir: Path, client_id: str, quarter_id: str, operations: list[dict], now: str,
          overlay: list[dict]) -> dict:
    qdir = client_dir / "quarters" / quarter_id
    plan, monitoring = _load(qdir / "plan.json"), _load(qdir / "monitoring.json")
    ledger = (_load(client_dir / "evidence.json") or {}).get("evidences", [])
    out = {"plan": plan, "monitoring": monitoring, "after": None, "normalized": [], "changes": [], "warnings": [],
           "resolution": [], "overlay_report": [], "stops": []}
    try:
        if plan is None:
            raise _Stop("error", "quarter_not_found", f"{quarter_id} has no plan.json")
        if ca.schema_errors(plan, "schemas/quarter-plan.schema.json") or plan["client_id"] != client_id or plan["quarter_id"] != quarter_id:
            raise _Stop("error", "invalid_plan", "plan.json is invalid or belongs to another client/Quarter")
        if monitoring is not None and (ca.schema_errors(monitoring, "schemas/quarter-monitoring.schema.json")
                                       or monitoring["client_id"] != client_id or monitoring["quarter_id"] != quarter_id):
            raise _Stop("error", "invalid_monitoring", "monitoring.json is invalid or belongs to another client/Quarter")
        ids = [op.get("operation_id") for op in operations]
        if len(ids) != len(set(ids)):
            raise _Stop("error", "duplicate_operation_id", "operation_id must be unique in the batch")
        target = plan["smart_objective"]["target"]["value"]
        after = copy.deepcopy(monitoring) if monitoring else {
            "schema_version": "1.0.0", "client_id": client_id, "quarter_id": quarter_id, "updated_at": now,
            "objective_progress": {"status": "unknown", "current_value": None, "target_value": target, "progress_percent": None,
                                   "observed_at": None, "evidence_ids": []}, "media_monitoring": [], "flags": []}
        if monitoring is None:
            out["changes"].append({"operation_id": ids[0] if ids else "monitoring", "action": "create_monitoring",
                                   "path": f"clients/{client_id}/quarters/{quarter_id}/monitoring.json", "material": True})
        for raw in operations:
            op = {k: v for k, v in raw.items()}
            oid, kind = op.get("operation_id"), op.get("type")
            if kind not in OP_FIELDS:
                raise _Stop("error", "unsupported_operation", f"unsupported operation type {kind!r}", oid)
            extra = set(op) - OP_FIELDS[kind]
            if extra:
                raise _Stop("error", "unexpected_fields", f"fields not valid for {kind}: {sorted(extra)}", oid)
            eids = op.get("evidence_ids") or []
            if not eids and kind != "resolve_flag":
                raise _Stop("error", "unresolved_evidence", "material operations need evidence_ids", oid)
            for eid in eids:
                res = resolve_evidence_id(eid, client_id=client_id, canonical_evidences=ledger, overlay_evidences=overlay)
                out["resolution"].append({"evidence_id": eid, "operation_id": oid, "resolved_from": res.resolved_from})
                if res.resolved_from == "unresolved":
                    raise _Stop("conflict" if "overlay_conflict" in res.reason else "error",
                                "overlay_conflict" if "overlay_conflict" in res.reason else "unresolved_evidence", f"{eid}: {res.reason}", oid)
                if res.resolved_from == "overlay":
                    out["warnings"].append({"code": "overlay_evidence_used", "message": f"{eid} resolved from evidence_overlay", "operation_id": oid})
            material = True
            if kind == "update_objective_progress":
                if "target_value" in op and op["target_value"] != target:
                    raise _Stop("conflict", "target_mismatch", f"target_value must equal the plan target {target}", oid)
                cur = after["objective_progress"]
                new = {**cur, **{k: op[k] for k in ("status", "current_value", "progress_percent", "observed_at") if k in op},
                       "target_value": target, "evidence_ids": list(dict.fromkeys(cur["evidence_ids"] + eids))}
                material = new != cur
                after["objective_progress"] = new
            elif kind == "upsert_media_actual":
                planned = [m for m in plan["media_plan"]["monthly"] if m["month"] == op["month"] and m["channel"] == op["channel"]]
                if len(planned) > 1:
                    raise _Stop("conflict", "ambiguous_planned_media", f"{(op['month'], op['channel'])} appears more than once in the plan", oid)
                if not planned:
                    out["warnings"].append({"code": "unplanned_media_actual", "message": f"{(op['month'], op['channel'])} is not in plan.json", "operation_id": oid})
                try:
                    media, st = upsert_media_actual(after["media_monitoring"], month=op["month"], channel=op["channel"],
                                                    actual_spend=op["actual_spend"], evidence_ids=eids,
                                                    observed_at=op.get("observed_at") or now,
                                                    planned_budget=planned[0]["planned_budget"] if planned else None,
                                                    pacing_percent=op.get("pacing_percent"))
                except AmbiguousMediaKey as e:
                    raise _Stop("conflict", "ambiguous_monitored_media", str(e), oid)
                except ValueError as e:
                    raise _Stop("error", "invalid_actual", str(e), oid)
                material = st != "no_change"
                after["media_monitoring"] = media
            else:
                same = [f for f in after["flags"] if f["flag_id"] == op["flag_id"]]
                if len(same) > 1:
                    raise _Stop("conflict", "duplicate_flag", f"flag {op['flag_id']!r} exists more than once", oid)
                if kind == "create_flag":
                    if same:
                        raise _Stop("conflict", "flag_exists", f"flag {op['flag_id']!r} already exists", oid)
                    after["flags"].append({"flag_id": op["flag_id"], "type": op["flag_type"], "statement": op["statement"], "status": "open",
                                           "first_seen_at": now, "last_validated_at": now, "resolved_at": None, "evidence_ids": list(eids)})
                elif not same:
                    raise _Stop("error", "flag_not_found", f"flag {op['flag_id']!r} does not exist", oid)
                elif kind == "validate_flag":
                    if same[0]["status"] == "resolved":
                        raise _Stop("conflict", "flag_resolved", "a resolved flag is never reopened", oid)
                    same[0].update(last_validated_at=now, evidence_ids=list(dict.fromkeys(same[0]["evidence_ids"] + eids)))
                else:  # resolve_flag
                    new_ev = [e for e in eids if e not in same[0]["evidence_ids"]]
                    if same[0]["status"] == "resolved" and not new_ev:
                        material = False
                    else:
                        if same[0]["status"] == "open" and not eids:
                            raise _Stop("error", "unresolved_evidence", "resolving an open flag needs evidence", oid)
                        same[0].update(status="resolved", resolved_at=same[0]["resolved_at"] or now, last_validated_at=now,
                                       evidence_ids=list(dict.fromkeys(same[0]["evidence_ids"] + eids)))
            out["normalized"].append(op)
            out["changes"].append({"operation_id": oid, "action": kind if material else "no_change",
                                   "path": f"clients/{client_id}/quarters/{quarter_id}/monitoring.json", "material": material})
        errs = ca.schema_errors(after, "schemas/quarter-monitoring.schema.json")
        if errs:
            raise _Stop("error", "invalid_after", "; ".join(errs[:3]))
        out["after"] = after
    except _Stop as s:
        out["stops"].append(s)
    return out


def compute_preview_hash(pv: dict) -> str:
    return content_sha256(ca.semantic({"client_id": pv["client_id"], "quarter_id": pv["quarter_id"],
                                       "base_state_hash": pv["mutation_plan"]["base_state_hash"],
                                       "operations": pv["mutation_plan"]["normalized_operations"], "after": pv["after"]}))


def _notice(s) -> dict:
    return {"code": s.code, "message": str(s), "operation_id": s.op_id}


def preview(client_dir: Path, *, client_id: str, operations: list[dict], quarter_id: Optional[str] = None,
            evidence_overlay: Optional[list[dict]] = None, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    now = clock()
    try:
        qid = _resolve_quarter(client_dir, quarter_id, now)
    except _Stop as s:
        qid, run = None, {"plan": None, "monitoring": None, "after": None, "normalized": [], "changes": [], "warnings": [],
                          "resolution": [], "overlay_report": [], "stops": [s]}
    else:
        run = _plan(client_dir, client_id, qid, operations, now, list(evidence_overlay or []))
    stops = run["stops"]
    material = any(c["material"] for c in run["changes"])
    qrel = f"clients/{client_id}/quarters/{qid}" if qid else f"clients/{client_id}/quarters"
    out = {
        "schema_version": "1.1.0" if evidence_overlay else "1.0.0", "skill": ACTION, "client_id": client_id, "quarter_id": qid,
        "generated_at": now, "mode": "preview", "status": stops[0].kind if stops else ("success" if material else "no_change"),
        "source_files": [{"kind": k, "path": p, "exists": e, "validated": True, "validation_errors": []} for k, p, e in (
            ("plan", f"{qrel}/plan.json", run["plan"] is not None), ("monitoring", f"{qrel}/monitoring.json", run["monitoring"] is not None),
            ("evidence", f"clients/{client_id}/evidence.json", (client_dir / "evidence.json").is_file()))],
        "operations": operations,
        "mutation_plan": None if stops else {"canonical_path": f"{qrel}/monitoring.json",
                                             "base_state_hash": base_state_hash(run["plan"], run["monitoring"]),
                                             "normalized_operations": run["normalized"], "changes": run["changes"], "will_write": False},
        "preview_hash": None, "before": run["monitoring"], "after": run["after"] if not stops else None, "applied_changes": [],
        "conflicts": [_notice(s) for s in stops if s.kind == "conflict"], "missing_data": [], "warnings": run["warnings"],
        "validation": {"plan_valid": run["plan"] is not None and not any(s.code == "invalid_plan" for s in stops),
                       "monitoring_valid": not any(s.code == "invalid_monitoring" for s in stops),
                       "evidence_valid": not any(s.code in ("unresolved_evidence", "overlay_conflict") for s in stops),
                       "after_valid": run["after"] is not None, "base_state_current": True, "atomic": True,
                       "errors": [_notice(s) for s in stops if s.kind == "error"]},
        "evidence_overlay_report": [], "evidence_resolution": run["resolution"] if evidence_overlay else [], "receipt": None,
    }
    if evidence_overlay:
        used = {r["evidence_id"] for r in run["resolution"] if r["resolved_from"] == "overlay"}
        out["evidence_overlay_report"] = [{"evidence_id": e["evidence_id"], "universal_schema_valid": not ca.schema_errors(e, "schemas/evidence.schema.json"),
                                           "canonical_shape_valid": True, "conflicts_with_canonical": False, "accepted": e["evidence_id"] in used,
                                           "reason": "resolved via overlay" if e["evidence_id"] in used else "not used or canonical"}
                                          for e in evidence_overlay]
    if out["mutation_plan"]:
        out["preview_hash"] = compute_preview_hash(out)
    return out


def approval_item_id(pv: dict) -> str:
    return f"monitoring:{pv['client_id']}:{pv['quarter_id']}"


def build_approval_candidate(pv: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    if pv.get("evidence_resolution") and any(r["resolved_from"] == "overlay" for r in pv["evidence_resolution"]):
        from scripts.lib.approval import ApprovalError
        raise ApprovalError("a preview resolved through evidence_overlay can never be approved for apply; promote the evidence and re-run preview")
    return ca.build_approval_candidate(pv, item_id=approval_item_id(pv), item_type=APPROVAL_ITEM_TYPE, source_type=APPROVAL_SOURCE_TYPE,
                                       approval_id=approval_id, created_at=created_at, preview_path=preview_path, quarter_id=pv["quarter_id"])


def apply(pv: Optional[dict], approval: Optional[dict], client_dir: Path, *, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    if pv is not None and pv.get("mode") == "preview" and pv.get("status") == "no_change":
        return {**pv, "mode": "apply"}
    qid = (pv or {}).get("quarter_id")
    qdir = client_dir / "quarters" / str(qid)

    def base_now():
        return base_state_hash(_load(qdir / "plan.json"), _load(qdir / "monitoring.json"))

    gate = ca.check_gate(pv, approval, client_dir, item_id=approval_item_id(pv) if pv and qid else "", item_type=APPROVAL_ITEM_TYPE,
                         bound_files=[], recompute_preview_hash=compute_preview_hash, recompute_base_hash=base_now)
    base = {**(pv or {}), "mode": "apply", "receipt": None, "applied_changes": [], "evidence_overlay_report": [], "evidence_resolution": []}
    if gate:
        code = "stale_preview" if gate[0]["code"] == "STALE_APPROVAL" else gate[0]["code"]
        return {**base, "status": "conflict" if code == "stale_preview" else "error",
                "conflicts": [{"code": code, "message": gate[0]["message"], "operation_id": None}]}
    now = clock()
    run = _plan(client_dir, pv["client_id"], qid, pv["mutation_plan"]["normalized_operations"], now, overlay=[])  # apply: canonical only
    if run["stops"]:
        s = run["stops"][0]
        return {**base, "status": s.kind, "conflicts": [_notice(s)]}
    after = run["after"]
    after["updated_at"] = now
    rel = f"quarters/{qid}/monitoring.json"
    before = (client_dir / rel).read_bytes() if (client_dir / rel).is_file() else None
    data = ca.serialize_json(after)
    receipt = ca.build_action_receipt(action=ACTION, client_id=pv["client_id"], preview=pv, approval=approval, executed_at=now,
                                      status="success", effects=[ca.effect(f"clients/{pv['client_id']}/{rel}", "update" if before else "create", before, data)])
    ca.atomic_multi_write(client_dir, {rel: data, f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)})
    return {**base, "status": "success", "after": after, "receipt": receipt,
            "applied_changes": [{"operation_id": c["operation_id"], "action": c["action"], "path": c["path"], "applied_at": now}
                                for c in run["changes"] if c["material"]]}
