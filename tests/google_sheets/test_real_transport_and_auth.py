"""The real transport is exercised against an injected, recording stand-in
for the googleapiclient `service` object — request shapes and error
mapping are verified without network access or real credentials."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib import google_sheets_auth as auth
from scripts.lib.google_sheets_transport import (
    GoogleApiSheetsTransport,
    GoogleSheetsAPIError,
    GoogleSheetsAuthError,
    GoogleSheetsNotFound,
    GoogleSheetsPermissionDenied,
    GoogleSheetsRangeError,
    map_google_error,
)


class _Req:
    def __init__(self, log, name, kwargs, response=None, error=None):
        self.log, self.name, self.kwargs, self.response, self.error = log, name, kwargs, response, error

    def execute(self, num_retries=0):
        self.log.append((self.name, self.kwargs))
        if self.error:
            raise self.error
        return self.response


class _Values:
    def __init__(self, svc):
        self.svc = svc

    def batchGet(self, **kw):
        return _Req(self.svc.log, "values.batchGet", kw, self.svc.responses.get("values.batchGet"), self.svc.error)

    def batchUpdate(self, **kw):
        return _Req(self.svc.log, "values.batchUpdate", kw, {"totalUpdatedCells": 2, "responses": [{"updatedRange": "Dados!A1:B1"}]}, self.svc.error)

    def batchClear(self, **kw):
        return _Req(self.svc.log, "values.batchClear", kw, {"clearedRanges": kw["body"]["ranges"]}, self.svc.error)


class _Spreadsheets:
    def __init__(self, svc):
        self.svc = svc

    def get(self, **kw):
        key = "get.grid" if kw.get("includeGridData") else "get.meta"
        return _Req(self.svc.log, key, kw, self.svc.responses.get(key), self.svc.error)

    def values(self):
        return _Values(self.svc)

    def batchUpdate(self, **kw):
        return _Req(self.svc.log, "batchUpdate", kw, {"replies": []}, self.svc.error)


class RecordingService:
    def __init__(self, responses=None, error=None):
        self.log, self.responses, self.error = [], responses or {}, error

    def spreadsheets(self):
        return _Spreadsheets(self)


class _Resp:
    def __init__(self, status):
        self.status = status


class HttpError(Exception):  # same duck-typed shape as googleapiclient.errors.HttpError
    def __init__(self, status, reason):
        super().__init__(reason)
        self.resp = _Resp(status)
        self.reason = reason


class RefreshError(Exception):
    pass


def test_metadata_request_and_normalization():
    svc = RecordingService({"get.meta": {
        "spreadsheetId": "fake-sheet-000000001", "properties": {"title": "Synthetic", "locale": "pt_BR", "timeZone": "America/Sao_Paulo"},
        "sheets": [{"properties": {"sheetId": 7, "title": "Dados", "index": 0, "gridProperties": {"rowCount": 10, "columnCount": 4}}}],
    }})
    meta = GoogleApiSheetsTransport(service=svc).get_spreadsheet_metadata("fake-sheet-000000001")
    assert meta["sheets"] == [{"sheet_id": 7, "title": "Dados", "index": 0, "row_count": 10, "column_count": 4, "frozen_row_count": 0, "frozen_column_count": 0, "hidden": False}]
    name, kw = svc.log[0]
    assert kw["includeGridData"] is False and "sheets(properties" in kw["fields"]


def test_values_batch_get_render_options_and_padding():
    svc = RecordingService({"values.batchGet": {"valueRanges": [{"range": "Dados!A1:C2", "values": [["a"]]}]}})
    out = GoogleApiSheetsTransport(service=svc).read_formulas("fake-sheet-000000001", ["Dados!A1:C2"])
    assert out[0]["values"] == [["a", "", ""], ["", "", ""]]
    kw = svc.log[0][1]
    assert kw["valueRenderOption"] == "FORMULA" and kw["dateTimeRenderOption"] == "FORMATTED_STRING" and kw["majorDimension"] == "ROWS"


def test_write_values_is_content_only_values_batch_update():
    svc = RecordingService()
    resp = GoogleApiSheetsTransport(service=svc).write_values("fake-sheet-000000001", [{"range": "Dados!A1:B1", "values": [[1, 2]]}], "RAW")
    name, kw = svc.log[0]
    assert name == "values.batchUpdate"
    assert kw["body"]["valueInputOption"] == "RAW"
    assert kw["body"]["data"] == [{"range": "Dados!A1:B1", "majorDimension": "ROWS", "values": [[1, 2]]}]
    assert resp == {"updated_cells": 2, "updated_ranges": ["Dados!A1:B1"]}
    with pytest.raises(ValueError):
        GoogleApiSheetsTransport(service=svc).write_values("x" * 12, [], "PARSED")


def test_clear_values_uses_values_batch_clear_never_an_empty_string_write():
    svc = RecordingService()
    resp = GoogleApiSheetsTransport(service=svc).clear_values("fake-sheet-000000001", ["Dados!A1:B2", "Dados!D4"])
    assert [name for name, _ in svc.log] == ["values.batchClear"]
    assert svc.log[0][1]["body"] == {"ranges": ["Dados!A1:B2", "Dados!D4"]}
    assert resp == {"cleared_ranges": ["Dados!A1:B2", "Dados!D4"]}


def test_set_number_formats_is_a_repeat_cell_restricted_to_number_format():
    svc = RecordingService()
    GoogleApiSheetsTransport(service=svc).set_number_formats(
        "fake-sheet-000000001", [{"sheet_id": 7, "range": "Dados!B2:D3", "number_format": {"type": "NUMBER", "pattern": "#,##0"}}])
    name, kw = svc.log[0]
    assert name == "batchUpdate"
    assert kw["body"]["requests"] == [{"repeatCell": {
        "range": {"sheetId": 7, "startRowIndex": 1, "endRowIndex": 3, "startColumnIndex": 1, "endColumnIndex": 4},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
        "fields": "userEnteredFormat.numberFormat",
    }}]


def test_get_cell_formats_returns_raw_user_entered_format_per_cell():
    fmt = {"numberFormat": {"type": "CURRENCY", "pattern": "[$R$ -416]#,##0.00"}, "backgroundColor": {"red": 1}}
    svc = RecordingService({"get.grid": {"sheets": [{
        "properties": {"title": "Dados"},
        "data": [{"startRow": 1, "startColumn": 1, "rowData": [{"values": [{"userEnteredFormat": fmt, "dataValidation": {"strict": True}}]}]}],
    }]}})
    out = GoogleApiSheetsTransport(service=svc).get_cell_formats("fake-sheet-000000001", ["Dados!B2:C2"])
    assert out == {
        "Dados!B2": {"user_entered_format": fmt, "data_validation": {"strict": True}},
        "Dados!C2": {"user_entered_format": None, "data_validation": None},
    }
    assert "userEnteredFormat" in svc.log[0][1]["fields"] and "effectiveFormat" not in svc.log[0][1]["fields"]


def test_duplicate_sheet_is_the_native_duplicate_sheet_request():
    class _DupService(RecordingService):
        def spreadsheets(self):
            s = _Spreadsheets(self)
            s.batchUpdate = lambda **kw: _Req(self.log, "batchUpdate", kw, {"replies": [{"duplicateSheet": {"properties": {"sheetId": 42, "title": "OUTUBRO", "index": 2}}}]})
            return s

    svc = _DupService()
    out = GoogleApiSheetsTransport(service=svc).duplicate_sheet("fake-sheet-000000001", 7, "OUTUBRO", 2)
    name, kw = svc.log[0]
    assert name == "batchUpdate"
    assert kw["body"] == {"requests": [{"duplicateSheet": {"sourceSheetId": 7, "insertSheetIndex": 2, "newSheetName": "OUTUBRO"}}]}
    assert out == {"sheet_id": 42, "title": "OUTUBRO", "index": 2}


def test_sheet_snapshot_normalizes_ids_and_keeps_cell_properties():
    svc = RecordingService({"get.grid": {"sheets": [{
        "properties": {"sheetId": 7, "title": "SETEMBRO", "index": 1, "gridProperties": {"rowCount": 10, "columnCount": 4, "frozenRowCount": 1}},
        "merges": [{"sheetId": 7, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 4}],
        "protectedRanges": [{"protectedRangeId": 99, "range": {"sheetId": 7, "startRowIndex": 0}, "warningOnly": True}],
        "data": [{"startRow": 0, "startColumn": 0, "columnMetadata": [{"pixelSize": 202}],
                  "rowData": [{"values": [{"userEnteredValue": {"stringValue": "PLAYBOOK"}, "userEnteredFormat": {"textFormat": {"bold": True}}},
                                          {"userEnteredValue": {"formulaValue": "=1+1"}, "note": "n", "hyperlink": "https://x"},
                                          {}, {"dataValidation": {"condition": {"type": "BOOLEAN"}}}]}]}],
    }]}})
    snap = GoogleApiSheetsTransport(service=svc).get_sheet_snapshot("fake-sheet-000000001", "SETEMBRO")
    assert svc.log[0][1]["ranges"] == ["SETEMBRO"] and svc.log[0][1]["includeGridData"] is True
    assert (snap["sheet_id"], snap["title"], snap["index"]) == (7, "SETEMBRO", 1)
    assert snap["merges"] == [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 4}]
    assert snap["protected_ranges"] == [{"range": {"startRowIndex": 0}, "warningOnly": True}]
    assert set(snap["cells"]) == {"A1", "B1", "D1"}
    assert snap["cells"]["B1"] == {"userEnteredValue": {"formulaValue": "=1+1"}, "note": "n", "hyperlink": "https://x"}
    assert snap["column_sizes"] == [{"size": 202, "hidden": False}]


def test_structure_fingerprint_from_grid_response():
    svc = RecordingService({"get.grid": {"sheets": [{
        "properties": {"sheetId": 7, "title": "Dados", "gridProperties": {"rowCount": 10, "columnCount": 4}},
        "merges": [{"startRowIndex": 0, "endRowIndex": 1}],
        "data": [{"startRow": 0, "startColumn": 0, "rowData": [{"values": [{"userEnteredFormat": {"textFormat": {"bold": True}}}]}]}],
    }]}})
    fp = GoogleApiSheetsTransport(service=svc).get_structure("fake-sheet-000000001", ["Dados!A1:B1"])
    assert set(fp["Dados"]["cells"]) == {"A1", "B1"}
    assert fp["Dados"]["cells"]["A1"] != fp["Dados"]["cells"]["B1"]
    assert svc.log[0][1]["includeGridData"] is True


@pytest.mark.parametrize("exc,expected", [
    (HttpError(401, "Request had invalid authentication credentials"), GoogleSheetsAuthError),
    (HttpError(403, "The caller does not have permission"), GoogleSheetsPermissionDenied),
    (HttpError(404, "Requested entity was not found"), GoogleSheetsNotFound),
    (HttpError(400, "Unable to parse range: Nope!A1"), GoogleSheetsRangeError),
    (HttpError(500, "Internal error"), GoogleSheetsAPIError),
    (RefreshError("invalid_grant"), GoogleSheetsAuthError),
])
def test_error_mapping(exc, expected):
    mapped = map_google_error(exc)
    assert type(mapped) is expected
    svc = RecordingService(error=exc)
    with pytest.raises(expected):
        GoogleApiSheetsTransport(service=svc).get_spreadsheet_metadata("fake-sheet-000000001")


def test_real_transport_requires_credentials_or_service():
    with pytest.raises(GoogleSheetsAuthError):
        GoogleApiSheetsTransport()


# -- auth configuration ------------------------------------------------------


def test_default_config_is_oauth_with_token_outside_repo(tmp_path):
    cfg = auth.load_auth_config({})
    assert cfg.mode == "oauth"
    assert auth.ENGINE_ROOT not in cfg.token_path.parents
    cfg = auth.load_auth_config({auth.ENV_TOKEN_PATH: str(tmp_path / "t.json"), auth.ENV_CLIENT_SECRETS: str(tmp_path / "cs.json")})
    assert cfg.token_path == (tmp_path / "t.json").resolve()


@pytest.mark.parametrize("env_name", [auth.ENV_TOKEN_PATH, auth.ENV_CLIENT_SECRETS])
def test_credential_paths_inside_engine_repo_are_refused(repo_root: Path, env_name):
    with pytest.raises(GoogleSheetsAuthError, match="inside the engine repository"):
        auth.load_auth_config({env_name: str(repo_root / "private" / "token.json")})


def test_service_account_mode_is_optional_and_explicit(tmp_path, repo_root):
    with pytest.raises(GoogleSheetsAuthError):
        auth.load_auth_config({auth.ENV_AUTH_MODE: "service_account"})
    cfg = auth.load_auth_config({auth.ENV_AUTH_MODE: "service_account", auth.ENV_SERVICE_ACCOUNT_FILE: str(tmp_path / "sa.json")})
    assert cfg.mode == "service_account"
    with pytest.raises(GoogleSheetsAuthError):
        auth.load_auth_config({auth.ENV_AUTH_MODE: "service_account", auth.ENV_SERVICE_ACCOUNT_FILE: str(repo_root / "sa.json")})
    with pytest.raises(GoogleSheetsAuthError):
        auth.load_auth_config({auth.ENV_AUTH_MODE: "api_key"})


def test_missing_token_is_auth_error_not_browser_popup(tmp_path):
    pytest.importorskip("google.oauth2.credentials")
    cfg = auth.load_auth_config({auth.ENV_TOKEN_PATH: str(tmp_path / "absent.json")})
    with pytest.raises(GoogleSheetsAuthError, match="scripts/google_sheets.py auth"):
        auth.load_credentials(cfg)


def test_auth_errors_never_leak_secret_material(tmp_path):
    pytest.importorskip("google.oauth2.credentials")
    token = tmp_path / "token.json"
    token.write_text('{"refresh_token": "SUPER-SECRET-REFRESH", "client_secret": "SUPER-SECRET-CLIENT"}', encoding="utf-8")
    cfg = auth.load_auth_config({auth.ENV_TOKEN_PATH: str(token)})
    with pytest.raises(GoogleSheetsAuthError) as e:
        auth.load_credentials(cfg)
    assert "SUPER-SECRET" not in str(e.value)
