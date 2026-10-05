"""Reference implementation of skills/manage-quarter/SKILL.md:
create_quarter and close_quarter, on the shared V1 ACTION contract
(scripts/lib/canonical_action.py):

    PREVIEW -> preview_hash -> approval (hash-locked) -> base-state check
            -> APPLY (atomic) -> receipt

- create_quarter writes quarters/<quarter_id>/plan.json with status
  "active" from an explicit plan input. It never reads seasonal drafts,
  never creates check-ins, monitoring or tasks, and refuses while another
  Quarter is active (there is no separate activate step: create is the
  activation, and at most one Quarter is active per client).
- close_quarter flips an active plan to "closed" and writes
  quarters/<quarter_id>/closure.json. It requires the period to have ended
  (calendar end != close), a completed current ROPRE check-in, and only
  LISTS carry_over_candidates: tasks are not completed, operations are
  not resolved, and the next Quarter is never created.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339

ACTION = "manage-quarter"
OUTPUT_SCHEMA_VERSION = "1.0.0"
APPROVAL_ITEM_TYPE = "quarter_lifecycle"
APPROVAL_SOURCE_TYPE = "quarter_lifecycle_preview"
PLAN_INPUT_KEYS = {"period", "smart_objective", "planning", "media_plan"}
OPEN_TASK_STATUSES = {"pending"}
CLOSED_OPERATION_STATUSES = {"completed", "cancelled", "materialized", "superseded", "executed", "revoked", "rejected"}
BOUND_FILES = ["client.json", "quarters/", "tasks.json", "operations.json"]


def calendar_bounds(quarter_id: str) -> tuple[date, date]:
    year, q = int(quarter_id[:4]), int(quarter_id[-1])
    start = date(year, 3 * (q - 1) + 1, 1)
    end = date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def compute_preview_hash(preview: dict) -> str:
    return content_sha256(ca.semantic({
        "client_id": preview["client_id"], "quarter_id": preview["quarter_id"], "operation": preview["operation"],
        "base_state_hash": preview["base_state_hash"], "proposed": preview["proposed"],
        "carry_over_candidates": preview["carry_over_candidates"],
    }))


def _output(client_id: str, quarter_id: str, operation: str, generated_at: str) -> dict:
    return {"schema_version": OUTPUT_SCHEMA_VERSION, "skill": ACTION, "client_id": client_id, "quarter_id": quarter_id,
            "operation": operation, "generated_at": generated_at, "mode": "preview", "status": "success",
            "base_state_files": list(BOUND_FILES), "base_state_hash": None, "preview_hash": None,
            "proposed": {"plan": None, "closure": None}, "carry_over_candidates": [], "checks": [],
            "conflicts": [], "errors": [], "warnings": [], "approval_id": None, "applied_changes": [], "receipt": None}


def _finish(out: dict, client_dir: Path) -> dict:
    if out["errors"]:
        out["status"] = "error"
    elif out["conflicts"]:
        out["status"] = "conflict"
    out["base_state_hash"] = ca.state_hash(client_dir, out["base_state_files"])
    out["preview_hash"] = compute_preview_hash(out)
    return out


def _other_active(client_dir: Path, quarter_id: str) -> list[str]:
    qdir = client_dir / "quarters"
    found = []
    for plan_path in sorted(qdir.glob("*/plan.json")) if qdir.is_dir() else []:
        plan = _load(plan_path)
        if plan.get("status") == "active" and plan.get("quarter_id") != quarter_id:
            found.append(plan["quarter_id"])
    return found


# ---------------------------------------------------------------------------
# previews
# ---------------------------------------------------------------------------


def preview_create(client_dir: Path, *, client_id: str, quarter_id: str, plan_input: dict,
                   clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    out = _output(client_id, quarter_id, "create_quarter", clock())
    client = _load(client_dir / "client.json")
    if not client or client.get("client_id") != client_id:
        out["errors"].append(ca.notice("CLIENT_NOT_FOUND", f"clients/{client_id}/client.json missing or for another client"))
        return _finish(out, client_dir)
    if not isinstance(quarter_id, str) or len(quarter_id) != 7 or quarter_id[4:6] != "-Q" or quarter_id[-1] not in "1234":
        out["errors"].append(ca.notice("INVALID_QUARTER_ID", f"{quarter_id!r} is not YYYY-QN"))
        return _finish(out, client_dir)
    extra = set(plan_input) - PLAN_INPUT_KEYS
    missing = PLAN_INPUT_KEYS - set(plan_input)
    if extra or missing:
        out["errors"].append(ca.notice("INVALID_PLAN_INPUT", f"plan input must have exactly {sorted(PLAN_INPUT_KEYS)} (extra={sorted(extra)}, missing={sorted(missing)}); status/planned_at/identity are set by this ACTION"))
        return _finish(out, client_dir)
    plan = {"schema_version": "1.0.0", "client_id": client_id, "quarter_id": quarter_id,
            "period": copy.deepcopy(plan_input["period"]), "status": "active", "planned_at": out["generated_at"],
            "smart_objective": copy.deepcopy(plan_input["smart_objective"]), "planning": copy.deepcopy(plan_input["planning"]),
            "media_plan": copy.deepcopy(plan_input["media_plan"])}
    errs = ca.schema_errors(plan, "schemas/quarter-plan.schema.json")
    if errs:
        out["errors"].append(ca.notice("INVALID_PLAN", "; ".join(errs[:5])))
        return _finish(out, client_dir)
    q_start, q_end = calendar_bounds(quarter_id)
    start, end = _d(plan["period"]["start"]), _d(plan["period"]["end"])
    checks = out["checks"]
    if not (q_start <= start <= end <= q_end):
        out["errors"].append(ca.notice("PERIOD_OUTSIDE_QUARTER", f"period {start}..{end} must lie within {quarter_id} ({q_start}..{q_end})"))
    deadline = _d(plan["smart_objective"]["deadline"])
    if not (start <= deadline <= end):
        out["errors"].append(ca.notice("SMART_DEADLINE_OUTSIDE_PERIOD", f"SMART deadline {deadline} outside period {start}..{end}"))
    months, keys = {f"{start.year:04d}-{m:02d}" for m in range(start.month, end.month + 1)}, set()
    for row in plan["media_plan"]["monthly"]:
        if row["month"] not in months:
            out["errors"].append(ca.notice("MEDIA_MONTH_OUTSIDE_PERIOD", f"media_plan month {row['month']} outside period"))
        key = (row["month"], row["channel"])
        if key in keys:
            out["errors"].append(ca.notice("DUPLICATE_MEDIA_ROW", f"duplicate media_plan row {key}"))
        keys.add(key)
    checks.append({"check": "plan_contract", "ok": not out["errors"]})
    if out["errors"]:
        return _finish(out, client_dir)
    existing = _load(client_dir / "quarters" / quarter_id / "plan.json")
    if existing is not None:
        if ca.semantic(existing) == ca.semantic(plan):
            out["status"] = "no_change"
            out["proposed"]["plan"] = existing
            out["warnings"].append(ca.notice("ALREADY_CREATED", f"{quarter_id} already exists with identical content"))
            return _finish(out, client_dir)
        out["conflicts"].append(ca.notice("QUARTER_EXISTS_DIVERGENT", f"{quarter_id} already exists with different content; never overwritten"))
        return _finish(out, client_dir)
    active = _other_active(client_dir, quarter_id)
    checks.append({"check": "no_other_active_quarter", "ok": not active})
    if active:
        out["conflicts"].append(ca.notice("ANOTHER_QUARTER_ACTIVE", f"{active} is still active; close it first (calendar end does not close a Quarter)"))
        return _finish(out, client_dir)
    out["proposed"]["plan"] = plan
    return _finish(out, client_dir)


def preview_close(client_dir: Path, *, client_id: str, quarter_id: str, as_of_date: Optional[str] = None,
                  clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    out = _output(client_id, quarter_id, "close_quarter", clock())
    today = datetime.now(timezone.utc).date()
    as_of = _d(as_of_date) if as_of_date else today
    if as_of > today:
        out["errors"].append(ca.notice("AS_OF_IN_FUTURE", f"as_of_date {as_of} is after the real date {today}"))
        return _finish(out, client_dir)
    qdir = client_dir / "quarters" / quarter_id
    plan = _load(qdir / "plan.json")
    if plan is None:
        out["errors"].append(ca.notice("QUARTER_NOT_FOUND", f"{quarter_id} has no plan.json"))
        return _finish(out, client_dir)
    errs = ca.schema_errors(plan, "schemas/quarter-plan.schema.json")
    if errs or plan.get("client_id") != client_id or plan.get("quarter_id") != quarter_id:
        out["errors"].append(ca.notice("INVALID_PLAN", "; ".join(errs[:5]) or "plan identity mismatch"))
        return _finish(out, client_dir)
    closure = _load(qdir / "closure.json")
    if plan["status"] == "closed":
        if closure is None:
            out["conflicts"].append(ca.notice("CLOSED_WITHOUT_CLOSURE", "plan is closed but closure.json is missing"))
        else:
            out["status"] = "no_change"
            out["proposed"] = {"plan": plan, "closure": closure}
            out["warnings"].append(ca.notice("ALREADY_CLOSED", f"{quarter_id} is already closed"))
        return _finish(out, client_dir)
    if plan["status"] != "active":
        out["conflicts"].append(ca.notice("QUARTER_NOT_ACTIVE", f"{quarter_id} status is {plan['status']!r}; only an active Quarter can be closed"))
        return _finish(out, client_dir)
    if closure is not None:
        out["conflicts"].append(ca.notice("CLOSURE_ALREADY_EXISTS", "closure.json exists for an active plan; never overwritten"))
    period_end = _d(plan["period"]["end"])
    out["checks"].append({"check": "period_ended", "ok": as_of > period_end})
    if as_of <= period_end:
        out["conflicts"].append(ca.notice("QUARTER_PERIOD_NOT_ENDED", f"as_of {as_of} is not after period end {period_end}"))
    monitoring = _load(qdir / "monitoring.json")
    if monitoring is not None:
        m_errs = ca.schema_errors(monitoring, "schemas/quarter-monitoring.schema.json")
        if m_errs or monitoring.get("quarter_id") != quarter_id:
            out["errors"].append(ca.notice("INVALID_MONITORING", "; ".join(m_errs[:5]) or "monitoring identity mismatch"))
    else:
        out["warnings"].append(ca.notice("NO_MONITORING", "no monitoring.json — the Quarter closes without observed results"))
    ropre = _load(qdir / "check-ins" / "current.json")
    ropre_ok = (ropre is not None and ropre.get("quarter_id") == quarter_id and ropre.get("status") == "completed"
                and not ca.schema_errors(ropre, "schemas/check-in-ropre.schema.json"))
    out["checks"].append({"check": "final_ropre_completed", "ok": ropre_ok})
    if not ropre_ok:
        out["conflicts"].append(ca.notice("ROPRE_NOT_COMPLETED", "the Quarter's current ROPRE check-in must exist and be completed (close-ropre) before closing"))
    tasks = (_load(client_dir / "tasks.json") or {}).get("tasks", [])
    ops = (_load(client_dir / "operations.json") or {}).get("operations", [])
    carry = []
    for t in tasks:
        if t.get("quarter_id") == quarter_id and t.get("status") in OPEN_TASK_STATUSES:
            due = t.get("due_at")
            carry.append({"kind": "task", "id": t["task_id"], "statement": t.get("title", ""), "status": t["status"],
                          "date": due, "overdue_as_of": bool(due) and _d(due) < as_of})
    for o in ops:
        if o.get("quarter_id") == quarter_id and o.get("status") not in CLOSED_OPERATION_STATUSES:
            when = o.get("scheduled_for")
            carry.append({"kind": "operation", "id": o["operation_id"], "statement": o.get("statement", ""), "status": o["status"],
                          "date": when, "overdue_as_of": bool(when) and _d(when) < as_of})
    out["carry_over_candidates"] = carry
    closed_plan = {**plan, "status": "closed"}
    out["proposed"] = {"plan": closed_plan, "closure": {
        "schema_version": "1.0.0", "client_id": client_id, "quarter_id": quarter_id, "period": plan["period"],
        "closed_at": None, "as_of_date": as_of.isoformat(), "ropre_check_in_id": (ropre or {}).get("check_in_id"),
        "monitoring_present": monitoring is not None, "carry_over_candidates": carry, "approval_id": None, "receipt_id": None}}
    return _finish(out, client_dir)


# ---------------------------------------------------------------------------
# approval + apply
# ---------------------------------------------------------------------------


def approval_item_id(preview: dict) -> str:
    return f"{preview['operation']}:{preview['client_id']}:{preview['quarter_id']}"


def build_quarter_approval_candidate(preview: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    return ca.build_approval_candidate(preview, item_id=approval_item_id(preview), item_type=APPROVAL_ITEM_TYPE,
                                       source_type=APPROVAL_SOURCE_TYPE, approval_id=approval_id, created_at=created_at,
                                       preview_path=preview_path, quarter_id=preview["quarter_id"])


def apply(preview: Optional[dict], approval: Optional[dict], client_dir: Path, *,
          clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Returns the preview shape with mode=apply. Any gate failure or
    invalid result -> status error/conflict with zero writes."""
    if preview is not None and preview.get("mode") == "preview" and preview.get("status") == "no_change":
        return {**preview, "mode": "apply", "applied_changes": []}
    result = {**(preview or _output("", "", "", clock())), "mode": "apply", "applied_changes": [], "receipt": None}
    gate = ca.check_gate(preview, approval, client_dir, item_id=approval_item_id(preview) if preview else "",
                         item_type=APPROVAL_ITEM_TYPE, bound_files=(preview or {}).get("base_state_files") or BOUND_FILES,
                         recompute_preview_hash=compute_preview_hash)
    if gate:
        return {**result, "status": "error" if gate[0]["code"] in ("NO_PREVIEW", "NO_APPROVAL", "PREVIEW_NOT_HASH_BOUND") else "conflict",
                "errors": gate}
    now = clock()
    problem = future_timestamp_problem(now)
    if problem:
        return {**result, "status": "error", "errors": [ca.notice("FUTURE_TIMESTAMP", problem)]}
    qrel = f"quarters/{preview['quarter_id']}"
    plan = copy.deepcopy(preview["proposed"]["plan"])
    writes: dict[str, bytes] = {}
    receipt_id = f"{ACTION}-{preview['client_id']}-{preview['preview_hash'][:12]}"
    if preview["operation"] == "create_quarter":
        plan["planned_at"] = now
    else:
        closure = {**preview["proposed"]["closure"], "closed_at": now, "approval_id": approval["approval_id"], "receipt_id": receipt_id}
        errs = ca.schema_errors(closure, "schemas/quarter-closure.schema.json")
        if errs:
            return {**result, "status": "error", "errors": [ca.notice("INVALID_RESULT", "; ".join(errs[:5]))]}
        writes[f"{qrel}/closure.json"] = ca.serialize_json(closure)
    errs = ca.schema_errors(plan, "schemas/quarter-plan.schema.json")
    if errs:
        return {**result, "status": "error", "errors": [ca.notice("INVALID_RESULT", "; ".join(errs[:5]))]}
    writes = {f"{qrel}/plan.json": ca.serialize_json(plan), **writes}
    effects = []
    for rel, data in writes.items():
        before = (client_dir / rel).read_bytes() if (client_dir / rel).is_file() else None
        effects.append(ca.effect(f"clients/{preview['client_id']}/{rel}", "update" if before else "create", before, data))
    receipt = ca.build_action_receipt(action=ACTION, client_id=preview["client_id"], preview=preview, approval=approval,
                                      executed_at=now, status="success", effects=effects)
    assert receipt["receipt_id"] == receipt_id
    writes[f"receipts/{receipt_id}.json"] = ca.serialize_json(receipt)
    ca.atomic_multi_write(client_dir, writes)
    return {**result, "status": "success", "approval_id": approval["approval_id"], "receipt": receipt,
            "applied_changes": [{"path": rel, "applied_at": now} for rel in writes if not rel.startswith("receipts/")]}
