from __future__ import annotations

import pytest

from scripts.lib.a1_notation import A1Error, cell_a1, col_to_letters, letters_to_col, parse_a1
from scripts.lib.google_sheets_transport import (
    GoogleSheetsAuthError,
    GoogleSheetsNotFound,
    GoogleSheetsRangeError,
)

from .conftest import Q, SPREADSHEET_ID, TAB


@pytest.mark.parametrize("col,letters", [(1, "A"), (26, "Z"), (27, "AA"), (52, "AZ"), (703, "AAA")])
def test_column_letters_roundtrip(col, letters):
    assert col_to_letters(col) == letters
    assert letters_to_col(letters) == col


def test_parse_quoted_sheet_with_accents_and_escaped_quote():
    a1 = parse_a1("'Métricas d''Acme'!B2:D4")
    assert (a1.sheet_title, a1.start_row, a1.start_col, a1.end_row, a1.end_col) == ("Métricas d'Acme", 2, 2, 4, 4)
    assert a1.to_a1() == "'Métricas d''Acme'!B2:D4"
    assert parse_a1(a1.to_a1()) == a1


def test_parse_single_cell_whole_sheet_and_open_ranges():
    assert parse_a1("Dados!C7").cells() == [(7, 3)]
    assert parse_a1("Dados").is_whole_sheet
    assert not parse_a1("Dados!A:C").is_bounded
    assert cell_a1("Dados", 2, 3) == "Dados!C2"


@pytest.mark.parametrize("bad", ["A1:B2", "B2", "Dados!", "Dados!B3:A1", "'Unterminated!A1", "Dados!1A"])
def test_parse_rejects_ambiguous_or_invalid(bad):
    with pytest.raises(A1Error):
        parse_a1(bad)


def test_fake_reads_values_formulas_and_pads(transport):
    vals = transport.read_values(SPREADSHEET_ID, [f"{Q}!A2:E2"])[0]["values"]
    assert vals == [["S1", 100, 10, 10, ""]]
    forms = transport.read_formulas(SPREADSHEET_ID, [f"{Q}!D2:D3"])[0]["values"]
    assert forms == [["=IFERROR(B2/C2,0)"], ["=IFERROR(B3/C3,0)"]]


def test_fake_write_keeps_format_and_user_entered_formula(transport):
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!B3", "values": [[5]]}], "RAW")
    assert transport.cell(SPREADSHEET_ID, TAB, "B3")["format"] == {"numberFormat": {"type": "CURRENCY"}}
    transport.write_values(SPREADSHEET_ID, [{"range": f"{Q}!E2", "values": [["=B2*2"]]}], "USER_ENTERED")
    assert transport.cell(SPREADSHEET_ID, TAB, "E2")["formula"] == "=B2*2"


def test_fake_errors_mirror_api(transport):
    with pytest.raises(GoogleSheetsNotFound):
        transport.get_spreadsheet_metadata("fake-does-not-exist-000")
    with pytest.raises(GoogleSheetsRangeError):
        transport.read_values(SPREADSHEET_ID, ["'Inexistente'!A1"])
    with pytest.raises(GoogleSheetsRangeError):
        transport.read_values(SPREADSHEET_ID, [f"{Q}!A1:Z999"])
    transport.auth_error = True
    with pytest.raises(GoogleSheetsAuthError):
        transport.list_sheets(SPREADSHEET_ID)
