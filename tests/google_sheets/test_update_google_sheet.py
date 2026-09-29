from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import approval as ap
from scripts.lib.google_sheets_patch import (
    apply_patch,
    build_patch_approval_candidate,
    formulas_equal,
    preview_patch,
)
from scripts.lib.google_sheets_transport import GoogleSheetsAPIError

from .conftest import CLIENT_ID, OTHER_CLIENT_ID, OTHER_SPREADSHEET_ID, Q, SPREADSHEET_ID, TAB, base_patch

SCHEMA = "skills/update-google-sheet/output.schema.json"
PATCH_SCHEMA = "schemas/google-sheet-patch.schema.json"


def _preview(transport, sources_doc, patch, **kw):
    return preview_patch(transport, client_id=kw.pop("client_id", CLIENT_ID), patch=patch, sources_doc=sources_doc, **kw)


def _approve(preview, approval_id="appr-gs-1"):
    cand = build_patch_approval_candidate(preview, approval_id=approval_id, created_at="2026-01-01T00:00:00Z", preview_path="preview.json")
    return ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=[preview["patch_id"]])


def _apply(transport, sources_doc, patch, preview, approval, **kw):
    return apply_patch(transport, client_id=kw.pop("client_id", CLIENT_ID), patch=patch, sources_doc=sources_doc, approved_preview=preview, approval=approval, **kw)


def _formula_snapshot(transport):
    return {
        tab: {rc: c["formula"] for rc, c in sheet["cells"].items() if c.get("formula")}
        for tab, sheet in transport._books[SPREADSHEET_ID]["sheets"].items()
    }


# -- preview ------------------------------------------------------------------


