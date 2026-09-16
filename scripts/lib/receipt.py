"""Build action receipts (schemas/action-receipt.schema.json) for the
operating loop. A receipt documents what a real ACTION apply did; it is
never itself canonical state.
"""

from __future__ import annotations

from typing import Optional

from scripts.lib.artifact_hash import content_sha256


def build_receipt(
    *,
    receipt_id: str,
    action: str,
    client_id: str,
    executed_at: str,
    input_payload: dict,
    approval_id: Optional[str],
    status: str,
    effects: Optional[list[dict]] = None,
    warnings: Optional[list[str]] = None,
    errors: Optional[list[str]] = None,
) -> dict:
    if status not in ("success", "partial", "no_change", "failed"):
        raise ValueError(f"invalid status: {status!r}")
    return {
        "schema_version": "1.0.0",
        "receipt_id": receipt_id,
        "action": action,
        "client_id": client_id,
        "executed_at": executed_at,
        "input_hash": content_sha256(input_payload),
        "approval_id": approval_id,
        "status": status,
        "effects": effects or [],
        "warnings": warnings or [],
        "errors": errors or [],
    }


def build_effect(
    *,
    target: str,
    operation: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    external_id: Optional[str] = None,
    external_url: Optional[str] = None,
) -> dict:
    return {
        "target": target,
        "operation": operation,
        "before_hash": content_sha256(before) if before is not None else None,
        "after_hash": content_sha256(after) if after is not None else None,
        "external_id": external_id,
        "external_url": external_url,
    }
