"""Sheets business modules E2E on synthetic clients and the fake transport:
metrics-sheet, operational-playbook, creative-performance-export.
Every write goes read -> patch preview -> approval -> update-google-sheet
apply -> verification -> receipt; retries are NO_CHANGE."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap_client
from scripts.lib import sheet_creative_export as sce
from scripts.lib import sheet_metrics as smx
from scripts.lib import sheet_modules as sh
from scripts.lib import sheet_playbook as spb
from scripts.lib.google_sheets_transport import FakeGoogleSheetsTransport

CLIENT = "acme-demo"
METRICS_SHEET, PLAYBOOK_SHEET, CREATIVE_SHEET = "fake-acme-metrics-0001", "fake-acme-playbook-0001", "fake-acme-creative-0001"
REPO = Path(__file__).resolve().parent.parent.parent


def _gsource(source_id, sheet_id, purpose):
    return {"source_id": source_id, "type": "google_sheet", "scope": "client", "location": None, "contains_multiple_clients": False,
            "client_selector": None, "canonical": False, "description": f"[synthetic] {purpose}",
            "google_sheet": {"spreadsheet_id": sheet_id, "expected_title": None, "purpose": purpose, "allowed_tabs": None, "writable": True}}


def _w(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def client(temp_workspace):
    out = bootstrap_client(CLIENT, workspace_root=str(temp_workspace), initial_sources=[
        _gsource("acme-metrics", METRICS_SHEET, "metrics"), _gsource("acme-playbook", PLAYBOOK_SHEET, "playbook"),
        _gsource("acme-creative", CREATIVE_SHEET, "creative")])
    assert out["status"] == "CREATED"
    c = temp_workspace / "clients" / CLIENT
    _w(c / "quarters/2026-Q4/plan.json", {
        "schema_version": "1.0.0", "client_id": CLIENT, "quarter_id": "2026-Q4", "period": {"start": "2026-10-01", "end": "2026-12-31"},
        "status": "active", "planned_at": "2026-10-01T10:00:00Z",
        "smart_objective": {"statement": "[synthetic] 12 sales", "metric": "sales", "baseline": None, "target": {"value": 12, "unit": "count"}, "deadline": "2026-12-31"},
        "planning": {"strategic_priorities": [], "assumptions": [], "evidence_ids": []},
        "media_plan": {"currency": "BRL", "monthly": [{"month": "2026-10", "channel": "meta_ads", "planned_budget": 2000.0}]}})
    _w(c / "quarters/2026-Q4/monitoring.json", {
        "schema_version": "1.0.0", "client_id": CLIENT, "quarter_id": "2026-Q4", "updated_at": "2026-10-20T10:00:00Z",
        "objective_progress": {"status": "on_track", "current_value": 5, "target_value": 12, "progress_percent": None, "observed_at": "2026-10-20T10:00:00Z", "evidence_ids": ["evobs-x"]},
        "media_monitoring": [{"month": "2026-10", "channel": "meta_ads", "actual_spend": 1069.07, "observed_at": "2026-10-20T10:00:00Z",
                              "evidence_ids": ["evobs-x"], "planned_budget": 2000.0, "attainment_percent": 53.4535, "variance_value": -930.93, "pacing_percent": None}],
        "flags": []})
    return c


def _approve(pv, n):
    return sh.build_approval(pv, approval_id=f"appr-{pv['business_operation_id']}-{n}", approved_by="operator-synthetic",
                             created_at="2026-10-21T09:00:00Z", approved_at="2026-10-21T09:00:01Z")


def _valid(result):
    from scripts.lib import canonical_action as ca
    assert ca.schema_errors(result, f"skills/{result['skill']}/output.schema.json") == []


def _run(transport, client, pv, n=1):
    assert pv["status"] == "PATCH_READY", pv["problems"]
    _valid(pv)
    out = sh.execute(transport, client_dir=client, business_preview=pv, approval=_approve(pv, n))
    assert out["status"] == "APPLIED", out["problems"]
    v = out["verification"]
    assert v and v["targets_match"] and v.get("structure_preserved", True)
    receipt = json.loads((client.parent.parent / out["google_receipt_ref"]).read_text(encoding="utf-8"))
    assert receipt["action"] == "update-google-sheet" and receipt["status"] == "success" and receipt["approval_id"] == out["approval_ref"]
    assert out["patch_hash"] and out["business_operation_id"]
    _valid(out)
    return out


# ---------------------------------------------------------------- METRICS


def _metrics_setup(client, transport, *, fields=None, headers=None):
    transport.add_spreadsheet(METRICS_SHEET, "Acme metrics (synthetic)", {"Indicadores": {"cells": {
        "A1": "Indicador", "B1": "Valor", "A2": "Meta planejado out", "A3": "Meta realizado out", "B3": 400, "A4": "Variação",
        "A5": "Progresso SMART", "A6": "Meta SMART", "A7": "Leads (sem fonte)"}}})
    _w(client / "sheet-contracts/metrics-sheet.json", {
        "schema_version": "1.0.0", "client_id": CLIENT, "module": "metrics-sheet", "source_id": "acme-metrics",
        "header_expectations": headers or [{"range": "'Indicadores'!A1", "value": "Indicador"}, {"range": "'Indicadores'!B1", "value": "Valor"}],
        "metrics": {"quarter_id": "2026-Q4", "fields": fields or [
            {"field": "media.2026-10.meta_ads.planned_budget", "range": "'Indicadores'!B2", "label": "Meta planned Oct"},
            {"field": "media.2026-10.meta_ads.actual_spend", "range": "'Indicadores'!B3", "label": "Meta spend Oct"},
            {"field": "media.2026-10.meta_ads.variance_value", "range": "'Indicadores'!B4", "label": "Meta variance Oct"},
            {"field": "objective.current_value", "range": "'Indicadores'!B5", "label": "objective progress"},
            {"field": "objective.target_value", "range": "'Indicadores'!B6"},
            {"field": "objective.progress_percent", "range": "'Indicadores'!B7"}]}})


def test_metrics_end_to_end(client):
    t = FakeGoogleSheetsTransport()
    _metrics_setup(client, t)
    canonical_before = (client / "quarters/2026-Q4/monitoring.json").read_bytes()
    pv = smx.prepare(t, client_dir=client, client_id=CLIENT)
    assert pv["status"] == "PATCH_READY" and t.write_calls == []
    assert "Meta spend Oct: 400 -> 1069.07" in pv["human_preview"]
    assert pv["details"]["not_available"] == ["objective.progress_percent"]  # never written as 0
    _run(t, client, pv)
    cells = t._books[METRICS_SHEET]["sheets"]["Indicadores"]["cells"]
    assert cells[(4, 2)]["value"] == -930.93 and cells[(3, 2)]["value"] == 1069.07
    assert cells.get((7, 2), {"value": None})["value"] in (None, "")  # NOT_AVAILABLE is never written as 0
    again = smx.prepare(t, client_dir=client, client_id=CLIENT)
    assert again["status"] == "NO_CHANGE" and sh.execute(t, client_dir=client, business_preview=again, approval=None)["status"] == "NO_CHANGE"
    assert (client / "quarters/2026-Q4/monitoring.json").read_bytes() == canonical_before  # the sheet never feeds canonical


@pytest.mark.parametrize("case", ["no_contract", "header_changed", "formula_cell", "tab_missing"])
def test_metrics_config_and_conflicts(client, case):
    t = FakeGoogleSheetsTransport()
    if case == "no_contract":
        assert smx.prepare(t, client_dir=client, client_id=CLIENT)["status"] == "CONFIG_REQUIRED"
        return
    _metrics_setup(client, t)
    sheet = t._books[METRICS_SHEET]["sheets"]["Indicadores"]["cells"]
    if case == "header_changed":
        sheet[(1, 2)] = {"value": "Valor (R$)", "formula": None}
    elif case == "formula_cell":
        sheet[(3, 2)] = {"value": 0, "formula": "=SUM(C3:D3)"}
    else:
        contract = json.loads((client / "sheet-contracts/metrics-sheet.json").read_text(encoding="utf-8"))
        for f in contract["metrics"]["fields"]:
            f["range"] = f["range"].replace("Indicadores", "Inexistente")
        contract["header_expectations"] = []
        _w(client / "sheet-contracts/metrics-sheet.json", contract)
    pv = smx.prepare(t, client_dir=client, client_id=CLIENT)
    assert pv["status"] == "CONFLICT_REVIEW_REQUIRED", pv
    assert t.write_calls == []


# ---------------------------------------------------------------- PLAYBOOK


def _playbook_setup(client, transport):
    template = {"A1": "PLAYBOOK", "A3": "AÇÕES CONFIRMADAS", "A9": "RECOMENDAÇÕES", "A15": "CONFIRMAÇÃO DO CLIENTE", "A21": "DEPENDÊNCIAS", "A27": "DECISÕES"}
    transport.add_spreadsheet(PLAYBOOK_SHEET, "Acme playbook (synthetic)", {"Modelo": {"cells": template}})
    _w(client / "sheet-contracts/operational-playbook.json", {
        "schema_version": "1.0.0", "client_id": CLIENT, "module": "operational-playbook", "source_id": "acme-playbook",
        "header_expectations": [{"range": "'Playbook 2026-10'!A1", "value": "PLAYBOOK"}],
        "playbook": {"template_tab": "Modelo", "target_tab": "Playbook 2026-10", "sections": {
            "CONFIRMED_ACTION": "'Playbook 2026-10'!A4:D8", "RECOMMENDATION": "'Playbook 2026-10'!A10:D14",
            "CLIENT_CONFIRMATION_REQUIRED": "'Playbook 2026-10'!A16:D20", "DEPENDENCY": "'Playbook 2026-10'!A22:D26",
            "DECISION_REQUIRED": "'Playbook 2026-10'!A28:D32"}}})
    _w(client / "tasks.json", {"schema_version": "1.0.0", "client_id": CLIENT, "updated_at": "2026-10-02T10:00:00Z", "tasks": [
        {"task_id": "t-acme-1", "client_id": CLIENT, "quarter_id": "2026-Q4", "title": "[synthetic] Ajustar landing page", "description": "d",
         "raised_at": "2026-10-02", "due_at": "2026-10-15", "status": "pending", "completed_at": None, "ekyte_url": None, "evidence_ids": [],
         "origin": {"type": "manual", "evidence_ids": []}}]})
    base = {"client_id": CLIENT, "quarter_id": "2026-Q4", "source": {"workflow": "replan-client", "source_item_id": "x", "source_artifact_id": "x", "source_artifact_hash": "a" * 64},
            "created_at": "2026-10-02T10:00:00Z", "updated_at": "2026-10-02T10:00:00Z", "approval": None, "external": None, "evidence_ids": [],
            "receipt_refs": [], "materialized_ref": None, "superseded_by": None, "supersedes": [], "notes": None}
    _w(client / "operations.json", {"schema_version": "1.0.0", "client_id": CLIENT, "updated_at": "2026-10-02T10:00:00Z", "operations": [
        {**base, "operation_id": "op-sched", "type": "scheduled", "statement": "[synthetic] Revisar relatório", "status": "scheduled",
         "scheduled_for": "2026-10-20", "deferred_until": None},
        {**base, "operation_id": "op-decide", "type": "decision_pending", "statement": "[synthetic] Decidir verba de novembro", "status": "pending",
         "scheduled_for": None, "deferred_until": None},
        {**base, "operation_id": "op-dep", "type": "deferred", "statement": "[synthetic] Escalar campanha", "status": "deferred",
         "scheduled_for": None, "deferred_until": {"type": "after_task", "reference_id": "t-acme-1", "description": "após a landing page"}}]})


SEASONAL = [{"element_id": "seas-1", "classification": "PLANNING_RECOMMENDATION", "statement": "[synthetic] Ação na última semana do mês",
             "date": "última semana do mês"}]


def test_playbook_end_to_end(client):
    t = FakeGoogleSheetsTransport()
    _playbook_setup(client, t)
    items = spb.collect_items(client, "2026-Q4", SEASONAL)
    by = {s: [i["reference"] for i in items if i["section"] == s] for s in spb.SECTIONS}
    assert by == {"CONFIRMED_ACTION": ["t-acme-1", "op-sched"], "RECOMMENDATION": ["seas-1"], "CLIENT_CONFIRMATION_REQUIRED": [],
                  "DEPENDENCY": ["op-dep"], "DECISION_REQUIRED": ["op-decide"]}
    assert [i["date"] for i in items if i["reference"] == "seas-1"] == [""]  # "last week of the month" never becomes a date

    pv = spb.prepare(t, client_dir=client, client_id=CLIENT, items=items)
    assert pv["details"]["phase"] == "duplicate" and pv["human_preview"][0].startswith("create sheet: YES")
    _run(t, client, pv, 1)
    pv2 = spb.prepare(t, client_dir=client, client_id=CLIENT, items=items)
    assert pv2["details"]["phase"] == "content" and pv2["human_preview"][0].startswith("create sheet: NO")
    _run(t, client, pv2, 2)
    tabs = [s["title"] for s in t.get_spreadsheet_metadata(PLAYBOOK_SHEET)["sheets"]]
    assert tabs == ["Modelo", "Playbook 2026-10"]  # duplicated exactly once
    cells = t._books[PLAYBOOK_SHEET]["sheets"]["Playbook 2026-10"]["cells"]
    assert cells[(4, 1)]["value"] == "[synthetic] Ajustar landing page" and cells[(4, 2)]["value"] == "2026-10-15"
    assert cells[(10, 1)]["value"] == "[synthetic] Ação na última semana do mês"
    assert cells.get((10, 2), {"value": None})["value"] in (None, "")  # no invented date
    again = spb.prepare(t, client_dir=client, client_id=CLIENT, items=items)
    assert again["status"] == "NO_CHANGE"
    assert [s["title"] for s in t.get_spreadsheet_metadata(PLAYBOOK_SHEET)["sheets"]] == tabs  # retry never duplicates


def test_playbook_approved_recommendation_and_manual_copies(client):
    t = FakeGoogleSheetsTransport()
    _playbook_setup(client, t)
    items = spb.collect_items(client, "2026-Q4", SEASONAL, approved_recommendation_ids=["seas-1"])
    assert [i["section"] for i in items if i["reference"] == "seas-1"] == ["CONFIRMED_ACTION"]
    t._books[PLAYBOOK_SHEET]["sheets"]["Playbook 2026-10"] = dict(t._books[PLAYBOOK_SHEET]["sheets"]["Modelo"], sheet_id=2001, index=1)
    pv = spb.prepare(t, client_dir=client, client_id=CLIENT, items=items)
    assert pv["status"] == "CONFLICT_REVIEW_REQUIRED" and pv["problems"][0]["code"] == "TARGET_EXISTS_UNTRACKED"


# ---------------------------------------------------------------- CREATIVE


def _creative_report(temp_workspace):
    from tests.intelligence import test_document_winning_creative as dwc

    root = temp_workspace
    for name, data in (("private/clients/synth-alpha/creatives/winner-a.png", dwc._png(1080, 1350)),):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (root / "clients/synth-alpha").mkdir(parents=True, exist_ok=True)
    (root / "clients/synth-alpha/client.json").write_text(json.dumps({"schema_version": "1.0.0", "client_id": "synth-alpha", "display_name": "x", "status": "active"}), encoding="utf-8")
    brief = dwc._brief(metrics=[m for m in dwc.FULL_METRICS if m["metric"] != "Vendas"])
    report = dwc._report(dwc._ctx(root, brief))
    report = json.loads(json.dumps(report).replace("synth-alpha", CLIENT))
    return report


def _creative_setup(client, transport):
    transport.add_spreadsheet(CREATIVE_SHEET, "Acme creatives (synthetic)", {"Criativos": {"row_count": 20, "cells": {
        "A1": "Chave", "B1": "Criativo", "C1": "Plataforma", "D1": "Período", "E1": "Investimento", "F1": "Vendas", "G1": "Hipótese", "H1": "Não generalizar", "I1": "Revisão"}}})
    _w(client / "sheet-contracts/creative-performance-export.json", {
        "schema_version": "1.0.0", "client_id": CLIENT, "module": "creative-performance-export", "source_id": "acme-creative",
        "header_expectations": [{"range": "'Criativos'!A1", "value": "Chave"}],
        "creative": {"tab": "Criativos", "first_row": 2, "last_row": 10, "columns": {
            "row_key": "A", "creative_id": "B", "platform": "C", "period": "D", "metric.investimento": "E", "metric.vendas": "F",
            "replication_hypothesis": "G", "do_not_generalize": "H", "report_revision": "I"}}})


def test_creative_export_insert_no_change_update(client, temp_workspace):
    t = FakeGoogleSheetsTransport()
    _creative_setup(client, t)
    report = _creative_report(temp_workspace)
    pv = sce.prepare(t, client_dir=client, client_id=CLIENT, report=report)
    assert pv["details"]["row_action"] == "INSERT" and pv["human_preview"][0].startswith("insert: row 2")
    _run(t, client, pv)
    cells = t._books[CREATIVE_SHEET]["sheets"]["Criativos"]["cells"]
    assert cells[(2, 1)]["value"] == f"{CLIENT}:winner-a" and cells[(2, 6)]["value"] == sh.NOT_AVAILABLE  # missing metric is never 0
    assert sce.prepare(t, client_dir=client, client_id=CLIENT, report=report)["status"] == "NO_CHANGE"
    revised = json.loads(json.dumps(report))
    revised["do_not_generalize"][0]["statement"] = "[synthetic] revised caution"
    pv3 = sce.prepare(t, client_dir=client, client_id=CLIENT, report=revised)
    assert pv3["details"]["row_action"] == "UPDATE_EXISTING" and pv3["details"]["row"] == 2
    _run(t, client, pv3, 2)
    keys = [c["value"] for (r, col), c in cells.items() if col == 1 and r >= 2 and c["value"]]
    assert keys == [f"{CLIENT}:winner-a"]


def test_creative_duplicate_key_is_conflict(client, temp_workspace):
    t = FakeGoogleSheetsTransport()
    _creative_setup(client, t)
    for r in (2, 3):
        t._books[CREATIVE_SHEET]["sheets"]["Criativos"]["cells"][(r, 1)] = {"value": f"{CLIENT}:winner-a", "formula": None}
    pv = sce.prepare(t, client_dir=client, client_id=CLIENT, report=_creative_report(temp_workspace))
    assert pv["status"] == "CONFLICT_REVIEW_REQUIRED" and pv["problems"][0]["code"] == "DUPLICATE_ROW_KEY"


# ---------------------------------------------------------------- GUARDS

BUSINESS_MODULES = ["scripts/lib/sheet_modules.py", "scripts/lib/sheet_metrics.py", "scripts/lib/sheet_playbook.py", "scripts/lib/sheet_creative_export.py"]
FORBIDDEN_IMPORTS = ("googleapiclient", "google.", "google_auth", "requests", "httplib2", "urllib", "http.client",
                     "scripts.lib.google_sheets_transport", "scripts.lib.google_drive_transport", "scripts.lib.google_sheets_auth")


@pytest.mark.parametrize("path", BUSINESS_MODULES)
def test_business_modules_never_touch_google_transport_directly(path):
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in imported if m.startswith(FORBIDDEN_IMPORTS) or m in ("google",)], imported
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "transport"]
    assert calls == [], "business modules pass the transport through; they never call it"


# ---------------------------------------------------------------- APPROVAL / STALE


def test_apply_requires_approval_and_is_stale_safe(client):
    t = FakeGoogleSheetsTransport()
    _metrics_setup(client, t)
    pv = smx.prepare(t, client_dir=client, client_id=CLIENT)
    no_approval = sh.execute(t, client_dir=client, business_preview=pv, approval=None)
    assert no_approval["status"] == "CONFLICT_REVIEW_REQUIRED" and t.write_calls == [] and no_approval["google_receipt_ref"] is None
    approval = _approve(pv, 9)
    t._books[METRICS_SHEET]["sheets"]["Indicadores"]["cells"][(3, 2)] = {"value": 777, "formula": None}  # a human edited the sheet
    out = sh.execute(t, client_dir=client, business_preview=pv, approval=approval)
    assert out["status"] == "CONFLICT_REVIEW_REQUIRED" and t.write_calls == []
    assert any(p["code"] in ("STALE_PREVIEW", "STALE_APPROVAL") for p in out["problems"])
    assert t._books[METRICS_SHEET]["sheets"]["Indicadores"]["cells"][(3, 2)]["value"] == 777  # never silently overwritten


def test_doctor_validates_sheet_contracts(client):
    from scripts import doctor
    from scripts.lib.workspace import resolve_workspace
    _w(client / "sheet-contracts/metrics-sheet.json", {"schema_version": "1.0.0", "client_id": CLIENT, "module": "metrics-sheet", "source_id": "acme-metrics"})
    ws = resolve_workspace(required=True, override=str(client.parent.parent))
    results = doctor.check_client_workspace_integrity(ws, doctor._schema_registry())
    assert results["Canonical memory"][0] == "FAIL"  # metrics module without a metrics mapping
