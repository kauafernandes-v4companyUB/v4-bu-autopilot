"""duplicate_sheet: the only structural operation of update-google-sheet.
Synthetic fixtures only — no real spreadsheet is contacted."""

from __future__ import annotations

import pytest

from scripts.lib import approval as ap
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch
from scripts.lib.google_sheets_transport import FakeGoogleSheetsTransport, sheet_content

from .conftest import CLIENT_ID, SPREADSHEET_ID, base_patch

SCHEMA = "skills/update-google-sheet/output.schema.json"
PATCH_SCHEMA = "schemas/google-sheet-patch.schema.json"
SRC, DST = "SETEMBRO", "OUTUBRO"
CHECKBOX = {"condition": {"type": "BOOLEAN"}}
STATUS = {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Em Andamento"}, {"userEnteredValue": "Finalizado"}]}, "strict": True}
HEADER = {"backgroundColor": {"red": 0.8}, "textFormat": {"bold": True}}


@pytest.fixture
def transport() -> FakeGoogleSheetsTransport:
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SPREADSHEET_ID, "Synthetic Metrics", {
        "CLIENTE": {"cells": {"A1": "cliente"}},
        SRC: {
            "row_count": 40, "column_count": 9, "frozen_row_count": 1, "column_sizes": [202, 266, 89, 175],
            "cells": {"A1": "PLAYBOOK", "A2": "AÇÃO", "B2": "PRAZO", "E2": "CHECK",
                      "A3": "Round Semanal", "B3": "Às segundas", "E3": True, "F3": False, "G3": "=COUNTIF(E3:F3,TRUE)",
                      "A13": "ENTREGA", "I13": "STATUS", "I14": "Em Andamento"},
            "computed": {"G3": 1},
            "merges": [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 9},
                       {"startRowIndex": 13, "endRowIndex": 14, "startColumnIndex": 2, "endColumnIndex": 8}],
            "formats": {"A1": HEADER, "A2": HEADER, "B2": HEADER, "B3": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}},
            "validations": {"E3": CHECKBOX, "F3": CHECKBOX, "I14": STATUS, "I15": STATUS},
        },
    })
    return t


def _patch(**op):
    return base_patch(patch_id="synthtest-dup-001", operations=[dict({"op_id": "dup", "type": "duplicate_sheet", "source_sheet_title": SRC, "new_sheet_title": DST}, **op)])


def _preview(t, sources_doc, patch):
    return preview_patch(t, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc)


def _approve(preview, approval_id="appr-dup"):
    cand = build_patch_approval_candidate(preview, approval_id=approval_id, created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    return ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=[preview["patch_id"]])


def _apply(t, sources_doc, patch, preview, approval):
    return apply_patch(t, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc, approved_preview=preview, approval=approval)


def _titles(t):
    return [s["title"] for s in t.get_spreadsheet_metadata(SPREADSHEET_ID)["sheets"]]


