from __future__ import annotations

import json

from jsonschema import Draft202012Validator


def test_all_operating_loop_schemas_valid_draft_2020_12(repo_root):
    files = [
        repo_root / "schemas" / "workflow-registry.schema.json",
        repo_root / "schemas" / "approval.schema.json",
        repo_root / "schemas" / "action-receipt.schema.json",
        repo_root / "schemas" / "operator-inbox.schema.json",
        repo_root / "schemas" / "workflow-report.schema.json",
        repo_root / "skills" / "publish-ekyte" / "output.schema.json",
        repo_root / "skills" / "reconcile-ekyte" / "output.schema.json",
        repo_root / "skills" / "midweek" / "output.schema.json",
        repo_root / "skills" / "week-close" / "output.schema.json",
    ]
    for f in files:
        assert f.is_file(), f
        Draft202012Validator.check_schema(json.loads(f.read_text(encoding="utf-8")))


def test_workflows_registry_validates(repo_root, validate):
    data = json.loads((repo_root / "workflows" / "registry.json").read_text(encoding="utf-8"))
    errors = validate(data, repo_root / "schemas" / "workflow-registry.schema.json")
    assert not errors, "\n".join(errors)


def test_workflows_registry_steps_resolve_in_skills_registry(repo_root):
    workflows = json.loads((repo_root / "workflows" / "registry.json").read_text(encoding="utf-8"))["workflows"]
    skills = json.loads((repo_root / "skills" / "registry.json").read_text(encoding="utf-8"))["skills"]
    known = {s["id"] for s in skills}
    implemented = {s["id"] for s in skills if s["implemented"]}
    for wf in workflows:
        unknown = set(wf["steps"]) - known
        assert not unknown, f"{wf['workflow_id']}: unknown steps {unknown}"
        if wf["status"] == "implemented":
            missing = set(wf["steps"]) - implemented
            assert not missing, f"{wf['workflow_id']} is implemented but references non-implemented skills: {missing}"


def test_replan_client_workflow_lists_the_real_seven_step_chain(repo_root):
    workflows = json.loads((repo_root / "workflows" / "registry.json").read_text(encoding="utf-8"))["workflows"]
    replan = next(w for w in workflows if w["workflow_id"] == "replan-client")
    assert replan["steps"] == [
        "build-context-pack", "diagnose-client", "calculate-gap",
        "identify-priorities", "replan-client", "audit-plan", "generate-tasks",
    ]


def test_publish_ekyte_workflow_is_honest_about_capability(repo_root):
    workflows = json.loads((repo_root / "workflows" / "registry.json").read_text(encoding="utf-8"))["workflows"]
    publish = next(w for w in workflows if w["workflow_id"] == "publish-ekyte")
    assert publish["approval_gate"]["required"] is True
    assert "EXTERNAL" in publish["side_effects"]


def test_no_workflow_has_approval_gate_required_false_with_external_side_effect(repo_root):
    workflows = json.loads((repo_root / "workflows" / "registry.json").read_text(encoding="utf-8"))["workflows"]
    for wf in workflows:
        if "EXTERNAL" in wf["side_effects"] or "TASK_LEDGER" in wf["side_effects"] or "ROPRE_CHECK_IN" in wf["side_effects"]:
            assert wf["approval_gate"]["required"] is True, f"{wf['workflow_id']} has a material side effect but no approval gate"
