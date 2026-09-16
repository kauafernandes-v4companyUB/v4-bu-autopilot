"""End-to-end synthetic chain: task_proposals -> approval -> task_bridge
-> (simulated) manage-task-ledger apply, on a temp workspace only.

The "simulated apply" here is a deliberately tiny local stand-in for
manage-task-ledger's own contract (append-if-new, no_change if
identical task_id+content already present) — manage-task-ledger itself
is a SKILL.md executed by Claude/Codex, not Python code, so it cannot
literally be invoked from pytest. This test exists to prove the
approval -> bridge chain produces exactly the operation
manage-task-ledger's real contract expects, and that the whole chain
behaves idempotently end to end (mission AG-AK).
"""

from __future__ import annotations

import copy
import json

from scripts.lib import approval as ap
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.task_bridge import build_create_task_operations
from scripts.lib.workspace import Workspace

CLIENT_ID = "synthtest-loop"
QUARTER_ID = "2026-Q2"


def _simulate_manage_task_ledger_apply(tasks_ledger: dict, operation: dict) -> tuple[dict, str]:
    """Minimal stand-in for manage-task-ledger create_task: append if the
    task_id is new; no_change (untouched) if an identical task already
    exists; never a second entry for the same task_id."""
    existing = next((t for t in tasks_ledger["tasks"] if t["task_id"] == operation["task_id"]), None)
    new_task = {
        **operation,
        "client_id": CLIENT_ID,
        "status": "pending",
        "completed_at": None,
        "ekyte_url": None,
        "external": None,
    }
    new_task.pop("operation_id", None)
    new_task.pop("type", None)

    if existing == new_task:
        return tasks_ledger, "no_change"
    if existing is not None:
        raise AssertionError("would have diverged on an existing task_id — manage-task-ledger would reject this as duplicate_task_id")

    updated = copy.deepcopy(tasks_ledger)
    updated["tasks"].append(new_task)
    updated["updated_at"] = "2026-04-05T00:00:00Z"
    return updated, "success"


def test_ag_full_chain_replan_to_local_task_preview(sample_task_proposals, tmp_path):
    ws = Workspace(root=tmp_path)
    for sub in ("clients", "private", "context/generated", "outputs"):
        (ws.root / sub).mkdir(parents=True, exist_ok=True)

    # approval
    cand = ap.build_approval_candidate(
        approval_id="appr-chain-1", client_id=CLIENT_ID, quarter_id=QUARTER_ID, created_at="2026-04-01T00:00:00Z",
        source_artifact_type="task_proposals", source_artifact_id=sample_task_proposals["proposal_set_id"],
        source_artifact=sample_task_proposals, source_artifact_path="p.json",
        candidate_items=[{"item_id": tp["proposal_id"], "item_type": "task_proposal", "payload": tp} for tp in sample_task_proposals["task_proposals"]],
    )
    approval = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["synthtest-tp-001"], defer_item_ids=["synthtest-tp-002"])
    assert approval["status"] == "partially_approved"

    # bridge
    bridge = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    assert len(bridge.operations) == 1

    # simulated preview: apply on the temp workspace's tasks.json only
    tasks_path = ws.client_file(CLIENT_ID, "tasks.json")
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    initial = {"schema_version": "1.0.0", "client_id": CLIENT_ID, "updated_at": "2026-04-01T00:00:00Z", "tasks": []}
    tasks_path.write_text(json.dumps(initial), encoding="utf-8")

    before_hash = content_sha256(json.loads(tasks_path.read_text()))
    updated, status = _simulate_manage_task_ledger_apply(initial, bridge.operations[0])
    tasks_path.write_text(json.dumps(updated), encoding="utf-8")
    after_hash = content_sha256(json.loads(tasks_path.read_text()))

    assert status == "success"
    assert before_hash != after_hash
    assert len(updated["tasks"]) == 1
    assert updated["tasks"][0]["task_id"] == bridge.operations[0]["task_id"]


def test_ah_same_approval_replayed_no_duplicate(sample_task_proposals, tmp_path):
    ws = Workspace(root=tmp_path)
    bridge = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    ledger = {"schema_version": "1.0.0", "client_id": CLIENT_ID, "updated_at": "t", "tasks": []}

    ledger, status1 = _simulate_manage_task_ledger_apply(ledger, bridge.operations[0])
    assert status1 == "success"
    assert len(ledger["tasks"]) == 1

    # replay: rebuild the SAME bridge operation from the SAME approved proposal
    bridge2 = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    ledger, status2 = _simulate_manage_task_ledger_apply(ledger, bridge2.operations[0])
    assert status2 == "no_change"
    assert len(ledger["tasks"]) == 1  # never a second entry


def test_ai_new_replan_invalidates_stale_approval(sample_task_proposals):
    cand = ap.build_approval_candidate(
        approval_id="appr-chain-2", client_id=CLIENT_ID, quarter_id=QUARTER_ID, created_at="2026-04-01T00:00:00Z",
        source_artifact_type="task_proposals", source_artifact_id=sample_task_proposals["proposal_set_id"],
        source_artifact=sample_task_proposals, source_artifact_path="p.json",
        candidate_items=[{"item_id": "synthtest-tp-001", "item_type": "task_proposal", "payload": sample_task_proposals["task_proposals"][0]}],
    )
    approval = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["synthtest-tp-001"])

    # a new replan-client run changes the proposal's due_at
    new_run = copy.deepcopy(sample_task_proposals)
    new_run["task_proposals"][0]["due_at"] = "2026-05-01"
    new_run["task_proposals"][0]["manage_task_operation"]["due_at"] = "2026-05-01"

    checks = ap.validate_approval(approval, new_run, {"synthtest-tp-001": new_run["task_proposals"][0]})
    assert not checks[0].ok
    assert "STALE_APPROVAL" in checks[0].reason


# AJ. no external side effect in test default

def test_aj_chain_never_constructs_a_real_transport():
    import scripts.lib.ekyte_transport as et
    assert not hasattr(et, "RealEkyteTransport"), "no real transport exists — nothing in this chain can accidentally call one"


# AK. canonical only changes in the explicit temp-workspace apply test above — verify isolation

def test_ak_apply_touches_only_the_temp_workspace_tasks_file(sample_task_proposals, tmp_path):
    ws = Workspace(root=tmp_path)
    for sub in ("clients", "private", "context/generated", "outputs"):
        (ws.root / sub).mkdir(parents=True, exist_ok=True)
    tasks_path = ws.client_file(CLIENT_ID, "tasks.json")
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    initial = {"schema_version": "1.0.0", "client_id": CLIENT_ID, "updated_at": "t", "tasks": []}
    tasks_path.write_text(json.dumps(initial), encoding="utf-8")

    before_listing = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())

    bridge = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    updated, _ = _simulate_manage_task_ledger_apply(initial, bridge.operations[0])
    tasks_path.write_text(json.dumps(updated), encoding="utf-8")

    after_listing = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert before_listing == after_listing  # same file set — only its content changed, nothing new created elsewhere
