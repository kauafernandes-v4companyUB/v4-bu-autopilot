from __future__ import annotations

import copy

import pytest

from jsonschema import Draft202012Validator

from scripts.lib import approval as ap

SOURCE = {"proposal_set_id": "x", "task_proposals": [{"proposal_id": "p1", "title": "A"}, {"proposal_id": "p2", "title": "B"}]}


def _candidate():
    return ap.build_approval_candidate(
        approval_id="appr-test-1", client_id="synthtest-loop", quarter_id="2026-Q2", created_at="2026-04-01T00:00:00Z",
        source_artifact_type="task_proposals", source_artifact_id="x", source_artifact=SOURCE, source_artifact_path="p.json",
        candidate_items=[
            {"item_id": "p1", "item_type": "task_proposal", "payload": {"proposal_id": "p1", "title": "A"}},
            {"item_id": "p2", "item_type": "task_proposal", "payload": {"proposal_id": "p2", "title": "B"}},
        ],
    )


# A. create candidate

def test_a_candidate_is_draft_and_unattended(repo_root, validate):
    cand = _candidate()
    assert cand["status"] == "draft"
    assert cand["approved_at"] is None
    assert cand["approved_by"] is None
    errors = validate(cand, repo_root / "schemas" / "approval.schema.json")
    assert not errors, errors


# B. approved exact hash

def test_b_approved_matches_exact_payload_hash():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1", "p2"])
    assert real["status"] == "approved"
    checks = ap.validate_approval(real, SOURCE, {"p1": {"proposal_id": "p1", "title": "A"}, "p2": {"proposal_id": "p2", "title": "B"}})
    assert all(c.ok for c in checks)


# C. stale approval blocked

def test_c_stale_approval_blocked_when_item_payload_changes():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"])
    with pytest.raises(ap.StaleApproval):
        ap.require_fresh_approved_items(real, SOURCE, {"p1": {"proposal_id": "p1", "title": "CHANGED"}})


def test_c_stale_approval_blocked_when_source_artifact_changes():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"])
    mutated_source = {**SOURCE, "task_proposals": SOURCE["task_proposals"] + [{"proposal_id": "p3", "title": "new"}]}
    with pytest.raises(ap.StaleApproval):
        ap.require_fresh_approved_items(real, mutated_source, {"p1": {"proposal_id": "p1", "title": "A"}})


# D. partial approval

def test_d_partial_approval_when_some_items_approved_some_not():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"], reject_item_ids=["p2"])
    assert real["status"] == "partially_approved"
    assert [i["item_id"] for i in real["scope"]["approved_items"]] == ["p1"]
    assert [i["item_id"] for i in real["scope"]["rejected_items"]] == ["p2"]


# E. rejected item blocked

def test_e_fully_rejected_approval_has_no_approved_items():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=[], reject_item_ids=["p1", "p2"])
    assert real["status"] == "rejected"
    assert real["scope"]["approved_items"] == []


def test_e_rejected_item_never_resolvable_via_validate_approval():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"], reject_item_ids=["p2"])
    # p2 isn't in approved_items at all, so it's simply absent from any fresh-item check
    fresh = ap.require_fresh_approved_items(real, SOURCE, {"p1": {"proposal_id": "p1", "title": "A"}})
    assert fresh == ["p1"]


# F. approval cannot self-authorize

def test_f_cannot_decide_on_a_non_draft_approval():
    cand = _candidate()
    real = ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"])
    with pytest.raises(ap.ApprovalError):
        ap.apply_operator_decision(real, approved_at="2026-04-03T00:00:00Z", approved_by="operator", approve_item_ids=["p2"])


def test_f_approved_by_is_required_and_never_defaulted():
    cand = _candidate()
    with pytest.raises(ap.ApprovalError):
        ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="", approve_item_ids=["p1"])


def test_f_candidate_alone_never_satisfies_validate_approval():
    cand = _candidate()
    checks = ap.validate_approval(cand, SOURCE, {"p1": {"proposal_id": "p1", "title": "A"}})
    assert all(not c.ok for c in checks)
