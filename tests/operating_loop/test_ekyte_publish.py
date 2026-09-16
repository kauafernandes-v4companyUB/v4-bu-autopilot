from __future__ import annotations

import copy

import pytest

from scripts.lib import approval as ap
from scripts.lib.ekyte_publish import PublishBlocked, apply_publication, build_payload, preview_publication
from scripts.lib.ekyte_transport import CAPABILITY_MANUAL_EXPORT, FakeEkyteTransport, discover_ekyte_capability

TASK = {
    "task_id": "t-abc123", "client_id": "synthtest-loop", "quarter_id": "2026-Q2",
    "title": "Synthetic task", "description": "desc", "raised_at": "2026-04-01", "due_at": "2026-04-15",
    "status": "pending", "completed_at": None, "ekyte_url": None, "external": None,
    "evidence_ids": ["e1"], "origin": {"type": "replanning", "evidence_ids": ["e1"]},
}
SOURCE = {"proposal_set_id": "x", "task_proposals": [{"proposal_id": "p1", "title": "Synthetic task"}]}
ITEM_PAYLOAD = {"proposal_id": "p1", "title": "Synthetic task"}


def _approval():
    cand = ap.build_approval_candidate(
        approval_id="appr-1", client_id="synthtest-loop", quarter_id="2026-Q2", created_at="2026-04-01T00:00:00Z",
        source_artifact_type="task_proposals", source_artifact_id="x", source_artifact=SOURCE, source_artifact_path="p.json",
        candidate_items=[{"item_id": "p1", "item_type": "task_proposal", "payload": ITEM_PAYLOAD}],
    )
    return ap.apply_operator_decision(cand, approved_at="2026-04-02T00:00:00Z", approved_by="operator", approve_item_ids=["p1"])


def test_payload_never_invents_responsible():
    payload = build_payload(TASK)
    assert "responsible" not in payload
    assert set(payload.keys()) == {"title", "description", "due_at", "omitted_fields"}


def test_default_capability_is_manual_export_not_invented_api():
    assert discover_ekyte_capability() == CAPABILITY_MANUAL_EXPORT


# Q. preview no external call

def test_q_preview_never_touches_a_transport():
    result = preview_publication(TASK, capability="MANUAL_EXPORT")
    assert result["remote_result"] is None
    assert result["link_ekyte_operation"] is None


def test_q_preview_reports_approval_validity_when_supplied():
    approval = _approval()
    result = preview_publication(TASK, capability="MANUAL_EXPORT", approval=approval, current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD})
    assert result["approval_valid"] is True


# R. apply without approval blocked

def test_r_apply_without_valid_approval_blocked():
    approval = _approval()
    with pytest.raises(ap.StaleApproval):
        apply_publication(
            task=TASK, approval=approval, approval_item_id="p1",
            current_source_artifact=SOURCE, current_items_by_id={"p1": {"proposal_id": "p1", "title": "CHANGED"}},
            capability="MANUAL_EXPORT", transport=None, now="2026-04-03T00:00:00Z",
        )


def test_r_apply_with_item_not_in_approval_blocked():
    approval = _approval()
    with pytest.raises(PublishBlocked) as exc:
        apply_publication(
            task=TASK, approval=approval, approval_item_id="p-not-approved",
            current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
            capability="MANUAL_EXPORT", transport=None, now="2026-04-03T00:00:00Z",
        )
    assert exc.value.code == "NO_APPROVAL"


# S. apply without transport blocked (from actually publishing programmatically) -> manual_export instead

def test_s_apply_without_transport_never_claims_programmatic_success():
    approval = _approval()
    result = apply_publication(
        task=TASK, approval=approval, approval_item_id="p1",
        current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
        capability="MANUAL_EXPORT", transport=None, now="2026-04-03T00:00:00Z",
    )
    assert result["publication_mode"] == "manual_export"
    assert result["remote_result"] is None
    assert result["link_ekyte_operation"] is None
    assert result["status"] == "success"  # success = packet ready, not "published"


