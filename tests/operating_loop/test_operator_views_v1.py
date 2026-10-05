"""Operator UX views (derived, read-only) and route/registry consistency.
Synthetic records only."""

import json
from datetime import date

import pytest

from scripts import doctor
from scripts.lib.operator_router import _ROUTES, route_command
from scripts.lib.operator_views import daily_view, operator_brief

TODAY = date(2026, 10, 5)


def _op(op_id, status, kind="scheduled", when=None, approval=None, external=None):
    return {"operation_id": op_id, "statement": f"[synthetic] {op_id}", "status": status, "type": kind,
            "scheduled_for": when, "deferred_until": {"type": "after_task", "reference_id": "t-x", "description": "after"} if kind == "deferred" else None,
            "approval": approval, "external": external}


OPS = {"operations": [
    _op("s-past", "scheduled", when="2026-09-18"),
    _op("s-today", "scheduled", when="2026-10-05"),
    _op("s-future", "scheduled", when="2026-10-20"),
    _op("s-done", "completed", when="2026-09-01"),
    _op("d-1", "deferred", kind="deferred"),
    _op("e-wait", "approved", kind="external_approved", approval={"status": "approved", "payload_hash": "a" * 64},
        external={"system": "meta_ads", "executed": False}),
    _op("e-done", "executed", kind="external_approved", approval={"status": "approved", "payload_hash": "b" * 64},
        external={"system": "meta_ads", "executed": True}),
    _op("e-revoked", "revoked", kind="external_approved", approval={"status": "revoked", "payload_hash": "c" * 64},
        external={"system": "ekyte", "executed": False}),
]}


# R, S
def test_scheduled_operations_overdue_is_derived_and_future_is_not_overdue():
    before = json.dumps(OPS, sort_keys=True)
    view = daily_view({"tasks": []}, OPS, TODAY)
    assert [o["operation_id"] for o in view["OPERATIONS_OVERDUE"]] == ["s-past"]
    assert view["OPERATIONS_OVERDUE"][0]["derived_state"] == "OVERDUE" and view["OPERATIONS_OVERDUE"][0]["status"] == "scheduled"
    scheduled = {o["operation_id"]: o["derived_state"] for o in view["OPERATIONS_SCHEDULED"]}
    assert scheduled == {"s-today": "TODAY", "s-future": "SCHEDULED"}
    assert "s-done" not in {o["operation_id"] for k in view for o in view[k] if isinstance(o, dict) and "operation_id" in o}
    assert [o["operation_id"] for o in view["DEFERRED"]] == ["d-1"]
    assert json.dumps(OPS, sort_keys=True) == before  # never rewrites the ledger


def test_external_review_states_never_execute():
    review = {o["operation_id"]: o["external_state"] for o in daily_view({"tasks": []}, OPS, TODAY)["EXTERNAL_REVIEW"]}
    assert review == {"e-wait": "APPROVED_WAITING_CAPABILITY", "e-done": "EXECUTED", "e-revoked": "REVOKED"}


def test_operator_brief_surfaces_overdue_operations_and_external_review(tmp_path):
    (tmp_path / "tasks.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    (tmp_path / "operations.json").write_text(json.dumps(OPS), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    brief = operator_brief("acme-demo", tmp_path, TODAY)
    assert [o["operation_id"] for o in brief["overdue_operations"]] == ["s-past"]
    assert "s-past" in {o.get("operation_id") for o in brief["priorities"]}
    assert "s-future" not in {o.get("operation_id") for o in brief["priorities"]}
    assert {o["operation_id"] for o in brief["external_action_review"]} == {"e-wait", "e-done", "e-revoked"}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


# T
def test_no_dangling_operator_route(repo_root):
    workflows = {w["workflow_id"] for w in json.loads((repo_root / "workflows/registry.json").read_text(encoding="utf-8"))["workflows"]}
    skills = {s["id"] for s in json.loads((repo_root / "skills/registry.json").read_text(encoding="utf-8"))["skills"] if s["implemented"]}
    assert all(target in workflows | skills for _, target, *_ in _ROUTES)
    review = route_command("quais ações externas estão aprovadas da acme?", "acme-demo")
    assert review["workflow"] == "operator-brief" and not review["mutation_allowed"] and not review["approval_required"]
    assert route_command("feche o quarter 2026-Q3 da acme", "acme-demo")["workflow"] == "close-quarter"
    assert route_command("feche a semana da acme", "acme-demo")["workflow"] == "week-close"


# U, V, W
def test_registries_consistent_and_doctor_detects_dangling_route(monkeypatch):
    status, problems = doctor.check_workflow_registry(doctor._schema_registry())
    assert status == "PASS", problems
    status, problems = doctor.check_skill_registry(doctor._schema_registry())
    assert status == "PASS", problems
    import scripts.lib.operator_router as router
    monkeypatch.setattr(router, "_ROUTES", router._ROUTES + (("ghost", "ghost-workflow", (r"ghost",), False, False),))
    status, problems = doctor.check_workflow_registry(doctor._schema_registry())
    assert status == "FAIL" and any("ghost-workflow" in p for p in problems)


def test_new_canonical_actions_are_registered(repo_root):
    skills = {s["id"]: s for s in json.loads((repo_root / "skills/registry.json").read_text(encoding="utf-8"))["skills"]}
    assert skills["manage-quarter"]["category"] == "ACTION" and skills["manage-quarter"]["implemented"]
    assert skills["promote-client-memory"]["version"] == "1.1.0"
    workflows = {w["workflow_id"]: w for w in json.loads((repo_root / "workflows/registry.json").read_text(encoding="utf-8"))["workflows"]}
    for wf in ("create-quarter", "close-quarter"):
        assert workflows[wf]["approval_gate"]["required"] and workflows[wf]["side_effects"] == ["QUARTER_PLAN"]


def test_midweek_surfaces_overdue_scheduled_operations(repo_root, validate):
    from scripts.lib.operator_views import build_midweek
    before = json.dumps(OPS, sort_keys=True)
    mw = build_midweek("acme-demo", {"tasks": []}, OPS, TODAY, quarter_id="2026-Q4")
    assert [o["operation_id"] for o in mw["operations_needing_attention"]] == ["s-past"]
    assert validate(mw, repo_root / "skills/midweek/output.schema.json") == []
    assert json.dumps(OPS, sort_keys=True) == before
