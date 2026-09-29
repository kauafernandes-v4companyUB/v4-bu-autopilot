"""Google Drive file lifecycle — FakeGoogleDriveTransport only; synthetic
ids (fake-*) only; no call ever reaches Google."""

from __future__ import annotations

import json

import pytest

from scripts.lib import google_sheets_auth as auth
from scripts.lib.google_drive_lifecycle import inspect_file, run_operation
from scripts.lib.google_drive_transport import (
    APP_PROP_OPERATION,
    APP_PROP_SOURCE,
    MIME_FOLDER,
    MIME_GOOGLE_SHEET,
    MIME_XLSX,
    FakeGoogleDriveTransport,
    GoogleApiDriveTransport,
)
from scripts.lib.google_sheets_transport import GoogleInsufficientScope, GoogleSheetsAPIError, GoogleSheetsAuthError

SCHEMA = "schemas/google-drive-file-operation.schema.json"
XLSX = "fake-xlsx-file"
NATIVE = "fake-native-sheet"
FOLDER = "fake-destination-folder"


@pytest.fixture
def drive() -> FakeGoogleDriveTransport:
    d = FakeGoogleDriveTransport()
    d.add_file(XLSX, name="Synthetic Playbook.xlsx", mime_type=MIME_XLSX, parents=["fake-src-folder"], content=b"PK\x03\x04synthetic-xlsx")
    d.add_file(NATIVE, name="[MODELO] Synthetic Metrics", mime_type=MIME_GOOGLE_SHEET, parents=["fake-src-folder"])
    d.add_file(FOLDER, name="Synthetic Client Folder", mime_type=MIME_FOLDER)
    d.add_file("fake-pdf-file", name="report.pdf", mime_type="application/pdf")
    return d


def _run(drive, operation, source, mode="apply", **kw):
    return run_operation(drive, operation=operation, source_file_id=source, name=kw.pop("name", "[Synthetic] Operational"), mode=mode, **kw)


# -- metadata -------------------------------------------------------------------


def test_metadata_native_sheet_and_xlsx(drive):
    native = inspect_file(drive, NATIVE)["file"]
    assert (native["mime_type"], native["kind"]) == (MIME_GOOGLE_SHEET, "google_sheet")
    xlsx = inspect_file(drive, XLSX)["file"]
    assert (xlsx["mime_type"], xlsx["kind"]) == (MIME_XLSX, "xlsx")
    assert xlsx["parents"] == ["fake-src-folder"] and xlsx["capabilities"]["can_download"] is True


def test_metadata_missing_and_denied(drive):
    assert inspect_file(drive, "fake-missing-file")["errors"][0]["code"] == "FILE_NOT_FOUND"
    drive.denied.add(XLSX)
    assert inspect_file(drive, XLSX)["errors"][0]["code"] == "PERMISSION_DENIED"


# -- convert xlsx ---------------------------------------------------------------


def test_convert_xlsx_creates_new_native_sheet_and_preserves_original(drive, validate, repo_root):
    original = drive.snapshot(XLSX)
    out = _run(drive, "convert_xlsx", XLSX, name="[Synthetic] Playbook", destination_folder_id=FOLDER)
    assert out["status"] == "created", out["errors"]
    assert not validate(out, repo_root / SCHEMA)
    created = out["created"]
    assert created["file_id"] != XLSX and created["spreadsheet_id"] == created["file_id"]
    assert created["mime_type"] == MIME_GOOGLE_SHEET
    assert created["name"] == "[Synthetic] Playbook"
    assert created["parents"] == [FOLDER]
    assert out["original_preserved"] is True
    assert drive.snapshot(XLSX) == original
    new = drive.files[created["file_id"]]
    assert new["imported_from_bytes"] == len(original["content"])
    assert new["appProperties"] == {APP_PROP_SOURCE: XLSX, APP_PROP_OPERATION: "convert_xlsx"}


def test_plan_creates_nothing(drive):
    before = set(drive.files)
    out = _run(drive, "convert_xlsx", XLSX, mode="plan")
    assert out["status"] == "planned" and out["created"] is None
    assert set(drive.files) == before
    assert not any(op in ("import_as_google_sheet", "copy_file", "download_file") for op, _ in drive.calls)


def test_convert_rejects_non_xlsx(drive):
    for source in (NATIVE, "fake-pdf-file"):
        out = _run(drive, "convert_xlsx", source)
        assert out["status"] == "error" and out["errors"][0]["code"] == "NOT_XLSX"
    assert _run(drive, "copy_sheet", XLSX)["errors"][0]["code"] == "NOT_GOOGLE_SHEET"


