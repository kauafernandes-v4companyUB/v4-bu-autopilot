"""document-winning-creative — operator row-selection rule (MAX_RESULTS),
structured result type, post reference and source trace. Synthetic fixtures
only: no real client, ad or export data."""

from __future__ import annotations

import copy
import csv
import io
import json

import pytest

from scripts.lib import creative_performance as cp
from tests.intelligence.test_document_winning_creative import ALPHA, OUT_SCHEMA, _brief, _ctx, _issues, _report, _write, ws  # noqa: F401

EXPORT = "private/clients/synth-alpha/bi/ads-export.csv"
MSG = "actions:onsite_conversion.messaging_conversation_started_7d"
SITE = "conversions:contact_website"
HEADER = ["Início dos relatórios", "Encerramento dos relatórios", "Nome do anúncio", "Nome do conjunto de anúncios", "Resultados",
          "Indicador de resultados", "Custo por resultados", "Valor gasto (BRL)", "Impressões", "Alcance"]
ROWS = [  # file line 2..7
    ["2026-01-01", "2026-01-31", "ad-a", "set-1", "12", MSG, "10.5", "126", "9000", "4000"],
    ["2026-01-01", "2026-01-31", "ad-b", "set-1", "30", MSG, "7.2", "216", "15000", "6000"],
    ["2026-01-01", "2026-01-31", "ad-b", "set-2", "18", MSG, "5", "90", "7000", ""],
    ["2026-01-01", "2026-01-31", "", "", "67", "", "", "480", "33500", "12000"],  # summary row: never a candidate
    ["2026-01-01", "2026-01-31", "ad-c", "set-2", "", "", "", "3.1", "200", "180"],
    ["2026-01-01", "2026-01-31", "ad-d", "set-3", "7", SITE, "6.4", "44.8", "2300", "1900"],
]


def _csv(rows, header=HEADER) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def _selection(**over) -> dict:
    s = {"rule": "MAX_RESULTS", "source": "OPERATOR_RULE", "source_path": EXPORT, "column": "Resultados",
         "result_type_column": "Indicador de resultados", "ad_name_column": "Nome do anúncio",
         "ad_set_name_column": "Nome do conjunto de anúncios", "campaign_name_column": None,
         "metric_columns": [{"metric": "Investimento", "column": "Valor gasto (BRL)", "unit": "brl"},
                            {"metric": "Impressões", "column": "Impressões", "unit": "count"},
                            {"metric": "Alcance", "column": "Alcance", "unit": "count"},
                            {"metric": "Custo por resultados", "column": "Custo por resultados", "unit": "brl"}],
         "notes": "O operador definiu MAX_RESULTS como regra de seleção deste pacote."}
    s.update(over)
    return s


def _row_ctx(ws, rows=ROWS, header=HEADER, selection=None, **brief_over):
    _write(ws / EXPORT, _csv(rows, header))
    over = {"metrics": [], "metric_sources": [{"path": EXPORT}], "metric_row_selection": selection or _selection(),
            "post_reference": {"url": "https://social.example/p/SYNTH123/", "note": None}}
    over.update(brief_over)
    return _ctx(ws, _brief(**over))


def _row_report(ctx: dict) -> dict:
    r = _report(ctx)
    r["metric_row_selection"] = copy.deepcopy(ctx["metric_row_selection"])
    r["post_reference"] = copy.deepcopy(ctx["post_reference"])
    res = next((m for m in ctx["provided_metrics"] if m["label"] == "Resultados"), None)
    if res and res["value"] is not None:
        refs = [res["metric_id"]]
        r["performance_summary"].append({"id": "PF-09", "statement": f"{res['value']:g} resultados na linha selecionada.",
                                         "learning_class": "PERFORMANCE_FACT", "metric_refs": refs, "source_trace": cp.source_trace(ctx, refs)})
    return r


# 1 --------------------------------------------------------------------------------------------------


