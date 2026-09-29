"""Spreadsheet file lifecycle on Google Drive — infrastructure, not a skill.

Creating an operational spreadsheet (copy of a template, or a native
conversion of an .xlsx) is a one-off provisioning step the operator runs
explicitly (scripts/google_sheets.py convert-xlsx / copy-sheet --apply),
before the new file id is declared in the client's sources.json. It
carries no business logic, so it is not a registered skill: skills keep
reading/writing CONTENT through read-google-sheet / update-google-sheet.

Rules enforced here:
- `plan` (default) never creates anything;
- the operation must match the source's REAL mimeType (convert_xlsx only
  for .xlsx, copy_sheet only for native Google Sheets);
- the original is never modified (the transport cannot), and its
  metadata is re-read after the operation to prove it;
- replay-safe: a copy this app already created for the same
  source/operation/name is returned as no_change instead of duplicated.

Output contract: schemas/google-drive-file-operation.schema.json
"""

from __future__ import annotations

from typing import Callable, Optional

from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339
from scripts.lib.google_drive_transport import (
    APP_PROP_OPERATION,
    APP_PROP_SOURCE,
    MIME_GOOGLE_SHEET,
    GoogleDriveTransport,
)
from scripts.lib.google_sheets_transport import GoogleSheetsError

SCHEMA_VERSION = "1.0.0"
OPERATIONS = {"convert_xlsx": "xlsx", "copy_sheet": "google_sheet"}
_PRESERVATION_FIELDS = ("file_id", "name", "mime_type", "parents", "trashed", "version", "modified_time")


def _notice(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _source_view(meta: dict) -> dict:
    return {k: meta[k] for k in ("file_id", "name", "mime_type", "kind", "parents", "web_view_link", "capabilities")}


def _created_view(meta: dict) -> dict:
    return {
        "file_id": meta["file_id"],
        "spreadsheet_id": meta["file_id"] if meta["mime_type"] == MIME_GOOGLE_SHEET else None,
        "name": meta["name"],
        "mime_type": meta["mime_type"],
        "parents": meta["parents"],
        "web_view_link": meta["web_view_link"],
    }


def run_operation(
    drive: GoogleDriveTransport,
    *,
    operation: str,
    source_file_id: str,
    name: str,
    destination_folder_id: Optional[str] = None,
    mode: str = "plan",
    clock: Callable[[], str] = utc_now_rfc3339,
) -> dict:
    generated_at = clock()
    out = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "mode": mode,
        "generated_at": generated_at,
        "status": "error",
        "source": None,
        "target": {"name": name, "destination_folder_id": destination_folder_id},
        "existing_copies": [],
        "created": None,
        "original_preserved": None,
        "warnings": [],
        "errors": [],
    }
    problem = future_timestamp_problem(generated_at)
    if problem:
        out["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))

    if operation not in OPERATIONS:
        out["errors"].append(_notice("UNSUPPORTED_OPERATION", f"operation must be one of {sorted(OPERATIONS)}"))
        return out
    if mode not in ("plan", "apply"):
        out["errors"].append(_notice("INVALID_MODE", "mode must be plan or apply"))
        return out
    if not isinstance(name, str) or not name.strip():
        out["errors"].append(_notice("INVALID_NAME", "a non-empty name for the new file is required"))
        return out

    try:
        source = drive.get_file_metadata(source_file_id)
        out["source"] = _source_view(source)
        if source["trashed"]:
            out["errors"].append(_notice("SOURCE_TRASHED", "source file is in the trash"))
            return out
        expected_kind = OPERATIONS[operation]
        if source["kind"] != expected_kind:
            code = "NOT_XLSX" if operation == "convert_xlsx" else "NOT_GOOGLE_SHEET"
            out["errors"].append(_notice(code, f"{operation} requires a {expected_kind} source; real mimeType is {source['mime_type']!r}"))
            return out
        capability = "can_download" if operation == "convert_xlsx" else "can_copy"
        if not source["capabilities"][capability]:
            out["errors"].append(_notice("PERMISSION_DENIED", f"source file does not allow {capability.removeprefix('can_')} for this account"))
            return out
        if destination_folder_id is not None:
            folder = drive.get_file_metadata(destination_folder_id)
            if folder["kind"] != "folder":
                out["errors"].append(_notice("DESTINATION_NOT_FOLDER", f"destination {destination_folder_id!r} is not a folder"))
                return out
        existing = drive.find_created_copies(source_file_id=source_file_id, operation=operation, name=name)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out

    out["existing_copies"] = [_created_view(m) for m in existing]
    if len(existing) > 1:
        out["errors"].append(_notice("DUPLICATE_OPERATIONAL_COPIES", f"{len(existing)} files already created from this source with this name — resolve manually, nothing created"))
        return out
    if existing:
        out["created"] = out["existing_copies"][0]
        out["status"] = "no_change"
        out["original_preserved"] = True
        return out
    if mode == "plan":
        out["status"] = "planned"
        return out

    app_properties = {APP_PROP_SOURCE: source_file_id, APP_PROP_OPERATION: operation}
    try:
        if operation == "convert_xlsx":
            content = drive.download_file(source_file_id)
            created = drive.import_as_google_sheet(content, name=name, parent_id=destination_folder_id, app_properties=app_properties)
        else:
            created = drive.copy_file(source_file_id, name=name, parent_id=destination_folder_id, app_properties=app_properties)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, f"{operation} failed, nothing was created: {e}"))
        return out

    out["created"] = _created_view(created)
    if created["mime_type"] != MIME_GOOGLE_SHEET:
        out["errors"].append(_notice("CONVERSION_NOT_NATIVE", f"created file has mimeType {created['mime_type']!r}, not a native Google Sheet"))
    if created["file_id"] == source_file_id:
        out["errors"].append(_notice("ORIGINAL_REUSED", "created file id equals the source id"))

    try:
        after = drive.get_file_metadata(source_file_id)
        out["original_preserved"] = all(after[k] == source[k] for k in _PRESERVATION_FIELDS)
    except GoogleSheetsError as e:
        out["warnings"].append(_notice("ORIGINAL_NOT_REVERIFIED", f"could not re-read the original after the operation: {e}"))
    if out["original_preserved"] is False:
        out["errors"].append(_notice("ORIGINAL_CHANGED", "original file metadata changed during the operation — investigate"))

    out["status"] = "error" if out["errors"] else "created"
    problem = future_timestamp_problem(clock())
    if problem:
        out["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))
    return out


def inspect_file(drive: GoogleDriveTransport, file_id: str, *, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Metadata only (file-metadata CLI). Never raises for API errors."""
    observed_at = clock()
    try:
        meta = drive.get_file_metadata(file_id)
        return {"observed_at": observed_at, "status": "success", "file": meta, "errors": []}
    except GoogleSheetsError as e:
        return {"observed_at": observed_at, "status": "error", "file": None, "errors": [_notice(e.code, str(e))]}
