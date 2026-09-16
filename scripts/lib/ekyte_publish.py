"""Reference logic backing skills/publish-ekyte/SKILL.md — payload
mapping, blocker detection, and the preview/apply decision tree. Pure
functions; the actual remote call (when a transport exists) goes
through scripts/lib/ekyte_transport.py, and the actual canonical write
(link_ekyte) is always a separate manage-task-ledger operation this
module only *proposes*, never applies.
"""

from __future__ import annotations

from typing import Optional

from scripts.lib import approval as ap
from scripts.lib.ekyte_transport import EkyteTaskConflict, EkyteTransport

_LOCAL_TO_REMOTE_STATUS = {"pending": "open", "completed": "done", "cancelled": "cancelled"}

MAPPED_FIELDS = {"title", "description", "due_at"}
KNOWN_LOCAL_FIELDS = {
    "task_id", "client_id", "quarter_id", "title", "description", "raised_at", "due_at",
    "status", "completed_at", "ekyte_url", "external", "evidence_ids", "origin",
}


def build_payload(task: dict) -> dict:
    omitted = sorted(KNOWN_LOCAL_FIELDS - MAPPED_FIELDS - {"task_id", "client_id", "quarter_id", "status", "completed_at", "ekyte_url", "external", "raised_at"})
    return {
        "title": task["title"],
        "description": task["description"],
        "due_at": task["due_at"],
        "omitted_fields": omitted,
    }


class PublishBlocked(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def preview_publication(task: dict, capability: str, approval: Optional[dict] = None, current_source_artifact: Optional[dict] = None, current_items_by_id: Optional[dict] = None) -> dict:
    payload = build_payload(task)
    approval_valid = None
    if approval is not None and current_source_artifact is not None and current_items_by_id is not None:
        checks = ap.validate_approval(approval, current_source_artifact, current_items_by_id)
        approval_valid = all(c.ok for c in checks)
    return {
        "capability": capability,
        "local_task": {
            "task_id": task["task_id"], "title": task["title"], "description": task["description"],
            "due_at": task["due_at"], "status": task["status"], "existing_external": task.get("external"),
        },
        "payload": payload,
        "approval_valid": approval_valid,
        "remote_result": None,
        "link_ekyte_operation": None,
    }


def apply_publication(
    *,
    task: dict,
    approval: dict,
    approval_item_id: str,
    current_source_artifact: dict,
    current_items_by_id: dict,
    capability: str,
    transport: Optional[EkyteTransport],
    now: str,
) -> dict:
    """Returns a dict with: status (success|no_change|failed),
    publication_mode, remote_result, link_ekyte_operation, blockers."""
    if task["status"] != "pending":
        raise PublishBlocked("TASK_NOT_PENDING", f"task {task['task_id']} has status={task['status']!r}")

    # R/C: approval must be fresh for exactly this item.
    fresh_ids = ap.require_fresh_approved_items(approval, current_source_artifact, current_items_by_id)
    if approval_item_id not in fresh_ids:
        raise PublishBlocked("NO_APPROVAL", f"approval does not cover item {approval_item_id!r}")

    payload = build_payload(task)
    existing = task.get("external")

    # U: idempotent replay — already bound, never publish twice.
    if existing and existing.get("external_id"):
        if transport is not None:
            remote = transport.fetch_task(existing["external_id"])
            if remote is not None and remote["title"] != payload["title"]:
                raise PublishBlocked("EXISTING_EXTERNAL_BINDING_CONFLICT", f"local binding {existing['external_id']} points to a remote task with a different title")
        return {
            "status": "no_change", "publication_mode": "programmatic" if transport else "manual_export",
            "remote_result": {"external_id": existing["external_id"], "url": existing["url"], "status": "already_bound"},
            "link_ekyte_operation": None, "blockers": [],
        }

    # S: no transport -> manual export packet, never claims remote success.
    if transport is None:
        return {
            "status": "success", "publication_mode": "manual_export",
            "remote_result": None, "link_ekyte_operation": None, "blockers": [],
        }

    # T: real (fake) transport create.
    try:
        remote = transport.create_task(payload)
    except EkyteTaskConflict as e:
        raise PublishBlocked("EXISTING_EXTERNAL_BINDING_CONFLICT", str(e))

    link_operation = {
        "operation_id": f"link-{task['task_id']}",
        "type": "link_ekyte",
        "task_id": task["task_id"],
        "ekyte_url": remote["url"],
        "external": {
            "system": "ekyte", "external_id": remote["external_id"], "url": remote["url"],
            "published_at": now, "last_verified_at": now,
        },
    }
    return {
        "status": "success", "publication_mode": "programmatic",
        "remote_result": {"external_id": remote["external_id"], "url": remote["url"], "status": remote["status"]},
        "link_ekyte_operation": link_operation, "blockers": [],
    }
