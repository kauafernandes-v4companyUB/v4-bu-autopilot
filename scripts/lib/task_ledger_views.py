"""Deterministic, read-only views over a task ledger for midweek/
week-close (operation/task-rules.md: overdue is always derived, never
persisted). No reasoning here — just date arithmetic and partitioning.
"""

from __future__ import annotations

from datetime import date, timedelta


def week_of(today: date) -> tuple[date, date]:
    """ISO week (Monday-Sunday) containing `today`."""
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def compute_overdue(tasks: list[dict], today: date) -> list[dict]:
    return [t for t in tasks if t["status"] == "pending" and t["due_at"] is not None and date.fromisoformat(t["due_at"]) < today]


def in_week(due_at: str | None, week_from: date, week_to: date) -> bool:
    if due_at is None:
        return False
    d = date.fromisoformat(due_at)
    return week_from <= d <= week_to


def partition_week(tasks: list[dict], week_from: date, week_to: date) -> dict[str, list[dict]]:
    """promised = due_at inside the week. executed = promised AND
    status=completed. not_executed = promised AND status in
    (pending, cancelled) by the end of the week."""
    promised = [t for t in tasks if in_week(t["due_at"], week_from, week_to)]
    executed = [t for t in promised if t["status"] == "completed"]
    not_executed = [t for t in promised if t["status"] in ("pending", "cancelled")]
    return {"promised": promised, "executed": executed, "not_executed": not_executed}
