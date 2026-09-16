"""Deterministic local-vs-remote task comparison for reconcile-ekyte.

Pure, mechanical classification — never decides what to do about a
divergence (operation/task-rules.md: Task Completion Authority policy).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from scripts.lib.ekyte_transport import EkyteTransport


@dataclass(frozen=True)
class Comparison:
    task_id: str
    classification: str  # MATCHED | LOCAL_ONLY | STATUS_MISMATCH | DUE_DATE_MISMATCH | UNKNOWN
    local: Optional[dict]
    remote: Optional[dict]
    details: str


def _external_binding(task: dict) -> Optional[dict]:
    external = task.get("external")
    if external and external.get("external_id"):
        return external
    return None


def classify_task(task: dict, transport: Optional[EkyteTransport]) -> Comparison:
    binding = _external_binding(task)
    local_view = {"status": task["status"], "due_at": task["due_at"], "external_id": binding["external_id"] if binding else None}

    if binding is None:
        return Comparison(task["task_id"], "LOCAL_ONLY", local_view, None, "never published — no external binding")

    if transport is None:
        return Comparison(task["task_id"], "UNKNOWN", local_view, None, "external binding exists but no transport is available to check remote state")

    remote = transport.fetch_task(binding["external_id"])
    if remote is None:
        return Comparison(task["task_id"], "UNKNOWN", local_view, None, "local binding exists but the transport found no matching remote record — needs investigation, not the same as never published")

    remote_view = {"status": remote["status"], "due_at": remote.get("due_at")}
    status_match = _status_equivalent(local_view["status"], remote_view["status"])
    due_match = local_view["due_at"] == remote_view["due_at"]

    if status_match and due_match:
        return Comparison(task["task_id"], "MATCHED", local_view, remote_view, "local and remote agree")
    if not status_match:
        extra = "" if due_match else "; due_at also differs"
        return Comparison(task["task_id"], "STATUS_MISMATCH", local_view, remote_view, f"local status={local_view['status']!r} vs remote status={remote_view['status']!r}{extra}")
    return Comparison(task["task_id"], "DUE_DATE_MISMATCH", local_view, remote_view, f"local due_at={local_view['due_at']!r} vs remote due_at={remote_view['due_at']!r}")


def _status_equivalent(local_status: str, remote_status: str) -> bool:
    """Local vocabulary (pending/completed/cancelled) vs. whatever the
    remote transport reports (e.g. FakeEkyteTransport uses 'open'/
    'done'). Only the two known-equivalent pairs are treated as a
    match; anything else is a mismatch rather than a guessed mapping."""
    equivalences = {
        ("pending", "open"),
        ("completed", "done"),
        ("cancelled", "cancelled"),
    }
    return (local_status, remote_status) in equivalences or local_status == remote_status


def reconcile_tasks(tasks: list[dict], transport: Optional[EkyteTransport]) -> list[Comparison]:
    return [classify_task(t, transport) for t in tasks]


def summarize(comparisons: list[Comparison]) -> dict:
    summary = {"matched": 0, "local_only": 0, "remote_only": 0, "status_mismatch": 0, "due_date_mismatch": 0, "unknown": 0}
    key_by_classification = {
        "MATCHED": "matched", "LOCAL_ONLY": "local_only", "REMOTE_ONLY": "remote_only",
        "STATUS_MISMATCH": "status_mismatch", "DUE_DATE_MISMATCH": "due_date_mismatch", "UNKNOWN": "unknown",
    }
    for c in comparisons:
        summary[key_by_classification[c.classification]] += 1
    return summary
