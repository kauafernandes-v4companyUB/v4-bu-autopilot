"""Bridge between approved task_proposals (skills/generate-tasks) and
manage-task-ledger operations (workflow apply-approved-tasks,
operation/task-rules.md).

This module NEVER writes clients/<client_id>/tasks.json — it only
builds the `create_task` operations that manage-task-ledger's own
preview/apply contract consumes. That contract (hashing, atomicity,
duplicate_task_id protection) is untouched and remains the sole writer.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.lib.task_identity import compute_task_id


class TaskBridgeError(Exception):
    pass


@dataclass(frozen=True)
class BridgeResult:
    operations: list[dict]
    skipped: list[dict]  # [{proposal_id, reason}]


def _canonical_task_matches_operation(client_id: str, task: dict, operation: dict) -> bool:
    """Compare the immutable create-task content only.

    The ledger adds lifecycle and external-binding fields after creation;
    those must not make a replay look like a divergent proposal.
    """
    fields = (
        "task_id", "quarter_id", "title", "description", "raised_at",
        "due_at", "origin", "evidence_ids",
    )
    return task.get("client_id") == client_id and all(task.get(field) == operation.get(field) for field in fields)


def build_create_task_operations(
    client_id: str,
    quarter_id: str,
    task_proposals: dict,
    approved_proposal_ids: list[str],
    existing_tasks: list[dict] | None = None,
) -> BridgeResult:
    """Only readiness="ready" proposals among approved_proposal_ids ever
    become a create_task operation (mission section 8 — READY is the
    only readiness that may auto-convert after approval). Anything else
    approved-but-not-ready is skipped with a reason, never silently
    forced into a task.
    """
    by_id = {tp["proposal_id"]: tp for tp in task_proposals["task_proposals"]}
    unknown = set(approved_proposal_ids) - set(by_id)
    if unknown:
        raise TaskBridgeError(f"approved proposal_id(s) not found in task_proposals: {sorted(unknown)}")

    operations: list[dict] = []
    skipped: list[dict] = []
    existing_by_id = {task["task_id"]: task for task in (existing_tasks or [])}

    for proposal_id in approved_proposal_ids:
        tp = by_id[proposal_id]
        if tp["readiness"] != "ready":
            skipped.append({"proposal_id": proposal_id, "reason": f"readiness={tp['readiness']!r}, only 'ready' may auto-convert after approval"})
            continue
        op = tp.get("manage_task_operation")
        if op is None:
            skipped.append({"proposal_id": proposal_id, "reason": "readiness=ready but manage_task_operation is null (contract violation upstream)"})
            continue

        expected_task_id = compute_task_id(client_id, quarter_id, tp["action_id"])
        if op["task_id"] != expected_task_id:
            raise TaskBridgeError(
                f"proposal {proposal_id}: manage_task_operation.task_id={op['task_id']!r} does not match the "
                f"deterministic identity {expected_task_id!r} for (client_id={client_id!r}, quarter_id={quarter_id!r}, "
                f"action_id={tp['action_id']!r}) — generate-tasks must derive task_id via scripts/lib/task_identity.py"
            )
        if "responsible" in op or "owner" in op:
            raise TaskBridgeError(f"proposal {proposal_id}: manage_task_operation must never carry responsible/owner")

        existing = existing_by_id.get(op["task_id"])
        if existing is not None:
            if _canonical_task_matches_operation(client_id, existing, op):
                skipped.append({"proposal_id": proposal_id, "reason": "task already materialized with identical canonical content"})
                continue
            raise TaskBridgeError(
                f"proposal {proposal_id}: task_id={op['task_id']!r} already exists with divergent canonical content; "
                "never overwrite an existing task through a replay"
            )

        operations.append(op)

    return BridgeResult(operations=operations, skipped=skipped)
