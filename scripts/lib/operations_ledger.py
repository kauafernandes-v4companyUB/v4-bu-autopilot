"""Contracts and pure validation for the canonical operations ledger.

This module deliberately has no transport or task writer.  A task is created
only by manage-task-ledger; external execution is handled by its own approved
transport.  This ledger preserves the human decision between those stages.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


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


def rebuild_operator_inbox(ledger: dict, tasks: dict | None = None, current_payload_hashes: dict[str, str] | None = None) -> dict:
    """Build a transient view. It never mutates the ledger or tasks."""
    current_payload_hashes = current_payload_hashes or {}
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
            if approval_is_stale(operation, current_payload_hashes.get(op_id)) or (operation.get("approval") or {}).get("status") == "stale":
                item["reason"] = "approval_stale"
                inbox["blocked"].append(item)
            elif (operation.get("approval") or {}).get("status") == "approved" and not (operation.get("external") or {}).get("executed"):
                inbox["external_actions"].append(item)
        elif operation["type"] == "decision_pending":
            inbox["decisions"].append(item)
    return inbox
