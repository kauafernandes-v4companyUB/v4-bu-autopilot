"""promote-client-memory: every declared canonical target is applied
through the same hash-bound, approval-gated, atomic path (SKILL.md 17.2,
scripts/lib/memory_promotion.py). Synthetic client only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap
from scripts.lib import approval as ap
from scripts.lib import memory_promotion as mp
from scripts.lib.evidence_id import compute_evidence_id

CLIENT = "acme-demo"
SRC = [{"path": f"context/generated/{CLIENT}/client-context.json", "kind": "generated_context"}]


def _ev(n: int, statement: str) -> dict:
    sha = "c" * 64
    return {"evidence_id": compute_evidence_id(CLIENT, "read-client-context", "account_handoff", f"obs-{n}", sha),
            "client_id": CLIENT, "source_type": "account_handoff", "source_skill": "read-client-context",
            "source_date": "2026-09-30", "observed_at": "2026-10-01T10:00:00Z", "type": "fact", "statement": statement,
            "confidence": "high", "reference": {"label": "synthetic handoff", "path": f"private/clients/{CLIENT}/h.pdf", "page": 1},
            "external_provenance": {"source_observation_id": f"obs-{n}", "source_file_sha256": sha, "source_output": SRC[0]["path"]},
            "tags": ["synthetic"]}


EV1, EV2, EV3 = _ev(1, "[synthetic] Segment is B2B equipment."), _ev(2, "[synthetic] Operator decided to pause channel X."), _ev(3, "[synthetic] Current goal is 10 sales.")


def _k_item(kid: str, statement: str, eid: str) -> dict:
    return {"knowledge_id": kid, "field": "segmento", "statement": statement, "knowledge_type": "fact", "confidence": "high",
            "status": "active", "observed_at": "2026-10-01T10:00:00Z",
            "provenance": {"source_skill": "read-client-context", "evidence_ids": [eid],
                           "promoted_at": "2026-10-01T11:00:00Z", "promoted_by": "promote-client-memory"}}


def _cand(cid, target, value, eid, action="promote", path=None):
    return {"candidate_id": cid, "target_file": target, "target_path": path, "category": "other_facts" if target == "knowledge.json" else None,
            "action": action, "summary": f"synthetic {target}", "reason": "synthetic test", "value": value,
            "evidence_ids": [eid], "confidence": "high"}


def _multi_candidates():
    return [
        _cand("c-knowledge", "knowledge.json", {"op": "append", "path": "/categories/other_facts", "key": "knowledge_id",
                                                "item": _k_item("acme-k-001", EV1["statement"], EV1["evidence_id"])}, EV1["evidence_id"]),
        _cand("c-decision", "decisions.json", {"op": "append", "path": "/decisions", "key": "decision_id",
                                               "item": {"decision_id": "acme-d-001", "statement": EV2["statement"], "decided_at": "2026-09-30",
                                                        "status": "active", "evidence_ids": [EV2["evidence_id"]]}}, EV2["evidence_id"]),
        _cand("c-state", "current-state.json", {"op": "set", "path": "/goals/sales_target", "value": {"value": 10, "unit": "count"}},
              EV3["evidence_id"], path="goals.sales_target"),
        _cand("c-history", "history", {"op": "create_file", "name": "acme-previous-segment.json",
                                       "content": {"candidate_id": "c-history", "knowledge_type": "fact", "statement": "[synthetic] old segment",
                                                   "confidence": "high", "evidence_ids": [EV1["evidence_id"]],
                                                   "provenance": {"source_skill": "read-client-context"}}}, EV1["evidence_id"], action="historize"),
        _cand("c-strategy", "strategy.md", {"op": "replace_text", "text": "# Strategy\n\n[synthetic] Focus on B2B equipment.\n"},
              EV1["evidence_id"], action="supersede"),
        _cand("c-source", "sources.json", {"op": "append", "path": "/sources", "key": "source_id",
                                           "item": {"source_id": "acme-bi", "type": "bi_dashboard", "scope": "client", "location": None,
                                                    "contains_multiple_clients": False, "client_selector": None, "canonical": False,
                                                    "description": "[synthetic] BI dashboard"}}, EV1["evidence_id"]),
        _cand("c-client", "client.json", {"op": "set", "path": "/status", "value": "active"}, EV1["evidence_id"], action="supersede"),
    ]


@pytest.fixture
def client_dir(temp_workspace):
    assert bootstrap(CLIENT, str(temp_workspace), "Acme Demo (synthetic)", force=False) == 0
    return temp_workspace / "clients" / CLIENT


def _preview(client_dir, candidates=None, ts="2026-10-02T09:00:00Z"):
    return mp.plan_promotion(client_id=CLIENT, client_dir=client_dir, candidates=candidates or _multi_candidates(),
                             evidence_items=[EV1, EV2, EV3], source_outputs=SRC, clock=lambda: ts)


def _approve(pv):
    c = mp.build_promotion_approval_candidate(pv, approval_id="appr-acme-multi", created_at="2026-10-02T09:05:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-02T09:06:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[mp.approval_item_id(pv)])


def _snap(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def _j(d, rel):
    return json.loads((d / rel).read_text(encoding="utf-8"))


def _apply(client_dir, pv=None):
    pv = pv or _preview(client_dir)
    assert pv["status"] == "success", pv["conflicts"]
    return pv, mp.apply_promotion(pv, _approve(pv), client_dir, clock=lambda: "2026-10-02T09:10:00Z")


# J, K, L, M, N, Q
def test_multi_target_apply_writes_every_target_with_provenance_and_receipt(client_dir, repo_root, validate):
    pv, out = _apply(client_dir)
    assert out["status"] == "success"
    assert {c["candidate_id"] for c in out["applied_changes"]} == {c["candidate_id"] for c in _multi_candidates()}
    knowledge = _j(client_dir, "knowledge.json")
    item = knowledge["categories"]["other_facts"][0]
    assert item["knowledge_id"] == "acme-k-001" and item["provenance"]["promoted_at"] == "2026-10-02T09:10:00Z"
    assert validate(knowledge, repo_root / "schemas/client-knowledge.schema.json") == []
    assert _j(client_dir, "decisions.json")["decisions"][0]["decision_id"] == "acme-d-001"
    state = _j(client_dir, "current-state.json")
    assert state["goals"]["sales_target"] == {"value": 10, "unit": "count"} and state["updated_at"] == "2026-10-02T09:10:00Z"
    assert _j(client_dir, "sources.json")["sources"][-1]["source_id"] == "acme-bi"
    assert _j(client_dir, "client.json")["status"] == "active"
    assert "Focus on B2B" in (client_dir / "strategy.md").read_text(encoding="utf-8")
    hist = _j(client_dir, "history/acme-previous-segment.json")
    assert hist["provenance"]["historized_by"] == "promote-client-memory"
    # supersede snapshot of the previous strategy.md preserved in history/; client.json "unknown" is a
    # template placeholder, not content, so replacing it needs no snapshot
    snapshots = sorted(p.name for p in (client_dir / "history").glob("*-superseded-by-*.json"))
    assert snapshots == ["strategy-md-superseded-by-c-strategy.json"]
    # evidence sync: every evidence used by a writing candidate is now canonical
    ledger = _j(client_dir, "evidence.json")
    assert {EV1["evidence_id"], EV2["evidence_id"], EV3["evidence_id"]} <= {e["evidence_id"] for e in ledger["evidences"]}
    assert validate(ledger, repo_root / "schemas/client-evidence.schema.json") == []
    # Q: one receipt, persisted, covering every written target
    receipt = out["receipt"]
    assert validate(receipt, repo_root / "schemas/action-receipt.schema.json") == []
    assert _j(client_dir, f"receipts/{receipt['receipt_id']}.json") == receipt
    targets = {e["target"].split(f"clients/{CLIENT}/", 1)[1] for e in receipt["effects"]}
    assert {"evidence.json", "knowledge.json", "current-state.json", "decisions.json", "client.json", "sources.json",
            "strategy.md", "history/acme-previous-segment.json"} <= targets
    assert receipt["approval_id"] == "appr-acme-multi"


# O
@pytest.mark.parametrize("touched", ["sources.json", "client.json", "strategy.md", "history/x.json"])
def test_stale_on_any_bound_target_blocks_everything(client_dir, touched):
    pv = _preview(client_dir)
    approval = _approve(pv)
    path = client_dir / touched
    if touched.endswith(".json") and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = "1.0.1"  # a semantic change, not just whitespace
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path.write_text((path.read_text(encoding="utf-8") if path.exists() else "{}") + "\nchanged\n", encoding="utf-8")
    before = _snap(client_dir)
    out = mp.apply_promotion(pv, approval, client_dir)
    assert out["status"] == "failed" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert _snap(client_dir) == before


# N — atomicity under a write failure in the middle of the commit
def test_failure_mid_commit_rolls_back_every_target(client_dir, monkeypatch):
    pv = _preview(client_dir)
    approval = _approve(pv)
    before = _snap(client_dir)
    real_replace, calls = os.replace, {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("simulated disk failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        mp.apply_promotion(pv, approval, client_dir)
    monkeypatch.setattr(os, "replace", real_replace)
    assert _snap(client_dir) == before


# P
def test_retry_is_idempotent(client_dir):
    _apply(client_dir)
    after_first = _snap(client_dir)
    again = _preview(client_dir, ts="2026-10-03T08:00:00Z")
    assert {c["action"] for c in again["promotion_plan"]} == {"skip"} and again["status"] == "success"
    out = mp.apply_promotion(again, _approve(again), client_dir)
    assert out["status"] == "no_change" and out["applied_changes"] == [] and out["receipt"]["status"] == "no_change"
    assert _snap(client_dir) == after_first


def test_replacing_existing_content_requires_supersede(client_dir):
    _apply(client_dir)
    clash = [_cand("c-knowledge-2", "knowledge.json", {"op": "append", "path": "/categories/other_facts", "key": "knowledge_id",
                                                       "item": _k_item("acme-k-001", "[synthetic] different", EV1["evidence_id"])}, EV1["evidence_id"])]
    pv = _preview(client_dir, candidates=clash)
    assert pv["status"] == "partial" and pv["promotion_plan"][0]["action"] == "conflict"
    sup = [_cand("c-knowledge-3", "knowledge.json", {"op": "replace_item", "path": "/categories/other_facts", "key": "knowledge_id",
                                                     "item": _k_item("acme-k-001", "[synthetic] corrected", EV1["evidence_id"])},
                 EV1["evidence_id"], action="supersede")]
    pv, out = _apply(client_dir, _preview(client_dir, candidates=sup))
    assert out["status"] == "success"
    assert _j(client_dir, "knowledge.json")["categories"]["other_facts"][0]["statement"] == "[synthetic] corrected"
    assert (client_dir / "history" / "knowledge-json-superseded-by-c-knowledge-3.json").is_file()


def test_unresolved_evidence_blocks_preview(client_dir):
    cand = [_cand("c-x", "decisions.json", {"op": "append", "path": "/decisions", "key": "decision_id",
                                            "item": {"decision_id": "acme-d-9", "statement": "s"}}, "evobs-ffffffffffffffff")]
    pv = mp.plan_promotion(client_id=CLIENT, client_dir=client_dir, candidates=cand, evidence_items=[], source_outputs=SRC)
    assert pv["status"] == "partial" and "unresolved_evidence" in pv["conflicts"][0]["description"]
