"""Contracts and pure validation for the canonical operations ledger.

This module deliberately has no transport or task writer.  A task is created
only by manage-task-ledger; external execution is handled by its own approved
transport.  This ledger preserves the human decision between those stages.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class OperationsLedgerError(ValueError):
    pass


TRANSITIONS = {
    "scheduled": {"completed", "cancelled", "materialized", "superseded"},
    "deferred": {"active", "cancelled", "superseded"},
    "approved": {"executed", "revoked", "superseded"},
}

TYPE_STATUSES = {
    "scheduled": {"scheduled", "completed", "cancelled", "materialized", "superseded"},
    "deferred": {"deferred", "active", "cancelled", "superseded"},
    "external_approved": {"approved", "executed", "revoked", "superseded"},
    "external_rejected": {"rejected", "superseded"},
    "decision_pending": {"pending", "active", "cancelled", "superseded"},
    "cancelled": {"cancelled"},
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def approval_is_stale(operation: dict, current_payload_hash: str | None) -> bool:
    approval = operation.get("approval") or {}
    return approval.get("status") == "approved" and current_payload_hash is not None and approval.get("payload_hash") != current_payload_hash


def external_execution_status(
    operation: dict,
    current_payload_hash: str | None = None,
    capability: dict | None = None,
) -> str:
    """Classify execution readiness without creating or invoking a transport.

    ``capability`` is an execution-time declaration supplied by the caller,
    never inferred from an approval. ``mode=real`` is required; a fake,
    dry-run, manual-export, missing, incompatible, or under-configured channel
    cannot make a real external action executable.
    """
    approval = operation.get("approval") or {}
    external = operation.get("external") or {}
    if external.get("executed"):
        return "executed"
    if approval_is_stale(operation, current_payload_hash) or approval.get("status") == "stale":
        return "approval_stale"
    if approval.get("status") != "approved":
        return "awaiting_approval"
    if not capability or capability.get("mode") != "real" or not capability.get("available"):
        return "awaiting_execution_channel"
    if not capability.get("compatible"):
        return "transport_incompatible"
    if not capability.get("requirements_satisfied"):
        return "transport_requirements_unsatisfied"
    if not capability.get("session_authorized"):
        return "awaiting_session_authorization"
    return "execution_ready"


def human_external_state(
    operation: dict,
    current_payload_hash: str | None = None,
    capability: dict | None = None,
) -> str:
    """Stable operator vocabulary for the three deliberately distinct states:
    approval, executability and actual execution.  This is a projection only.
    """
    raw = external_execution_status(operation, current_payload_hash, capability)
    mapping = {
        "awaiting_approval": "APPROVAL_REQUIRED",
        "awaiting_execution_channel": "APPROVED_WAITING_CAPABILITY",
        "execution_ready": "EXECUTION_READY",
        "executed": "EXECUTED",
        "approval_stale": "STALE",
        "transport_incompatible": "BLOCKED",
        "transport_requirements_unsatisfied": "BLOCKED",
        "awaiting_session_authorization": "BLOCKED",
    }
    if (operation.get("approval") or {}).get("status") in {"revoked", "rejected"}:
        return "REVOKED"
    return mapping[raw]


def transition(operation: dict, target_status: str, now: str, *, materialized_task_id: str | None = None) -> dict:
    current = operation["status"]
    if target_status not in TRANSITIONS.get(current, set()):
        raise OperationsLedgerError(f"invalid operation transition: {current!r} -> {target_status!r}")
    result = dict(operation)
    result["status"] = target_status
    result["updated_at"] = now
    if target_status == "materialized":
        if not materialized_task_id:
            raise OperationsLedgerError("materialized transition requires task_id")
        result["materialized_ref"] = {"task_id": materialized_task_id}
    return result


def add_operation(ledger: dict, operation: dict, now: str) -> tuple[dict, str]:
    """Pure, idempotent insertion; divergent reuse of an ID is always blocked."""
    existing = [item for item in ledger.get("operations", []) if item["operation_id"] == operation["operation_id"]]
    if existing:
        if existing[0] == operation:
            return ledger, "no_change"
        raise OperationsLedgerError(f"operation_id already exists with divergent content: {operation['operation_id']}")
    if operation.get("client_id") != ledger.get("client_id"):
        raise OperationsLedgerError("operation client_id differs from ledger")
    result = dict(ledger)
    result["operations"] = [*ledger.get("operations", []), operation]
    result["updated_at"] = now
    return result, "created"


def apply_add_operation(path: Path, operation: dict, now: str) -> str:
    """Atomically persist an explicit add operation, or return no_change on replay.

    This is intentionally only a local-ledger writer. It cannot create a task
    or invoke an external transport.
    """
    if path.is_file():
        ledger = json.loads(path.read_text(encoding="utf-8"))
    else:
        ledger = {
            "schema_version": "1.0.0", "client_id": operation["client_id"],
            "updated_at": now, "operations": [],
        }
    updated, result = add_operation(ledger, operation, now)
    if result == "no_change":
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp.write(payload)
        temp.flush()
        os.fsync(temp.fileno())
        temp_name = temp.name
    os.replace(temp_name, path)
    return result


def validate_semantics(ledger: dict, tasks: dict | None = None, receipts_dir: Path | None = None) -> list[str]:
    """Validate cross-record invariants beyond JSON Schema."""
    errors: list[str] = []
    operations = ledger.get("operations", [])
    ids = [operation.get("operation_id") for operation in operations]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        errors.append(f"duplicate operation_id(s): {duplicates}")
    task_ids = {task.get("task_id") for task in (tasks or {}).get("tasks", [])}
    for operation in operations:
        op_id = operation.get("operation_id")
        if operation.get("client_id") != ledger.get("client_id"):
            errors.append(f"{op_id}: client_id differs from ledger")
        if operation.get("status") not in TYPE_STATUSES.get(operation.get("type"), set()):
            errors.append(f"{op_id}: status is invalid for operation type")
        if operation.get("status") == "materialized":
            ref = operation.get("materialized_ref") or {}
            if ref.get("task_id") not in task_ids:
                errors.append(f"{op_id}: materialized task ref does not resolve")
        external = operation.get("external")
        approval = operation.get("approval")
        if external:
            if external.get("executed") and not operation.get("receipt_refs"):
                errors.append(f"{op_id}: external executed=true requires receipt_refs")
            if operation.get("type") == "external_approved" and approval and approval.get("status") == "approved" and not approval.get("payload_hash"):
                errors.append(f"{op_id}: approved external action requires payload_hash")
            if approval and approval.get("status") == "stale" and external.get("executed"):
                errors.append(f"{op_id}: stale approval cannot be executed")
        for ref in operation.get("receipt_refs", []):
            if receipts_dir is not None:
                receipt_path = receipts_dir / Path(ref["path"]).name
                if not receipt_path.is_file():
                    errors.append(f"{op_id}: receipt ref does not resolve: {ref['receipt_id']}")
                elif canonical_hash(json.loads(receipt_path.read_text(encoding="utf-8"))) != ref["content_sha256"]:
                    errors.append(f"{op_id}: receipt ref hash differs: {ref['receipt_id']}")
    return errors


def rebuild_operator_inbox(
    ledger: dict,
    tasks: dict | None = None,
    current_payload_hashes: dict[str, str] | None = None,
    external_capabilities: dict[str, dict] | None = None,
) -> dict:
    """Build a transient view. It never mutates the ledger or tasks."""
    current_payload_hashes = current_payload_hashes or {}
    external_capabilities = external_capabilities or {}
    inbox = {"scheduling": [], "decisions": [], "external_actions": [], "blocked": []}
    for operation in ledger.get("operations", []):
        status = operation["status"]
        op_id = operation["operation_id"]
        if status in {"cancelled", "completed", "materialized", "superseded", "executed", "revoked", "rejected"}:
            continue
        item = {"operation_id": op_id, "statement": operation["statement"], "status": status}
        if operation["type"] == "scheduled":
            item["scheduled_for"] = operation["scheduled_for"]
            inbox["scheduling"].append(item)
        elif operation["type"] == "deferred":
            item["deferred_until"] = operation["deferred_until"]
            inbox["decisions"].append(item)
        elif operation["type"] == "external_approved":
            execution_status = external_execution_status(
                operation, current_payload_hashes.get(op_id), external_capabilities.get(op_id)
            )
            item["execution_status"] = execution_status
            if execution_status == "approval_stale":
                item["reason"] = execution_status
                inbox["blocked"].append(item)
            elif execution_status != "executed":
                item["human_status"] = (
                    "APROVADA / AGUARDANDO CANAL DE EXECUÇÃO"
                    if execution_status == "awaiting_execution_channel"
                    else execution_status
                )
                inbox["external_actions"].append(item)
        elif operation["type"] == "decision_pending":
            inbox["decisions"].append(item)
    return inbox


# ---------------------------------------------------------------------------
# V1 ACTION contract (operation/action-contract.md): hash-bound preview,
# approval-gated atomic apply, receipt. Pure helpers above stay the rules.
# ---------------------------------------------------------------------------

V1_ACTION = "manage-operations-ledger"
V1_ITEM_TYPE = "operations_ledger_change"
V1_SOURCE_TYPE = "operations_ledger_preview"
V1_BOUND_FILES = ["operations.json", "tasks.json"]


def _v1_run(ledger: dict, changes: list[dict], now: str) -> tuple[dict, list[str], list[str]]:
    """Apply `changes` in memory. Returns (ledger, applied_descriptions, errors)."""
    current, applied, errors = json.loads(json.dumps(ledger)), [], []
    for i, change in enumerate(changes):
        try:
            if change.get("kind") == "add":
                current, result = add_operation(current, change["operation"], now)
                if result != "no_change":
                    applied.append(f"add:{change['operation']['operation_id']}")
            elif change.get("kind") == "transition":
                ops = [o for o in current.get("operations", []) if o["operation_id"] == change["operation_id"]]
                if len(ops) != 1:
                    raise OperationsLedgerError(f"operation {change['operation_id']!r} not found exactly once")
                if ops[0]["status"] == change["target_status"]:
                    continue
                new = transition(ops[0], change["target_status"], now, materialized_task_id=change.get("materialized_task_id"))
                current = {**current, "updated_at": now,
                           "operations": [new if o["operation_id"] == new["operation_id"] else o for o in current["operations"]]}
                applied.append(f"transition:{change['operation_id']}->{change['target_status']}")
            else:
                raise OperationsLedgerError(f"change {i}: kind must be 'add' or 'transition'")
        except (OperationsLedgerError, KeyError) as exc:
            errors.append(f"change {i}: {exc}")
    return current, applied, errors


def preview_changes(client_dir: Path, *, client_id: str, changes: list[dict], clock=None) -> dict:
    """Hash-bound preview of explicit operator changes to operations.json."""
    from scripts.lib import canonical_action as ca
    from scripts.lib.exec_clock import utc_now_rfc3339

    now = (clock or utc_now_rfc3339)()
    path = client_dir / "operations.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {
        "schema_version": "1.0.0", "client_id": client_id, "updated_at": None, "operations": []}
    after, applied, errors = _v1_run(ledger, changes, now)
    tasks_path = client_dir / "tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8")) if tasks_path.is_file() else None
    if not errors:
        errors += ca.schema_errors(after, "schemas/operations-ledger.schema.json")
        errors += validate_semantics(after, tasks, client_dir / "receipts")
    status = "error" if errors else ("no_change" if not applied else "success")
    preview = {"schema_version": "1.1.0", "skill": V1_ACTION, "client_id": client_id, "mode": "preview", "status": status,
               "generated_at": now, "changes": changes, "applied_summary": applied, "operations": after if not errors else ledger,
               "base_state_files": list(V1_BOUND_FILES), "base_state_hash": ca.state_hash(client_dir, V1_BOUND_FILES),
               "preview_hash": None, "approval_id": None, "receipt": None, "warnings": [], "errors": errors}
    preview["preview_hash"] = v1_preview_hash(preview)
    return preview


def v1_preview_hash(preview: dict) -> str:
    from scripts.lib import canonical_action as ca
    from scripts.lib.artifact_hash import content_sha256

    return content_sha256(ca.semantic({"client_id": preview["client_id"], "base_state_hash": preview["base_state_hash"],
                                       "changes": preview["changes"], "operations": preview["operations"]}))


def v1_approval_item_id(preview: dict) -> str:
    return f"operations-ledger:{preview['client_id']}"


def build_changes_approval_candidate(preview: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    from scripts.lib import canonical_action as ca

    return ca.build_approval_candidate(preview, item_id=v1_approval_item_id(preview), item_type=V1_ITEM_TYPE,
                                       source_type=V1_SOURCE_TYPE, approval_id=approval_id, created_at=created_at,
                                       preview_path=preview_path)


def apply_changes(preview: dict | None, approval: dict | None, client_dir: Path, *, clock=None) -> dict:
    """Gate -> re-run the approved changes on the (unchanged) ledger -> one
    atomic write of operations.json + receipt. Any failure: zero writes."""
    from scripts.lib import canonical_action as ca
    from scripts.lib.exec_clock import utc_now_rfc3339

    if preview is not None and preview.get("mode") == "preview" and preview.get("status") == "no_change":
        return {**preview, "mode": "apply"}
    gate = ca.check_gate(preview, approval, client_dir, item_id=v1_approval_item_id(preview) if preview else "",
                         item_type=V1_ITEM_TYPE, bound_files=V1_BOUND_FILES, recompute_preview_hash=v1_preview_hash)
    base = {**(preview or {}), "mode": "apply", "receipt": None}
    if gate:
        return {**base, "status": "error" if gate[0]["code"] in ("NO_PREVIEW", "NO_APPROVAL", "PREVIEW_NOT_HASH_BOUND") else "conflict",
                "errors": [f"{g['code']}: {g['message']}" for g in gate]}
    now = (clock or utc_now_rfc3339)()
    path = client_dir / "operations.json"
    before = path.read_bytes() if path.is_file() else None
    ledger = json.loads(before) if before else {"schema_version": "1.0.0", "client_id": preview["client_id"], "updated_at": None, "operations": []}
    after, _applied, errors = _v1_run(ledger, preview["changes"], now)
    if errors:
        return {**base, "status": "conflict", "errors": errors}
    data = ca.serialize_json(after)
    receipt = ca.build_action_receipt(action=V1_ACTION, client_id=preview["client_id"], preview=preview, approval=approval,
                                      executed_at=now, status="success",
                                      effects=[ca.effect(f"clients/{preview['client_id']}/operations.json", "update" if before else "create", before, data)])
    ca.atomic_multi_write(client_dir, {"operations.json": data, f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)})
    return {**base, "status": "success", "operations": after, "approval_id": approval["approval_id"], "receipt": receipt, "errors": []}
