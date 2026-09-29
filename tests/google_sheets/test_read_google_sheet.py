from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.google_sheets_read import read_google_sheet
from scripts.lib.google_sheets_transport import GoogleSheetsAPIError

from .conftest import CLIENT_ID, OTHER_SPREADSHEET_ID, Q, SOURCE_ID, SPREADSHEET_ID

SCHEMA = "skills/read-google-sheet/output.schema.json"


def _read(transport, sources_doc, ranges, **kw):
    kw.setdefault("source_id", SOURCE_ID)
    return read_google_sheet(transport, client_id=kw.pop("client_id", CLIENT_ID), sources_doc=sources_doc, ranges=ranges, **kw)


def test_read_snapshot_values_formulas_tabs(transport, sources_doc, validate, repo_root):
    out = _read(transport, sources_doc, [f"{Q}!A1:D3", "Resumo"], include_formatted=True)
    assert out["status"] == "success", out["errors"]
    assert not validate(out, repo_root / SCHEMA)
    assert out["source"]["spreadsheet_id"] == SPREADSHEET_ID
    assert out["source"]["source_date"] is None
    assert [t["title"] for t in out["tabs"]] == ["Métricas", "Resumo"]
    first = out["ranges"][0]
    assert first["values"][1] == ["S1", 100, 10, 10]
    assert {f["cell"]: f["formula"] for f in first["formulas"]} == {"D2": "=IFERROR(B2/C2,0)", "D3": "=IFERROR(B3/C3,0)"}
    assert first["formatted_values"] is not None
    assert out["ranges"][1]["formulas"][0]["formula"] == "='Métricas'!F2"
    assert any(w["code"] == "RANGE_TRIMMED" for w in out["warnings"])


def test_read_never_writes(transport, sources_doc):
    _read(transport, sources_doc, [f"{Q}!A1:D3"])
    assert transport.write_calls == []
    assert all(op not in ("write_values", "batch_update") for op, _ in transport.calls)


def test_read_by_url_locator_resolves_same_source(transport, sources_doc):
    out = _read(transport, sources_doc, [f"{Q}!A1"], source_id=None, spreadsheet_locator=f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid=0")
    assert out["status"] == "success"
    assert out["source"]["source_id"] == SOURCE_ID


def test_observed_at_is_real_clock(transport, sources_doc):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    out = _read(transport, sources_doc, [f"{Q}!A1"])
    observed = datetime.strptime(out["source"]["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= observed <= datetime.now(timezone.utc) + timedelta(seconds=1)
    assert out["generated_at"] == out["source"]["observed_at"]


def test_future_clock_is_flagged(transport, sources_doc):
    out = _read(transport, sources_doc, [f"{Q}!A1"], clock=lambda: "2999-01-01T00:00:00Z")
    assert any(w["code"] == "EXECUTION_TIMESTAMP_IN_FUTURE" for w in out["warnings"])


def test_missing_tab_and_out_of_grid_are_partial(transport, sources_doc):
    out = _read(transport, sources_doc, [f"{Q}!A1:B2", "'Não Existe'!A1", f"{Q}!A1:Z999"])
    assert out["status"] == "partial"
    codes = {m["code"] for m in out["missing_data"]}
    assert codes == {"SHEET_NOT_FOUND", "RANGE_OUT_OF_GRID"}
    assert len(out["ranges"]) == 1


def test_only_invalid_ranges_is_error(transport, sources_doc, validate, repo_root):
    out = _read(transport, sources_doc, ["A1:B2"])
    assert out["status"] == "error"
    assert out["errors"][0]["code"] == "INVALID_RANGE"
    assert not validate(out, repo_root / SCHEMA)


def test_no_ranges_requested_is_error(transport, sources_doc):
    assert _read(transport, sources_doc, [])["errors"][0]["code"] == "NO_RANGES_REQUESTED"


def test_client_isolation_other_clients_spreadsheet_refused(transport, sources_doc, other_sources_doc):
    # client A may not read client B's declared sheet
    out = _read(transport, sources_doc, ["Dados!A1"], source_id=None, spreadsheet_locator=OTHER_SPREADSHEET_ID)
    assert out["status"] == "error" and out["errors"][0]["code"] == "SOURCE_NOT_REGISTERED"
    # a sources.json of another client is never accepted
    out = _read(transport, other_sources_doc, ["Dados!A1"], source_id=None, spreadsheet_locator=OTHER_SPREADSHEET_ID, client_id=CLIENT_ID)
    assert out["errors"][0]["code"] == "CLIENT_ISOLATION"
    assert transport.calls == []


def test_wrong_spreadsheet_title_mismatch(transport, sources_doc):
    sources_doc["sources"][1]["google_sheet"]["expected_title"] = "Some Other Title"
    out = _read(transport, sources_doc, [f"{Q}!A1"])
    assert out["status"] == "error" and out["errors"][0]["code"] == "WRONG_SPREADSHEET"


def test_name_is_never_a_locator(transport, sources_doc):
    out = _read(transport, sources_doc, [f"{Q}!A1"], source_id=None, spreadsheet_locator="Synthetic Metrics")
    assert out["errors"][0]["code"] == "INVALID_LOCATOR"


def test_tab_allowlist(transport, sources_doc):
    sources_doc["sources"][1]["google_sheet"]["allowed_tabs"] = ["Resumo"]
    out = _read(transport, sources_doc, [f"{Q}!A1", "Resumo!A1"])
    assert out["status"] == "partial"
    assert out["errors"][0]["code"] == "TAB_NOT_ALLOWED"


def test_auth_and_api_errors(transport, sources_doc):
    transport.auth_error = True
    out = _read(transport, sources_doc, [f"{Q}!A1"])
    assert out["status"] == "error" and out["errors"][0]["code"] == "AUTH_ERROR"
    transport.auth_error = False
    transport.fail_next = GoogleSheetsAPIError("HTTP 500: backend error")
    out = _read(transport, sources_doc, [f"{Q}!A1"])
    assert out["status"] == "error" and out["errors"][0]["code"] == "API_ERROR"


def test_unknown_spreadsheet_is_not_found(transport, sources_doc):
    sources_doc["sources"][1]["google_sheet"]["spreadsheet_id"] = "fake-deleted-sheet-0000"
    out = _read(transport, sources_doc, [f"{Q}!A1"])
    assert out["errors"][0]["code"] == "SPREADSHEET_NOT_FOUND"


def test_idempotent_content_hash(transport, sources_doc):
    a = _read(transport, sources_doc, [f"{Q}!A1:D3"])
    b = _read(transport, sources_doc, [f"{Q}!A1:D3"])
    assert a["ranges"][0]["content_sha256"] == b["ranges"][0]["content_sha256"]
