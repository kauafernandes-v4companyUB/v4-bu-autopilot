"""clear_value semantics (values.batchClear, format preserved) and the
minimal set_number_format operation. The fake transport reproduces the
formatting side effects observed on the real API — see
FakeGoogleSheetsTransport. All ids and values are synthetic."""

from __future__ import annotations

import copy

import pytest

from scripts.lib import approval as ap
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch
from scripts.lib.google_sheets_transport import FakeGoogleSheetsTransport

from .conftest import CLIENT_ID, Q, SPREADSHEET_ID, TAB, base_patch

SCHEMA = "skills/update-google-sheet/output.schema.json"
PATCH_SCHEMA = "schemas/google-sheet-patch.schema.json"
CURRENCY = {"type": "CURRENCY", "pattern": "[$R$ -416]#,##0.00"}
INTEGER = {"type": "NUMBER", "pattern": "#,##0"}
BG = {"backgroundColor": {"red": 0.85, "green": 0.1, "blue": 0.2}, "textFormat": {"bold": True}}
RULE = {"condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]}, "strict": False}


@pytest.fixture
def transport() -> FakeGoogleSheetsTransport:
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SPREADSHEET_ID, "Synthetic Metrics", {
        TAB: {
            "row_count": 50, "column_count": 10,
            "cells": {"A1": "Semana", "B1": "Investimento", "C1": "Cliques",
                      "B2": 1000, "C2": 1000, "B3": 1500, "C3": 900, "D2": "=IFERROR(B2/C2,0)", "F2": "=SUM(B2:B10)"},
            "computed": {"D2": 1, "F2": 2500},
            "formats": {"B1": dict(BG, numberFormat=CURRENCY), "B2": dict(BG, numberFormat=CURRENCY), "B3": dict(BG, numberFormat=CURRENCY),
                        "C2": dict(BG, numberFormat=INTEGER), "C3": dict(BG, numberFormat=INTEGER), "D2": {"numberFormat": CURRENCY}},
            "validations": {"B2": RULE, "B3": RULE, "C2": RULE},
        },
    })
    return t


def _preview(t, sources_doc, patch):
    return preview_patch(t, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc)


def _apply(t, sources_doc, patch, preview):
    cand = build_patch_approval_candidate(preview, approval_id="appr-fmt", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    approval = ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=[preview["patch_id"]])
    return apply_patch(t, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc, approved_preview=preview, approval=approval)


def _clear_patch(rng=f"{Q}!B2:C3"):
    return base_patch(permissions={"allow_clear": True}, operations=[{"op_id": "clear", "type": "clear_value", "range": rng}])


# -- the observed API behaviour the fake must keep reproducing -----------------


def test_fake_reproduces_real_api_format_side_effects(transport):
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!B2", "values": [[""]]}], "RAW")
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!B3", "values": [["texto"]]}], "RAW")
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!C2", "values": [[1234.5]]}], "RAW")
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!C3", "values": [["1234.5"]]}], "USER_ENTERED")
    for ref in ("B2", "B3"):  # "" and text with RAW drop only the number format
        cell = transport.cell(SPREADSHEET_ID, TAB, ref)
        assert "numberFormat" not in cell["format"] and cell["format"]["backgroundColor"] == BG["backgroundColor"]
        assert cell["data_validation"] == RULE
    assert transport.cell(SPREADSHEET_ID, TAB, "C2")["format"]["numberFormat"] == INTEGER
    assert transport.cell(SPREADSHEET_ID, TAB, "C3")["format"]["numberFormat"] == INTEGER


# -- clear_value ------------------------------------------------------------------