def test_conversion_failure_creates_nothing(drive):
    before = set(drive.files)
    drive.fail_import = GoogleSheetsAPIError("HTTP 500: conversion failed")
    out = _run(drive, "convert_xlsx", XLSX)
    assert out["status"] == "error" and out["errors"][0]["code"] == "API_ERROR"
    assert out["created"] is None and set(drive.files) == before


def test_destination_must_be_a_folder(drive):
    out = _run(drive, "convert_xlsx", XLSX, destination_folder_id=NATIVE)
    assert out["errors"][0]["code"] == "DESTINATION_NOT_FOLDER"
    missing = _run(drive, "convert_xlsx", XLSX, destination_folder_id="fake-missing-folder")
    assert missing["errors"][0]["code"] == "FILE_NOT_FOUND"


def test_convert_is_replay_safe(drive):
    first = _run(drive, "convert_xlsx", XLSX)
    count = len(drive.files)
    again = _run(drive, "convert_xlsx", XLSX)
    assert again["status"] == "no_change"
    assert again["created"]["file_id"] == first["created"]["file_id"]
    assert len(drive.files) == count
    assert _run(drive, "convert_xlsx", XLSX, mode="plan")["status"] == "no_change"


def test_duplicate_existing_copies_block(drive):
    props = {APP_PROP_SOURCE: XLSX, APP_PROP_OPERATION: "convert_xlsx"}
    for i in (1, 2):
        drive.add_file(f"fake-dup-{i}", name="[Synthetic] Operational", mime_type=MIME_GOOGLE_SHEET, app_properties=props)
    count = len(drive.files)
    out = _run(drive, "convert_xlsx", XLSX)
    assert out["errors"][0]["code"] == "DUPLICATE_OPERATIONAL_COPIES" and len(drive.files) == count


# -- copy native ------------------------------------------------------------------


def test_copy_native_sheet(drive, validate, repo_root):
    original = drive.snapshot(NATIVE)
    out = _run(drive, "copy_sheet", NATIVE, name="[Synthetic] Planilha de Métricas")
    assert out["status"] == "created" and not validate(out, repo_root / SCHEMA)
    assert out["created"]["file_id"] != NATIVE and out["created"]["mime_type"] == MIME_GOOGLE_SHEET
    assert out["created"]["name"] == "[Synthetic] Planilha de Métricas"
    assert drive.snapshot(NATIVE) == original and out["original_preserved"] is True
    assert ("copy_file", NATIVE) in drive.calls and not any(op == "download_file" for op, _ in drive.calls)
    assert _run(drive, "copy_sheet", NATIVE, name="[Synthetic] Planilha de Métricas")["status"] == "no_change"


def test_copy_failure_and_capability(drive):
    drive.fail_copy = GoogleSheetsAPIError("HTTP 500: backend")
    assert _run(drive, "copy_sheet", NATIVE)["status"] == "error"
    drive.fail_copy = None
    drive.files[NATIVE]["capabilities"]["canCopy"] = False
    assert _run(drive, "copy_sheet", NATIVE)["errors"][0]["code"] == "PERMISSION_DENIED"


def test_auth_and_insufficient_scope_errors(drive):
    drive.auth_error = True
    assert _run(drive, "convert_xlsx", XLSX)["errors"][0]["code"] == "AUTH_ERROR"
    drive.auth_error = False
    drive.insufficient_scope = True
    out = _run(drive, "convert_xlsx", XLSX)
    assert out["errors"][0]["code"] == "INSUFFICIENT_SCOPE"
    assert "google_sheets.py auth" in out["errors"][0]["message"]


def test_invalid_inputs(drive):
    assert _run(drive, "delete_file", XLSX)["errors"][0]["code"] == "UNSUPPORTED_OPERATION"
    assert _run(drive, "convert_xlsx", XLSX, name="  ")["errors"][0]["code"] == "INVALID_NAME"
    assert drive.calls == []


def test_drive_transport_has_no_mutating_operation_on_existing_files():
    forbidden = {"update", "delete", "trash", "move", "rename", "update_file", "delete_file"}
    assert not forbidden & set(dir(GoogleApiDriveTransport))
    assert not forbidden & set(dir(FakeGoogleDriveTransport))


# -- real transport request shapes (injected service, offline) ----------------------


class _Req:
    def __init__(self, log, name, kw, resp):
        self.log, self.name, self.kw, self.resp = log, name, kw, resp

    def execute(self, num_retries=0):
        self.log.append((self.name, self.kw))
        return self.resp


class _Files:
    def __init__(self, log):
        self.log = log

    def get(self, **kw):
        return _Req(self.log, "get", kw, {"id": kw["fileId"], "name": "x", "mimeType": MIME_XLSX, "capabilities": {"canDownload": True}})

    def copy(self, **kw):
        return _Req(self.log, "copy", kw, {"id": "fake-new", "name": kw["body"]["name"], "mimeType": MIME_GOOGLE_SHEET})

    def list(self, **kw):
        return _Req(self.log, "list", kw, {"files": []})


