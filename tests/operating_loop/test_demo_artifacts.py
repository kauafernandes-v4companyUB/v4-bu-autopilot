"""Validates examples/demo-client/acme-demo/operating-loop/ — the
synthetic, versioned proof that the full operating loop (replan ->
approval -> local task -> publish preview/fake-apply -> reconcile ->
midweek -> week-close) works end to end on 100% fictitious data."""

from __future__ import annotations

import json


def _demo_dir(repo_root):
    return repo_root / "examples" / "demo-client" / "acme-demo" / "operating-loop"


def test_all_operating_loop_demo_artifacts_validate(repo_root, validate):
    base = _demo_dir(repo_root)
    checks = [
        ("operator-inbox.json", repo_root / "schemas" / "operator-inbox.schema.json"),
        ("approval.json", repo_root / "schemas" / "approval.schema.json"),
        ("task-ledger-preview.json", repo_root / "skills" / "manage-task-ledger" / "output.schema.json"),
        ("ekyte-preview.json", repo_root / "skills" / "publish-ekyte" / "output.schema.json"),
        ("ekyte-apply-fake.json", repo_root / "skills" / "publish-ekyte" / "output.schema.json"),
        ("reconciliation.json", repo_root / "skills" / "reconcile-ekyte" / "output.schema.json"),
        ("midweek-preview.json", repo_root / "skills" / "midweek" / "output.schema.json"),
        ("week-close-preview.json", repo_root / "skills" / "week-close" / "output.schema.json"),
        ("workflow-report.json", repo_root / "schemas" / "workflow-report.schema.json"),
    ]
    for name, schema_path in checks:
        instance = json.loads((base / name).read_text(encoding="utf-8"))
        errors = validate(instance, schema_path)
        assert not errors, f"{name}: " + "\n".join(errors)


def test_demo_apply_used_fake_transport_only(repo_root):
    data = json.loads((_demo_dir(repo_root) / "ekyte-apply-fake.json").read_text(encoding="utf-8"))
    assert "fake-ekyte.local" in data["remote_result"]["url"]
    assert any("FakeEkyteTransport" in w for w in data["warnings"])


def test_demo_approval_is_hash_locked_to_task_proposals(repo_root):
    tp = json.loads((repo_root / "examples/demo-client/acme-demo/intelligence/task-proposals.json").read_text())
    approval = json.loads((_demo_dir(repo_root) / "approval.json").read_text())
    from scripts.lib.artifact_hash import content_sha256
    assert approval["source_artifact"]["artifact_hash"] == content_sha256(tp)


def test_demo_task_id_matches_deterministic_identity(repo_root):
    from scripts.lib.task_identity import compute_task_id
    tp = json.loads((repo_root / "examples/demo-client/acme-demo/intelligence/task-proposals.json").read_text())
    ready = next(t for t in tp["task_proposals"] if t["readiness"] == "ready")
    expected = compute_task_id("acme-demo", "2026-Q1", ready["action_id"])
    assert ready["manage_task_operation"]["task_id"] == expected

    tasks = json.loads((repo_root / "examples/demo-client/acme-demo/tasks.json").read_text())
    assert any(t["task_id"] == expected for t in tasks["tasks"])


def test_demo_task_preview_is_a_real_first_materialization(repo_root):
    base = _demo_dir(repo_root)
    preview = json.loads((base / "task-ledger-preview.json").read_text())
    tasks = json.loads((repo_root / "examples/demo-client/acme-demo/tasks.json").read_text())
    proposed = preview["operations"][0]
    materialized = next(t for t in tasks["tasks"] if t["task_id"] == proposed["task_id"])

    assert preview["status"] == "success"
    assert preview["mutation_plan"]["will_write"] is True
    assert preview["mutation_plan"]["changes"][0]["action"] == "create_task"
    assert preview["before"]["tasks"] != preview["after"]["tasks"]
    for field in ("task_id", "quarter_id", "title", "description", "raised_at", "due_at", "origin", "evidence_ids"):
        assert materialized[field] == proposed[field]


def test_demo_never_mentions_walmaq_or_real_data(repo_root):
    base = _demo_dir(repo_root)
    for f in base.glob("*.json"):
        text = f.read_text(encoding="utf-8").lower()
        assert "walmaq" not in text, f
