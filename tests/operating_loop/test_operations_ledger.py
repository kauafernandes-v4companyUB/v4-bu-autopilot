from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from scripts.lib.operations_ledger import (
    OperationsLedgerError, add_operation, apply_add_operation, approval_is_stale, canonical_hash,
    rebuild_operator_inbox, transition, validate_semantics,
)


def operation(kind: str, operation_id: str = "op-1") -> dict:
    external = kind == "external_approved"
    return {
        "operation_id": operation_id, "client_id": "acme-demo", "quarter_id": "2026-Q1",
        "type": kind, "source": {"workflow": "replan-client", "source_item_id": "S1", "source_artifact_id": "proposal-1", "source_artifact_hash": "a" * 64},
        "statement": "Synthetic operational decision", "status": "approved" if external else kind,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "scheduled_for": "2026-01-10" if kind == "scheduled" else None,
        "deferred_until": {"type": "after_task", "reference_id": "task-1", "description": "After synthetic task"} if kind == "deferred" else None,
        "approval": {"status": "approved", "approved_at": "2026-01-01T00:00:00Z", "approved_by": "operator", "payload_hash": "b" * 64, "conditions": []} if external else None,
        "external": {"system": "synthetic", "action_type": "remove", "executed": False, "executed_at": None, "external_id": None, "external_url": None} if external else None,
        "evidence_ids": [], "receipt_refs": [], "materialized_ref": None,
        "superseded_by": None, "supersedes": [], "notes": None,
    }


def ledger(*operations: dict) -> dict:
    return {"schema_version": "1.0.0", "client_id": "acme-demo", "updated_at": "2026-01-01T00:00:00Z", "operations": list(operations)}


def test_schema_accepts_canonical_operations_ledger():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas/operations-ledger.schema.json").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(ledger(operation("scheduled"))))


def test_scheduled_deferred_and_approval_survive_transient_deletion(tmp_path):
    canonical = ledger(operation("scheduled", "s3"), operation("deferred", "d1"), operation("external_approved", "e1"))
    canonical_path = tmp_path / "clients/acme-demo/operations.json"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text(json.dumps(canonical))
    transient = tmp_path / "context/generated/acme-demo/operating-loop"
    transient.mkdir(parents=True)
    (transient / "operator-inbox.json").write_text("obsolete")
    for file in transient.iterdir():
        file.unlink()
    rebuilt = rebuild_operator_inbox(json.loads(canonical_path.read_text()))
    assert [item["operation_id"] for item in rebuilt["scheduling"]] == ["s3"]
    assert [item["operation_id"] for item in rebuilt["decisions"]] == ["d1"]
    assert [item["operation_id"] for item in rebuilt["external_actions"]] == ["e1"]


def test_payload_change_makes_approval_stale_and_non_executable():
    item = operation("external_approved")
    assert approval_is_stale(item, "c" * 64)
    assert rebuild_operator_inbox(ledger(item), current_payload_hashes={"op-1": "c" * 64})["external_actions"] == []


def test_approved_is_not_executed():
    item = operation("external_approved")
    assert item["approval"]["status"] == "approved"
    assert item["external"]["executed"] is False


def test_new_replan_cannot_erase_operation_and_supersession_keeps_history():
    old = operation("scheduled", "old")
    new = operation("scheduled", "new")
    old["status"] = "superseded"; old["superseded_by"] = "new"
    new["supersedes"] = ["old"]
    state, result = add_operation(ledger(old), new, "2026-01-02T00:00:00Z")
    assert result == "created" and [item["operation_id"] for item in state["operations"]] == ["old", "new"]


def test_materialized_operation_references_task_and_task_remains_authority():
    item = transition(operation("scheduled"), "materialized", "2026-01-02T00:00:00Z", materialized_task_id="task-1")
    tasks = {"tasks": [{"task_id": "task-1", "status": "pending", "title": "Canonical task"}]}
    assert validate_semantics(ledger(item), tasks) == []
    assert tasks["tasks"][0]["status"] == "pending"


def test_same_operation_apply_is_idempotent_and_duplicate_divergence_is_blocked():
    item = operation("scheduled")
    state, result = add_operation(ledger(), item, "2026-01-02T00:00:00Z")
    replay, replay_result = add_operation(state, item, "2026-01-03T00:00:00Z")
    assert replay_result == "no_change" and replay == state
    divergent = copy.deepcopy(item); divergent["statement"] = "changed"
    with pytest.raises(OperationsLedgerError, match="divergent"):
        add_operation(state, divergent, "2026-01-03T00:00:00Z")


def test_local_apply_writes_once_and_replay_does_not_rewrite(tmp_path):
    path = tmp_path / "clients/acme-demo/operations.json"
    item = operation("scheduled")
    assert apply_add_operation(path, item, "2026-01-02T00:00:00Z") == "created"
    before = path.read_bytes()
    assert apply_add_operation(path, item, "2026-01-03T00:00:00Z") == "no_change"
    assert path.read_bytes() == before


def test_duplicate_ids_and_missing_materialized_task_are_reported():
    assert "duplicate operation_id" in validate_semantics(ledger(operation("scheduled"), operation("scheduled")))[0]
    materialized = transition(operation("scheduled"), "materialized", "2026-01-02T00:00:00Z", materialized_task_id="missing")
    assert "does not resolve" in validate_semantics(ledger(materialized), {"tasks": []})[0]


def test_receipt_refs_are_preserved_and_external_execution_requires_one(tmp_path):
    item = operation("external_approved")
    item["external"]["executed"] = True
    item["external"]["executed_at"] = "2026-01-02T00:00:00Z"
    assert "requires receipt_refs" in validate_semantics(ledger(item))[0]
    receipt = {"receipt_id": "r1", "effect": "synthetic"}
    receipts = tmp_path / "receipts"; receipts.mkdir()
    (receipts / "r1.json").write_text(json.dumps(receipt))
    item["receipt_refs"] = [{"receipt_id": "r1", "path": "r1.json", "content_sha256": canonical_hash(receipt)}]
    assert validate_semantics(ledger(item), receipts_dir=receipts) == []


def test_no_external_action_is_performed_by_ledger_helpers():
    item = operation("external_approved")
    before = copy.deepcopy(item)
    rebuild_operator_inbox(ledger(item))
    assert item == before