def test_max_results_selects_the_single_maximum_row(ws):
    ctx = _row_ctx(ws)
    sel = ctx["metric_row_selection"]
    row = sel["selected_row"]
    assert (row["row_number"], row["ad_name"], row["ad_set_name"], row["campaign_name"]) == (3, "ad-b", "set-1", None)
    assert row["result"] == {"value": 30.0, "source_metric_name": "Resultados", "source_result_type": MSG,
                             "normalized_label": "conversa por mensagem iniciada", "normalization_confidence": "HIGH"}
    assert (sel["source"], sel["candidate_count"], sel["next_highest_value"], sel["tied"]) == ("OPERATOR_RULE", 4, 18.0, False)
    assert {x["row_number"]: x["reason"] for x in sel["excluded_rows"]} == {5: "SUMMARY_ROW_WITHOUT_AD_NAME", 6: "EMPTY_OR_INVALID_RESULT"}
    by_label = {m["label"]: m for m in ctx["provided_metrics"]}
    assert by_label["Investimento"]["value"] == 216 and by_label["Investimento"]["source_row"] == 3
    assert by_label["Investimento"]["source_column"] == "Valor gasto (BRL)" and by_label["Investimento"]["provenance"] == "S-02"
    assert _issues(_row_report(ctx), ctx) == []


def test_empty_cell_in_selected_row_is_not_available_never_zero(ws):
    rows = copy.deepcopy(ROWS)
    rows[1][9] = ""  # Alcance empty on the winning row
    ctx = _row_ctx(ws, rows)
    reach = next(m for m in ctx["provided_metrics"] if m["label"] == "Alcance")
    assert reach["value"] is None and reach["status"] == "NOT_AVAILABLE" and "metric:reach" in ctx["required_unknowns"]


def test_column_must_exist(ws):
    with pytest.raises(cp.CreativePerformanceError, match="ROW_SELECTION_COLUMN_MISSING"):
        _row_ctx(ws, selection=_selection(column="Results"))
    ctx = _row_ctx(ws)
    report = _row_report(ctx)
    report["metric_row_selection"]["column"] = "Alcance"
    assert any(i.startswith("ROW_SELECTION_COLUMN_MISSING") for i in _issues(report, ctx))


# 2 --------------------------------------------------------------------------------------------------


def test_a_higher_value_in_another_row_fails_validation(ws):
    ctx = _row_ctx(ws)
    report = _row_report(ctx)
    lower = report["metric_row_selection"]["selected_row"]
    lower.update(row_number=4, ad_set_name="set-2")
    lower["result"]["value"] = 18.0
    assert any(i.startswith("ROW_SELECTION_NOT_MAX") for i in _issues(report, ctx))
    ghost = _row_report(ctx)
    ghost["metric_row_selection"]["selected_row"]["row_number"] = 99
    assert any(i.startswith("ROW_SELECTION_ROW_NOT_FOUND") for i in _issues(ghost, ctx))
    wrong = _row_report(ctx)
    wrong["metric_row_selection"]["selected_row"]["result"]["value"] = 31.0
    assert any(i.startswith("ROW_SELECTION_VALUE_MISMATCH") for i in _issues(wrong, ctx))


# 3 --------------------------------------------------------------------------------------------------


def test_tie_at_the_maximum_is_never_resolved_automatically(ws):
    rows = copy.deepcopy(ROWS)
    rows[0][4] = "30"  # ad-a now ties ad-b
    ctx = _row_ctx(ws, rows)
    sel = ctx["metric_row_selection"]
    assert sel["selected_row"] is None and sel["tied"] and sel["tied_rows"] == [2, 3]
    assert any(w.startswith("RESULT_TIE") for w in ctx["warnings"])
    assert not any(m["label"] == "Resultados" for m in ctx["provided_metrics"])  # no row, no row metrics
    assert any(i.startswith("RESULT_TIE") for i in _issues(_row_report(ctx), ctx))
    confirmed = _row_ctx(ws, rows, selection=_selection(confirmed_row_number=2))
    assert confirmed["metric_row_selection"]["tie_resolution"] == "OPERATOR_CONFIRMED"
    assert confirmed["metric_row_selection"]["selected_row"]["ad_name"] == "ad-a"
    assert _issues(_row_report(confirmed), confirmed) == []
    with pytest.raises(cp.CreativePerformanceError, match="not a maximum row"):
        _row_ctx(ws, rows, selection=_selection(confirmed_row_number=4))
    with pytest.raises(cp.CreativePerformanceError, match="only for resolving"):
        _row_ctx(ws, selection=_selection(confirmed_row_number=3))


