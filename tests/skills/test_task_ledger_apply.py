"""manage-task-ledger reference apply (scripts/lib/task_ledger.py) on the V1
ACTION contract. Synthetic client; fixture files written directly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap_client
from scripts.lib import approval as ap
from scripts.lib import task_ledger as tl

CLIENT = "acme-demo"
EV = "evobs-00000000000000e1"


@pytest.fixture
def client(temp_workspace, repo_root):
    assert bootstrap_client(CLIENT, workspace_root=str(temp_workspace))["status"] == "CREATED"
    c = temp_workspace / "clients" / CLIENT
    plan = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/plan.json").read_text(encoding="utf-8"))
    plan.update(client_id=CLIENT, quarter_id="2026-Q4", status="active", period={"start": "2026-10-01", "end": "2026-12-31"})
    plan["smart_objective"]["deadline"] = "2026-12-31"
    (c / "quarters" / "2026-Q4").mkdir(parents=True)
    (c / "quarters" / "2026-Q4" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    ledger = json.loads((c / "evidence.json").read_text(encoding="utf-8"))
    ledger["evidences"].append({"evidence_id": EV, "client_id": CLIENT, "type": "fact", "statement": "[synthetic] fact", "confidence": "high",
                                "observed_at": "2026-10-01T10:00:00Z", "source_id": None, "source_kind": "manual_authorized_input",
                                "source_reference": {"label": "synthetic", "source_location": None, "page": None, "row": None, "column": None,
                                                     "section": None, "uri": None},
                                "added_at": "2026-10-01T10:00:00Z", "added_by": "promote-client-memory"})
    (c / "evidence.json").write_text(json.dumps(ledger), encoding="utf-8")
    return c


def _create(task_id="t-acme-1", due="2026-10-20", origin="replanning", evidence=(EV,)):
    return {"operation_id": f"op-{task_id}", "type": "create_task", "task_id": task_id, "title": "[synthetic] task",
            "description": "[synthetic] description", "raised_at": "2026-10-02", "due_at": due,
            "origin": {"type": origin, "evidence_ids": list(evidence)}, "evidence_ids": list(evidence)}


def _approve(pv):
    c = tl.build_approval_candidate(pv, approval_id=f"appr-{pv['preview_hash'][:8]}", created_at="2026-10-02T09:00:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-02T09:01:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[tl.approval_item_id(pv)])


def _do(client, ops, clock="2026-10-02T10:00:00Z"):
    pv = tl.preview(client, client_id=CLIENT, operations=ops, clock=lambda: clock)
    if pv["status"] != "success":
        return pv, tl.apply(pv, None, client)
    return pv, tl.apply(pv, _approve(pv), client, clock=lambda: clock)


def _tasks(client):
    return {t["task_id"]: t for t in json.loads((client / "tasks.json").read_text(encoding="utf-8"))["tasks"]}


def test_create_resolves_quarter_validates_and_writes_receipt(client, repo_root, validate):
    op = _create()
    op.pop("quarter_id", None)  # omitted: resolved from the single active Quarter
    pv, out = _do(client, [op])
    assert pv["mutation_plan"]["normalized_operations"][0]["quarter_id"] == "2026-Q4"
    assert validate(pv, repo_root / "skills/manage-task-ledger/output.schema.json") == []
    assert out["status"] == "success" and validate(out, repo_root / "skills/manage-task-ledger/output.schema.json") == []
    task = _tasks(client)["t-acme-1"]
    assert task["status"] == "pending" and task["client_id"] == CLIENT and task["evidence_ids"] == [EV]
    assert (client / "receipts" / f"{out['receipt']['receipt_id']}.json").is_file()
    again = tl.preview(client, client_id=CLIENT, operations=[_create()])
    assert again["status"] == "conflict" and again["conflicts"][0]["code"] == "duplicate_task_id"


def test_lifecycle_rules_and_no_ops(client):
    _do(client, [_create("t-a"), _create("t-b")])
    _, out = _do(client, [{"operation_id": "c1", "type": "complete_task", "task_id": "t-a", "evidence_ids": [EV]}], "2026-10-05T10:00:00Z")
    assert out["status"] == "success" and _tasks(client)["t-a"]["completed_at"] == "2026-10-05"
    pv, out = _do(client, [{"operation_id": "c2", "type": "complete_task", "task_id": "t-a", "evidence_ids": []}])
    assert pv["status"] == "no_change" and out["status"] == "no_change" and _tasks(client)["t-a"]["completed_at"] == "2026-10-05"
    pv, _ = _do(client, [{"operation_id": "x1", "type": "cancel_task", "task_id": "t-a", "evidence_ids": [EV]}])
    assert pv["status"] == "conflict"
    pv, _ = _do(client, [{"operation_id": "x2", "type": "cancel_task", "task_id": "t-b", "evidence_ids": []}])
    assert pv["status"] == "error" and pv["validation"]["errors"][0]["code"] == "missing_evidence"
    _, out = _do(client, [{"operation_id": "r1", "type": "reschedule_task", "task_id": "t-b", "due_at": "2026-11-01", "evidence_ids": [EV]}])
    assert out["status"] == "success" and _tasks(client)["t-b"]["due_at"] == "2026-11-01" and _tasks(client)["t-b"]["raised_at"] == "2026-10-02"
    _, out = _do(client, [{"operation_id": "l1", "type": "link_ekyte", "task_id": "t-b", "ekyte_url": "https://example.com/task/1"}])
    assert out["status"] == "success" and _tasks(client)["t-b"]["ekyte_url"] == "https://example.com/task/1"


@pytest.mark.parametrize("case", ["unresolved_evidence", "unknown_quarter", "client_id_supplied", "duplicate_op_ids"])
def test_invalid_batches_write_nothing(client, case):
    before = (client / "tasks.json").read_bytes()
    op = _create()
    if case == "unresolved_evidence":
        ops = [_create(evidence=("evobs-ffffffffffffffff",))]
    elif case == "unknown_quarter":
        op["quarter_id"] = "2027-Q1"
        ops = [op]
    elif case == "client_id_supplied":
        op["client_id"] = "beta-demo"
        ops = [op]
    else:
        ops = [_create("t-1"), {**_create("t-2"), "operation_id": "op-t-1"}]
    pv, out = _do(client, ops)
    assert pv["status"] in ("error", "conflict") and out["status"] in ("error", "conflict")
    assert (client / "tasks.json").read_bytes() == before


def test_stale_preview_blocks_apply(client):
    pv = tl.preview(client, client_id=CLIENT, operations=[_create("t-late")])
    approval = _approve(pv)
    _do(client, [_create("t-first")])
    before = (client / "tasks.json").read_bytes()
    out = tl.apply(pv, approval, client)
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "stale_preview"
    assert (client / "tasks.json").read_bytes() == before


def test_overdue_is_derived_never_persisted(client):
    _do(client, [_create("t-old", due="2026-10-03")], "2026-10-02T10:00:00Z")
    pv = tl.preview(client, client_id=CLIENT, operations=[], clock=lambda: "2026-10-05T10:00:00Z")
    assert pv["task_summary"]["overdue"] == 1 and pv["task_summary"]["overdue_tasks"][0]["overdue_days"] == 2
    assert _tasks(client)["t-old"]["status"] == "pending"
