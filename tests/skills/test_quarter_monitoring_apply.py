"""monitor-quarter reference apply (scripts/lib/quarter_monitoring.py). Synthetic only."""

from __future__ import annotations

import json

import pytest

from scripts.bootstrap_client import bootstrap_client
from scripts.lib import approval as ap
from scripts.lib import quarter_monitoring as qm

CLIENT = "acme-demo"
EV = "evobs-00000000000000f1"


def _evidence(eid=EV, value=1069.07):
    return {"evidence_id": eid, "client_id": CLIENT, "type": "metric", "statement": f"[synthetic] spend {value}", "value": value, "unit": "brl",
            "confidence": "high", "observed_at": "2026-10-05T10:00:00Z", "source_date": None, "period": {"from": "2026-10-01", "to": "2026-10-31"},
            "source_id": None, "source_kind": "bi_dashboard_export", "source_skill": "read-bi",
            "source_reference": {"label": "synthetic BI", "source_location": None, "page": 1, "row": None, "column": None, "section": None, "uri": None},
            "external_provenance": None, "tags": ["spend"], "added_at": "2026-10-05T10:00:00Z", "added_by": "promote-client-memory"}


@pytest.fixture
def client(temp_workspace, repo_root):
    assert bootstrap_client(CLIENT, workspace_root=str(temp_workspace))["status"] == "CREATED"
    c = temp_workspace / "clients" / CLIENT
    plan = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/plan.json").read_text(encoding="utf-8"))
    plan.update(client_id=CLIENT, quarter_id="2026-Q4", status="active", period={"start": "2026-10-01", "end": "2026-12-31"})
    plan["smart_objective"]["deadline"] = "2026-12-31"
    plan["media_plan"] = {"currency": "BRL", "monthly": [{"month": "2026-10", "channel": "meta_ads", "planned_budget": 2000.0}]}
    (c / "quarters" / "2026-Q4").mkdir(parents=True)
    (c / "quarters" / "2026-Q4" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    ledger = json.loads((c / "evidence.json").read_text(encoding="utf-8"))
    ledger["evidences"].append(_evidence())
    (c / "evidence.json").write_text(json.dumps(ledger), encoding="utf-8")
    return c


def _approve(pv):
    c = qm.build_approval_candidate(pv, approval_id=f"appr-{pv['preview_hash'][:8]}", created_at="2026-10-05T11:00:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-05T11:01:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[qm.approval_item_id(pv)])


MEDIA = {"operation_id": "m1", "type": "upsert_media_actual", "month": "2026-10", "channel": "meta_ads", "actual_spend": 1069.07, "evidence_ids": [EV]}


def test_media_actual_creates_monitoring_with_money_normalized_and_receipt(client, repo_root, validate):
    pv = qm.preview(client, client_id=CLIENT, operations=[MEDIA])
    assert pv["status"] == "success" and pv["quarter_id"] == "2026-Q4"
    assert validate(pv, repo_root / "skills/monitor-quarter/output.schema.json") == []
    out = qm.apply(pv, _approve(pv), client)
    assert out["status"] == "success" and validate(out, repo_root / "skills/monitor-quarter/output.schema.json") == []
    mon = json.loads((client / "quarters/2026-Q4/monitoring.json").read_text(encoding="utf-8"))
    rec = mon["media_monitoring"][0]
    assert rec["variance_value"] == -930.93 and rec["planned_budget"] == 2000.0 and mon["objective_progress"]["status"] == "unknown"
    assert (client / "receipts" / f"{out['receipt']['receipt_id']}.json").is_file()
    plan_before = (client / "quarters/2026-Q4/plan.json").read_bytes()
    again = qm.preview(client, client_id=CLIENT, operations=[{**MEDIA, "observed_at": rec["observed_at"]}])
    assert again["status"] == "no_change" and (client / "quarters/2026-Q4/plan.json").read_bytes() == plan_before


def test_overlay_preview_is_never_approvable_and_apply_ignores_overlay(client):
    other = _evidence("evobs-00000000000000f2", 10.0)
    overlay = {k: v for k, v in other.items() if k not in ("source_id", "source_kind", "source_reference", "added_at", "added_by")}
    overlay.update(source_type="bi_dashboard_export", reference={"label": "synthetic"})
    pv = qm.preview(client, client_id=CLIENT, operations=[{**MEDIA, "evidence_ids": [other["evidence_id"]]}], evidence_overlay=[overlay])
    assert pv["status"] == "success" and pv["warnings"][0]["code"] == "overlay_evidence_used"
    with pytest.raises(ap.ApprovalError):
        _approve(pv)


@pytest.mark.parametrize(("op", "code"), [
    ({"operation_id": "o1", "type": "update_objective_progress", "target_value": 999, "evidence_ids": [EV]}, "target_mismatch"),
    ({**MEDIA, "evidence_ids": ["evobs-ffffffffffffffff"]}, "unresolved_evidence"),
    ({**MEDIA, "planned_budget": 1.0}, "unexpected_fields"),
    ({"operation_id": "f1", "type": "validate_flag", "flag_id": "nope", "evidence_ids": [EV]}, "flag_not_found"),
])
def test_invalid_operations_block(client, op, code):
    pv = qm.preview(client, client_id=CLIENT, operations=[op])
    assert pv["status"] in ("error", "conflict")
    assert code in {n["code"] for n in pv["conflicts"] + pv["validation"]["errors"]}
    assert not (client / "quarters/2026-Q4/monitoring.json").exists()


def test_flag_lifecycle_and_stale(client):
    create = {"operation_id": "f1", "type": "create_flag", "flag_id": "risk-x", "flag_type": "risk", "statement": "[synthetic] risk", "evidence_ids": [EV]}
    pv = qm.preview(client, client_id=CLIENT, operations=[create])
    assert qm.apply(pv, _approve(pv), client)["status"] == "success"
    resolve = {"operation_id": "f2", "type": "resolve_flag", "flag_id": "risk-x", "evidence_ids": [EV]}
    stale = qm.preview(client, client_id=CLIENT, operations=[resolve])
    approval = _approve(stale)
    pv2 = qm.preview(client, client_id=CLIENT, operations=[MEDIA])
    qm.apply(pv2, _approve(pv2), client)
    before = (client / "quarters/2026-Q4/monitoring.json").read_bytes()
    out = qm.apply(stale, approval, client)
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "stale_preview"
    assert (client / "quarters/2026-Q4/monitoring.json").read_bytes() == before
