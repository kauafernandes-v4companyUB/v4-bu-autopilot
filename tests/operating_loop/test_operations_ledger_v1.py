"""manage-operations-ledger on the V1 ACTION contract: hash-bound preview,
approval-gated atomic apply, receipt. Synthetic client only."""

import json
from pathlib import Path

import pytest

from scripts.lib import approval as ap
from scripts.lib import operations_ledger as ol

CLIENT = "acme-demo"


def _op(op_id="op-acme-1", when="2026-10-10"):
    return {"operation_id": op_id, "client_id": CLIENT, "quarter_id": "2026-Q4", "type": "scheduled",
            "source": {"workflow": "replan-client", "source_item_id": "acme-tp-1", "source_artifact_id": "acme-tp", "source_artifact_hash": "d" * 64},
            "statement": "[synthetic] review landing page", "status": "scheduled", "created_at": "2026-10-02T09:00:00Z",
            "updated_at": "2026-10-02T09:00:00Z", "scheduled_for": when, "deferred_until": None, "approval": None, "external": None,
            "evidence_ids": [], "receipt_refs": [], "materialized_ref": None, "superseded_by": None, "supersedes": [], "notes": None}


@pytest.fixture
def client_dir(tmp_path):
    d = tmp_path / "clients" / CLIENT
    d.mkdir(parents=True)
    (d / "tasks.json").write_text(json.dumps({"schema_version": "1.0.0", "client_id": CLIENT, "updated_at": None, "tasks": []}), encoding="utf-8")
    return d


def _approve(pv):
    c = ol.build_changes_approval_candidate(pv, approval_id="appr-ops-1", created_at="2026-10-02T09:05:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-02T09:06:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[ol.v1_approval_item_id(pv)])


def _snap(d: Path):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_add_preview_apply_receipt_and_idempotent_replay(client_dir, repo_root, validate):
    before = _snap(client_dir)
    pv = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op()}], clock=lambda: "2026-10-02T09:00:00Z")
    assert pv["status"] == "success" and _snap(client_dir) == before
    assert validate(pv, repo_root / "skills/manage-operations-ledger/output.schema.json") == []
    out = ol.apply_changes(pv, _approve(pv), client_dir, clock=lambda: "2026-10-02T09:10:00Z")
    assert out["status"] == "success" and validate(out, repo_root / "skills/manage-operations-ledger/output.schema.json") == []
    ledger = json.loads((client_dir / "operations.json").read_text(encoding="utf-8"))
    assert [o["operation_id"] for o in ledger["operations"]] == ["op-acme-1"]
    assert (client_dir / "receipts" / f"{out['receipt']['receipt_id']}.json").is_file()
    again = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op()}])
    assert again["status"] == "no_change" and ol.apply_changes(again, None, client_dir)["status"] == "no_change"


def test_transition_requires_fresh_approval(client_dir):
    pv = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op()}])
    ol.apply_changes(pv, _approve(pv), client_dir)
    done = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "transition", "operation_id": "op-acme-1", "target_status": "completed"}])
    assert done["status"] == "success"
    approval = _approve(done)
    # a concurrent ledger change after the preview makes the approval stale
    other = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op("op-acme-2")}])
    ol.apply_changes(other, _approve(other), client_dir)
    before = _snap(client_dir)
    out = ol.apply_changes(done, approval, client_dir)
    assert out["status"] == "conflict" and out["errors"][0].startswith("STALE_APPROVAL")
    assert _snap(client_dir) == before


@pytest.mark.parametrize("change", [
    {"kind": "transition", "operation_id": "missing", "target_status": "completed"},
    {"kind": "transition", "operation_id": "op-acme-1", "target_status": "executed"},
    {"kind": "teleport"},
])
def test_invalid_changes_are_errors_and_not_approvable(client_dir, change):
    pv = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op()}])
    ol.apply_changes(pv, _approve(pv), client_dir)
    bad = ol.preview_changes(client_dir, client_id=CLIENT, changes=[change])
    assert bad["status"] == "error" and bad["errors"]
    with pytest.raises(ap.ApprovalError):
        _approve(bad)


def test_apply_without_approval_writes_nothing(client_dir):
    pv = ol.preview_changes(client_dir, client_id=CLIENT, changes=[{"kind": "add", "operation": _op()}])
    before = _snap(client_dir)
    assert ol.apply_changes(pv, None, client_dir)["status"] == "error"
    assert _snap(client_dir) == before
