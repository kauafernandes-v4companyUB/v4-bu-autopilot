"""Post-write verification vs. Google Sheets' automatic URL linking.

Observed on the real API: a RAW write of a string that is a URL is stored
byte-for-byte, and Sheets adds userEnteredFormat.textFormat.link = {uri: <the
text>} on its own. That one unrequested property must not fail verification;
every real difference (value, number, formula, managed format, any other
format/validation change, a link to another uri) still must. Synthetic only.
"""

from __future__ import annotations

from scripts.lib import approval as ap
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch

from .conftest import CLIENT_ID, Q, SPREADSHEET_ID, TAB, base_patch

SCHEMA = "skills/update-google-sheet/output.schema.json"
URL = "https://social.example/p/SYNTH123/#advertiser"
OTHER_URL = "https://social.example/p/SYNTH999/"
LINK = {"textFormat": {"link": {"uri": URL}}}


def _run(transport, sources_doc, patch, after_write=None):
    preview = preview_patch(transport, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc)
    assert preview["status"] == "success", (preview["errors"], preview["conflicts"])
    cand = build_patch_approval_candidate(preview, approval_id="appr-link-1", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    approval = ap.apply_operator_decision(cand, approved_at="2026-01-01T00:00:01Z", approved_by="operator", approve_item_ids=[patch["patch_id"]])
    transport.after_write = after_write
    return apply_patch(transport, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc, approved_preview=preview, approval=approval)


def _url_patch(value=URL, input_option="RAW"):
    return base_patch(operations=[{"op_id": "op-url", "type": "write_value", "range": f"{Q}!H5", "values": [[value]], "input_option": input_option}])


def _failed_structure(out):
    v = out["verification"]
    assert out["status"] == "conflict" and out["receipt"]["status"] == "partial"
    assert v["structure_preserved"] is False and v["auto_linked_cells"] == []
    return v


def test_fake_auto_links_a_raw_url_string_only(transport):
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!H5:J5", "values": [[URL, "plain text", 7]]}], "RAW")
    assert transport.cell(SPREADSHEET_ID, TAB, "H5") == {"value": URL, "formula": None, "format": LINK}
    assert "format" not in transport.cell(SPREADSHEET_ID, TAB, "I5")
    assert "format" not in transport.cell(SPREADSHEET_ID, TAB, "J5")


def test_raw_url_read_back_with_automatic_link_verifies(transport, sources_doc, validate, repo_root):
    out = _run(transport, sources_doc, _url_patch())
    assert out["status"] == "success", (out["conflicts"], out["verification"])
    v = out["verification"]
    assert v["targets_match"] and v["structure_preserved"] and v["structure_differences"] == []
    assert v["auto_linked_cells"] == [f"{Q}!H5"]  # reported, not silently dropped
    assert out["receipt"]["status"] == "success"
    assert transport.cell(SPREADSHEET_ID, TAB, "H5")["format"] == LINK
    assert not validate(out, repo_root / SCHEMA)


def test_automatic_link_on_top_of_existing_formatting_verifies(transport, sources_doc):
    transport.set_format(SPREADSHEET_ID, TAB, "H5", {"textFormat": {"bold": True}, "horizontalAlignment": "LEFT"})
    out = _run(transport, sources_doc, _url_patch())
    assert out["status"] == "success", out["verification"]
    assert out["verification"]["auto_linked_cells"] == [f"{Q}!H5"]
    assert transport.cell(SPREADSHEET_ID, TAB, "H5")["format"] == {
        "textFormat": {"bold": True, "link": {"uri": URL}}, "horizontalAlignment": "LEFT"}


def test_replay_over_an_auto_linked_cell_is_no_change(transport, sources_doc):
    assert _run(transport, sources_doc, _url_patch())["status"] == "success"
    again = preview_patch(transport, client_id=CLIENT_ID, patch=_url_patch(), sources_doc=sources_doc)
    assert again["status"] == "no_change" and again["diff"] == []


def test_different_url_read_back_fails(transport, sources_doc):
    out = _run(transport, sources_doc, _url_patch(),
               after_write=lambda t: t.set_cell(SPREADSHEET_ID, TAB, "H5", OTHER_URL))
    v = out["verification"]
    assert out["status"] == "conflict" and v["targets_match"] is False
    assert v["mismatches"][0]["cell"] == f"{Q}!H5" and v["mismatches"][0]["observed"]["value"] == OTHER_URL
    assert v["auto_linked_cells"] == []


def test_link_to_another_uri_than_the_written_text_fails(transport, sources_doc):
    out = _run(transport, sources_doc, _url_patch(),
               after_write=lambda t: t.set_format(SPREADSHEET_ID, TAB, "H5", {"textFormat": {"link": {"uri": OTHER_URL}}}))
    v = _failed_structure(out)
    assert v["targets_match"] is True
    assert v["structure_differences"] == [{"sheet": TAB, "cell": "H5", "property": "cell_format_or_validation"}]


def test_link_plus_any_other_format_change_fails(transport, sources_doc):
    out = _run(transport, sources_doc, _url_patch(),
               after_write=lambda t: t.set_format(SPREADSHEET_ID, TAB, "H5", {"textFormat": {"link": {"uri": URL}, "bold": True}}))
    _failed_structure(out)


def test_link_plus_data_validation_change_fails(transport, sources_doc):
    def remote(t):
        t._books[SPREADSHEET_ID]["sheets"][TAB]["cells"][(5, 8)]["data_validation"] = {"condition": {"type": "BOOLEAN"}}
    _failed_structure(_run(transport, sources_doc, _url_patch(), after_write=remote))


def test_link_on_a_non_raw_write_is_not_tolerated(transport, sources_doc):
    # USER_ENTERED was not observed to auto-link; the tolerance stays RAW-only
    out = _run(transport, sources_doc, _url_patch(input_option="USER_ENTERED"),
               after_write=lambda t: t.set_format(SPREADSHEET_ID, TAB, "H5", LINK))
    _failed_structure(out)


def test_link_on_text_that_is_not_a_url_fails(transport, sources_doc):
    # Sheets only auto-links URLs: a link on plain text is a real change even with uri == text
    patch = base_patch(operations=[{"op_id": "op-url", "type": "write_value", "range": f"{Q}!H5:H6", "values": [[URL], ["texto"]]}])
    out = _run(transport, sources_doc, patch,
               after_write=lambda t: t.set_format(SPREADSHEET_ID, TAB, "H6", {"textFormat": {"link": {"uri": "texto"}}}))
    v = out["verification"]
    assert out["status"] == "conflict" and v["auto_linked_cells"] == [f"{Q}!H5"]
    assert v["structure_differences"] == [{"sheet": TAB, "cell": "H6", "property": "cell_format_or_validation"}]


def test_different_plain_text_fails(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "op-t", "type": "write_value", "range": f"{Q}!H5", "values": [["texto esperado"]]}])
    out = _run(transport, sources_doc, patch, after_write=lambda t: t.set_cell(SPREADSHEET_ID, TAB, "H5", "texto alterado"))
    assert out["status"] == "conflict" and out["verification"]["targets_match"] is False


