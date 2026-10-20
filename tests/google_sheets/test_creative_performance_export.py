"""export-creative-performance-to-google-sheet — synthetic end-to-end over
FakeGoogleSheetsTransport, plus the generic add_sheet / BU-destination /
chunked-read support it relies on. No real client, sheet or network."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.lib import approval as ap
from scripts.lib import creative_performance as cp
from scripts.lib import creative_performance_sheet_export as ex
from scripts.lib.a1_notation import cell_a1, col_to_letters, quote_sheet_title
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch
from scripts.lib.google_sheets_sources import load_bu_sources
from scripts.lib.google_sheets_transport import FakeGoogleSheetsTransport, GoogleApiSheetsTransport
from tests.intelligence.test_document_winning_creative import ALPHA, BETA, OUT_SCHEMA, _brief, _ctx, _png, _report, _write, ws  # noqa: F401
from tests.intelligence.test_document_winning_creative_row_selection import MSG, _row_ctx, _row_report

SHEET_ID = "fake-creative-board-0001"
SHEET_TITLE = "Synthetic Creative Board"
GAMMA = "synth-gamma"
RV = Draft202012Validator(json.loads(ex.REPORT_SCHEMA_PATH.read_text(encoding="utf-8")))
EXPORT_SCHEMA = Draft202012Validator(json.loads(ex.OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")))
TITLES = {t["key"]: t["title"] for t in ex.TABS}


def _bu_registry(allowed=(ALPHA, BETA)):
    return {"schema_version": "1.0.0", "registry_scope": "bu", "client_id": "bu", "sources": [{
        "source_id": "synth-creative-board", "type": "google_sheet", "scope": "bu", "contains_multiple_clients": True,
        "allowed_client_ids": list(allowed), "description": "synthetic consolidated board",
        "google_sheet": {"spreadsheet_id": SHEET_ID, "expected_title": SHEET_TITLE, "writable": True}}]}


@pytest.fixture
def board(ws):
    """Workspace with 2 alpha reports, 1 beta report (real zero), 1 gamma report (not allowed), a BU registry and a fake board."""
    ctx = _row_ctx(ws)
    first = _row_report(ctx)
    first["learning_summary"] = cp.learning_counts(first)
    cp.write_report(ws, first, ctx, schema_validator=OUT_SCHEMA)
    ctx2 = _ctx(ws, _brief(creative_id="winner-c"))
    cp.write_report(ws, _report(ctx2), ctx2, schema_validator=OUT_SCHEMA)
    beta = _ctx(ws, _brief(client_id=BETA, creative_id="beta-1", assets=[{"path": "private/clients/synth-beta/creatives/beta.png", "kind": "image"}],
                           metrics=[{"metric": "Investimento", "value": 80.0, "unit": "brl", "source": "operator"},
                                    {"metric": "Vendas", "value": 0, "unit": "count", "source": "operator"}], operator_instructions=[]))
    cp.write_report(ws, _report(beta), beta, schema_validator=OUT_SCHEMA)
    _write(ws / "clients" / GAMMA / "client.json", {"schema_version": "1.0.0", "client_id": GAMMA})
    _write(ws / "private/clients/synth-gamma/creatives/g.png", _png(10, 20))
    gamma = _ctx(ws, _brief(client_id=GAMMA, creative_id="gamma-1", assets=[{"path": "private/clients/synth-gamma/creatives/g.png", "kind": "image"}], metrics=[]))
    cp.write_report(ws, _report(gamma), gamma, schema_validator=OUT_SCHEMA)
    _write(ws / "bu" / "sources.json", _bu_registry())
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SHEET_ID, SHEET_TITLE, {"OUTRA ABA": {"cells": {"A1": "anotação manual", "B2": "=1+1"}}})
    return ws, t


def _req(**over):
    r = {"schema_version": "1.0.0", "export_id": "synth-board", "destination": {"source_id": "synth-creative-board"}, "scope": {"client_ids": [ALPHA, BETA]}}
    r.update(over)
    return r


def _preview(t, ws, req):
    out = ex.preview_export(t, workspace_root=ws, request=req, bu_sources=load_bu_sources(ws), report_validator=RV)
    assert not list(EXPORT_SCHEMA.iter_errors(out)), list(EXPORT_SCHEMA.iter_errors(out))[:2]
    return out


def _approve(preview):
    pv = preview["patch_preview"]
    cand = build_patch_approval_candidate(pv, approval_id=f"appr-{pv['patch_id']}", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    return ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=[pv["patch_id"]])


def _apply(t, ws, req, preview, approval=None):
    out = ex.apply_export(t, workspace_root=ws, request=req, bu_sources=load_bu_sources(ws), approved_export_preview=preview,
                          approval=approval if approval is not None else _approve(preview), report_validator=RV)
    assert not list(EXPORT_SCHEMA.iter_errors(out))
    return out


def _export(t, ws, req):
    results = []
    for _ in range(2):
        pv = _preview(t, ws, req)
        if pv["status"] == "no_change":
            break
        assert pv["status"] == "success", (pv["conflicts"], pv["errors"])
        results.append((pv, _apply(t, ws, req, pv)))
        assert results[-1][1]["status"] == "success", (results[-1][1]["conflicts"], results[-1][1]["errors"])
    return results


def _rows(t, key):
    tab = ex.TAB_BY_KEY[key]
    meta = {s["title"]: s for s in t.get_spreadsheet_metadata(SHEET_ID)["sheets"]}[tab["title"]]
    [block] = t.read_values(SHEET_ID, [f"{quote_sheet_title(tab['title'])}!A1:{col_to_letters(len(tab['columns']))}{meta['row_count']}"])
    header, *data = block["values"]
    return header, [dict(zip(header, r)) for r in data if any(v not in (None, "") for v in r)]


def _report_json(ws, cid, creative):
    return json.loads((ws / f"context/generated/{cid}/creative-performance/{creative}/creative-performance.json").read_text(encoding="utf-8"))


# 1, 20, 24, 25 --------------------------------------------------------------------------------------


def test_single_report_full_cycle_structure_then_content(board):
    ws, t = board
    req = _req(scope={"report_paths": ["context/generated/synth-alpha/creative-performance/winner-a/creative-performance.json"]})
    pv = _preview(t, ws, req)
    assert pv["phase"] == "structure" and pv["status"] == "success" and pv["tabs_to_create"] == [x["title"] for x in ex.TABS]
    assert pv["summary"]["basis"] == "planned_after_structure" and pv["summary"]["inserts"]["creatives"] == 1
    assert t.write_calls == [] and t.structure_calls == [] and t.clear_calls == []  # preview never writes
    assert [o["type"] for o in pv["patch"]["operations"]] == ["add_sheet"] * 5 and pv["patch"]["data_client_ids"] == [ALPHA]
    res = _apply(t, ws, req, pv)
    assert res["status"] == "success" and res["apply_result"]["verification"]["add_sheet"]["all_present_and_empty"]
    assert len(t.structure_calls) == 1 and res["post_apply"]["next_phase"] == "content"
    sheets = {s["title"]: s for s in t.get_spreadsheet_metadata(SHEET_ID)["sheets"]}
    assert sheets[TITLES["creatives"]]["column_count"] == len(ex.TAB_BY_KEY["creatives"]["columns"]) and sheets[TITLES["creatives"]]["frozen_row_count"] == 1
    pv2 = _preview(t, ws, req)
    assert pv2["phase"] == "content" and pv2["headers_to_create"] == [x["title"] for x in ex.TABS]
    assert t.write_calls == []
    res2 = _apply(t, ws, req, pv2)
    assert res2["status"] == "success" and res2["apply_result"]["verification"]["targets_match"]
    assert res2["post_apply"]["content_converged"] is True  # re-read after apply: every exported row is NO_CHANGE
    header, rows = _rows(t, "creatives")
    assert header == list(ex.TAB_BY_KEY["creatives"]["columns"]) and [(r["client_id"], r["creative_id"]) for r in rows] == [(ALPHA, "winner-a")]


# 2, 14 ----------------------------------------------------------------------------------------------


def test_multiple_clients_and_isolation(board):
    ws, t = board
    _export(t, ws, _req())
    _, rows = _rows(t, "creatives")
    assert sorted((r["client_id"], r["creative_id"]) for r in rows) == [(ALPHA, "winner-a"), (ALPHA, "winner-c"), (BETA, "beta-1")]
    assert not any(GAMMA in json.dumps(_rows(t, k)[1]) for k in TITLES)  # gamma never scoped
    blocked = _preview(t, ws, _req(scope={"client_ids": [ALPHA, GAMMA]}))
    assert blocked["status"] == "error" and any(e["code"] == "CLIENT_NOT_ALLOWED" for e in blocked["errors"])
    mixed = _preview(t, ws, _req(scope={"client_ids": [ALPHA], "report_paths": ["context/generated/synth-beta/creative-performance/beta-1/creative-performance.json"]}))
    assert any(e["code"] == "CLIENT_ISOLATION" for e in mixed["errors"])
    with pytest.raises(ex.ExportError):
        ex.discover_reports(ws, {"client_ids": ["bu"]})
    with pytest.raises(ex.ExportError):
        ex.discover_reports(ws, {})  # never a silent "all clients"


# 3, 4 -----------------------------------------------------------------------------------------------


def test_second_run_is_no_change_without_writes(board):
    ws, t = board
    _export(t, ws, _req())
    writes = (len(t.write_calls), len(t.clear_calls), len(t.structure_calls))
    again = _preview(t, ws, _req())
    assert again["status"] == "no_change" and again["patch"] is None
    assert all(v == 0 for v in again["summary"]["inserts"].values()) and sum(again["summary"]["no_changes"].values()) > 0
    assert (len(t.write_calls), len(t.clear_calls), len(t.structure_calls)) == writes
    assert all(len(_rows(t, k)[1]) == len({tuple(r[c] for c in ex.TAB_BY_KEY[k]["key_columns"]) for r in _rows(t, k)[1]}) for k in TITLES)  # no duplicates


# 5 --------------------------------------------------------------------------------------------------


def test_regenerated_report_is_an_update_with_changed_cells(board):
    ws, t = board
    _export(t, ws, _req())
    path = ws / "context/generated/synth-alpha/creative-performance/winner-c/creative-performance.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["replication_hypotheses"][0]["test_suggestion"] = "Novo teste controlado sintético."
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pv = _preview(t, ws, _req())
    assert pv["status"] == "success" and pv["summary"]["updates"]["hypotheses"] == 1 and sum(pv["summary"]["inserts"].values()) == 0
    upd = next(c for c in pv["changes"] if c["tab"] == "hypotheses")
    assert upd["action"] == "UPDATE" and {c["column"] for c in upd["cells_changed"]} == {"teste_sugerido", "report_sha256"}
    creative_upd = next(c for c in pv["changes"] if c["tab"] == "creatives")
    assert {c["column"] for c in creative_upd["cells_changed"]} == {"report_sha256"}
    res = _apply(t, ws, _req(), pv)
    assert res["status"] == "success" and res["post_apply"]["content_converged"]
    _, rows = _rows(t, "hypotheses")
    assert [r["teste_sugerido"] for r in rows if r["creative_id"] == "winner-c"] == ["Novo teste controlado sintético."]


def test_removed_item_becomes_orphan_warning_never_deleted(board):
    ws, t = board
    _export(t, ws, _req())
    path = ws / "context/generated/synth-alpha/creative-performance/winner-c/creative-performance.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["do_not_generalize"] = []
    report["learning_summary"]["DO_NOT_GENERALIZE"] = 0
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    pv = _preview(t, ws, _req())
    assert pv["summary"]["orphans"]["do_not_generalize"] == 1 and any(w["code"] == "ORPHAN_ROW" for w in pv["warnings"])
    assert not any(o["type"] == "clear_value" and "NÃO GENERALIZAR" in o["range"] for o in pv["patch"]["operations"])


# 6, 7, 8, 9, 22 -------------------------------------------------------------------------------------


def test_metric_cells_empty_zero_derived_and_result_type(board):
    ws, t = board
    _export(t, ws, _req())
    header, rows = _rows(t, "creatives")
    assert "faturamento" not in header and "revenue" not in header  # revenue is never part of this view
    by = {r["creative_id"]: r for r in rows}
    beta = by["beta-1"]
    assert beta["vendas"] == 0 and beta["investimento"] == 80.0  # a real zero stays zero
    assert beta["cliques"] in (None, "") and beta["ctr_percent"] in (None, "") and beta["impressoes"] in (None, "")  # absent -> empty, never 0
    a = by["winner-a"]
    rep = _report_json(ws, ALPHA, "winner-a")
    derived = {d["metric_key"]: d["value"] for d in rep["derived_metrics"]}
    assert a["cpm"] == derived["cpm"] and a["metricas_derivadas"] == "frequencia, cpm"  # the report's value, flagged DERIVED
    assert a["investimento"] == 216 and "investimento" not in a["metricas_derivadas"]  # provided
    assert a["resultado_valor"] == 30 and a["resultado_tipo_original"] == MSG and a["resultado_rotulo"] == "conversa por mensagem iniciada"
    assert a["anuncio"] == "ad-b" and a["conjunto"] == "set-1" and a["post_url"] == "https://social.example/p/SYNTH123/"
    assert "HETEROGENEOUS_RESULT_TYPES" in a["avisos"] and a["origem_vencedor"] == "OPERATOR_DECLARED"


# 10, 11, 12, 13 -------------------------------------------------------------------------------------


def test_learning_classes_stay_in_their_own_tabs(board):
    ws, t = board
    _export(t, ws, _req())
    rep = _report_json(ws, ALPHA, "winner-c")
    _, patterns = _rows(t, "patterns")
    mine = [p for p in patterns if p["creative_id"] == "winner-c"]
    assert sorted(p["pattern_id"] for p in mine) == sorted(e["element_id"] for e in rep["observed_elements"] if e["status"] == "OBSERVED")
    assert {p["status"] for p in patterns} == {"OBSERVED"}
    _, hyps = _rows(t, "hypotheses")
    assert {h["classe"] for h in hyps} == {"REPLICATION_HYPOTHESIS"}
    h_text = rep["replication_hypotheses"][0]["statement"]
    assert [h["hipotese"] for h in hyps if h["creative_id"] == "winner-c"] == [h_text]
    assert h_text not in json.dumps(patterns, ensure_ascii=False) and h_text not in json.dumps(_rows(t, "creatives")[1], ensure_ascii=False)
    _, dng = _rows(t, "do_not_generalize")
    assert {d["classe"] for d in dng} == {"DO_NOT_GENERALIZE"} and len([d for d in dng if d["creative_id"] == "winner-c"]) == len(rep["do_not_generalize"])
    _, sources = _rows(t, "sources")
    assert all(not str(s["referencia"]).startswith(("/", "~")) and ":\\" not in str(s["referencia"]) for s in sources)
    assert all(s["referencia"].startswith("private/clients/") for s in sources)
    for bad in ("/home/user/x.png", "C:\\x\\y.png", "E:/x.png", "../x.png", "a/../b", "~/x"):
        assert ex._safe_relative(bad) is None


# 15 -------------------------------------------------------------------------------------------------


def test_unmanaged_tab_stays_intact(board):
    ws, t = board
    before = copy.deepcopy(t._books[SHEET_ID]["sheets"]["OUTRA ABA"])
    _export(t, ws, _req())
    assert t._books[SHEET_ID]["sheets"]["OUTRA ABA"]["cells"] == before["cells"]


# 16, 17 ---------------------------------------------------------------------------------------------


def test_incompatible_header_and_duplicate_key_block(board):
    ws, t = board
    t2 = FakeGoogleSheetsTransport()
    t2.add_spreadsheet(SHEET_ID, SHEET_TITLE, {TITLES["hypotheses"]: {"cells": {"A1": "cliente", "B1": "hipótese"}, "column_count": 12, "row_count": 100}})
    pv = _preview(t2, ws, _req())
    assert pv["status"] == "conflict" and any(c["code"] == "SCHEMA_MISMATCH" for c in pv["conflicts"]) and pv["patch"] is None
    cols = ex.TAB_BY_KEY["creatives"]["columns"]
    cells = {f"{col_to_letters(i + 1)}1": c for i, c in enumerate(cols)}
    for row in (2, 3):
        cells.update({f"A{row}": ALPHA, f"B{row}": "winner-a", f"{col_to_letters(len(cols))}{row}": "x"})
    t3 = FakeGoogleSheetsTransport()
    t3.add_spreadsheet(SHEET_ID, SHEET_TITLE, {TITLES["creatives"]: {"cells": cells, "column_count": len(cols), "row_count": 100}})
    pv = _preview(t3, ws, _req())
    assert any(c["code"] == "DUPLICATE_LOGICAL_KEY" for c in pv["conflicts"]) and t3.write_calls == [] and t3.structure_calls == []
    t4 = FakeGoogleSheetsTransport()
    t4.add_spreadsheet(SHEET_ID, SHEET_TITLE, {TITLES["creatives"]: {"cells": {**{f"{col_to_letters(i + 1)}1": c for i, c in enumerate(cols)}, "C2": "orphan"},
                                                                       "column_count": len(cols), "row_count": 100}})
    assert any(c["code"] == "CORRUPTED_KEY" for c in _preview(t4, ws, _req())["conflicts"])


# 18, 19 ---------------------------------------------------------------------------------------------


def test_stale_preview_and_changed_source_report_block_apply(board):
    ws, t = board
    req = _req()
    first = _preview(t, ws, req)
    _apply(t, ws, req, first)
    pv = _preview(t, ws, req)
    assert pv["phase"] == "content"
    t.set_cell(SHEET_ID, TITLES["creatives"], "A2", "intruso")  # the sheet moved after the preview
    stale = _apply(t, ws, req, pv)
    assert stale["status"] == "conflict" and stale["conflicts"][0]["code"] in ("STALE_PREVIEW", "CORRUPTED_KEY") and t.write_calls == []
    t.set_cell(SHEET_ID, TITLES["creatives"], "A2", None)
    pv = _preview(t, ws, req)
    path = ws / "context/generated/synth-beta/creative-performance/beta-1/creative-performance.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # same content, different file bytes
    changed = _apply(t, ws, req, pv)
    assert changed["status"] == "conflict" and changed["conflicts"][0]["code"] == "SOURCE_REPORT_CHANGED" and t.write_calls == []
    other = _preview(t, ws, req)
    wrong_approval = _approve(first)
    blocked = _apply(t, ws, req, other, approval=wrong_approval)
    assert blocked["status"] == "error" and t.write_calls == []


def test_formula_inside_a_managed_cell_is_never_destroyed(board):
    ws, t = board
    _export(t, ws, _req())
    tab = ex.TAB_BY_KEY["hypotheses"]
    col = col_to_letters(tab["columns"].index("teste_sugerido") + 1)
    _, rows = _rows(t, "hypotheses")
    row = 2 + next(i for i, r in enumerate(rows) if r["creative_id"] == "winner-c")
    t.set_cell(SHEET_ID, tab["title"], f"{col}{row}", "=CONCAT(\"a\";\"b\")")  # someone put a formula in a managed cell
    path = ws / "context/generated/synth-alpha/creative-performance/winner-c/creative-performance.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["replication_hypotheses"][0]["test_suggestion"] = "Outra sugestão sintética."
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    writes = len(t.write_calls)
    pv = _preview(t, ws, _req())
    assert pv["status"] == "conflict" and any(c["code"] == "FORMULA_OVERWRITE_BLOCKED" for c in pv["conflicts"])
    assert len(t.write_calls) == writes


# 21 -------------------------------------------------------------------------------------------------


def test_markdown_is_never_the_source(board):
    ws, t = board
    for md in ws.glob("context/generated/*/creative-performance/*/creative-performance.md"):
        md.write_text("corrompido — não é JSON", encoding="utf-8")
    _write(ws / "context/generated/synth-alpha/creative-performance/only-md/creative-performance.md", "# só markdown")
    _export(t, ws, _req())
    _, rows = _rows(t, "creatives")
    assert "only-md" not in {r["creative_id"] for r in rows} and len(rows) == 3
    src = Path(ex.__file__).read_text(encoding="utf-8")
    assert ".md" not in src.replace("SKILL.md", "")


# 23 -------------------------------------------------------------------------------------------------


def test_no_google_library_is_required():
    for path in (Path(ex.__file__), ex.REPO_ROOT / "scripts" / "creative_performance_sheet_export.py"):
        text = path.read_text(encoding="utf-8")
        assert "import googleapiclient" not in text and "from google" not in text and "import google." not in text
    cli = (ex.REPO_ROOT / "scripts" / "creative_performance_sheet_export.py").read_text(encoding="utf-8")
    assert "    from scripts.lib.google_sheets_auth import build_real_transport" in cli  # lazy: only preview/apply touch auth


def test_dry_run_cli_plans_locally_without_transport(board, capsys):
    ws, _ = board
    from scripts import creative_performance_sheet_export as cli
    assert cli.main(["--workspace", str(ws), "dry-run", "--client", ALPHA, "--client", BETA]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["inserts"]["creatives"] == 3 and not out["errors"] and not out["conflicts"]


# generic support: add_sheet, BU isolation, chunked reads --------------------------------------------


def _bu_patch(ops, **over):
    p = {"schema_version": "1.0.0", "patch_id": "synth-add", "client_id": "bu", "source_id": "synth-creative-board", "data_client_ids": [ALPHA], "operations": ops}
    p.update(over)
    return p


def _add(title="NOVA", **kw):
    return {"op_id": f"add-{title}", "type": "add_sheet", "new_sheet_title": title, "row_count": 50, "column_count": 30, **kw}


def test_add_sheet_operation_generic(repo_root, validate):
    reg = _bu_registry()
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SHEET_ID, SHEET_TITLE, {"EXISTENTE": {"cells": {"A1": "x"}}})
    patch = _bu_patch([_add("NOVA", frozen_row_count=1), _add("OUTRA")])
    assert not validate(patch, repo_root / "schemas/google-sheet-patch.schema.json")
    pv = preview_patch(t, client_id="bu", patch=patch, sources_doc=reg)
    assert pv["status"] == "success" and pv["sheet_plan"]["operation"] == "add_sheet" and t.structure_calls == []
    assert not validate(pv, repo_root / "skills/update-google-sheet/output.schema.json")
    cand = build_patch_approval_candidate(pv, approval_id="a1", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    appr = ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=["synth-add"])
    res = apply_patch(t, client_id="bu", patch=patch, sources_doc=reg, approved_preview=pv, approval=appr)
    assert res["status"] == "success" and len(t.structure_calls) == 1 and res["receipt"]["effects"][0]["operation"] == "add_sheet"
    assert not validate(res, repo_root / "skills/update-google-sheet/output.schema.json")
    sheets = {s["title"]: s for s in t.get_spreadsheet_metadata(SHEET_ID)["sheets"]}
    assert (sheets["NOVA"]["row_count"], sheets["NOVA"]["column_count"], sheets["NOVA"]["frozen_row_count"]) == (50, 30, 1)
    again = apply_patch(t, client_id="bu", patch=patch, sources_doc=reg, approved_preview=pv, approval=appr)
    assert again["status"] == "no_change" and len(t.structure_calls) == 1  # already the requested empty tabs
    t.set_cell(SHEET_ID, "NOVA", "A1", "conteúdo")
    assert preview_patch(t, client_id="bu", patch=patch, sources_doc=reg)["conflicts"][0]["code"] == "DESTINATION_EXISTS"
    mixed = _bu_patch([_add("X"), {"op_id": "w", "type": "write_value", "range": "'EXISTENTE'!A2", "values": [["y"]]}])
    assert any(e["code"] == "ADD_SHEET_NOT_ALONE" for e in preview_patch(t, client_id="bu", patch=mixed, sources_doc=reg)["errors"])
    assert any(e["code"] == "DUPLICATE_ADD_SHEET" for e in preview_patch(t, client_id="bu", patch=_bu_patch([_add("Y"), dict(_add("Y"), op_id="y2")]), sources_doc=reg)["errors"])


def test_bu_destination_isolation_rules():
    reg = _bu_registry()
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SHEET_ID, SHEET_TITLE, {"A": {}})
    for bad in ({"data_client_ids": None}, {"data_client_ids": [GAMMA]}, {"data_client_ids": ["bu"]}, {"client_id": ALPHA}):
        patch = _bu_patch([_add("Z")], **bad)
        out = preview_patch(t, client_id=patch["client_id"], patch=patch, sources_doc=reg)
        assert out["status"] == "error" and out["errors"][0]["code"] == "CLIENT_ISOLATION", bad
    client_doc = {"schema_version": "1.0.0", "client_id": ALPHA, "sources": [dict(reg["sources"][0], allowed_client_ids=[ALPHA])]}
    out = preview_patch(t, client_id=ALPHA, patch=_bu_patch([_add("Z")], client_id=ALPHA), sources_doc=client_doc)
    assert out["errors"][0]["code"] == "CLIENT_ISOLATION"  # a client's own sources.json can never grant a multi-client write
    fake_bu = dict(client_doc, client_id="bu")
    out = preview_patch(t, client_id="bu", patch=_bu_patch([_add("Z")]), sources_doc=fake_bu)
    assert out["errors"][0]["code"] == "CLIENT_ISOLATION"  # 'bu' without the BU registry is refused


def test_real_transport_add_sheets_and_chunked_reads():
    class _Req:
        def __init__(self, log, kind, kw, resp):
            self.log, self.kind, self.kw, self.resp = log, kind, kw, resp

        def execute(self, num_retries=0):
            self.log.append((self.kind, self.kw))
            return self.resp

    log = []

    class Values:
        def batchGet(self, **kw):
            return _Req(log, "batchGet", kw, {"valueRanges": [{"range": r, "values": [["v"]]} for r in kw["ranges"]]})

    class Sheets:
        def values(self):
            return Values()

        def batchUpdate(self, **kw):
            return _Req(log, "batchUpdate", kw, {"replies": [{"addSheet": {"properties": {"sheetId": 9, "title": "N", "index": 3}}}]})

        def get(self, **kw):
            return _Req(log, "get", kw, {"sheets": [{"properties": {"sheetId": 1, "title": "T", "gridProperties": {"rowCount": 200, "columnCount": 5}},
                                                     "data": [{"startRow": int(r.split("A")[-1]) - 1, "startColumn": 0,
                                                               "rowData": [{"values": [{"userEnteredFormat": {"n": r}}]}]} for r in kw["ranges"]]}]})

    class Svc:
        def spreadsheets(self):
            return Sheets()

    tr = GoogleApiSheetsTransport(service=Svc())
    created = tr.add_sheets("fake-sheet-000000001", [{"title": "N", "row_count": 10, "column_count": 4, "frozen_row_count": 1, "insert_index": None}])
    assert created == [{"sheet_id": 9, "title": "N", "index": 3}]
    assert log[0][1]["body"] == {"requests": [{"addSheet": {"properties": {"title": "N", "gridProperties": {"rowCount": 10, "columnCount": 4, "frozenRowCount": 1}}}}]}
    ranges = [f"'T'!A{i}" for i in range(1, 121)]
    got = tr.read_values("fake-sheet-000000001", ranges)
    assert len(got) == 120 and [len(kw["ranges"]) for k, kw in log if k == "batchGet"] == [50, 50, 20]
    fmts = tr.get_cell_formats("fake-sheet-000000001", ranges)
    assert len(fmts) == 120 and fmts[cell_a1("T", 120, 1)]["user_entered_format"] == {"n": "'T'!A120"}
    fp = tr.get_structure("fake-sheet-000000001", ranges)
    assert len(fp["T"]["cells"]) == 120 and [len(kw["ranges"]) for k, kw in log if k == "get"] == [50, 50, 20, 50, 50, 20]