# 4 --------------------------------------------------------------------------------------------------


def test_same_ad_in_other_ad_sets_is_never_aggregated(ws):
    ctx = _row_ctx(ws)
    sel = ctx["metric_row_selection"]
    assert sel["same_ad_name_rows"] == [4] and sel["aggregated"] is False
    assert sel["selected_row"]["result"]["value"] == 30.0  # not 30 + 18
    summed = _row_report(ctx)
    summed["metric_row_selection"]["selected_row"]["result"]["value"] = 48.0
    assert any(i.startswith("ROW_SELECTION_VALUE_MISMATCH") for i in _issues(summed, ctx))
    flagged = _row_report(ctx)
    flagged["metric_row_selection"]["aggregated"] = True
    assert any(i.startswith("schema") for i in _issues(flagged, ctx))


# 5 --------------------------------------------------------------------------------------------------


def test_original_result_type_is_preserved(ws):
    ctx = _row_ctx(ws)
    res = next(m for m in ctx["provided_metrics"] if m["label"] == "Resultados")
    assert res["result_type"] == MSG and res["metric_key"] == "resultados" and res["canonical_metric"] is None  # not mapped to messages
    assert "messages" not in {m["metric_key"] for m in ctx["provided_metrics"] + ctx["derived_metrics"]}
    report = _row_report(ctx)
    report["metric_row_selection"]["selected_row"]["result"]["source_result_type"] = "conversa por mensagem iniciada"
    assert any(i.startswith("RESULT_TYPE_ALTERED") for i in _issues(report, ctx))
    no_type = _row_ctx(ws, selection=_selection(result_type_column=None))
    assert no_type["metric_row_selection"]["selected_row"]["result"]["source_result_type"] == "UNKNOWN"
    assert no_type["metric_row_selection"]["selected_row"]["result"]["normalized_label"] is None
    assert cp.describe_result_type("actions:offsite_conversion.custom.123")["normalization_confidence"] == "MEDIUM"
    assert cp.describe_result_type("some_new_event") == {"source_result_type": "some_new_event", "normalized_label": None, "normalization_confidence": None}


# 6 --------------------------------------------------------------------------------------------------


def test_heterogeneous_result_types_warn_without_blocking(ws):
    ctx = _row_ctx(ws)
    warn = [w for w in ctx["warnings"] if w.startswith("HETEROGENEOUS_RESULT_TYPES")]
    assert len(warn) == 1 and MSG in warn[0] and SITE in warn[0] and "O operador definiu MAX_RESULTS" in warn[0]
    assert ctx["metric_row_selection"]["result_types_found"] == sorted([MSG, SITE])
    report = _row_report(ctx)
    assert _issues(report, ctx) == []
    report["warnings"] = [w for w in report["warnings"] if not w.startswith("HETEROGENEOUS")]
    assert any(i.startswith("WARNING_DROPPED") for i in _issues(report, ctx))
    homogeneous = _row_ctx(ws, ROWS[:3])
    assert not any(w.startswith("HETEROGENEOUS") for w in homogeneous["warnings"])


# 7 --------------------------------------------------------------------------------------------------


def test_post_link_needs_no_match_with_the_row(ws):
    ctx = _row_ctx(ws)
    assert ctx["post_reference"] == {"url": "https://social.example/p/SYNTH123/", "source": "OPERATOR_PROVIDED",
                                     "metric_row_match_required": False, "opened": False, "note": None}
    report = _row_report(ctx)
    assert _issues(report, ctx) == []
    report["post_reference"]["url"] = "https://social.example/p/OTHER/"
    assert any(i.startswith("POST_REFERENCE_ALTERED") for i in _issues(report, ctx))
    with pytest.raises(cp.CreativePerformanceError):
        _row_ctx(ws, post_reference={"url": "not a url"})


