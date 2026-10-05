"""Reference preview/apply for skills/close-ropre/SKILL.md on the V1 ACTION
contract (scripts/lib/canonical_action.py). Forward-only state machine
absent -> draft -> ready -> completed, with the single documented rotation
of a completed+historized current to a new draft and the documented
recovery cases. Files: quarters/<q>/check-ins/current.json and
quarters/<q>/check-ins/history/<check_in_id>.json.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import utc_now_rfc3339

ACTION = "close-ropre"
APPROVAL_ITEM_TYPE = "ropre_transition"
APPROVAL_SOURCE_TYPE = "ropre_draft"
ITEM_LISTS = ("results", "objectives", "premises", "risks", "next_steps")


class _Stop(Exception):
    def __init__(self, kind: str, code: str, message: str):
        super().__init__(message)
        self.kind, self.code = kind, code


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _paths(quarter_id: str, check_in_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    base = f"quarters/{quarter_id}/check-ins"
    return f"{base}/current.json", (f"{base}/history/{check_in_id}.json" if check_in_id else None)


def _business(check_in: dict) -> dict:
    return {k: v for k, v in check_in.items() if k not in ("status", "completed_at")}


def _references(client_dir: Path, client_id: str, check_in: dict) -> tuple[dict, dict]:
    ledger = {e["evidence_id"]: e for e in (_load(client_dir / "evidence.json") or {}).get("evidences", [])}
    tasks = (_load(client_dir / "tasks.json") or {}).get("tasks", [])
    ev_ids = set(check_in.get("evidence_ids", []))
    for lst in ITEM_LISTS:
        for item in check_in.get(lst, []):
            ev_ids.update(item.get("evidence_ids", []))
    evidence = {}
    for eid in sorted(ev_ids):
        e = ledger.get(eid)
        if e is None:
            raise _Stop("error", "unresolved_evidence", f"{eid} is not in this client's evidence ledger")
        if e.get("client_id") != client_id:
            raise _Stop("conflict", "client_isolation_violation", f"{eid} belongs to another client")
        evidence[eid] = e
    task_refs = {}
    for tid in sorted({i.get("task_id") for i in check_in.get("next_steps", []) if i.get("task_id")} | set(check_in.get("task_ids", []))):
        found = [t for t in tasks if t["task_id"] == tid]
        if not found:
            raise _Stop("error", "unresolved_task_reference", f"task {tid!r} does not exist")
        if len(found) > 1:
            raise _Stop("conflict", "ambiguous_task_reference", f"task {tid!r} exists more than once")
        if found[0].get("client_id") != client_id:
            raise _Stop("conflict", "client_isolation_violation", f"task {tid!r} belongs to another client")
        task_refs[tid] = found[0]
    return evidence, task_refs


def _check_draft(draft: dict, client_id: str, quarter_id: str) -> None:
    errs = ca.schema_errors(draft, "schemas/check-in-ropre.schema.json")
    if errs:
        raise _Stop("error", "invalid_draft", "; ".join(errs[:3]))
    if draft.get("status") != "draft" or draft.get("completed_at") is not None:
        raise _Stop("error", "invalid_draft", "a saved draft must be status=draft with completed_at=null; it is never repaired")
    if draft["client_id"] != client_id or draft["quarter_id"] != quarter_id:
        raise _Stop("conflict", "check_in_identity_conflict", "draft belongs to another client/Quarter")
    steps = {i["task_id"] for i in draft.get("next_steps", []) if i.get("task_id")}
    if set(draft.get("task_ids", [])) != steps or len(draft.get("task_ids", [])) != len(set(draft.get("task_ids", []))):
        raise _Stop("error", "task_ids_mismatch", "task_ids must be exactly the unique non-null next_steps[].task_id")
    used = {e for lst in ITEM_LISTS for i in draft.get(lst, []) for e in i.get("evidence_ids", [])}
    missing = used - set(draft.get("evidence_ids", []))
    if missing:
        raise _Stop("error", "evidence_ids_mismatch", f"evidence used by items but absent from draft evidence_ids: {sorted(missing)}")


def _plan(client_dir: Path, client_id: str, quarter_id: str, operation: dict, now: str) -> dict:
    cur_rel, _ = _paths(quarter_id)
    current = _load(client_dir / cur_rel)
    out = {"current": current, "after_current": None, "history_before": None, "history_after": None, "history_rel": None,
           "effect": "none", "policy": None, "business_hash": None, "material": False, "applied_action": None,
           "base": None, "stops": []}
    try:
        plan = _load(client_dir / "quarters" / quarter_id / "plan.json")
        if plan is None or ca.schema_errors(plan, "schemas/quarter-plan.schema.json") or plan["client_id"] != client_id or plan["quarter_id"] != quarter_id:
            raise _Stop("error", "invalid_plan", f"{quarter_id} has no valid plan for this client")
        if current is not None:
            if ca.schema_errors(current, "schemas/check-in-ropre.schema.json"):
                raise _Stop("error", "invalid_current", "current.json is invalid")
            if current["client_id"] != client_id or current["quarter_id"] != quarter_id:
                raise _Stop("conflict", "check_in_identity_conflict", "current.json belongs to another client/Quarter")
        kind = operation.get("type")
        subject = None
        if kind == "save_draft":
            draft = operation["ropre_draft"]
            _check_draft(draft, client_id, quarter_id)
            subject = draft
            _, hist_new = _paths(quarter_id, draft["check_in_id"])
            if (client_dir / hist_new).is_file() and (current is None or current["check_in_id"] != draft["check_in_id"]):
                raise _Stop("conflict", "check_in_id_reuse", f"{draft['check_in_id']} already exists in history")
            if current is None:
                out.update(after_current=draft, material=True, applied_action="save_draft")
            elif current["check_in_id"] == draft["check_in_id"]:
                if ca.semantic(current) != ca.semantic(draft):
                    raise _Stop("conflict", "current_check_in_diverged", "same check_in_id with different content")
                out["after_current"] = current
            elif current["status"] in ("draft", "ready"):
                raise _Stop("conflict", "open_check_in_exists", f"{current['check_in_id']} is still {current['status']}")
            else:
                _, hist_a = _paths(quarter_id, current["check_in_id"])
                hist = _load(client_dir / hist_a)
                if hist is None:
                    raise _Stop("conflict", "completed_not_historized", f"{current['check_in_id']} is completed but has no history copy")
                if ca.semantic(hist) != ca.semantic(current):
                    raise _Stop("conflict", "history_collision", f"history of {current['check_in_id']} diverges from current")
                out.update(after_current=draft, material=True, applied_action="rotate_closed_current_to_new_draft")
        elif kind in ("mark_ready", "complete_check_in"):
            if current is None:
                raise _Stop("error", "no_current_check_in", "there is no current check-in")
            subject = current
            out["history_rel"] = _paths(quarter_id, current["check_in_id"])[1]
            hist = _load(client_dir / out["history_rel"])
            out["history_before"] = hist
            if kind == "mark_ready":
                if current["status"] == "draft":
                    out.update(after_current={**current, "status": "ready"}, material=True, applied_action="mark_ready")
                elif current["status"] == "ready":
                    out["after_current"] = current
                else:
                    raise _Stop("conflict", "invalid_transition", "completed -> ready is not allowed")
            else:
                if current["status"] == "draft":
                    raise _Stop("conflict", "invalid_transition", "draft -> completed skips ready")
                if hist is not None and ca.schema_errors(hist, "schemas/check-in-ropre.schema.json"):
                    raise _Stop("error", "invalid_history", "history check-in is invalid")
                if current["status"] == "ready":
                    out["business_hash"] = content_sha256(_business(current))
                    if hist is None:
                        completed = {**current, "status": "completed", "completed_at": now}
                        out.update(after_current=completed, history_after=completed, effect="create", policy="apply_clock",
                                   material=True, applied_action="complete_current")
                    elif hist.get("status") == "completed" and _business(hist) == _business(current):
                        out.update(after_current=hist, history_after=hist, effect="recover_current", policy="existing_history",
                                   material=True, applied_action="recover_current")
                    else:
                        raise _Stop("conflict", "history_collision", "history differs from the ready current check-in")
                else:  # completed
                    if hist is None:
                        out.update(after_current=current, history_after=current, effect="repair_history", policy="existing_history",
                                   material=True, applied_action="repair_history")
                    elif ca.semantic(hist) == ca.semantic(current):
                        out.update(after_current=current, history_after=hist, effect="verify_identical")
                    else:
                        raise _Stop("conflict", "history_collision", "history differs from the completed current check-in")
        else:
            raise _Stop("error", "unsupported_operation", f"unsupported operation {kind!r}")
        evidence, task_refs = _references(client_dir, client_id, subject)
        hist_state = {p.name: _load(p) for p in sorted((client_dir / "quarters" / quarter_id / "check-ins" / "history").glob("*.json"))} \
            if (client_dir / "quarters" / quarter_id / "check-ins" / "history").is_dir() else {}
        out["base"] = {"current": current, "history": hist_state, "plan": plan, "evidence": evidence, "tasks": task_refs,
                       "draft": operation.get("ropre_draft")}
    except _Stop as s:
        out["stops"].append(s)
    return out


def compute_preview_hash(pv: dict) -> str:
    mp = pv["mutation_plan"]
    intent = None
    if pv["operation"]["type"] == "complete_check_in":
        intent = {"check_in_id": (pv["before_current"] or {}).get("check_in_id"), "target_status": "completed",
                  "completion_time_policy": mp["completion_time_policy"], "business_content_hash": mp["business_content_hash"]}
    return content_sha256({"client_id": pv["client_id"], "quarter_id": pv["quarter_id"], "operation": pv["operation"],
                           "base_state_hash": mp["base_state_hash"], "completion_intent": intent,
                           "proposed_history_effect": mp["proposed_history_effect"],
                           "after_current": ca.semantic(pv["after_current"]) if pv["operation"]["type"] != "complete_check_in" else None})


def preview(client_dir: Path, *, client_id: str, quarter_id: str, operation: dict, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    now = clock()
    run = _plan(client_dir, client_id, quarter_id, operation, now)
    stops = run["stops"]
    cur_rel, _ = _paths(quarter_id)
    status = stops[0].kind if stops else ("success" if run["material"] else "no_change")
    out = {
        "schema_version": "1.0.0", "skill": ACTION, "client_id": client_id, "quarter_id": quarter_id, "generated_at": now, "mode": "preview",
        "status": status,
        "source_files": [{"kind": k, "path": f"clients/{client_id}/{p}", "exists": (client_dir / p).is_file(), "validated": True, "validation_errors": []}
                         for k, p in (("quarter_plan", f"quarters/{quarter_id}/plan.json"), ("current_check_in", cur_rel),
                                      ("evidence", "evidence.json"), ("tasks", "tasks.json"))],
        "operation": operation, "before_current": run["current"], "after_current": None if stops else run["after_current"],
        "history_before": run["history_before"], "history_after": None if stops else run["history_after"],
        "mutation_plan": None if stops else {"current_path": f"clients/{client_id}/{cur_rel}",
                                             "history_path": f"clients/{client_id}/{run['history_rel']}" if run["history_rel"] else None,
                                             "base_state_hash": content_sha256(run["base"]), "proposed_history_effect": run["effect"],
                                             "completion_time_policy": run["policy"], "business_content_hash": run["business_hash"],
                                             "will_write": False},
        "preview_hash": None, "applied_changes": [],
        "conflicts": [{"code": s.code, "message": str(s)} for s in stops if s.kind == "conflict"], "missing_data": [], "warnings": [],
        "validation": {"quarter_plan_valid": not any(s.code == "invalid_plan" for s in stops), "current_valid": not any(s.code == "invalid_current" for s in stops),
                       "history_valid": not any(s.code in ("invalid_history", "history_collision") for s in stops),
                       "evidence_valid": not any(s.code == "unresolved_evidence" for s in stops),
                       "tasks_valid": not any("task_reference" in s.code for s in stops), "after_valid": not stops, "base_state_current": True,
                       "single_file_atomic": True, "multi_file_recovery_valid": True,
                       "errors": [{"code": s.code, "message": str(s)} for s in stops if s.kind == "error"]},
        "receipt": None,
    }
    if out["mutation_plan"]:
        out["preview_hash"] = compute_preview_hash(out)
    return out


def approval_item_id(pv: dict) -> str:
    return f"ropre:{pv['client_id']}:{pv['quarter_id']}:{pv['operation']['type']}"


def build_approval_candidate(pv: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    return ca.build_approval_candidate(pv, item_id=approval_item_id(pv), item_type=APPROVAL_ITEM_TYPE, source_type=APPROVAL_SOURCE_TYPE,
                                       approval_id=approval_id, created_at=created_at, preview_path=preview_path, quarter_id=pv["quarter_id"])


def apply(pv: Optional[dict], approval: Optional[dict], client_dir: Path, *, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    if pv is not None and pv.get("mode") == "preview" and pv.get("status") == "no_change":
        return {**pv, "mode": "apply"}

    def base_now():
        run = _plan(client_dir, pv["client_id"], pv["quarter_id"], pv["operation"], clock())
        return content_sha256(run["base"]) if not run["stops"] else "stale"

    gate = ca.check_gate(pv, approval, client_dir, item_id=approval_item_id(pv) if pv and pv.get("operation") else "",
                         item_type=APPROVAL_ITEM_TYPE, bound_files=[], recompute_preview_hash=compute_preview_hash,
                         recompute_base_hash=base_now if pv and pv.get("mutation_plan") else None)
    base = {**(pv or {}), "mode": "apply", "receipt": None, "applied_changes": []}
    if gate:
        code = "stale_preview" if gate[0]["code"] == "STALE_APPROVAL" else gate[0]["code"]
        return {**base, "status": "conflict" if code == "stale_preview" else "error", "conflicts": [{"code": code, "message": gate[0]["message"]}]}
    now = clock()
    run = _plan(client_dir, pv["client_id"], pv["quarter_id"], pv["operation"], now)
    if run["stops"]:
        s = run["stops"][0]
        return {**base, "status": s.kind, "conflicts": [{"code": s.code, "message": str(s)}]}
    cur_rel, _ = _paths(pv["quarter_id"])
    writes: dict[str, bytes] = {}
    if run["history_after"] is not None and run["effect"] in ("create", "repair_history"):
        writes[run["history_rel"]] = ca.serialize_json(run["history_after"])  # immutable history first
    if run["after_current"] is not None and run["applied_action"] != "repair_history":
        writes[cur_rel] = ca.serialize_json(run["after_current"])
    for rel, data in writes.items():
        if ca.schema_errors(json.loads(data), "schemas/check-in-ropre.schema.json"):
            return {**base, "status": "error", "conflicts": [{"code": "invalid_after", "message": rel}]}
    effects = []
    for rel, data in writes.items():
        before = (client_dir / rel).read_bytes() if (client_dir / rel).is_file() else None
        effects.append(ca.effect(f"clients/{pv['client_id']}/{rel}", "update" if before else "create", before, data))
    receipt = ca.build_action_receipt(action=ACTION, client_id=pv["client_id"], preview=pv, approval=approval, executed_at=now,
                                      status="success", effects=effects)
    ca.atomic_multi_write(client_dir, {**writes, f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)})
    actions = []
    if run["history_rel"] in writes:
        actions.append({"path": f"clients/{pv['client_id']}/{run['history_rel']}", "action": "repair_history" if run["effect"] == "repair_history" else "create_history", "applied_at": now})
    if cur_rel in writes:
        actions.append({"path": f"clients/{pv['client_id']}/{cur_rel}", "action": run["applied_action"], "applied_at": now})
    return {**base, "status": "success", "after_current": run["after_current"], "history_after": run["history_after"],
            "receipt": receipt, "applied_changes": actions}
