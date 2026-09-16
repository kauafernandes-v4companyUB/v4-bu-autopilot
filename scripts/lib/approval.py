"""Approval model helpers (schemas/approval.schema.json,
operation/task-rules.md, operation/replanning-rules.md).

Core rule: an approval is hash-locked to the exact payload it approves.
If the source artifact (e.g. task-proposals.json) changes after an
approval is created, the approval is STALE for any item whose payload no
longer matches — and no material ACTION may consume a stale approval.

No function here ever sets status to "approved"/"partially_approved" on
its own — that requires an explicit operator request, applied by
whoever calls create_approval_record with approved_at/approved_by
supplied. build_approval_candidate (status="draft") is the only thing a
skill may produce unattended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from scripts.lib.artifact_hash import content_sha256


class ApprovalError(Exception):
    pass


class StaleApproval(ApprovalError):
    """Raised when an approval's hash-lock no longer matches the current
    source artifact or item payload."""


def compute_payload_hash(item_payload: dict) -> str:
    return content_sha256(item_payload)


def build_approval_candidate(
    *,
    approval_id: str,
    client_id: str,
    quarter_id: Optional[str],
    created_at: str,
    source_artifact_type: str,
    source_artifact_id: str,
    source_artifact: dict,
    source_artifact_path: str,
    candidate_items: list[dict],
) -> dict:
    """Build a status="draft" approval candidate — never approved by
    this function. `candidate_items` is a list of {item_id, item_type,
    payload} the operator can choose to approve/reject/defer; this
    candidate proposes them all as approved_items with conditions=[] so
    the operator can edit the record (or a follow-up call to
    apply_operator_decision) before it becomes real.
    """
    approved_items = [
        {
            "item_id": item["item_id"],
            "item_type": item["item_type"],
            "approved_payload_hash": compute_payload_hash(item["payload"]),
            "conditions": [],
            "notes": None,
        }
        for item in candidate_items
    ]
    return {
        "schema_version": "1.0.0",
        "approval_id": approval_id,
        "client_id": client_id,
        "quarter_id": quarter_id,
        "created_at": created_at,
        "approved_at": None,
        "approved_by": None,
        "source_artifact": {
            "type": source_artifact_type,
            "artifact_id": source_artifact_id,
            "artifact_hash": content_sha256(source_artifact),
            "path": source_artifact_path,
        },
        "scope": {"approved_items": approved_items, "rejected_items": [], "deferred_items": []},
        "status": "draft",
        "superseded_by": None,
        "notes": None,
    }


def apply_operator_decision(
    candidate: dict,
    *,
    approved_at: str,
    approved_by: str,
    approve_item_ids: list[str],
    reject_item_ids: Optional[list[str]] = None,
    defer_item_ids: Optional[list[str]] = None,
) -> dict:
    """Turn a draft candidate into a real approval record, reflecting an
    explicit operator decision. This is the ONLY path that ever produces
    status in {approved, partially_approved, rejected} — always requires
    approved_by/approved_at supplied by the caller from a real operator
    request, never defaulted or inferred."""
    if candidate["status"] != "draft":
        raise ApprovalError(f"can only decide on a draft candidate, got status={candidate['status']!r}")
    if not approved_by:
        raise ApprovalError("approved_by is required and must come from a real operator identifier — never inferred")

    reject_item_ids = set(reject_item_ids or [])
    defer_item_ids = set(defer_item_ids or [])
    approve_item_ids = set(approve_item_ids)

    all_items = {i["item_id"]: i for i in candidate["scope"]["approved_items"]}
    unknown = (approve_item_ids | reject_item_ids | defer_item_ids) - set(all_items)
    if unknown:
        raise ApprovalError(f"unknown item_id(s) not present in candidate: {sorted(unknown)}")
    overlap = (approve_item_ids & reject_item_ids) | (approve_item_ids & defer_item_ids) | (reject_item_ids & defer_item_ids)
    if overlap:
        raise ApprovalError(f"item_id(s) assigned to more than one decision bucket: {sorted(overlap)}")

    approved = [all_items[i] for i in approve_item_ids]
    rejected = [{"item_id": i, "item_type": all_items[i]["item_type"], "notes": None} for i in reject_item_ids]
    deferred = [{"item_id": i, "item_type": all_items[i]["item_type"], "notes": None} for i in defer_item_ids]

    total = len(all_items)
    if len(approved) == 0:
        status = "rejected" if len(rejected) == total else "draft"
    elif len(approved) == total:
        status = "approved"
    else:
        status = "partially_approved"

    return {
        **candidate,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "scope": {"approved_items": approved, "rejected_items": rejected, "deferred_items": deferred},
        "status": status,
    }


@dataclass(frozen=True)
class ApprovalItemCheck:
    item_id: str
    ok: bool
    reason: str


def validate_approval(approval: dict, current_source_artifact: dict, current_items_by_id: dict[str, dict]) -> list[ApprovalItemCheck]:
    """Validate an approval against the CURRENT state of its source
    artifact and items. Returns one check per approved_item.

    An item is stale if either:
      - the source artifact's current content_sha256 no longer matches
        approval.source_artifact.artifact_hash, OR
      - the specific item's current payload hash no longer matches
        approved_payload_hash.
    """
    if approval["status"] not in ("approved", "partially_approved", "consumed"):
        return [
            ApprovalItemCheck(item["item_id"], False, f"approval status is {approval['status']!r}, not approved")
            for item in approval["scope"]["approved_items"]
        ]

    source_hash_now = content_sha256(current_source_artifact)
    source_ok = source_hash_now == approval["source_artifact"]["artifact_hash"]

    checks = []
    for item in approval["scope"]["approved_items"]:
        if not source_ok:
            checks.append(ApprovalItemCheck(item["item_id"], False, "STALE_APPROVAL: source artifact changed since approval"))
            continue
        current_item = current_items_by_id.get(item["item_id"])
        if current_item is None:
            checks.append(ApprovalItemCheck(item["item_id"], False, "STALE_APPROVAL: approved item no longer exists in source artifact"))
            continue
        current_hash = compute_payload_hash(current_item)
        if current_hash != item["approved_payload_hash"]:
            checks.append(ApprovalItemCheck(item["item_id"], False, "STALE_APPROVAL: item payload changed since approval"))
            continue
        checks.append(ApprovalItemCheck(item["item_id"], True, "matches approved payload"))
    return checks


def require_fresh_approved_items(approval: dict, current_source_artifact: dict, current_items_by_id: dict[str, dict]) -> list[str]:
    """Convenience: returns the list of item_ids that are validly
    approved and fresh. Raises StaleApproval if ANY approved item is
    stale — an operating-loop caller decides whether to proceed with a
    reduced set explicitly, this function never silently drops items."""
    checks = validate_approval(approval, current_source_artifact, current_items_by_id)
    stale = [c for c in checks if not c.ok]
    if stale:
        raise StaleApproval("; ".join(f"{c.item_id}: {c.reason}" for c in stale))
    return [c.item_id for c in checks]