class _Service:
    def __init__(self):
        self.log = []

    def files(self):
        return _Files(self.log)


def test_real_drive_transport_request_shapes():
    svc = _Service()
    t = GoogleApiDriveTransport(service=svc)
    assert t.get_file_metadata("fake-xlsx-file")["kind"] == "xlsx"
    t.copy_file("fake-native-sheet", name="N", parent_id="fake-folder", app_properties={APP_PROP_SOURCE: "fake-native-sheet"})
    t.find_created_copies(source_file_id="fake-it's", operation="copy_sheet", name="O'Brien")
    (_, get_kw), (_, copy_kw), (_, list_kw) = svc.log
    assert get_kw["supportsAllDrives"] is True and "mimeType" in get_kw["fields"]
    assert copy_kw["body"] == {"name": "N", "parents": ["fake-folder"], "appProperties": {APP_PROP_SOURCE: "fake-native-sheet"}}
    assert "value='fake-it\\'s'" in list_kw["q"] and "name = 'O\\'Brien'" in list_kw["q"] and "trashed = false" in list_kw["q"]


def test_real_import_uses_native_sheet_target_mime():
    pytest.importorskip("googleapiclient.http")
    captured = {}

    class Files:
        def create(self, **kw):
            captured.update(kw)
            return _Req([], "create", kw, {"id": "fake-new", "name": kw["body"]["name"], "mimeType": MIME_GOOGLE_SHEET})

    class Svc:
        def files(self):
            return Files()

    out = GoogleApiDriveTransport(service=Svc()).import_as_google_sheet(b"PK", name="N", parent_id=None, app_properties={})
    assert captured["body"]["mimeType"] == MIME_GOOGLE_SHEET and "parents" not in captured["body"]
    assert captured["media_body"].mimetype() == MIME_XLSX
    assert out["kind"] == "google_sheet"


# -- auth scopes ---------------------------------------------------------------------


def test_login_requests_sheets_plus_minimal_drive_scopes():
    assert auth.SCOPES == [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    ]
    assert "https://www.googleapis.com/auth/drive" not in auth.SCOPES


def _token(tmp_path, scopes):
    p = tmp_path / "token.json"
    p.write_text(json.dumps({
        "token": "fake-access", "refresh_token": "fake-refresh", "client_id": "fake-client.apps.googleusercontent.com",
        "client_secret": "fake-secret", "token_uri": "https://oauth2.googleapis.com/token", "scopes": scopes,
        "expiry": "2999-01-01T00:00:00Z",
    }), encoding="utf-8")
    return auth.load_auth_config({auth.ENV_TOKEN_PATH: str(p)})


def test_old_sheets_only_token_still_works_for_sheets_but_drive_asks_reauth(tmp_path):
    pytest.importorskip("google.oauth2.credentials")
    cfg = _token(tmp_path, [auth.SHEETS_SCOPE])
    creds = auth.load_credentials(cfg, auth.SHEETS_REQUIRED_SCOPES)
    assert creds.valid
    with pytest.raises(GoogleInsufficientScope) as e:
        auth.load_credentials(cfg, auth.DRIVE_REQUIRED_SCOPES)
    msg = str(e.value)
    assert "drive.readonly" in msg and "drive.file" in msg and "google_sheets.py auth" in msg
    assert "fake-secret" not in msg and "fake-refresh" not in msg
    assert auth.token_scope_status(cfg) == {"sheets_scopes_granted": True, "drive_scopes_granted": False}


def test_token_with_all_scopes_serves_drive(tmp_path):
    pytest.importorskip("google.oauth2.credentials")
    cfg = _token(tmp_path, list(auth.SCOPES))
    assert auth.load_credentials(cfg, auth.DRIVE_REQUIRED_SCOPES).valid
    assert auth.token_scope_status(cfg) == {"sheets_scopes_granted": True, "drive_scopes_granted": True}


def test_token_without_scope_info_requires_reauth(tmp_path):
    pytest.importorskip("google.oauth2.credentials")
    cfg = _token(tmp_path, [])
    with pytest.raises(GoogleSheetsAuthError, match="google_sheets.py auth"):
        auth.load_credentials(cfg)


def test_insufficient_scope_http_error_is_mapped():
    from scripts.lib.google_sheets_transport import map_google_error

    class Resp:
        status = 403

    class HttpError(Exception):
        resp = Resp()
        reason = "Request had insufficient authentication scopes."

    assert isinstance(map_google_error(HttpError()), GoogleInsufficientScope)


def test_no_real_ids_in_drive_fixtures():
    for fid in (XLSX, NATIVE, FOLDER):
        assert fid.startswith("fake-")