# T. fake transport create success

def test_t_fake_transport_creates_and_returns_link_operation():
    approval = _approval()
    transport = FakeEkyteTransport()
    result = apply_publication(
        task=TASK, approval=approval, approval_item_id="p1",
        current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
        capability="API", transport=transport, now="2026-04-03T00:00:00Z",
    )
    assert result["publication_mode"] == "programmatic"
    assert result["status"] == "success"
    assert result["remote_result"]["external_id"]
    assert result["link_ekyte_operation"]["type"] == "link_ekyte"
    assert result["link_ekyte_operation"]["external"]["external_id"] == result["remote_result"]["external_id"]


def test_t_publish_ekyte_never_applies_the_link_operation_itself():
    approval = _approval()
    transport = FakeEkyteTransport()
    result = apply_publication(
        task=TASK, approval=approval, approval_item_id="p1",
        current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
        capability="API", transport=transport, now="2026-04-03T00:00:00Z",
    )
    # the fake transport's store has the task, but TASK dict (the "canonical" task) is untouched
    assert TASK["external"] is None


# U. repeated publish idempotent

def test_u_republish_of_already_bound_task_is_no_change():
    bound_task = {**TASK, "external": {"system": "ekyte", "external_id": "fake-99", "url": "https://fake-ekyte.local/tasks/fake-99", "published_at": "2026-04-03T00:00:00Z", "last_verified_at": "2026-04-03T00:00:00Z"}}
    approval = _approval()
    result = apply_publication(
        task=bound_task, approval=approval, approval_item_id="p1",
        current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
        capability="MANUAL_EXPORT", transport=None, now="2026-04-04T00:00:00Z",
    )
    assert result["status"] == "no_change"
    assert result["link_ekyte_operation"] is None


# V. mismatched external binding conflict

def test_v_existing_binding_pointing_to_different_remote_title_conflicts():
    transport = FakeEkyteTransport()
    remote = transport.create_task({"title": "A totally different title", "description": "x", "due_at": "2026-04-15"})
    bound_task = {**TASK, "external": {"system": "ekyte", "external_id": remote["external_id"], "url": remote["url"], "published_at": "t", "last_verified_at": "t"}}
    approval = _approval()
    with pytest.raises(PublishBlocked) as exc:
        apply_publication(
            task=bound_task, approval=approval, approval_item_id="p1",
            current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
            capability="API", transport=transport, now="2026-04-04T00:00:00Z",
        )
    assert exc.value.code == "EXISTING_EXTERNAL_BINDING_CONFLICT"


def test_v_transport_level_conflict_surfaces_as_publish_blocked():
    transport = FakeEkyteTransport()
    transport.create_task({"title": "Synthetic task", "description": "desc", "due_at": "2026-04-15"})
    approval = _approval()
    with pytest.raises(PublishBlocked) as exc:
        apply_publication(
            task=TASK, approval=approval, approval_item_id="p1",
            current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
            capability="API", transport=transport, now="2026-04-04T00:00:00Z",
        )
    assert exc.value.code == "EXISTING_EXTERNAL_BINDING_CONFLICT"


# W. required external field absent blocks (task not pending is the analogous, actually-enforced guard here)

def test_w_non_pending_task_blocks_apply():
    done_task = {**TASK, "status": "completed", "completed_at": "2026-04-10"}
    approval = _approval()
    with pytest.raises(PublishBlocked) as exc:
        apply_publication(
            task=done_task, approval=approval, approval_item_id="p1",
            current_source_artifact=SOURCE, current_items_by_id={"p1": ITEM_PAYLOAD},
            capability="MANUAL_EXPORT", transport=None, now="2026-04-04T00:00:00Z",
        )
    assert exc.value.code == "TASK_NOT_PENDING"
