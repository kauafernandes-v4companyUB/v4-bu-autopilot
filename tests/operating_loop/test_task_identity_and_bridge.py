from __future__ import annotations

import copy

import pytest

from scripts.lib.task_bridge import TaskBridgeError, build_create_task_operations
from scripts.lib.task_identity import compute_task_id

CLIENT_ID = "synthtest-loop"
QUARTER_ID = "2026-Q2"


def test_task_id_is_deterministic_and_stable_across_calls():
    a = compute_task_id(CLIENT_ID, QUARTER_ID, "action-1")
    b = compute_task_id(CLIENT_ID, QUARTER_ID, "action-1")
    assert a == b


def test_task_id_changes_with_any_identity_component():
    base = compute_task_id(CLIENT_ID, QUARTER_ID, "action-1")
    assert compute_task_id("other-client", QUARTER_ID, "action-1") != base
    assert compute_task_id(CLIENT_ID, "2026-Q3", "action-1") != base
    assert compute_task_id(CLIENT_ID, QUARTER_ID, "action-2") != base


def test_task_id_never_derived_from_timestamp():
    import inspect
    params = list(inspect.signature(compute_task_id).parameters)
    assert params == ["client_id", "quarter_id", "action_id"]


# G. ready -> create operation

def test_g_ready_proposal_becomes_create_operation(sample_task_proposals):
    result = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    assert len(result.operations) == 1
    assert result.operations[0]["type"] == "create_task"
    assert not result.skipped


# H. needs_scheduling not applied / I. needs_decision not applied

def test_h_i_non_ready_approved_proposal_is_skipped_not_forced(sample_task_proposals):
    result = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-002"])
    assert result.operations == []
    assert result.skipped[0]["proposal_id"] == "synthtest-tp-002"
    assert "needs_decision" in result.skipped[0]["reason"]


# J. dependency not applied (same mechanism as H/I — any non-ready readiness is skipped)

def test_j_dependency_readiness_never_auto_converts():
    proposals = {
        "task_proposals": [
            {
                "proposal_id": "dep-1", "action_id": "a-dep", "classification": "information_request",
                "readiness": "dependency", "manage_task_operation": None,
            }
        ]
    }
    result = build_create_task_operations(CLIENT_ID, QUARTER_ID, proposals, ["dep-1"])
    assert result.operations == []
    assert result.skipped[0]["proposal_id"] == "dep-1"


# K. duplicate prevention (identity check inside the bridge)

def test_k_task_id_mismatch_is_rejected_defensively(sample_task_proposals):
    broken = copy.deepcopy(sample_task_proposals)
    broken["task_proposals"][0]["manage_task_operation"]["task_id"] = "t-wrongidentity000"
    with pytest.raises(TaskBridgeError):
        build_create_task_operations(CLIENT_ID, QUARTER_ID, broken, ["synthtest-tp-001"])


def test_k_never_carries_responsible_field(sample_task_proposals):
    broken = copy.deepcopy(sample_task_proposals)
    broken["task_proposals"][0]["manage_task_operation"]["responsible"] = "someone"
    with pytest.raises(TaskBridgeError):
        build_create_task_operations(CLIENT_ID, QUARTER_ID, broken, ["synthtest-tp-001"])


# L. idempotent replay — same approved set twice produces the same operations

def test_l_replay_produces_identical_operations(sample_task_proposals):
    r1 = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    r2 = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"])
    assert r1.operations == r2.operations


def test_l_replay_against_identical_canonical_task_is_no_change(sample_task_proposals):
    operation = sample_task_proposals["task_proposals"][0]["manage_task_operation"]
    existing = {
        **{key: operation[key] for key in ("task_id", "quarter_id", "title", "description", "raised_at", "due_at", "origin", "evidence_ids")},
        "client_id": CLIENT_ID,
        "status": "pending",
        "completed_at": None,
        "ekyte_url": None,
        "external": None,
    }
    result = build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"], [existing])
    assert result.operations == []
    assert result.skipped == [{"proposal_id": "synthtest-tp-001", "reason": "task already materialized with identical canonical content"}]


def test_l_existing_task_with_same_identity_but_different_content_blocks_replay(sample_task_proposals):
    operation = sample_task_proposals["task_proposals"][0]["manage_task_operation"]
    existing = {
        **{key: operation[key] for key in ("task_id", "quarter_id", "title", "description", "raised_at", "due_at", "origin", "evidence_ids")},
        "client_id": CLIENT_ID,
        "status": "pending",
        "completed_at": None,
        "ekyte_url": None,
    }
    existing["title"] = "Different task"
    with pytest.raises(TaskBridgeError, match="divergent canonical content"):
        build_create_task_operations(CLIENT_ID, QUARTER_ID, sample_task_proposals, ["synthtest-tp-001"], [existing])


def test_unknown_proposal_id_raises():
    with pytest.raises(TaskBridgeError):
        build_create_task_operations(CLIENT_ID, QUARTER_ID, {"task_proposals": []}, ["does-not-exist"])
