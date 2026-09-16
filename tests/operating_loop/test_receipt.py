from __future__ import annotations

import pytest

from scripts.lib.receipt import build_effect, build_receipt


def test_m_success_receipt(repo_root, validate):
    r = build_receipt(
        receipt_id="r-1", action="manage-task-ledger", client_id="synthtest-loop", executed_at="2026-04-01T00:00:00Z",
        input_payload={"ops": [1]}, approval_id="appr-1", status="success",
        effects=[build_effect(target="clients/synthtest-loop/tasks.json", operation="create_task", before={"tasks": []}, after={"tasks": [1]})],
    )
    errors = validate(r, repo_root / "schemas" / "action-receipt.schema.json")
    assert not errors, errors
    assert r["status"] == "success"
    assert r["effects"][0]["before_hash"] != r["effects"][0]["after_hash"]


# N. no_change

def test_n_no_change_receipt_has_no_material_effect(repo_root, validate):
    r = build_receipt(
        receipt_id="r-2", action="manage-task-ledger", client_id="synthtest-loop", executed_at="2026-04-01T00:00:00Z",
        input_payload={"ops": [1]}, approval_id="appr-1", status="no_change", effects=[],
    )
    errors = validate(r, repo_root / "schemas" / "action-receipt.schema.json")
    assert not errors, errors
    assert r["effects"] == []


# O. failure

def test_o_failure_receipt_has_errors(repo_root, validate):
    r = build_receipt(
        receipt_id="r-3", action="publish-ekyte", client_id="synthtest-loop", executed_at="2026-04-01T00:00:00Z",
        input_payload={}, approval_id="appr-1", status="failed", errors=["transport unavailable"],
    )
    errors = validate(r, repo_root / "schemas" / "action-receipt.schema.json")
    assert not errors, errors
    assert r["errors"] == ["transport unavailable"]


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        build_receipt(receipt_id="r", action="x", client_id="c", executed_at="2026-01-01T00:00:00Z", input_payload={}, approval_id=None, status="bogus")


# P. hashes

def test_p_input_hash_is_deterministic():
    r1 = build_receipt(receipt_id="r", action="x", client_id="c", executed_at="2026-01-01T00:00:00Z", input_payload={"a": 1, "b": 2}, approval_id=None, status="success")
    r2 = build_receipt(receipt_id="r2", action="x", client_id="c", executed_at="2026-01-01T00:00:01Z", input_payload={"b": 2, "a": 1}, approval_id=None, status="success")
    assert r1["input_hash"] == r2["input_hash"]


def test_p_effect_before_after_hash_null_when_not_provided():
    e = build_effect(target="t", operation="op")
    assert e["before_hash"] is None
    assert e["after_hash"] is None


def test_receipt_with_no_approval_id_still_valid_for_no_gate_actions(repo_root, validate):
    r = build_receipt(receipt_id="r", action="midweek", client_id="c", executed_at="2026-01-01T00:00:00Z", input_payload={}, approval_id=None, status="success")
    errors = validate(r, repo_root / "schemas" / "action-receipt.schema.json")
    assert not errors, errors