# 8 --------------------------------------------------------------------------------------------------


def test_winner_status_stays_operator_declared(ws):
    ctx = _row_ctx(ws)
    assert ctx["winner_status"]["source"] == "OPERATOR_DECLARED" and ctx["winner_status"]["statistically_compared"] is False
    for source in ("STATISTICALLY_PROVEN", "AUTOMATICALLY_SELECTED", "COMPARATIVELY_VALIDATED"):
        report = _row_report(ctx)
        report["winner_status"]["source"] = source
        assert any(i.startswith("schema") for i in _issues(report, ctx))


# 9 --------------------------------------------------------------------------------------------------


def test_performance_facts_trace_the_selected_row(ws):
    ctx = _row_ctx(ws)
    report = _row_report(ctx)
    pf = report["performance_summary"][-1]
    assert pf["source_trace"] == [{"metric_ref": pf["metric_refs"][0], "source_id": "S-02", "source_row": 3,
                                   "source_column": "Resultados", "result_type": MSG}]
    md = cp.render_markdown(report)
    assert "linha 3 `Resultados` tipo `" + MSG + "`" in md and "## Seleção da linha de métricas" in md
    untraced = copy.deepcopy(report)
    del untraced["performance_summary"][-1]["source_trace"]
    assert any(i.startswith("SOURCE_TRACE") for i in _issues(untraced, ctx))
    wrong_row = copy.deepcopy(report)
    wrong_row["performance_summary"][-1]["source_trace"][0]["source_row"] = 4
    assert any(i.startswith("SOURCE_TRACE") for i in _issues(wrong_row, ctx))
    missing = copy.deepcopy(report)
    del missing["metric_row_selection"]
    assert any(i.startswith("ROW_SELECTION_MISSING") for i in _issues(missing, ctx))


def test_selection_without_rule_in_brief_is_rejected(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    report["metric_row_selection"] = _row_report(_row_ctx(ws))["metric_row_selection"]
    assert any(i.startswith("ROW_SELECTION_UNEXPECTED") for i in _issues(report, ctx))


# 10 -------------------------------------------------------------------------------------------------


def test_renderer_never_duplicates_items(ws):
    ctx = _row_ctx(ws)
    report = _row_report(ctx)
    report["do_not_generalize"] += [
        {"id": "NG-02", "statement": "Não comparar com outros tipos de resultado.", "learning_class": "DO_NOT_GENERALIZE", "related_elements": []},
        {"id": "NG-03", "statement": "Não somar linhas de outros conjuntos.", "learning_class": "DO_NOT_GENERALIZE", "related_elements": []}]
    assert _issues(report, ctx) == []
    md = cp.render_markdown(report)
    for item in report["do_not_generalize"] + report["replication_hypotheses"] + report["performance_summary"]:
        assert md.count(item["statement"]) == 1, item["statement"]
    dup = copy.deepcopy(report)
    dup["do_not_generalize"].append(dict(dup["do_not_generalize"][1], id="NG-04"))
    assert any(i.startswith("DUPLICATE_ITEM: do_not_generalize repeats statement") for i in _issues(dup, ctx))


def test_write_and_markdown_round_trip_with_selection(ws):
    ctx = _row_ctx(ws)
    report = _row_report(ctx)
    report["learning_summary"] = cp.learning_counts(report)
    out = cp.write_report(ws, report, ctx, schema_validator=OUT_SCHEMA)
    written = json.loads(out["json"].read_text(encoding="utf-8"))
    assert written == report and cp.markdown_matches(written, out["markdown"].read_text(encoding="utf-8"))
    assert out["json"].parent.parent.name == "creative-performance" and ALPHA in str(out["json"])