def test_different_number_fails(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "op-n", "type": "write_value", "range": f"{Q}!H5", "values": [[42]]}])
    out = _run(transport, sources_doc, patch, after_write=lambda t: t.set_cell(SPREADSHEET_ID, TAB, "H5", 43))
    assert out["status"] == "conflict" and out["verification"]["targets_match"] is False


def test_number_read_back_as_the_url_text_fails(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "op-n", "type": "write_value", "range": f"{Q}!H5", "values": [[42]]}])
    out = _run(transport, sources_doc, patch, after_write=lambda t: (
        t.set_cell(SPREADSHEET_ID, TAB, "H5", URL), t.set_format(SPREADSHEET_ID, TAB, "H5", LINK)))
    v = out["verification"]
    assert out["status"] == "conflict" and v["targets_match"] is False and v["structure_preserved"] is False


def test_different_formula_fails(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "op-f", "type": "write_formula", "range": f"{Q}!H5", "formulas": [["=SUM(B2:B3)"]]}])
    out = _run(transport, sources_doc, patch, after_write=lambda t: t.set_cell(SPREADSHEET_ID, TAB, "H5", "=SUM(B2:B4)"))
    assert out["status"] == "conflict" and out["verification"]["targets_match"] is False


def test_url_cell_turned_into_a_formula_fails(transport, sources_doc):
    out = _run(transport, sources_doc, _url_patch(),
               after_write=lambda t: t.set_cell(SPREADSHEET_ID, TAB, "H5", f'=HYPERLINK("{URL}")'))
    v = out["verification"]
    assert out["status"] == "conflict" and v["targets_match"] is False and v["auto_linked_cells"] == []


def test_managed_number_format_different_fails(transport, sources_doc):
    patch = base_patch(operations=[{"op_id": "op-nf", "type": "set_number_format", "range": f"{Q}!C2",
                                    "number_format": {"type": "NUMBER", "pattern": "0.00"}}])
    out = _run(transport, sources_doc, patch,
               after_write=lambda t: t.set_format(SPREADSHEET_ID, TAB, "C2", {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}))
    assert out["status"] == "conflict" and out["verification"]["targets_match"] is False