def test_preview_describes_the_duplication_without_writing(transport, sources_doc, validate, repo_root):
    patch = _patch()
    assert not validate(patch, repo_root / PATCH_SCHEMA)
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "success", (out["errors"], out["conflicts"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.structure_calls == [] and transport.write_calls == [] and _titles(transport) == ["CLIENTE", SRC]
    plan = out["sheet_plan"]
    assert plan["spreadsheet_id"] == SPREADSHEET_ID
    assert plan["source"]["title"] == SRC and plan["source"]["sheet_id"] == 1001 and plan["source"]["index"] == 1
    assert plan["destination"] == {"title": DST, "exists": False, "insert_index": 2, "identical_to_source": None}
    assert plan["source"]["merges"] == ["A1:I1", "C14:H14"]
    assert plan["source"]["formulas"] == 1 and plan["source"]["data_validations"] == 4 and plan["source"]["checkbox_validations"] == 2
    assert plan["source"]["column_sizes"] == [202, 266, 89, 175]
    assert out["mutation_plan"]["write_requests"] == [{"op_id": "dup", "range": "SETEMBRO", "method": "spreadsheets.batchUpdate:duplicateSheet", "value_input_option": None}]
    assert out["mutation_plan"]["content_only"] is False and out["mutation_plan"]["cells_to_change"] == 0
    assert len(out["base_state_hash"]) == 64 and len(out["preview_hash"]) == 64
    assert _preview(transport, sources_doc, patch)["preview_hash"] == out["preview_hash"]  # deterministic


def test_apply_duplicates_natively_and_preserves_everything(transport, sources_doc, validate, repo_root):
    patch = _patch()
    before_src = transport.get_sheet_snapshot(SPREADSHEET_ID, SRC)
    preview = _preview(transport, sources_doc, patch)
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success", (out["conflicts"], out["verification"])
    assert not validate(out, repo_root / SCHEMA)
    assert transport.structure_calls == [{"spreadsheet_id": SPREADSHEET_ID, "duplicate_sheet": {"source_sheet_id": 1001, "new_sheet_title": DST, "insert_index": 2}}]
    assert transport.write_calls == [] and transport.clear_calls == [] and transport.format_calls == []
    assert _titles(transport) == ["CLIENTE", SRC, DST]
    new = transport.get_sheet_snapshot(SPREADSHEET_ID, DST)
    assert sheet_content(new) == sheet_content(before_src)  # values, formulas, formats, validations, merges, sizes
    assert new["cells"]["G3"]["userEnteredValue"] == {"formulaValue": "=COUNTIF(E3:F3,TRUE)"}
    assert new["cells"]["E3"]["dataValidation"] == CHECKBOX and new["cells"]["I14"]["dataValidation"] == STATUS
    assert new["cells"]["A1"]["userEnteredFormat"] == HEADER and len(new["merges"]) == 2
    assert new["column_sizes"][:2] == [{"size": 202, "hidden": False}, {"size": 266, "hidden": False}]
    assert new["sheet_id"] != before_src["sheet_id"]
    assert transport.get_sheet_snapshot(SPREADSHEET_ID, SRC) == before_src  # source untouched
    v = out["verification"]
    assert v["targets_match"] and v["formulas_outside_patch_intact"] and v["structure_preserved"] and v["mismatches"] == []
    assert v["duplicate_sheet"]["content_equal_to_source"] and v["duplicate_sheet"]["other_sheets_intact"]
    assert out["applied"]["created_sheet"]["title"] == DST
    assert out["receipt"]["status"] == "success" and out["receipt"]["effects"][0]["operation"] == "duplicate_sheet"


def test_existing_destination_is_a_conflict_and_never_overwritten(transport, sources_doc):
    transport.add_spreadsheet(SPREADSHEET_ID, "Synthetic Metrics", {"CLIENTE": {"cells": {}}, SRC: {"cells": {"A1": "x"}}, DST: {"cells": {"A1": "outro"}}})
    patch = _patch()
    preview = _preview(transport, sources_doc, patch)
    assert preview["status"] == "conflict" and preview["conflicts"][0]["code"] == "DESTINATION_EXISTS"
    assert preview["sheet_plan"]["destination"]["exists"] is True and preview["mutation_plan"]["will_write"] is False
    out = _apply(transport, sources_doc, patch, preview, None)
    assert out["status"] == "error" and transport.structure_calls == []
    assert transport.get_sheet_snapshot(SPREADSHEET_ID, DST)["cells"]["A1"]["userEnteredValue"] == {"stringValue": "outro"}


def test_missing_source_is_a_conflict(transport, sources_doc):
    out = _preview(transport, sources_doc, _patch(source_sheet_title="AGOSTO"))
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "SOURCE_SHEET_NOT_FOUND"
    assert transport.structure_calls == []


def test_wrong_spreadsheet_is_refused(transport, sources_doc):
    transport._books[SPREADSHEET_ID]["title"] = "Another title"
    out = _preview(transport, sources_doc, _patch())
    assert out["status"] == "error" and out["errors"][0]["code"] == "WRONG_SPREADSHEET"


def test_hash_lock_blocks_apply_when_the_source_changed_after_preview(transport, sources_doc):
    patch = _patch()
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    transport.set_cell(SPREADSHEET_ID, SRC, "A3", "Round Semanal (editado)")
    out = _apply(transport, sources_doc, patch, preview, approval)
    assert out["status"] == "conflict" and out["conflicts"][0]["code"] == "STALE_PREVIEW"
    assert transport.structure_calls == [] and DST not in _titles(transport)


def test_apply_requires_approval_of_this_exact_preview(transport, sources_doc):
    patch = _patch()
    preview = _preview(transport, sources_doc, patch)
    other = dict(preview, preview_hash="0" * 64)
    out = _apply(transport, sources_doc, patch, preview, _approve(other))
    assert out["status"] == "error" and out["errors"][0]["code"] == "STALE_APPROVAL"
    assert transport.structure_calls == []


def test_replay_is_safe_no_change(transport, sources_doc):
    patch = _patch()
    preview = _preview(transport, sources_doc, patch)
    approval = _approve(preview)
    assert _apply(transport, sources_doc, patch, preview, approval)["status"] == "success"
    again = _apply(transport, sources_doc, patch, preview, approval)
    assert again["status"] == "no_change" and len(transport.structure_calls) == 1
    replay_preview = _preview(transport, sources_doc, patch)
    assert replay_preview["status"] == "no_change" and replay_preview["sheet_plan"]["destination"]["identical_to_source"] is True
    transport.set_cell(SPREADSHEET_ID, DST, "A14", "Nova entrega")  # once the copy is edited, a replay is a conflict, never an overwrite
    assert _preview(transport, sources_doc, patch)["conflicts"][0]["code"] == "DESTINATION_EXISTS"


def test_verification_catches_a_copy_that_differs_or_a_touched_source(transport, sources_doc):
    patch = _patch()
    preview = _preview(transport, sources_doc, patch)
    transport.after_write = lambda t: (t.set_cell(SPREADSHEET_ID, DST, "B3", "outro prazo"), t.set_cell(SPREADSHEET_ID, SRC, "A3", "mexido"))
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "conflict" and out["receipt"]["status"] == "partial"
    v = out["verification"]
    assert v["targets_match"] is False and {"property": "cell", "cell": "B3"} in v["mismatches"]
    assert v["formulas_outside_patch_intact"] is False and v["structure_preserved"] is False


def test_insert_before_the_source_keeps_the_source_intact(transport, sources_doc):
    patch = _patch(insert_index=0)
    preview = _preview(transport, sources_doc, patch)
    out = _apply(transport, sources_doc, patch, preview, _approve(preview))
    assert out["status"] == "success", out["verification"]
    assert _titles(transport) == [DST, "CLIENTE", SRC]


@pytest.mark.parametrize("op,code", [
    ({"new_sheet_title": ""}, "INVALID_OPERATION"),
    ({"new_sheet_title": SRC}, "INVALID_OPERATION"),
    ({"new_sheet_title": "x" * 101}, "INVALID_OPERATION"),
    ({"insert_index": -1}, "INVALID_OPERATION"),
])
def test_invalid_duplicate_operations(transport, sources_doc, op, code):
    out = _preview(transport, sources_doc, _patch(**op))
    assert out["status"] == "error" and out["errors"][0]["code"] == code and transport.structure_calls == []


def test_duplicate_sheet_must_be_alone_in_its_patch(transport, sources_doc, validate, repo_root):
    patch = base_patch(patch_id="synthtest-dup-002", operations=[
        {"op_id": "dup", "type": "duplicate_sheet", "source_sheet_title": SRC, "new_sheet_title": DST},
        {"op_id": "w", "type": "write_value", "range": "'SETEMBRO'!A20", "values": [["x"]]},
    ])
    out = _preview(transport, sources_doc, patch)
    assert out["status"] == "error" and out["errors"][0]["code"] == "DUPLICATE_SHEET_NOT_ALONE"
    assert validate(base_patch(operations=[{"op_id": "w", "type": "write_value", "values": [[1]]}]), repo_root / PATCH_SCHEMA)  # range still required for cell ops
