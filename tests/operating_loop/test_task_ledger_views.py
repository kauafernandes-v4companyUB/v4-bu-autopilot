from __future__ import annotations

import json
from datetime import date

from scripts.lib.task_ledger_views import compute_overdue, partition_week, week_of

TASKS = [
    {"task_id": "t-1", "status": "pending", "due_at": "2026-04-10"},   # within week, not overdue if today<=10
    {"task_id": "t-2", "status": "completed", "due_at": "2026-04-12"},  # within week, executed
    {"task_id": "t-3", "status": "pending", "due_at": "2026-04-01"},   # before week, overdue
    {"task_id": "t-4", "status": "cancelled", "due_at": "2026-04-11"},  # within week, not executed
    {"task_id": "t-5", "status": "pending", "due_at": None},           # no due date — never overdue, never in a week
]


def test_week_of_monday_to_sunday():
    # 2026-04-08 is a Wednesday
    monday, sunday = week_of(date(2026, 4, 8))
    assert monday == date(2026, 4, 6)
    assert sunday == date(2026, 4, 12)
    assert (sunday - monday).days == 6


# AB. overdue calculated at runtime

def test_ab_overdue_is_pending_and_past_due_only():
    overdue = compute_overdue(TASKS, today=date(2026, 4, 8))
    ids = {t["task_id"] for t in overdue}
    assert ids == {"t-3"}


def test_ab_completed_task_never_overdue_even_if_due_date_passed():
    tasks = [{"task_id": "t-x", "status": "completed", "due_at": "2026-01-01"}]
    assert compute_overdue(tasks, today=date(2026, 4, 8)) == []


def test_ab_no_due_date_never_overdue():
    tasks = [{"task_id": "t-x", "status": "pending", "due_at": None}]
    assert compute_overdue(tasks, today=date(2026, 4, 8)) == []


# AA/AD. completed/pending separation, promised vs executed

def test_aa_ad_partition_week():
    monday, sunday = date(2026, 4, 6), date(2026, 4, 12)
    result = partition_week(TASKS, monday, sunday)
    promised_ids = {t["task_id"] for t in result["promised"]}
    executed_ids = {t["task_id"] for t in result["executed"]}
    not_executed_ids = {t["task_id"] for t in result["not_executed"]}
    assert promised_ids == {"t-1", "t-2", "t-4"}
    assert executed_ids == {"t-2"}
    assert not_executed_ids == {"t-1", "t-4"}


# AC. unknown execution status is never presented as completed

def test_ac_pending_task_never_in_executed_list():
    monday, sunday = date(2026, 4, 6), date(2026, 4, 12)
    result = partition_week(TASKS, monday, sunday)
    assert "t-1" not in {t["task_id"] for t in result["executed"]}


def test_task_outside_week_is_never_promised():
    monday, sunday = date(2026, 4, 6), date(2026, 4, 12)
    result = partition_week(TASKS, monday, sunday)
    assert "t-3" not in {t["task_id"] for t in result["promised"]}
    assert "t-5" not in {t["task_id"] for t in result["promised"]}


# AE. no invented carry-over — structural schema check

def test_ae_week_close_schema_never_lets_carry_forward_apply_anything(repo_root):
    schema = json.loads((repo_root / "skills" / "week-close" / "output.schema.json").read_text())
    candidate_props = set(schema["properties"]["carry_forward_candidates"]["items"]["properties"].keys())
    assert candidate_props == {"task_id", "title", "reason"}  # no due_at, no status — never an implicit apply


def test_ae_week_close_schema_has_no_apply_mode(repo_root):
    schema = json.loads((repo_root / "skills" / "week-close" / "output.schema.json").read_text())
    assert "mode" not in schema["properties"]


# AF. feeds ROPRE input — structural check

def test_af_ropre_preparation_inputs_present_in_week_close_schema(repo_root):
    schema = json.loads((repo_root / "skills" / "week-close" / "output.schema.json").read_text())
    assert "ropre_preparation_inputs" in schema["properties"]
    props = schema["properties"]["ropre_preparation_inputs"]["properties"]
    assert set(props.keys()) == {"results_candidates", "next_steps_candidates"}