def test_clear_value_removes_content_and_preserves_every_cell_property(transport, sources_doc, validate, repo_root):
    patch = _clear_patch()
    assert not validate(patch, repo_root / PATCH_SCHEMA)
    before = {ref: transport.cell(SPREADSHEET_ID, TAB, ref) for ref in ("B2", "B3", "C2", "C3")}
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success" and not validate(preview, repo_root / SCHEMA)
    assert [d["change"] for d in preview["diff"]] == ["cleared"] * 4
    assert preview["after"][f"{Q}!B2"] == {"value": None, "formula": None}
    assert preview["mutation_plan"]["write_requests"] == [
        {"op_id": "clear", "range": f"{Q}!B2:C3", "method": "values.batchClear", "value_input_option": None}]
    assert preview["mutation_plan"]["content_only"] is True

    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "success", (out["conflicts"], out["verification"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.write_calls == []  # never an "" write
    assert transport.clear_calls == [{"spreadsheet_id": SPREADSHEET_ID, "ranges": [f"{Q}!B2:C3"]}]
    assert out["applied"]["write_requests_sent"] == [{"method": "values.batchClear", "value_input_option": None, "ranges": [f"{Q}!B2:C3"]}]
    assert out["applied"]["updated_cells"] == 4
    for ref, cell in before.items():
        now = transport.cell(SPREADSHEET_ID, TAB, ref)
        assert now["value"] is None and now["formula"] is None
        assert now.get("format") == cell.get("format")  # userEnteredFormat incl. numberFormat
        assert now.get("data_validation") == cell.get("data_validation")
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["format"]["numberFormat"] == CURRENCY
    assert transport.cell(SPREADSHEET_ID, TAB, "D2")["formula"] == "=IFERROR(B2/C2,0)"
    assert transport.cell(SPREADSHEET_ID, TAB, "F2")["formula"] == "=SUM(B2:B10)"
    v = out["verification"]
    assert v["targets_match"] and v["formulas_outside_patch_intact"] and v["structure_preserved"] and v["structure_differences"] == []
    assert out["receipt"]["effects"][0]["operation"] == "values_batch_clear"
    assert _preview(transport, sources_doc, patch)["status"] == "no_change"


def test_clear_of_a_formula_cell_still_requires_declaration(transport, sources_doc):
    preview = _preview(transport, sources_doc, _clear_patch(f"{Q}!D2"))
    assert preview["status"] == "conflict" and preview["conflicts"][0]["code"] == "FORMULA_OVERWRITE_BLOCKED"


def test_mixed_patch_clears_first_then_writes(transport, sources_doc):
    patch = base_patch(permissions={"allow_clear": True}, operations=[
        {"op_id": "w", "type": "write_value", "range": f"{Q}!C2", "values": [[42]]},
        {"op_id": "clear", "type": "clear_value", "range": f"{Q}!B2:B3"},
    ])
    out = _apply(transport, sources_doc, patch, _preview(transport, sources_doc, patch))
    assert out["status"] == "success", out["verification"]
    assert [s["method"] for s in out["applied"]["write_requests_sent"]] == ["values.batchClear", "values.batchUpdate"]
    assert transport.cell(SPREADSHEET_ID, TAB, "C2")["format"]["numberFormat"] == INTEGER  # number write keeps it
    assert out["receipt"]["effects"][0]["operation"] == "values_batch_clear+values_batch_update"


# -- text writes over number-formatted cells -------------------------------------


def test_raw_text_over_number_format_is_warned_in_preview_and_caught_after_write(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "hdr", "type": "write_value", "range": f"{Q}!B1", "values": [["SEMANA1"]]}])
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success"
    assert [w["code"] for w in preview["warnings"]] == ["NUMBER_FORMAT_WILL_BE_RESET"]
    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "conflict" and out["verification"]["structure_preserved"] is False
    assert out["verification"]["structure_differences"] == [{"sheet": TAB, "cell": "B1", "property": "cell_format_or_validation"}]


# -- set_number_format ------------------------------------------------------------


def _format_patch(rng=f"{Q}!B2:B3", nf=None):
    return base_patch(operations=[{"op_id": "nf", "type": "set_number_format", "range": rng, "number_format": nf or INTEGER}])


