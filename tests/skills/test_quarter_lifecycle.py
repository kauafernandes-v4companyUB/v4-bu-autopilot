"""manage-quarter: create_quarter / close_quarter on the V1 ACTION contract
(skills/manage-quarter/SKILL.md, scripts/lib/quarter_lifecycle.py).
Synthetic client only (acme-demo), temp workspace."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap
from scripts.lib import approval as ap
from scripts.lib import quarter_lifecycle as ql

CLIENT = "acme-demo"


def _q4_input(target=12):
    return {
        "period": {"start": "2026-10-01", "end": "2026-12-31"},
        "smart_objective": {"statement": f"[synthetic] {target} qualified sales by 2026-12-31.", "metric": "qualified sales",
                            "baseline": None, "target": {"value": target, "unit": "count"}, "deadline": "2026-12-31"},
        "planning": {"strategic_priorities": ["[synthetic] priority"], "assumptions": [], "evidence_ids": []},
        "media_plan": {"currency": "BRL", "monthly": [{"month": "2026-10", "channel": "meta_ads", "planned_budget": 1500.0},
                                                      {"month": "2026-11", "channel": "meta_ads", "planned_budget": 1500.0}]},
    }


def _q3_plan(status="active"):
    return {"schema_version": "1.0.0", "client_id": CLIENT, "quarter_id": "2026-Q3", "period": {"start": "2026-07-01", "end": "2026-09-30"},
            "status": status, "planned_at": "2026-07-01T12:00:00Z",
            "smart_objective": {"statement": "[synthetic] 15 sales by 2026-09-30.", "metric": "sales", "baseline": None,
                                "target": {"value": 15, "unit": "count"}, "deadline": "2026-09-30"},
            "planning": {"strategic_priorities": [], "assumptions": [], "evidence_ids": []},
            "media_plan": {"currency": "BRL", "monthly": [{"month": "2026-09", "channel": "meta_ads", "planned_budget": 2000.0}]}}


def _w(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def client_dir(temp_workspace):
    assert bootstrap(CLIENT, str(temp_workspace), "Acme Demo (synthetic)", force=False) == 0
    return temp_workspace / "clients" / CLIENT


@pytest.fixture
def q3_ready_to_close(client_dir, repo_root):
    qdir = client_dir / "quarters" / "2026-Q3"
    _w(qdir / "plan.json", _q3_plan())
    ropre = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/check-ins/demo-2026-01-20.json").read_text(encoding="utf-8"))
    ropre.update(quarter_id="2026-Q3", check_in_id="acme-ropre-2026-09-30", scheduled_for="2026-09-30", status="completed",
                 completed_at="2026-09-30T18:00:00Z")
    _w(qdir / "check-ins" / "current.json", ropre)
    _w(client_dir / "tasks.json", {"schema_version": "1.0.0", "client_id": CLIENT, "updated_at": "2026-09-20T10:00:00Z", "tasks": [
        {"task_id": "t-open-1", "client_id": CLIENT, "quarter_id": "2026-Q3", "title": "[synthetic] open task", "raised_at": "2026-09-01",
         "due_at": "2026-09-24", "status": "pending", "completed_at": None, "ekyte_url": None, "evidence_ids": [], "origin": {"type": "manual", "evidence_ids": []}},
        {"task_id": "t-done-1", "client_id": CLIENT, "quarter_id": "2026-Q3", "title": "[synthetic] done task", "raised_at": "2026-09-01",
         "due_at": "2026-09-10", "status": "completed", "completed_at": "2026-09-09T10:00:00Z", "ekyte_url": None, "evidence_ids": [], "origin": {"type": "manual", "evidence_ids": []}},
    ]})
    _w(client_dir / "operations.json", {"schema_version": "1.0.0", "client_id": CLIENT, "updated_at": "2026-09-20T10:00:00Z", "operations": [
        {"operation_id": "op-sched-1", "client_id": CLIENT, "quarter_id": "2026-Q3", "type": "scheduled", "statement": "[synthetic] scheduled op",
         "status": "scheduled", "scheduled_for": "2026-09-18"},
        {"operation_id": "op-done-1", "client_id": CLIENT, "quarter_id": "2026-Q3", "type": "scheduled", "statement": "[synthetic] done op",
         "status": "completed", "scheduled_for": "2026-09-05"},
    ]})
    return client_dir


def _approve(pv):
    c = ql.build_quarter_approval_candidate(pv, approval_id=f"appr-{pv['operation']}", created_at="2026-10-02T09:00:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-02T09:01:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[ql.approval_item_id(pv)])


def _snap(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def _create(client_dir, plan_input=None, quarter="2026-Q4"):
    return ql.preview_create(client_dir, client_id=CLIENT, quarter_id=quarter, plan_input=plan_input or _q4_input())


# A
def test_create_preview_writes_nothing_and_is_valid(client_dir, repo_root, validate):
    before = _snap(client_dir)
    pv = _create(client_dir)
    assert pv["status"] == "success" and pv["proposed"]["plan"]["status"] == "active"
    assert validate(pv, repo_root / "skills/manage-quarter/output.schema.json") == []
    assert _snap(client_dir) == before


# B
def test_approved_create_applies_with_receipt(client_dir, repo_root, validate):
    pv = _create(client_dir)
    out = ql.apply(pv, _approve(pv), client_dir, clock=lambda: "2026-10-02T09:05:00Z")
    assert out["status"] == "success"
    plan = json.loads((client_dir / "quarters/2026-Q4/plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "active" and plan["planned_at"] == "2026-10-02T09:05:00Z"
    assert validate(plan, repo_root / "schemas/quarter-plan.schema.json") == []
    assert validate(out["receipt"], repo_root / "schemas/action-receipt.schema.json") == []
    assert (client_dir / "receipts" / f"{out['receipt']['receipt_id']}.json").is_file()
    assert not (client_dir / "quarters/2026-Q4/check-ins").exists() and not (client_dir / "quarters/2026-Q4/monitoring.json").exists()
    assert validate(out, repo_root / "skills/manage-quarter/output.schema.json") == []


# C
def test_create_is_idempotent(client_dir):
    pv = _create(client_dir)
    ql.apply(pv, _approve(pv), client_dir)
    after = _snap(client_dir)
    again = _create(client_dir)
    assert again["status"] == "no_change"
    assert ql.apply(again, None, client_dir)["status"] == "no_change"
    assert ql.apply(pv, _approve(pv), client_dir)["status"] == "conflict"  # the old approval is now stale
    assert _snap(client_dir) == after


# D
@pytest.mark.parametrize("case", ["divergent_existing", "other_active", "deadline_outside", "period_outside", "media_outside", "extra_key"])
def test_conflicting_or_invalid_create_blocks(client_dir, case):
    plan_input = _q4_input()
    if case == "divergent_existing":
        pv = _create(client_dir)
        ql.apply(pv, _approve(pv), client_dir)
        plan_input = _q4_input(target=99)
    elif case == "other_active":
        _w(client_dir / "quarters/2026-Q3/plan.json", _q3_plan())
    elif case == "deadline_outside":
        plan_input["smart_objective"]["deadline"] = "2027-01-15"
    elif case == "period_outside":
        plan_input["period"]["end"] = "2027-01-31"
    elif case == "media_outside":
        plan_input["media_plan"]["monthly"].append({"month": "2026-09", "channel": "meta_ads", "planned_budget": 1.0})
    else:
        plan_input["status"] = "active"
    before = _snap(client_dir)
    pv = _create(client_dir, plan_input)
    assert pv["status"] in ("conflict", "error")
    expected = {"divergent_existing": "QUARTER_EXISTS_DIVERGENT", "other_active": "ANOTHER_QUARTER_ACTIVE",
                "deadline_outside": "SMART_DEADLINE_OUTSIDE_PERIOD", "period_outside": "PERIOD_OUTSIDE_QUARTER",
                "media_outside": "MEDIA_MONTH_OUTSIDE_PERIOD", "extra_key": "INVALID_PLAN_INPUT"}[case]
    assert expected in {n["code"] for n in pv["conflicts"] + pv["errors"]}
    with pytest.raises(ap.ApprovalError):
        _approve(pv)
    assert ql.apply(pv, None, client_dir)["status"] in ("error", "conflict")
    assert _snap(client_dir) == before


def test_unknown_client_is_an_error(temp_workspace):
    pv = ql.preview_create(temp_workspace / "clients" / "nobody", client_id="nobody", quarter_id="2026-Q4", plan_input=_q4_input())
    assert pv["status"] == "error" and pv["errors"][0]["code"] == "CLIENT_NOT_FOUND"


# E, H
def test_close_preview_writes_nothing_and_lists_carry_over(q3_ready_to_close, repo_root, validate):
    before = _snap(q3_ready_to_close)
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    assert pv["status"] == "success", pv["conflicts"] + pv["errors"]
    assert validate(pv, repo_root / "skills/manage-quarter/output.schema.json") == []
    carry = {(c["kind"], c["id"]): c for c in pv["carry_over_candidates"]}
    assert set(carry) == {("task", "t-open-1"), ("operation", "op-sched-1")}
    assert carry[("task", "t-open-1")]["overdue_as_of"] and carry[("operation", "op-sched-1")]["overdue_as_of"]
    assert _snap(q3_ready_to_close) == before


# F, I
def test_approved_close_applies_without_touching_tasks_operations_or_next_quarter(q3_ready_to_close, repo_root, validate):
    tasks_before = (q3_ready_to_close / "tasks.json").read_bytes()
    ops_before = (q3_ready_to_close / "operations.json").read_bytes()
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    out = ql.apply(pv, _approve(pv), q3_ready_to_close, clock=lambda: "2026-10-02T10:00:00Z")
    assert out["status"] == "success"
    plan = json.loads((q3_ready_to_close / "quarters/2026-Q3/plan.json").read_text(encoding="utf-8"))
    assert plan == {**_q3_plan(), "status": "closed"}
    closure = json.loads((q3_ready_to_close / "quarters/2026-Q3/closure.json").read_text(encoding="utf-8"))
    assert validate(closure, repo_root / "schemas/quarter-closure.schema.json") == []
    assert closure["closed_at"] == "2026-10-02T10:00:00Z" and closure["approval_id"] == "appr-close_quarter"
    assert closure["receipt_id"] == out["receipt"]["receipt_id"]
    assert (q3_ready_to_close / "tasks.json").read_bytes() == tasks_before
    assert (q3_ready_to_close / "operations.json").read_bytes() == ops_before
    assert sorted(p.name for p in (q3_ready_to_close / "quarters").iterdir() if p.is_dir()) == ["2026-Q3"]
    again = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    assert again["status"] == "no_change"


# G
@pytest.mark.parametrize("case", ["period_not_ended", "ropre_draft", "ropre_missing", "not_active", "missing_plan", "future_as_of"])
def test_close_requires_preconditions(q3_ready_to_close, case):
    qdir = q3_ready_to_close / "quarters/2026-Q3"
    as_of = "2026-10-02"
    if case == "period_not_ended":
        as_of = "2026-09-30"
    elif case == "ropre_draft":
        ropre = json.loads((qdir / "check-ins/current.json").read_text(encoding="utf-8"))
        ropre.update(status="draft", completed_at=None)
        _w(qdir / "check-ins/current.json", ropre)
    elif case == "ropre_missing":
        (qdir / "check-ins/current.json").unlink()
    elif case == "not_active":
        _w(qdir / "plan.json", _q3_plan(status="planned"))
    elif case == "missing_plan":
        (qdir / "plan.json").unlink()
    else:
        as_of = "2999-01-01"
    before = _snap(q3_ready_to_close)
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date=as_of)
    assert pv["status"] in ("conflict", "error")
    expected = {"period_not_ended": "QUARTER_PERIOD_NOT_ENDED", "ropre_draft": "ROPRE_NOT_COMPLETED", "ropre_missing": "ROPRE_NOT_COMPLETED",
                "not_active": "QUARTER_NOT_ACTIVE", "missing_plan": "QUARTER_NOT_FOUND", "future_as_of": "AS_OF_IN_FUTURE"}[case]
    assert expected in {n["code"] for n in pv["conflicts"] + pv["errors"]}
    assert _snap(q3_ready_to_close) == before


def test_close_is_stale_when_ledgers_change_after_preview(q3_ready_to_close):
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    approval = _approve(pv)
    tasks = json.loads((q3_ready_to_close / "tasks.json").read_text(encoding="utf-8"))
    tasks["tasks"][0]["status"] = "cancelled"
    _w(q3_ready_to_close / "tasks.json", tasks)
    before = _snap(q3_ready_to_close)
    out = ql.apply(pv, approval, q3_ready_to_close)
    assert out["status"] == "conflict" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert _snap(q3_ready_to_close) == before


def test_tampered_close_preview_is_stale(q3_ready_to_close):
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    approval = _approve(pv)
    tampered = copy.deepcopy(pv)
    tampered["carry_over_candidates"] = []
    tampered["proposed"]["closure"]["carry_over_candidates"] = []
    tampered["preview_hash"] = ql.compute_preview_hash(tampered)
    out = ql.apply(tampered, approval, q3_ready_to_close)
    assert out["status"] == "conflict" and out["errors"][0]["code"] == "STALE_APPROVAL"


def test_full_cycle_close_then_create_next(q3_ready_to_close):
    pv = ql.preview_close(q3_ready_to_close, client_id=CLIENT, quarter_id="2026-Q3", as_of_date="2026-10-02")
    assert ql.apply(pv, _approve(pv), q3_ready_to_close)["status"] == "success"
    blocked_before = _create(q3_ready_to_close)
    assert blocked_before["status"] == "success"  # Q3 is closed, so Q4 may now be created
    assert ql.apply(blocked_before, _approve(blocked_before), q3_ready_to_close)["status"] == "success"