def test_preview_builds_before_after_diff_hashes_without_writing(transport, sources_doc, patch, validate, repo_root):
    assert not validate(patch, repo_root / PATCH_SCHEMA)
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "success", (out["errors"], out["conflicts"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.write_calls == []
    assert out["before"][f"{Q}!B3"] == {"value": None, "formatted_value": None, "formula": None}
    assert out["after"][f"{Q}!B3"] == {"value": 250, "formula": None}
    assert [d["cell"] for d in out["diff"]] == [f"{Q}!B3", f"{Q}!C3"]
    assert out["mutation_plan"]["will_write"] is True and out["mutation_plan"]["content_only"] is True
    assert len(out["base_state_hash"]) == 64 and len(out["preview_hash"]) == 64


def test_preview_is_deterministic(transport, sources_doc, patch):
    a, b = _preview(transport, sources_doc, patch), _preview(transport, sources_doc, patch)
    assert (a["base_state_hash"], a["preview_hash"]) == (b["base_state_hash"], b["preview_hash"])


def test_preview_generated_at_is_real_clock(transport, sources_doc, patch):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    out = _preview(transport, sources_doc, patch)
    ts = datetime.strptime(out["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= ts <= datetime.now(timezone.utc) + timedelta(seconds=1)
    future = _preview(transport, sources_doc, patch, clock=lambda: "2999-01-01T00:00:00Z")
    assert any(w["code"] == "EXECUTION_TIMESTAMP_IN_FUTURE" for w in future["warnings"])


# -- apply --------------------------------------------------------------------


def test_apply_authorized_writes_verifies_and_preserves(transport, sources_doc, patch, validate, repo_root):
    formulas_before = _formula_snapshot(transport)
    preview = _preview(transport, sources_doc, patch)
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success", (out["errors"], out["conflicts"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.cell(SPREADSHEET_ID, TAB, "B3")["value"] == 250
    assert transport.cell(SPREADSHEET_ID, TAB, "C3")["value"] == 5
    assert transport.cell(SPREADSHEET_ID, TAB, "B3")["format"] == {"numberFormat": {"type": "CURRENCY"}}
    assert _formula_snapshot(transport) == formulas_before
    v = out["verification"]
    assert v["targets_match"] and v["formulas_outside_patch_intact"] and v["structure_preserved"]
    assert out["receipt"]["status"] == "success" and out["receipt"]["approval_id"] == "appr-gs-1"
    assert len(transport.write_calls) == 1 and transport.write_calls[0]["value_input_option"] == "RAW"


def test_apply_without_approval_or_preview_is_blocked(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    no_approval = _apply(transport, sources_doc, patch, preview, None)
    assert no_approval["status"] == "error" and no_approval["errors"][0]["code"] == "NO_APPROVAL"
    draft = build_patch_approval_candidate(preview, approval_id="d", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    draft_out = _apply(transport, sources_doc, patch, preview, draft)
    assert draft_out["errors"][0]["code"] == "STALE_APPROVAL"
    no_preview = _apply(transport, sources_doc, patch, None, _approve(preview))
    assert no_preview["errors"][0]["code"] == "NO_PREVIEW"
    assert transport.write_calls == []


def test_approval_is_hash_locked_to_the_preview(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    tampered = copy.deepcopy(preview)
    tampered["after"][f"{Q}!B3"]["value"] = 999
    out = _apply(transport, sources_doc, patch, tampered, approval)
    assert out["status"] == "error" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert transport.write_calls == []


def test_stale_preview_when_base_changes(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    transport.set_cell(SPREADSHEET_ID, TAB, "C3", 7)  # someone edits a target cell after preview
    out = _apply(transport, sources_doc, patch, preview, approval)
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "STALE_PREVIEW"
    assert transport.write_calls == []
    assert transport.cell(SPREADSHEET_ID, TAB, "C3")["value"] == 7


def test_stale_preview_when_formula_outside_patch_changes(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    transport.set_cell(SPREADSHEET_ID, TAB, "F2", "=SUM(B2:B20)")
    out = _apply(transport, sources_doc, patch, preview, approval)
    assert out["conflicts"][0]["code"] == "STALE_PREVIEW" and transport.write_calls == []


def test_patch_changed_after_approval_is_mismatch(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    altered = copy.deepcopy(patch)
    altered["operations"][0]["values"] = [[300, 5]]
    out = _apply(transport, sources_doc, altered, preview, approval)
    assert out["conflicts"][0]["code"] == "PATCH_MISMATCH" and transport.write_calls == []


def test_idempotent_replay_is_no_change(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    assert _apply(transport, sources_doc, patch, preview, approval)["status"] == "success"
    writes = len(transport.write_calls)
    again = _apply(transport, sources_doc, patch, preview, approval)
    assert again["status"] == "no_change"
    assert len(transport.write_calls) == writes
    assert _preview(transport, sources_doc, patch)["status"] == "no_change"


# -- formulas -------------------------------------------------------------------


def test_write_formula(transport, sources_doc, validate, repo_root):
    patch = base_patch(operations=[{"op_id": "f1", "type": "write_formula", "range": f"{Q}!E2:E3", "formulas": [["=B2*2"], ["=B3*2"]]}])
    assert not validate(patch, repo_root / PATCH_SCHEMA)
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success"
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "E3")["formula"] == "=B3*2"
    assert transport.write_calls[0]["value_input_option"] == "USER_ENTERED"


def test_value_over_formula_is_conflict_by_default(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "v1", "type": "write_value", "range": f"{Q}!D2", "values": [[42]]}])
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "conflict"
    assert out["conflicts"][0]["code"] == "FORMULA_OVERWRITE_BLOCKED" and out["conflicts"][0]["cell"] == f"{Q}!D2"
    assert out["mutation_plan"]["will_write"] is False
    # and apply can never be reached with it: a conflict preview is not applicable
    blocked = _apply(transport, sources_doc, patch, out, None)
    assert blocked["status"] == "error"
    assert transport.cell(SPREADSHEET_ID, TAB, "D2")["formula"] == "=IFERROR(B2/C2,0)"
    assert transport.write_calls == []


def test_clearing_or_replacing_formula_requires_declaration(transport, sources_doc):
    replace = base_patch(operations=[{"op_id": "f1", "type": "write_formula", "range": f"{Q}!D2", "formulas": [["=B2/C2"]]}])
    assert _preview(transport, sources_doc, replace)["conflicts"][0]["code"] == "FORMULA_REPLACE_NOT_DECLARED"
    clear = base_patch(permissions={"allow_clear": True}, operations=[{"op_id": "c1", "type": "clear_value", "range": f"{Q}!D2"}])
    assert _preview(transport, sources_doc, clear)["conflicts"][0]["code"] == "FORMULA_OVERWRITE_BLOCKED"


def test_declared_formula_replacement_is_explicit_in_preview_and_applied(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "v1", "type": "write_value", "range": f"{Q}!D2", "values": [[42]], "replace_existing_formula": True}])
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "success"
    assert preview["mutation_plan"]["formula_replacements"] == [{"cell": f"{Q}!D2", "op_id": "v1", "existing_formula": "=IFERROR(B2/C2,0)"}]
    assert preview["diff"][0]["change"] == "formula_removed"
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "D2")["formula"] is None
    assert transport.cell(SPREADSHEET_ID, TAB, "D3")["formula"] == "=IFERROR(B3/C3,0)"


def test_formulas_outside_patch_tampered_during_write_is_detected(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)

    def misbehaving_remote(t):
        t.set_cell(SPREADSHEET_ID, TAB, "F2", 123)  # a formula outside the patch turned into a value

    transport.after_write = misbehaving_remote
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "conflict"
    assert out["verification"]["formulas_outside_patch_intact"] is False
    assert out["verification"]["changed_formulas_outside_patch"][0]["cell"] == f"{Q}!F2"
    assert out["receipt"]["status"] == "partial"


def test_formatting_change_during_write_is_detected(transport, sources_doc, patch):
    preview = _preview(transport, sources_doc, patch)
    transport.after_write = lambda t: t.set_format(SPREADSHEET_ID, TAB, "B3", {"numberFormat": {"type": "TEXT"}})
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "conflict" and out["verification"]["structure_preserved"] is False


def test_formula_comparison_tolerates_api_normalization():
    assert formulas_equal("=sum(b2:b10)", "=SUM(B2:B10)")
    assert formulas_equal('=IF(A1="x", 1, 0)', '=IF(A1="x",1,0)')
    assert not formulas_equal('=IF(A1="x",1,0)', '=IF(A1="X",1,0)')


# -- validation / blockers --------------------------------------------------------


@pytest.mark.parametrize("op,code", [
    ({"op_id": "a", "type": "write_value", "range": f"{Q}!B3:C3", "values": [[1]]}, "SHAPE_MISMATCH"),
    ({"op_id": "a", "type": "write_value", "range": f"{Q}!B3", "values": [["=B2"]]}, "VALUE_LOOKS_LIKE_FORMULA"),
    ({"op_id": "a", "type": "write_formula", "range": f"{Q}!E3", "formulas": [["B2"]]}, "INVALID_FORMULA"),
    ({"op_id": "a", "type": "clear_value", "range": f"{Q}!B3"}, "CLEAR_NOT_AUTHORIZED"),
    ({"op_id": "a", "type": "insert_rows", "range": f"{Q}!B3"}, "UNSUPPORTED_OPERATION"),
    ({"op_id": "a", "type": "write_value", "range": f"{Q}!B:B", "values": [[1]]}, "INVALID_RANGE"),
    ({"op_id": "a", "type": "write_value", "range": "B3", "values": [[1]]}, "INVALID_RANGE"),
])
def test_invalid_operations_are_errors_without_io(transport, sources_doc, op, code):
    out = _preview(transport, sources_doc, base_patch(operations=[op]))
    assert out["status"] == "error" and out["errors"][0]["code"] == code
    assert transport.calls == []


def test_overlapping_targets_and_duplicate_ids(transport, sources_doc):
    ops = [
        {"op_id": "a", "type": "write_value", "range": f"{Q}!B3:C3", "values": [[1, 2]]},
        {"op_id": "b", "type": "write_value", "range": f"{Q}!C3", "values": [[3]]},
        {"op_id": "a", "type": "write_value", "range": f"{Q}!E3", "values": [[3]]},
    ]
    codes = {e["code"] for e in _preview(transport, sources_doc, base_patch(operations=ops))["errors"]}
    assert codes == {"OVERLAPPING_TARGETS", "DUPLICATE_OP_ID"}


def test_nonexistent_tab_and_out_of_grid(transport, sources_doc):
    tab = _preview(transport, sources_doc, base_patch(operations=[{"op_id": "a", "type": "write_value", "range": "'Não Existe'!A1", "values": [[1]]}]))
    assert tab["errors"][0]["code"] == "SHEET_NOT_FOUND"
    grid = _preview(transport, sources_doc, base_patch(operations=[{"op_id": "a", "type": "write_value", "range": f"{Q}!A51", "values": [[1]]}]))
    assert grid["errors"][0]["code"] == "RANGE_OUT_OF_GRID"
    assert transport.write_calls == []


def test_wrong_spreadsheet(transport, sources_doc, patch):
    sources_doc["sources"][1]["google_sheet"]["expected_title"] = "Planilha Errada"
    assert _preview(transport, sources_doc, patch)["errors"][0]["code"] == "WRONG_SPREADSHEET"
    wrong_id = base_patch(spreadsheet_id=OTHER_SPREADSHEET_ID)
    assert _preview(transport, sources_doc, wrong_id)["errors"][0]["code"] == "WRONG_SPREADSHEET"


def test_client_isolation(transport, sources_doc, other_sources_doc, patch):
    foreign_patch = base_patch(client_id=OTHER_CLIENT_ID)
    assert _preview(transport, sources_doc, foreign_patch)["errors"][0]["code"] == "CLIENT_ISOLATION"
    assert _preview(transport, other_sources_doc, patch)["errors"][0]["code"] == "CLIENT_ISOLATION"
    other_sheet = base_patch(source_id=None, spreadsheet_id=OTHER_SPREADSHEET_ID)
    other_sheet.pop("source_id")
    assert _preview(transport, sources_doc, other_sheet)["errors"][0]["code"] == "SOURCE_NOT_REGISTERED"
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    approval["client_id"] = OTHER_CLIENT_ID
    assert _apply(transport, sources_doc, patch, preview, approval)["errors"][0]["code"] == "CLIENT_ISOLATION"
    assert transport.write_calls == []


def test_non_writable_and_multi_client_sources_refused(transport, sources_doc, patch):
    sources_doc["sources"][1]["google_sheet"]["writable"] = False
    assert _preview(transport, sources_doc, patch)["errors"][0]["code"] == "SOURCE_NOT_WRITABLE"
    sources_doc["sources"][1]["google_sheet"]["writable"] = True
    sources_doc["sources"][1]["contains_multiple_clients"] = True
    assert _preview(transport, sources_doc, patch)["errors"][0]["code"] == "CLIENT_ISOLATION"


def test_auth_and_api_errors(transport, sources_doc, patch, validate, repo_root):
    transport.auth_error = True
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "error" and out["errors"][0]["code"] == "AUTH_ERROR"
    assert not validate(out, repo_root / SCHEMA)
    transport.auth_error = False
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    calls = {"n": 0}
    real_write = transport.write_values

    def failing_write(*a, **k):
        calls["n"] += 1
        raise GoogleSheetsAPIError("HTTP 503: service unavailable")

    transport.write_values = failing_write
    out = _apply(transport, sources_doc, patch, preview, approval)
    transport.write_values = real_write
    assert calls["n"] == 1
    assert out["status"] == "error" and out["errors"][0]["code"] == "API_ERROR"
    assert out["receipt"]["status"] == "failed"
    assert not validate(out, repo_root / SCHEMA)


def test_user_entered_value_is_verified_by_parsed_number(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "u", "type": "write_value", "range": f"{Q}!C3", "values": [["12"]], "input_option": "USER_ENTERED"}])
    preview = _preview(transport, sources_doc, patch)
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "C3")["value"] == 12
    assert _preview(transport, sources_doc, patch)["status"] == "no_change"


def test_clear_value_when_authorized(transport, sources_doc):
    patch = base_patch(permissions={"allow_clear": True}, operations=[{"op_id": "c", "type": "clear_value", "range": f"{Q}!B2:C2"}])
    preview = _preview(transport, sources_doc, patch)
    assert [d["change"] for d in preview["diff"]] == ["cleared", "cleared"]
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["value"] is None
    assert transport.cell(SPREADSHEET_ID, TAB, "B2")["format"] == {"numberFormat": {"type": "CURRENCY"}}
