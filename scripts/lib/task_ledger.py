"""Reference preview/apply for skills/manage-task-ledger/SKILL.md on the V1
ACTION contract (scripts/lib/canonical_action.py). Semantics follow the
SKILL.md exactly; this module adds no rule of its own.

Operations: create_task, complete_task, cancel_task, reschedule_task,
link_ekyte. A batch is all-or-nothing; overdue is never persisted.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import utc_now_rfc3339

ACTION = "manage-task-ledger"
APPROVAL_ITEM_TYPE = "task_ledger_change"
APPROVAL_SOURCE_TYPE = "task_ledger_preview"


class _Stop(Exception):
    def __init__(self, kind: str, code: str, message: str, op_id: Optional[str] = None):
        super().__init__(message)
        self.kind, self.code, self.op_id = kind, code, op_id


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _union(*lists) -> list:
    out = []
    for lst in lists:
        for x in lst or []:
            if x not in out:
                out.append(x)
    return out


def _resolve_quarter(client_dir: Path, client_id: str, today: date) -> str:
    qdir = client_dir / "quarters"
    active = []
    for p in sorted(qdir.glob("*/plan.json")) if qdir.is_dir() else []:
        plan = _load(p)
        if plan.get("status") == "active" and not ca.schema_errors(plan, "schemas/quarter-plan.schema.json"):
            active.append(plan["quarter_id"])
    if len(active) > 1:
        raise _Stop("error", "multiple_active_quarters", f"more than one active Quarter: {active}")
    if active:
        return active[0]
    current = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
    if (qdir / current / "plan.json").is_file():
        return current
    raise _Stop("error", "unknown_origin_quarter", "no active Quarter and the current calendar Quarter does not exist")


def _bound_files(normalized: list[dict]) -> list[str]:
    quarters = sorted({op["quarter_id"] for op in normalized if op["type"] == "create_task"})
    return ["tasks.json", "evidence.json"] + [f"quarters/{q}/plan.json" for q in quarters]


def _run(client_dir: Path, client_id: str, operations: list[dict], now: str, today: date) -> dict:
    """Pure planning against the current files. Returns a dict with
    before/after/normalized/changes and a list of stops (conflict/error)."""
    tasks_doc = _load(client_dir / "tasks.json")
    evidence_doc = _load(client_dir / "evidence.json") or {"evidences": []}
    known_ev = {e["evidence_id"] for e in evidence_doc.get("evidences", []) if e.get("client_id") == client_id}
    stops: list[_Stop] = []
    result = {"before": tasks_doc, "after": None, "normalized": [], "changes": [], "stops": stops, "plans_valid": True}
    try:
        ids = [op.get("operation_id") for op in operations]
        if len(ids) != len(set(ids)):
            raise _Stop("error", "duplicate_operation_id", "operation_id must be unique in the batch")
        if tasks_doc is not None:
            errs = ca.schema_errors(tasks_doc, "schemas/task-ledger.schema.json")
            if errs:
                raise _Stop("error", "invalid_tasks", "; ".join(errs[:3]))
            if tasks_doc.get("client_id") != client_id or any(t.get("client_id") != client_id for t in tasks_doc["tasks"]):
                raise _Stop("conflict", "client_isolation_violation", "tasks.json or a task belongs to another client")
        after = copy.deepcopy(tasks_doc) if tasks_doc else {"schema_version": "1.0.0", "client_id": client_id,
                                                            "updated_at": now, "tasks": []}
        if tasks_doc is None:
            result["changes"].append({"operation_id": operations[0]["operation_id"] if operations else "ledger",
                                      "action": "create_ledger", "path": "clients/{}/tasks.json".format(client_id), "material": True})

        def evidence_ok(op_id, eids, allow_empty):
            if not eids and not allow_empty:
                raise _Stop("error", "missing_evidence", "a material operation needs at least one resolvable evidence ID", op_id)
            missing = [e for e in eids if e not in known_ev]
            if missing:
                raise _Stop("error", "unresolved_evidence", f"evidence not in this client's ledger: {missing}", op_id)

        def one(task_id, op_id):
            found = [t for t in after["tasks"] if t["task_id"] == task_id]
            if not found:
                raise _Stop("error", "task_not_found", f"task {task_id!r} does not exist", op_id)
            if len(found) > 1:
                raise _Stop("conflict", "duplicate_canonical_task_id", f"task {task_id!r} exists more than once", op_id)
            return found[0]

        for raw in operations:
            op = copy.deepcopy(raw)
            oid, kind = op.get("operation_id"), op.get("type")
            path = f"clients/{client_id}/tasks.json#{op.get('task_id')}"
            material = True
            if kind == "create_task":
                if "client_id" in op:
                    raise _Stop("error", "client_id_not_accepted", "create_task never accepts client_id", oid)
                if not op.get("quarter_id"):
                    op["quarter_id"] = _resolve_quarter(client_dir, client_id, today)
                plan = _load(client_dir / "quarters" / op["quarter_id"] / "plan.json")
                if plan is None or ca.schema_errors(plan, "schemas/quarter-plan.schema.json") or plan.get("client_id") != client_id \
                        or plan.get("quarter_id") != op["quarter_id"]:
                    result["plans_valid"] = False
                    raise _Stop("error", "unknown_origin_quarter", f"{op['quarter_id']} has no valid plan for this client", oid)
                manual = op["origin"]["type"] == "manual"
                evidence_ok(oid, _union(op["evidence_ids"], op["origin"]["evidence_ids"]), allow_empty=manual)
                if any(t["task_id"] == op["task_id"] for t in after["tasks"]):
                    raise _Stop("conflict", "duplicate_task_id", f"task {op['task_id']!r} already exists", oid)
                after["tasks"].append({"task_id": op["task_id"], "client_id": client_id, "quarter_id": op["quarter_id"],
                                       "title": op["title"], "description": op["description"], "raised_at": op["raised_at"],
                                       "due_at": op["due_at"], "status": "pending", "completed_at": None,
                                       "ekyte_url": op.get("ekyte_url"), "evidence_ids": _union(op["evidence_ids"], op["origin"]["evidence_ids"]),
                                       "origin": op["origin"]})
            elif kind in ("complete_task", "cancel_task"):
                task = one(op["task_id"], oid)
                target = "completed" if kind == "complete_task" else "cancelled"
                other = "cancelled" if target == "completed" else "completed"
                new_ev = [e for e in op["evidence_ids"] if e not in task["evidence_ids"]]
                if task["status"] == other:
                    raise _Stop("conflict", f"task_{other}", f"task {op['task_id']!r} is {other}", oid)
                if task["status"] == target:
                    evidence_ok(oid, new_ev, allow_empty=True)
                    material = bool(new_ev)
                    task["evidence_ids"] = _union(task["evidence_ids"], new_ev)
                else:
                    evidence_ok(oid, op["evidence_ids"], allow_empty=False)
                    task["status"] = target
                    task["completed_at"] = today.isoformat() if target == "completed" else None
                    task["evidence_ids"] = _union(task["evidence_ids"], op["evidence_ids"])
            elif kind == "reschedule_task":
                task = one(op["task_id"], oid)
                if task["status"] != "pending":
                    raise _Stop("conflict", "task_not_pending", f"only pending tasks can be rescheduled ({task['status']})", oid)
                new_ev = [e for e in op["evidence_ids"] if e not in task["evidence_ids"]]
                if task["due_at"] == op["due_at"] and not new_ev:
                    material = False
                else:
                    evidence_ok(oid, op["evidence_ids"], allow_empty=False)
                    task["due_at"] = op["due_at"]
                    task["evidence_ids"] = _union(task["evidence_ids"], new_ev)
            elif kind == "link_ekyte":
                task = one(op["task_id"], oid)
                if task.get("ekyte_url") == op["ekyte_url"]:
                    material = False
                else:
                    ext = task.get("external") or {}
                    if ext.get("url") and ext["url"] != op["ekyte_url"]:
                        raise _Stop("conflict", "external_binding_conflict", "external.url differs from the new eKyte URL", oid)
                    task["ekyte_url"] = op["ekyte_url"]
            else:
                raise _Stop("error", "unsupported_operation", f"unsupported operation type {kind!r}", oid)
            result["normalized"].append(op)
            result["changes"].append({"operation_id": oid, "action": kind if material else "no_change", "path": path, "material": material})
        ids_after = [t["task_id"] for t in after["tasks"]]
        if len(ids_after) != len(set(ids_after)):
            raise _Stop("conflict", "duplicate_task_id", "duplicate task_id in the proposed ledger")
        errs = ca.schema_errors(after, "schemas/task-ledger.schema.json")
        if errs:
            raise _Stop("error", "invalid_after", "; ".join(errs[:3]))
        result["after"] = after
    except _Stop as s:
        stops.append(s)
    return result


def _summary(after: Optional[dict], today: date) -> Optional[dict]:
    if after is None:
        return None
    tasks = after["tasks"]
    overdue = [t for t in tasks if t["status"] == "pending" and date.fromisoformat(t["due_at"]) < today]
    return {"as_of_date": today.isoformat(), "total": len(tasks), "pending": sum(t["status"] == "pending" for t in tasks),
            "completed": sum(t["status"] == "completed" for t in tasks), "cancelled": sum(t["status"] == "cancelled" for t in tasks),
            "overdue": len(overdue), "due_today": sum(t["status"] == "pending" and t["due_at"] == today.isoformat() for t in tasks),
            "overdue_tasks": [{"task_id": t["task_id"], "title": t["title"], "due_at": t["due_at"], "is_overdue": True,
                               "overdue_days": (today - date.fromisoformat(t["due_at"])).days} for t in overdue]}


def compute_preview_hash(pv: dict) -> str:
    return content_sha256(ca.semantic({"client_id": pv["client_id"], "base_state_hash": pv["mutation_plan"]["base_state_hash"],
                                       "operations": pv["mutation_plan"]["normalized_operations"], "after": pv["after"]}))


def preview(client_dir: Path, *, client_id: str, operations: list[dict], clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    now = clock()
    today = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
    run = _run(client_dir, client_id, operations, now, today)
    stops = run["stops"]
    material = any(c["material"] for c in run["changes"])
    status = stops[0].kind if stops else ("success" if material else "no_change")
    files = _bound_files(run["normalized"]) if not stops else ["tasks.json", "evidence.json"]
    out = {
        "schema_version": "1.0.0", "skill": ACTION, "client_id": client_id, "generated_at": now, "mode": "preview", "status": status,
        "source_files": [{"kind": "tasks" if f == "tasks.json" else "evidence" if f == "evidence.json" else "quarter_plan",
                          "path": f"clients/{client_id}/{f}", "exists": (client_dir / f).is_file(), "validated": True,
                          "validation_errors": []} for f in files],
        "operations": operations,
        "mutation_plan": {"canonical_path": f"clients/{client_id}/tasks.json", "base_state_hash": ca.state_hash(client_dir, files),
                          "normalized_operations": run["normalized"], "changes": run["changes"], "will_write": False},
        "preview_hash": None, "before": run["before"], "after": run["after"] if not stops else None,
        "task_summary": _summary(run["after"] or run["before"], today), "applied_changes": [],
        "conflicts": [{"code": s.code, "message": str(s), "operation_id": s.op_id} for s in stops if s.kind == "conflict"],
        "missing_data": [], "warnings": [],
        "validation": {"tasks_valid": not any(s.code == "invalid_tasks" for s in stops), "evidence_valid": not any(s.code == "unresolved_evidence" for s in stops),
                       "quarter_plans_valid": run["plans_valid"], "after_valid": run["after"] is not None, "base_state_current": True,
                       "atomic": True, "errors": [{"code": s.code, "message": str(s), "operation_id": s.op_id} for s in stops if s.kind == "error"]},
        "receipt": None,
    }
    out["preview_hash"] = compute_preview_hash(out)
    return out


def approval_item_id(pv: dict) -> str:
    return f"task-ledger:{pv['client_id']}"


def build_approval_candidate(pv: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    return ca.build_approval_candidate(pv, item_id=approval_item_id(pv), item_type=APPROVAL_ITEM_TYPE, source_type=APPROVAL_SOURCE_TYPE,
                                       approval_id=approval_id, created_at=created_at, preview_path=preview_path)


def apply(pv: Optional[dict], approval: Optional[dict], client_dir: Path, *, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    if pv is not None and pv.get("mode") == "preview" and pv.get("status") == "no_change":
        return {**pv, "mode": "apply"}
    files = [f["path"].split("/", 2)[2] for f in (pv or {}).get("source_files", [])] or ["tasks.json"]
    gate = ca.check_gate(pv, approval, client_dir, item_id=approval_item_id(pv) if pv else "", item_type=APPROVAL_ITEM_TYPE,
                         bound_files=files, recompute_preview_hash=compute_preview_hash)
    base = {**(pv or {}), "mode": "apply", "receipt": None, "applied_changes": []}
    if gate:
        notices = [{"code": "stale_preview" if g["code"] == "STALE_APPROVAL" else g["code"], "message": g["message"], "operation_id": None} for g in gate]
        return {**base, "status": "conflict" if gate[0]["code"] == "STALE_APPROVAL" else "error", "conflicts": notices}
    now = clock()
    today = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
    run = _run(client_dir, pv["client_id"], pv["mutation_plan"]["normalized_operations"], now, today)
    if run["stops"]:
        s = run["stops"][0]
        return {**base, "status": s.kind, "conflicts": [{"code": s.code, "message": str(s), "operation_id": s.op_id}]}
    after = run["after"]
    after["updated_at"] = now
    before = (client_dir / "tasks.json").read_bytes() if (client_dir / "tasks.json").is_file() else None
    data = ca.serialize_json(after)
    receipt = ca.build_action_receipt(action=ACTION, client_id=pv["client_id"], preview=pv, approval=approval, executed_at=now,
                                      status="success", effects=[ca.effect(f"clients/{pv['client_id']}/tasks.json",
                                                                           "update" if before else "create", before, data)])
    ca.atomic_multi_write(client_dir, {"tasks.json": data, f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)})
    applied = [{"operation_id": c["operation_id"], "action": c["action"], "path": c["path"], "applied_at": now}
               for c in run["changes"] if c["material"]]
    return {**base, "status": "success", "after": after, "applied_changes": applied, "receipt": receipt,
            "task_summary": _summary(after, today)}
