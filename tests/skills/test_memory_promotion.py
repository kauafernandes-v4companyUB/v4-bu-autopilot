"""promote-client-memory hash binding, approval gate and stale safety
(skills/promote-client-memory/SKILL.md section 17.2,
scripts/lib/memory_promotion.py). Synthetic client only, temp workspace."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap
from scripts.lib import approval as ap
from scripts.lib import memory_promotion as mp
from scripts.lib.evidence_id import compute_evidence_id

CLIENT = "acme-promo"
SOURCE_OUTPUTS = [{"path": f"context/generated/{CLIENT}/bi/read-bi.json", "kind": "generated_context"}]


def _clock(ts):
    return lambda: ts


def _evidence(obs_id="biobs-0000000000000a01", value=500.0, statement=None):
    sha = hashlib.sha256(b"synthetic-promotion-fixture").hexdigest()
    return {
        "evidence_id": compute_evidence_id(CLIENT, "read-bi", "bi_dashboard_export", obs_id, sha),
        "client_id": CLIENT, "source_type": "bi_dashboard_export", "source_skill": "read-bi", "source_date": None,
        "observed_at": "2026-02-01T10:00:00Z", "type": "metric",
        "statement": statement or f"[synthetic] Meta Ads spend of {value} for 2026-01-01..2026-01-31.",
        "confidence": "high", "reference": {"label": "synthetic BI", "path": f"private/clients/{CLIENT}/bi/x.pdf", "page": 1},
        "value": value, "unit": "brl", "period": {"from": "2026-01-01", "to": "2026-01-31"},
        "external_provenance": {"source_observation_id": obs_id, "source_file_sha256": sha,
                                "source_output": SOURCE_OUTPUTS[0]["path"]},
        "tags": ["spend", "meta_ads"],
    }


@pytest.fixture
def client_dir(temp_workspace):
    assert bootstrap(CLIENT, str(temp_workspace), "Acme Promo (synthetic)", force=False) == 0
    return temp_workspace / "clients" / CLIENT


def _preview(client_dir, evidence=None, ts="2026-02-02T09:00:00Z"):
    return mp.plan_evidence_promotion(client_id=CLIENT, client_dir=client_dir, evidence_items=evidence or [_evidence()],
                                      source_outputs=SOURCE_OUTPUTS, candidate_prefix="acme-promo-test", clock=_clock(ts))


def _approve(preview):
    cand = mp.build_promotion_approval_candidate(preview, approval_id="appr-acme-1", created_at="2026-02-02T09:05:00Z",
                                                 preview_path=f"context/generated/{CLIENT}/memory-promotion.json")
    return ap.apply_operator_decision(cand, approved_at="2026-02-02T09:06:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[mp.approval_item_id(preview)])


def _snapshot(client_dir: Path) -> dict:
    return {str(p.relative_to(client_dir)): p.read_bytes() for p in sorted(client_dir.rglob("*")) if p.is_file()}


# A, B, L
def test_preview_is_hash_bound_and_valid(client_dir, repo_root, validate):
    pv = _preview(client_dir)
    assert pv["schema_version"] == "1.1.0" and pv["mode"] == "preview" and pv["status"] == "success"
    assert len(pv["preview_hash"]) == 64 and len(pv["base_state_hash"]) == 64
    assert set(mp.ALWAYS_BOUND_FILES) <= set(pv["mutation_plan"]["canonical_targets"])
    assert pv["mutation_plan"]["base_state_hash"] == pv["base_state_hash"] and pv["mutation_plan"]["will_write"] is False
    assert [c["action"] for c in pv["promotion_plan"]] == ["promote"] and pv["applied_changes"] == []
    assert validate(pv, repo_root / "skills/promote-client-memory/output.schema.json") == []
    assert validate(_approve(pv), repo_root / "schemas/approval.schema.json") == []


# L — legacy outputs stay readable; a 1.1.0 output without hashes is invalid
def test_schema_backward_compatibility(client_dir, repo_root, validate):
    pv = _preview(client_dir)
    legacy = {k: v for k, v in pv.items() if k not in ("base_state_hash", "preview_hash", "mutation_plan", "approval_id")}
    legacy["schema_version"] = "1.0.0"
    assert validate(legacy, repo_root / "skills/promote-client-memory/output.schema.json") == []
    broken = {**legacy, "schema_version": "1.1.0"}
    assert validate(broken, repo_root / "skills/promote-client-memory/output.schema.json") != []


# C, D
def test_preview_hash_is_deterministic_and_ignores_execution_timestamps(client_dir):
    a = _preview(client_dir, ts="2026-02-02T09:00:00Z")
    b = _preview(client_dir, ts="2026-02-02T09:00:00Z")
    c = _preview(client_dir, ts="2026-03-15T18:30:00Z")
    assert a["preview_hash"] == b["preview_hash"] == c["preview_hash"]
    assert a["base_state_hash"] == c["base_state_hash"]
    assert a["generated_at"] != c["generated_at"]
    assert a["promotion_plan"][0]["value"]["added_at"] != c["promotion_plan"][0]["value"]["added_at"]
    assert _preview(client_dir, evidence=[_evidence(value=501.0)])["preview_hash"] != a["preview_hash"]


# E
def test_correct_approval_applies_atomically(client_dir, repo_root, validate):
    pv = _preview(client_dir)
    out = mp.apply_promotion(pv, _approve(pv), client_dir, clock=_clock("2026-02-02T09:10:00Z"))
    assert out["status"] == "success" and out["errors"] == []
    assert [c["candidate_id"] for c in out["applied_changes"]] == ["acme-promo-test-001"]
    ledger = json.loads((client_dir / "evidence.json").read_text(encoding="utf-8"))
    item = ledger["evidences"][-1]
    assert item["evidence_id"] == _evidence()["evidence_id"]
    assert item["source_kind"] == "bi_dashboard_export" and item["added_by"] == "promote-client-memory"
    assert item["added_at"] == ledger["updated_at"] == "2026-02-02T09:10:00Z"
    assert validate(ledger, repo_root / "schemas/client-evidence.schema.json") == []
    assert not [p for p in client_dir.iterdir() if p.name.endswith(".tmp")]


# F, I
@pytest.mark.parametrize("mode", ["other_preview", "tampered_hash", "no_approval", "draft_only"])
def test_wrong_or_missing_approval_blocks_with_zero_writes(client_dir, mode):
    pv = _preview(client_dir)
    if mode == "other_preview":
        approval = _approve(_preview(client_dir, evidence=[_evidence(value=999.0)]))
    elif mode == "tampered_hash":
        approval = _approve(pv)
        approval["scope"]["approved_items"][0]["approved_payload_hash"] = "0" * 64
    elif mode == "draft_only":
        approval = mp.build_promotion_approval_candidate(pv, approval_id="d", created_at="2026-02-02T09:05:00Z", preview_path="x")
    else:
        approval = None
    before = _snapshot(client_dir)
    out = mp.apply_promotion(pv, approval, client_dir)
    assert out["status"] == "failed" and out["applied_changes"] == []
    assert out["errors"][0]["code"] == ("NO_APPROVAL" if mode == "no_approval" else "STALE_APPROVAL")
    assert _snapshot(client_dir) == before


# G, I
@pytest.mark.parametrize("target", ["knowledge.json", "current-state.json", "decisions.json", "evidence.json"])
def test_canonical_change_after_preview_is_stale_with_zero_writes(client_dir, target):
    pv = _preview(client_dir)
    approval = _approve(pv)
    path = client_dir / target
    data = json.loads(path.read_text(encoding="utf-8"))
    data["updated_at"] = "2026-02-02T09:07:00Z" if data.get("updated_at") != "2026-02-02T09:07:00Z" else None
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before = _snapshot(client_dir)
    out = mp.apply_promotion(pv, approval, client_dir)
    assert out["status"] == "failed" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert "base_state_hash" in out["errors"][0]["message"]
    assert _snapshot(client_dir) == before


# H, I
@pytest.mark.parametrize("recompute_hash", [False, True])
def test_payload_change_after_preview_is_stale_with_zero_writes(client_dir, recompute_hash):
    pv = _preview(client_dir)
    approval = _approve(pv)
    tampered = copy.deepcopy(pv)
    tampered["promotion_plan"][0]["value"]["value"] = 12345.0
    tampered["evidence"][0]["value"] = 12345.0
    if recompute_hash:  # even a consistent re-hash cannot reuse the old approval
        tampered["preview_hash"] = mp.compute_preview_hash(tampered)
    before = _snapshot(client_dir)
    out = mp.apply_promotion(tampered, approval, client_dir)
    assert out["status"] == "failed" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert _snapshot(client_dir) == before


# J
def test_idempotent_replay_is_no_change(client_dir):
    pv = _preview(client_dir)
    assert mp.apply_promotion(pv, _approve(pv), client_dir)["status"] == "success"
    stale = mp.apply_promotion(pv, _approve(pv), client_dir)  # same old preview: canonical moved on
    assert stale["errors"][0]["code"] == "STALE_APPROVAL"
    again = _preview(client_dir)
    assert [c["action"] for c in again["promotion_plan"]] == ["skip"] and again["status"] == "success"
    before = _snapshot(client_dir)
    out = mp.apply_promotion(again, _approve(again), client_dir)
    assert out["status"] == "no_change" and out["applied_changes"] == []
    assert _snapshot(client_dir) == before


# K — no external lock file; legacy/unbound previews and hand-written locks never authorize apply
def test_no_external_lock_file_needed_or_accepted(client_dir, tmp_path):
    pv = _preview(client_dir)
    legacy = {k: v for k, v in pv.items() if k not in ("base_state_hash", "preview_hash", "mutation_plan", "approval_id")}
    legacy["schema_version"] = "1.0.0"
    (tmp_path / "preview.locks.json").write_text(json.dumps({"preview_hash": pv["preview_hash"]}), encoding="utf-8")
    out = mp.apply_promotion(legacy, _approve(pv), client_dir)
    assert out["status"] == "failed" and out["errors"][0]["code"] == "PREVIEW_NOT_HASH_BOUND"
    assert mp.apply_promotion(pv, _approve(pv), client_dir)["status"] == "success"


def test_conflicting_evidence_is_never_applicable(client_dir):
    pv = _preview(client_dir)
    assert mp.apply_promotion(pv, _approve(pv), client_dir)["status"] == "success"
    clash = _preview(client_dir, evidence=[_evidence(statement="[synthetic] different statement, same identity")])
    assert clash["status"] == "partial" and clash["promotion_plan"][0]["action"] == "conflict"
    with pytest.raises(ap.ApprovalError):
        _approve(clash)
    before = _snapshot(client_dir)
    forced = ap.apply_operator_decision(
        ap.build_approval_candidate(approval_id="x", client_id=CLIENT, quarter_id=None, created_at="2026-02-02T09:05:00Z",
                                    source_artifact_type=mp.APPROVAL_SOURCE_TYPE, source_artifact_id="x", source_artifact=clash,
                                    source_artifact_path="x",
                                    candidate_items=[{"item_id": mp.approval_item_id(clash), "item_type": mp.APPROVAL_ITEM_TYPE,
                                                      "payload": mp.approval_item_payload(clash)}]),
        approved_at="2026-02-02T09:06:00Z", approved_by="operator-synthetic", approve_item_ids=[mp.approval_item_id(clash)])
    assert mp.apply_promotion(clash, forced, client_dir)["status"] == "failed"
    assert _snapshot(client_dir) == before


def test_other_canonical_targets_are_bound_and_not_written_by_reference_apply(client_dir):
    pv = _preview(client_dir)
    pv["promotion_plan"].append({"candidate_id": "acme-promo-test-k1", "target_file": "strategy.md", "target_path": None,
                                 "category": None, "action": "promote", "summary": "s", "reason": "r",
                                 "evidence_ids": [pv["evidence"][0]["evidence_id"]], "confidence": "high", "value": "x"})
    bound = mp.bind_preview({k: v for k, v in pv.items() if k not in ("preview_hash", "base_state_hash", "mutation_plan")}, client_dir)
    assert "strategy.md" in bound["mutation_plan"]["canonical_targets"]
    before = _snapshot(client_dir)
    out = mp.apply_promotion(bound, _approve(bound), client_dir)
    assert out["status"] == "failed" and out["errors"][0]["code"] == "UNSUPPORTED_TARGET"
    assert _snapshot(client_dir) == before
