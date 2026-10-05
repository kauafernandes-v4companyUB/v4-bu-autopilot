"""close-ropre reference apply (scripts/lib/ropre_lifecycle.py). Synthetic only."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.bootstrap_client import bootstrap_client
from scripts.lib import approval as ap
from scripts.lib import ropre_lifecycle as rl

CLIENT, Q = "acme-demo", "2026-Q4"


def _draft(repo_root, check_in_id="acme-ropre-1"):
    d = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/check-ins/demo-2026-01-20.json").read_text(encoding="utf-8"))
    d.update(client_id=CLIENT, quarter_id=Q, check_in_id=check_in_id, status="draft", completed_at=None, task_ids=[], evidence_ids=[])
    for lst in ("results", "objectives", "next_steps"):
        for item in d.get(lst, []):
            item["evidence_ids"] = []
    for item in d.get("next_steps", []):
        item["task_id"] = None
    return d


@pytest.fixture
def client(temp_workspace, repo_root):
    assert bootstrap_client(CLIENT, workspace_root=str(temp_workspace))["status"] == "CREATED"
    c = temp_workspace / "clients" / CLIENT
    plan = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/plan.json").read_text(encoding="utf-8"))
    plan.update(client_id=CLIENT, quarter_id=Q, status="active", period={"start": "2026-10-01", "end": "2026-12-31"})
    plan["smart_objective"]["deadline"] = "2026-12-31"
    (c / "quarters" / Q).mkdir(parents=True)
    (c / "quarters" / Q / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return c


def _approve(pv):
    c = rl.build_approval_candidate(pv, approval_id=f"appr-{pv['preview_hash'][:8]}", created_at="2026-12-20T09:00:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-12-20T09:01:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[rl.approval_item_id(pv)])


def _do(client, op, clock="2026-12-20T10:00:00Z"):
    pv = rl.preview(client, client_id=CLIENT, quarter_id=Q, operation=op, clock=lambda: clock)
    out = rl.apply(pv, _approve(pv), client, clock=lambda: clock) if pv["status"] == "success" else rl.apply(pv, None, client)
    return pv, out


def _cur(client):
    return json.loads((client / "quarters" / Q / "check-ins" / "current.json").read_text(encoding="utf-8"))


def test_full_forward_lifecycle_with_history_and_receipts(client, repo_root, validate):
    pv, out = _do(client, {"operation_id": "s1", "type": "save_draft", "ropre_draft": _draft(repo_root)})
    assert out["status"] == "success" and _cur(client)["status"] == "draft"
    assert validate(pv, repo_root / "skills/close-ropre/output.schema.json") == []
    _, out = _do(client, {"operation_id": "r1", "type": "mark_ready"})
    assert out["status"] == "success" and _cur(client)["status"] == "ready"
    pv, out = _do(client, {"operation_id": "c1", "type": "complete_check_in"}, "2026-12-21T18:00:00Z")
    assert out["status"] == "success" and validate(out, repo_root / "skills/close-ropre/output.schema.json") == []
    cur = _cur(client)
    hist = json.loads((client / "quarters" / Q / "check-ins" / "history" / "acme-ropre-1.json").read_text(encoding="utf-8"))
    assert cur == hist and cur["status"] == "completed" and cur["completed_at"] == "2026-12-21T18:00:00Z"
    assert len(list((client / "receipts").glob("*.json"))) == 3
    again, out = _do(client, {"operation_id": "c2", "type": "complete_check_in"})
    assert again["status"] == "no_change" and _cur(client)["completed_at"] == "2026-12-21T18:00:00Z"


@pytest.mark.parametrize("case", ["skip_ready", "reverse", "open_exists", "diverged"])
def test_invalid_transitions_never_write(client, repo_root, case):
    _do(client, {"operation_id": "s1", "type": "save_draft", "ropre_draft": _draft(repo_root)})
    if case == "reverse":
        _do(client, {"operation_id": "r1", "type": "mark_ready"})
        _do(client, {"operation_id": "c1", "type": "complete_check_in"})
        op = {"operation_id": "x", "type": "mark_ready"}
    elif case == "skip_ready":
        op = {"operation_id": "x", "type": "complete_check_in"}
    elif case == "open_exists":
        op = {"operation_id": "x", "type": "save_draft", "ropre_draft": _draft(repo_root, "acme-ropre-2")}
    else:
        d = _draft(repo_root)
        d["long_term_view"] = "[synthetic] changed"
        op = {"operation_id": "x", "type": "save_draft", "ropre_draft": d}
    before = (client / "quarters" / Q / "check-ins" / "current.json").read_bytes()
    pv, out = _do(client, op)
    assert pv["status"] == "conflict" and out["status"] in ("conflict", "error")
    assert (client / "quarters" / Q / "check-ins" / "current.json").read_bytes() == before


def test_rotation_after_completed_and_historized(client, repo_root):
    for op in ({"operation_id": "s1", "type": "save_draft", "ropre_draft": _draft(repo_root)},
               {"operation_id": "r1", "type": "mark_ready"}, {"operation_id": "c1", "type": "complete_check_in"}):
        _do(client, op)
    pv, out = _do(client, {"operation_id": "s2", "type": "save_draft", "ropre_draft": _draft(repo_root, "acme-ropre-2")})
    assert out["status"] == "success" and _cur(client)["check_in_id"] == "acme-ropre-2"
    assert (client / "quarters" / Q / "check-ins" / "history" / "acme-ropre-1.json").is_file()
    reuse, _ = _do(client, {"operation_id": "s3", "type": "save_draft", "ropre_draft": _draft(repo_root, "acme-ropre-1")})
    assert reuse["status"] == "conflict"


def test_stale_and_unresolved_references(client, repo_root):
    _do(client, {"operation_id": "s1", "type": "save_draft", "ropre_draft": _draft(repo_root)})
    pv = rl.preview(client, client_id=CLIENT, quarter_id=Q, operation={"operation_id": "r1", "type": "mark_ready"})
    approval = _approve(pv)
    cur = _cur(client)
    cur["long_term_view"] = "[synthetic] edited by hand"
    (client / "quarters" / Q / "check-ins" / "current.json").write_text(json.dumps(cur), encoding="utf-8")
    out = rl.apply(pv, approval, client)
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "stale_preview"
    bad = _draft(repo_root, "acme-ropre-9")
    bad["evidence_ids"] = ["evobs-ffffffffffffffff"]
    pv2 = rl.preview(client, client_id=CLIENT, quarter_id=Q, operation={"operation_id": "s9", "type": "save_draft", "ropre_draft": bad})
    assert pv2["status"] in ("error", "conflict")