def test_set_number_format_preview_apply_verify_and_replay(transport, sources_doc, validate, repo_root):
    patch = _format_patch()
    assert not validate(patch, repo_root / PATCH_SCHEMA)
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success" and not validate(preview, repo_root / SCHEMA)
    assert preview["before"][f"{Q}!B2"] == {"value": 1000, "formatted_value": "1000", "formula": None, "number_format": CURRENCY}
    assert preview["after"][f"{Q}!B2"] == {"value": 1000, "formula": None, "number_format": INTEGER}
    assert [d["change"] for d in preview["diff"]] == ["number_format_set"] * 2
    assert preview["mutation_plan"]["content_only"] is False
    assert preview["mutation_plan"]["write_requests"][0]["method"] == "spreadsheets.batchUpdate:repeatCell(userEnteredFormat.numberFormat)"

    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "success", (out["conflicts"], out["verification"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.write_calls == [] and transport.clear_calls == []
    assert transport.format_calls[0]["requests"] == [{"sheet_id": 1000, "range": f"{Q}!B2:B3", "number_format": INTEGER}]
    for ref in ("B2", "B3"):
        cell = transport.cell(SPREADSHEET_ID, TAB, ref)
        assert cell["format"] == dict(BG, numberFormat=INTEGER) and cell["data_validation"] == RULE
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["value"] == 1000
    assert out["receipt"]["effects"][0]["operation"] == "number_format_repeat_cell"
    assert _preview(transport, sources_doc, patch)["status"] == "no_change"


def test_set_number_format_restores_a_removed_format_on_an_empty_cell(transport, sources_doc):
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!B2", "values": [[""]]}], "RAW")  # legacy damage
    assert "numberFormat" not in transport.cell(SPREADSHEET_ID, TAB, "B2")["format"]
    patch = _format_patch(f"{Q}!B2", CURRENCY)
    preview = _preview(transport, sources_doc, patch)
    assert preview["before"][f"{Q}!B2"]["number_format"] is None
    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["format"] == dict(BG, numberFormat=CURRENCY)
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["value"] is None


def test_set_number_format_on_formula_cell_never_touches_the_formula(transport, sources_doc):
    patch = _format_patch(f"{Q}!D2", INTEGER)
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success" and not preview["conflicts"]
    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "D2")["formula"] == "=IFERROR(B2/C2,0)"


def test_set_number_format_verification_catches_any_other_format_change(transport, sources_doc):
    patch = _format_patch()
    preview = _preview(transport, sources_doc, patch)

    def remote_restyles(t):
        fmt = copy.deepcopy(t.cell(SPREADSHEET_ID, TAB, "B2")["format"])
        fmt["backgroundColor"] = {"blue": 1}
        t.set_format(SPREADSHEET_ID, TAB, "B2", fmt)

    transport.after_write = remote_restyles
    out = _apply(transport, sources_doc, patch, preview)
    assert out["status"] == "conflict" and out["verification"]["structure_preserved"] is False
    assert {"sheet": TAB, "cell": "B2", "property": "format_other_than_number_format"} in out["verification"]["structure_differences"]


@pytest.mark.parametrize("nf", [{"type": "BOLD"}, {"type": "NUMBER", "color": "red"}, {"pattern": "#,##0"}, "NUMBER"])
def test_invalid_number_format_is_rejected(transport, sources_doc, validate, repo_root, nf):
    patch = base_patch(operations=[{"op_id": "nf", "type": "set_number_format", "range": f"{Q}!B2", "number_format": nf}])
    assert validate(patch, repo_root / PATCH_SCHEMA)
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "error" and out["errors"][0]["code"] == "INVALID_NUMBER_FORMAT"


def test_set_number_format_cannot_share_a_cell_with_a_content_operation(transport, sources_doc):
    patch = base_patch(operations=[
        {"op_id": "w", "type": "write_value", "range": f"{Q}!B2", "values": [[5]]},
        {"op_id": "nf", "type": "set_number_format", "range": f"{Q}!B2", "number_format": INTEGER},
    ])
    assert _preview(transport, sources_doc, patch)["errors"][0]["code"] == "OVERLAPPING_TARGETS"
