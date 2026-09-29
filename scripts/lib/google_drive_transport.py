"""Minimal Google Drive transport — file lifecycle for the spreadsheet flow
only (docs/workflows/google-sheets.md):

    Google Drive  -> resolve / copy / convert the FILE
    Google Sheets -> read / write the CONTENT (google_sheets_transport.py)

Deliberately small. It can read metadata, download bytes, and CREATE new
files (import an .xlsx as a native Google Sheet, copy a native sheet). It
has no update, move, rename, trash or delete operation at all, so an
original file can never be modified through it — preservation is
structural, not just a rule.

Every created file carries appProperties (source file id + operation) so
a replay can find the copy it already made instead of duplicating it.
"""

from __future__ import annotations

import copy
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.lib.google_sheets_transport import (
    GoogleSheetsAPIError,
    GoogleSheetsAuthError,
    GoogleInsufficientScope,
    GoogleSheetsDependencyMissing,
    GoogleSheetsNotFound,
    GoogleSheetsPermissionDenied,
    map_google_error,
)

MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_FOLDER = "application/vnd.google-apps.folder"

APP_PROP_SOURCE = "v4_source_file_id"
APP_PROP_OPERATION = "v4_lifecycle_operation"

_FILE_FIELDS = "id,name,mimeType,parents,trashed,webViewLink,version,modifiedTime,appProperties,capabilities(canCopy,canDownload,canEdit,canAddChildren)"


class DriveFileNotFound(GoogleSheetsNotFound):
    code = "FILE_NOT_FOUND"


def file_kind(mime_type: Optional[str]) -> str:
    return {MIME_GOOGLE_SHEET: "google_sheet", MIME_XLSX: "xlsx", MIME_FOLDER: "folder"}.get(mime_type, "other")


def normalize_file(raw: dict) -> dict:
    caps = raw.get("capabilities") or {}
    return {
        "file_id": raw.get("id"),
        "name": raw.get("name"),
        "mime_type": raw.get("mimeType"),
        "kind": file_kind(raw.get("mimeType")),
        "parents": list(raw.get("parents") or []),
        "trashed": bool(raw.get("trashed", False)),
        "web_view_link": raw.get("webViewLink"),
        "version": raw.get("version"),
        "modified_time": raw.get("modifiedTime"),
        "app_properties": dict(raw.get("appProperties") or {}),
        "capabilities": {
            "can_copy": bool(caps.get("canCopy", False)),
            "can_download": bool(caps.get("canDownload", False)),
            "can_edit": bool(caps.get("canEdit", False)),
            "can_add_children": bool(caps.get("canAddChildren", False)),
        },
    }


class GoogleDriveTransport(ABC):
    @abstractmethod
    def get_file_metadata(self, file_id: str) -> dict:
        """normalize_file() shape."""

    @abstractmethod
    def download_file(self, file_id: str) -> bytes:
        """Raw bytes of a binary (non-Google-native) file, e.g. .xlsx."""

    @abstractmethod
    def import_as_google_sheet(self, content: bytes, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        """Create a NEW native Google Sheet from .xlsx bytes (Drive import,
        target mimeType application/vnd.google-apps.spreadsheet)."""

    @abstractmethod
    def copy_file(self, file_id: str, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        """Create a NEW file as a native Drive copy of `file_id`."""

    @abstractmethod
    def find_created_copies(self, *, source_file_id: str, operation: str, name: str) -> list[dict]:
        """Non-trashed files previously created by this app for exactly this
        source/operation/name (appProperties match)."""


# ---------------------------------------------------------------------------
# Real transport
# ---------------------------------------------------------------------------


def _q_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class GoogleApiDriveTransport(GoogleDriveTransport):
    """Drive API v3. `service` injectable for offline request-shape tests."""

    def __init__(self, service: Any = None, credentials: Any = None, num_retries: int = 2):
        if service is None:
            if credentials is None:
                raise GoogleSheetsAuthError("no credentials supplied — use scripts/lib/google_sheets_auth.py build_real_drive_transport()")
            try:
                from googleapiclient.discovery import build  # type: ignore
            except ImportError as e:  # pragma: no cover - depends on local install
                raise GoogleSheetsDependencyMissing("google-api-python-client is not installed: pip install -r requirements-google.txt") from e
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._service = service
        self._num_retries = num_retries

    def _execute(self, request: Any) -> Any:
        try:
            return request.execute(num_retries=self._num_retries)
        except Exception as e:  # noqa: BLE001 - every failure is mapped, none swallowed
            mapped = map_google_error(e)
            if type(mapped) is GoogleSheetsNotFound:
                mapped = DriveFileNotFound(str(mapped))
            raise mapped from e

    def get_file_metadata(self, file_id: str) -> dict:
        return normalize_file(self._execute(self._service.files().get(fileId=file_id, fields=_FILE_FIELDS, supportsAllDrives=True)))

    def download_file(self, file_id: str) -> bytes:
        try:
            from googleapiclient.http import MediaIoBaseDownload  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise GoogleSheetsDependencyMissing("google-api-python-client is not installed: pip install -r requirements-google.txt") from e
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, self._service.files().get_media(fileId=file_id, supportsAllDrives=True))
        try:
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=self._num_retries)
        except Exception as e:  # noqa: BLE001
            mapped = map_google_error(e)
            raise (DriveFileNotFound(str(mapped)) if type(mapped) is GoogleSheetsNotFound else mapped) from e
        return buf.getvalue()

    def import_as_google_sheet(self, content: bytes, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        try:
            from googleapiclient.http import MediaIoBaseUpload  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise GoogleSheetsDependencyMissing("google-api-python-client is not installed: pip install -r requirements-google.txt") from e
        body = {"name": name, "mimeType": MIME_GOOGLE_SHEET, "appProperties": app_properties}
        if parent_id:
            body["parents"] = [parent_id]
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=MIME_XLSX, resumable=True)
        return normalize_file(self._execute(self._service.files().create(body=body, media_body=media, fields=_FILE_FIELDS, supportsAllDrives=True)))

    def copy_file(self, file_id: str, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        body = {"name": name, "appProperties": app_properties}
        if parent_id:
            body["parents"] = [parent_id]
        return normalize_file(self._execute(self._service.files().copy(fileId=file_id, body=body, fields=_FILE_FIELDS, supportsAllDrives=True)))

    def find_created_copies(self, *, source_file_id: str, operation: str, name: str) -> list[dict]:
        q = (
            f"appProperties has {{ key='{APP_PROP_SOURCE}' and value={_q_literal(source_file_id)} }} and "
            f"appProperties has {{ key='{APP_PROP_OPERATION}' and value={_q_literal(operation)} }} and "
            f"name = {_q_literal(name)} and trashed = false"
        )
        resp = self._execute(self._service.files().list(
            q=q, spaces="drive", fields=f"files({_FILE_FIELDS})", pageSize=10,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ))
        return [normalize_file(f) for f in resp.get("files", [])]


# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


@dataclass
class FakeGoogleDriveTransport(GoogleDriveTransport):
    """In-memory Drive for tests and dry runs. Never touches the network.

    Failure injection: `auth_error`, `denied` (file ids -> PERMISSION_DENIED),
    `insufficient_scope` (True -> every call raises INSUFFICIENT_SCOPE),
    `fail_import` / `fail_copy` (exception raised on create)."""

    files: dict = field(default_factory=dict)
    denied: set = field(default_factory=set)
    auth_error: bool = False
    insufficient_scope: bool = False
    fail_import: Optional[Exception] = None
    fail_copy: Optional[Exception] = None
    calls: list = field(default_factory=list)
    _next: int = 1

    def add_file(self, file_id: str, *, name: str, mime_type: str, parents: Optional[list] = None, content: bytes = b"",
                 can_copy: bool = True, can_download: bool = True, can_edit: bool = True, app_properties: Optional[dict] = None) -> None:
        self.files[file_id] = {
            "id": file_id, "name": name, "mimeType": mime_type, "parents": list(parents or []), "trashed": False,
            "webViewLink": f"https://fake-drive.local/{file_id}", "version": "1", "modifiedTime": "2026-01-01T00:00:00Z",
            "appProperties": dict(app_properties or {}), "content": content,
            "capabilities": {"canCopy": can_copy, "canDownload": can_download, "canEdit": can_edit, "canAddChildren": mime_type == MIME_FOLDER},
        }

    def _enter(self, op: str, file_id: Optional[str] = None) -> Optional[dict]:
        self.calls.append((op, file_id))
        if self.auth_error:
            raise GoogleSheetsAuthError("fake: credentials rejected")
        if self.insufficient_scope:
            raise GoogleInsufficientScope("HTTP 403: Request had insufficient authentication scopes. — re-run `python scripts/google_sheets.py auth`")
        if file_id is None:
            return None
        if file_id in self.denied:
            raise GoogleSheetsPermissionDenied(f"HTTP 403: The user does not have sufficient permissions for file {file_id}")
        raw = self.files.get(file_id)
        if raw is None or raw["trashed"]:
            raise DriveFileNotFound(f"HTTP 404: File not found: {file_id}")
        return raw

    def _new_id(self) -> str:
        new_id = f"fake-created-{self._next}"
        self._next += 1
        return new_id

    def get_file_metadata(self, file_id: str) -> dict:
        return normalize_file(self._enter("get_file_metadata", file_id))

    def download_file(self, file_id: str) -> bytes:
        raw = self._enter("download_file", file_id)
        if raw["mimeType"].startswith("application/vnd.google-apps."):
            raise GoogleSheetsAPIError("HTTP 403: Only files with binary content can be downloaded. Use Export with Docs Editors files.")
        return bytes(raw["content"])

    def _check_parent(self, parent_id: Optional[str]) -> None:
        if parent_id is not None:
            self._enter("check_parent", parent_id)

    def import_as_google_sheet(self, content: bytes, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        self._enter("import_as_google_sheet")
        self._check_parent(parent_id)
        if self.fail_import is not None:
            raise self.fail_import
        new_id = self._new_id()
        self.add_file(new_id, name=name, mime_type=MIME_GOOGLE_SHEET, parents=[parent_id] if parent_id else ["fake-root"], app_properties=app_properties)
        self.files[new_id]["imported_from_bytes"] = len(content)
        return normalize_file(self.files[new_id])

    def copy_file(self, file_id: str, *, name: str, parent_id: Optional[str], app_properties: dict) -> dict:
        source = self._enter("copy_file", file_id)
        self._check_parent(parent_id)
        if self.fail_copy is not None:
            raise self.fail_copy
        new_id = self._new_id()
        self.add_file(new_id, name=name, mime_type=source["mimeType"], parents=[parent_id] if parent_id else list(source["parents"]),
                      content=source["content"], app_properties=app_properties)
        return normalize_file(self.files[new_id])

    def find_created_copies(self, *, source_file_id: str, operation: str, name: str) -> list[dict]:
        self._enter("find_created_copies")
        return [
            normalize_file(f) for f in self.files.values()
            if not f["trashed"] and f["name"] == name
            and f["appProperties"].get(APP_PROP_SOURCE) == source_file_id
            and f["appProperties"].get(APP_PROP_OPERATION) == operation
        ]

    def snapshot(self, file_id: str) -> dict:
        return copy.deepcopy(self.files[file_id])

