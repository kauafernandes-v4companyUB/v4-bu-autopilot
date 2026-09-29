"""Google Sheets transport abstraction (skills/read-google-sheet,
skills/update-google-sheet).

Generic on purpose: no client, V4 or spreadsheet-specific logic lives
here. Three pieces:

- ``GoogleSheetsTransport``: the interface every transport implements.
- ``GoogleApiSheetsTransport``: the real one, over the official Google
  Sheets API v4 (google-api-python-client). The ``service`` object is
  injectable so request shapes can be tested without network access.
  Credentials come from scripts/lib/google_sheets_auth.py — never from
  this module, never from the repository.
- ``FakeGoogleSheetsTransport``: in-memory, deterministic, for tests and
  dry runs. Never touches the network.

Content writes go through ``values.batchUpdate``; clears go through
``values.batchClear``, which removes values/formulas and keeps every other
cell property. Observed on the real API (disposable-sheet test,
2026-09-29): ``values.batchUpdate`` writing ``""`` or a text value with
``RAW`` REMOVES the cell's ``userEnteredFormat.numberFormat`` (background
and data validation survive); writing a number (``RAW`` or
``USER_ENTERED``) keeps it. That is why a clear must never be sent as
``""``. ``set_number_formats`` is the only formatting write: a
``repeatCell`` restricted to the ``userEnteredFormat.numberFormat`` field.
``batch_update`` (raw spreadsheets.batchUpdate) exists for future,
explicitly authorized structural operations and is not used by
update-google-sheet.
"""

from __future__ import annotations

import copy
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from scripts.lib.a1_notation import A1Error, A1Range, cell_a1, col_to_letters, parse_a1, quote_sheet_title

VALUE_RENDER_OPTIONS = ("UNFORMATTED_VALUE", "FORMATTED_VALUE", "FORMULA")
VALUE_INPUT_OPTIONS = ("RAW", "USER_ENTERED")


class GoogleSheetsError(Exception):
    code = "API_ERROR"


class GoogleSheetsAuthError(GoogleSheetsError):
    code = "AUTH_ERROR"


class GoogleSheetsPermissionDenied(GoogleSheetsAuthError):
    code = "PERMISSION_DENIED"


class GoogleInsufficientScope(GoogleSheetsAuthError):
    """The token authenticates but was not granted a scope this operation
    needs (e.g. a token created before Drive scopes were added)."""

    code = "INSUFFICIENT_SCOPE"


class GoogleSheetsNotFound(GoogleSheetsError):
    code = "SPREADSHEET_NOT_FOUND"


class GoogleSheetsRangeError(GoogleSheetsError):
    code = "INVALID_RANGE"


class GoogleSheetsAPIError(GoogleSheetsError):
    code = "API_ERROR"


class GoogleSheetsDependencyMissing(GoogleSheetsError):
    code = "DEPENDENCY_MISSING"


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def pad_grid(values: list, a1: A1Range) -> list[list]:
    """The API trims trailing empty rows/cells. For a bounded range,
    return a full rectangle padded with "" so cell positions are stable."""
    if not a1.is_bounded:
        return [list(r) for r in values]
    grid = []
    for r in range(a1.n_rows):
        row = list(values[r]) if r < len(values) else []
        row = row[: a1.n_cols] + [""] * max(0, a1.n_cols - len(row))
        grid.append(row)
    return grid


def fingerprint_structure(sheets: list[dict], ranges: list[str]) -> dict:
    """Normalize a spreadsheets.get(includeGridData) response into a
    comparable structure fingerprint: grid properties, merges and
    sheet-level formatting objects per sheet, plus userEnteredFormat /
    dataValidation per cell of each requested bounded range. Used to
    prove that a content-only write preserved structure and formatting."""
    parsed = [parse_a1(r) for r in ranges]
    out: dict[str, dict] = {}
    for sheet in sheets:
        props = sheet.get("properties", {})
        title = props.get("title")
        grid = props.get("gridProperties", {})
        cells: dict[str, str] = {}
        seen: dict[tuple[int, int], dict] = {}
        for block in sheet.get("data", []) or []:
            r0 = block.get("startRow", 0)
            c0 = block.get("startColumn", 0)
            for ri, row in enumerate(block.get("rowData", []) or []):
                for ci, cell in enumerate(row.get("values", []) or []):
                    seen[(r0 + ri + 1, c0 + ci + 1)] = {
                        "format": cell.get("userEnteredFormat"),
                        "data_validation": cell.get("dataValidation"),
                    }
        for a1 in parsed:
            if a1.sheet_title != title or not a1.is_bounded:
                continue
            for row, col in a1.cells():
                state = seen.get((row, col), {"format": None, "data_validation": None})
                cells[f"{col_to_letters(col)}{row}"] = _sha(state)
        out[title] = {
            "sheet_id": props.get("sheetId"),
            "grid": {
                "row_count": grid.get("rowCount"),
                "column_count": grid.get("columnCount"),
                "frozen_row_count": grid.get("frozenRowCount", 0),
                "frozen_column_count": grid.get("frozenColumnCount", 0),
            },
            "merges_sha256": _sha(sorted(sheet.get("merges", []) or [], key=lambda m: json.dumps(m, sort_keys=True))),
            "conditional_formats_sha256": _sha(sheet.get("conditionalFormats", []) or []),
            "protected_ranges_sha256": _sha(sheet.get("protectedRanges", []) or []),
            "basic_filter_sha256": _sha(sheet.get("basicFilter")),
            "banded_ranges_sha256": _sha(sheet.get("bandedRanges", []) or []),
            "cells": dict(sorted(cells.items())),
        }
    return out


class GoogleSheetsTransport(ABC):
    """Interface shared by the real and the fake transport."""

    @abstractmethod
    def get_spreadsheet_metadata(self, spreadsheet_id: str) -> dict:
        """Returns {spreadsheet_id, title, locale, time_zone, sheets: [{sheet_id,
        title, index, row_count, column_count, frozen_row_count,
        frozen_column_count, hidden}]}."""

    @abstractmethod
    def get_values(self, spreadsheet_id: str, ranges: list[str], value_render: str) -> list[dict]:
        """One entry per requested range, in order: {requested_range,
        returned_range, values}. Bounded ranges are padded (pad_grid)."""

    @abstractmethod
    def get_structure(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        """fingerprint_structure() of the sheets covering `ranges`."""

    @abstractmethod
    def write_values(self, spreadsheet_id: str, data: list[dict], value_input_option: str) -> dict:
        """data: [{range, values}]. Content only (values.batchUpdate).
        Returns {updated_cells, updated_ranges}."""

    @abstractmethod
    def clear_values(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        """values.batchClear: removes values and formulas only; format,
        data validation and every other cell property are kept.
        Returns {cleared_ranges}."""

    @abstractmethod
    def get_cell_formats(self, spreadsheet_id: str, ranges: list[str]) -> dict[str, dict]:
        """Raw per-cell {user_entered_format, data_validation} of every cell
        of the bounded `ranges`, keyed by cell_a1 ('Tab'!B2). Missing
        properties are None."""

    @abstractmethod
    def set_number_formats(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        """requests: [{sheet_id, range, number_format}]. One repeatCell per
        range with fields=userEnteredFormat.numberFormat — nothing else about
        the cell is touched. Returns {updated_ranges}."""

    @abstractmethod
    def get_sheet_snapshot(self, spreadsheet_id: str, sheet_title: str) -> dict:
        """normalize_sheet_snapshot() of one whole tab: identity (sheet_id,
        title, index) plus everything a native duplicate is expected to
        carry — grid, sizes, merges, formatting objects and every cell's
        value/formula, format, validation, hyperlink, note and rich text."""

    @abstractmethod
    def duplicate_sheet(self, spreadsheet_id: str, source_sheet_id: int, new_sheet_title: str, insert_index: int) -> dict:
        """Native spreadsheets.batchUpdate duplicateSheet. Returns the new
        sheet's {sheet_id, title, index}. Never overwrites an existing tab."""

    @abstractmethod
    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        """Raw spreadsheets.batchUpdate. Structural/format operations only
        when explicitly authorized — never used for content patches."""

    def list_sheets(self, spreadsheet_id: str) -> list[dict]:
        return self.get_spreadsheet_metadata(spreadsheet_id)["sheets"]

    def read_values(self, spreadsheet_id: str, ranges: list[str]) -> list[dict]:
        return self.get_values(spreadsheet_id, ranges, "UNFORMATTED_VALUE")

    def read_formatted_values(self, spreadsheet_id: str, ranges: list[str]) -> list[dict]:
        return self.get_values(spreadsheet_id, ranges, "FORMATTED_VALUE")

    def read_formulas(self, spreadsheet_id: str, ranges: list[str]) -> list[dict]:
        return self.get_values(spreadsheet_id, ranges, "FORMULA")


# ---------------------------------------------------------------------------
# Real transport
# ---------------------------------------------------------------------------

_METADATA_FIELDS = "spreadsheetId,properties(title,locale,timeZone),sheets(properties(sheetId,title,index,hidden,gridProperties))"
_STRUCTURE_FIELDS = (
    "sheets(properties(sheetId,title,index,gridProperties),merges,conditionalFormats,protectedRanges,"
    "basicFilter,bandedRanges,data(startRow,startColumn,rowData(values(userEnteredFormat,dataValidation))))"
)
_CELL_FORMAT_FIELDS = "sheets(properties(title),data(startRow,startColumn,rowData(values(userEnteredFormat,dataValidation))))"
_SHEET_SNAPSHOT_FIELDS = (
    "sheets(properties,merges,conditionalFormats,protectedRanges,basicFilter,bandedRanges,charts(chartId),"
    "data(startRow,startColumn,rowMetadata(pixelSize,hiddenByUser),columnMetadata(pixelSize,hiddenByUser),"
    "rowData(values(userEnteredValue,userEnteredFormat,dataValidation,hyperlink,note,textFormatRuns))))"
)
_SNAPSHOT_CELL_KEYS = ("userEnteredValue", "userEnteredFormat", "dataValidation", "hyperlink", "note", "textFormatRuns")
_SHEET_IDENTITY_KEYS = ("sheet_id", "title", "index")


def _strip_ids(obj: Any) -> Any:
    """Drop sheet-scoped ids (sheetId, protectedRangeId, bandedRangeId, …) so
    a duplicate's formatting objects compare equal to the source's."""
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items() if k not in ("sheetId", "protectedRangeId", "bandedRangeId", "chartId", "filterViewId")}
    if isinstance(obj, list):
        return [_strip_ids(v) for v in obj]
    return obj


def normalize_sheet_snapshot(sheet: dict) -> dict:
    """spreadsheets.get(includeGridData) sheet → comparable snapshot."""
    props = sheet.get("properties", {})
    grid = props.get("gridProperties", {})
    cells: dict[str, dict] = {}
    rows, cols = [], []
    for block in sheet.get("data", []) or []:
        r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
        rows = [{"size": m.get("pixelSize"), "hidden": bool(m.get("hiddenByUser"))} for m in block.get("rowMetadata", []) or []] or rows
        cols = [{"size": m.get("pixelSize"), "hidden": bool(m.get("hiddenByUser"))} for m in block.get("columnMetadata", []) or []] or cols
        for ri, row in enumerate(block.get("rowData", []) or []):
            for ci, cell in enumerate(row.get("values", []) or []):
                kept = {k: cell[k] for k in _SNAPSHOT_CELL_KEYS if cell.get(k) not in (None, {}, [])}
                if kept:
                    cells[f"{col_to_letters(c0 + ci + 1)}{r0 + ri + 1}"] = kept
    return {
        "sheet_id": props.get("sheetId"), "title": props.get("title"), "index": props.get("index"),
        "hidden": bool(props.get("hidden", False)),
        "tab_color": props.get("tabColorStyle") or props.get("tabColor"),
        "right_to_left": bool(props.get("rightToLeft", False)),
        "grid": {k: grid.get(k) for k in ("rowCount", "columnCount", "frozenRowCount", "frozenColumnCount", "hideGridlines", "rowGroupControlAfter", "columnGroupControlAfter")},
        "row_sizes": rows, "column_sizes": cols,
        "merges": sorted(_strip_ids(sheet.get("merges", []) or []), key=lambda m: json.dumps(m, sort_keys=True)),
        "conditional_formats": _strip_ids(sheet.get("conditionalFormats", []) or []),
        "protected_ranges": _strip_ids(sheet.get("protectedRanges", []) or []),
        "basic_filter": _strip_ids(sheet.get("basicFilter")),
        "banded_ranges": _strip_ids(sheet.get("bandedRanges", []) or []),
        "charts_count": len(sheet.get("charts", []) or []),
        "cells": dict(sorted(cells.items())),
    }


def sheet_content(snapshot: dict) -> dict:
    """The snapshot without identity: what a faithful duplicate must equal."""
    return {k: v for k, v in snapshot.items() if k not in _SHEET_IDENTITY_KEYS}


def sheet_content_sha256(snapshot: dict) -> str:
    return _sha(sheet_content(snapshot))


def snapshot_differences(a: dict, b: dict, limit: int = 50) -> list[dict]:
    """Where two snapshots differ (identity ignored)."""
    out = []
    ca, cb = sheet_content(a), sheet_content(b)
    for key in sorted(set(ca) | set(cb)):
        if key == "cells":
            for ref in sorted(set(ca["cells"]) | set(cb["cells"])):
                if ca["cells"].get(ref) != cb["cells"].get(ref):
                    out.append({"property": "cell", "cell": ref})
        elif ca.get(key) != cb.get(key):
            out.append({"property": key})
    return out[:limit]


def grid_range(sheet_id: int, a1: A1Range) -> dict:
    """0-based, end-exclusive GridRange for a bounded A1 range."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": a1.start_row - 1, "endRowIndex": a1.end_row,
        "startColumnIndex": a1.start_col - 1, "endColumnIndex": a1.end_col,
    }


def cell_formats_from_grid(sheets: list[dict], ranges: list[str]) -> dict[str, dict]:
    """Raw {user_entered_format, data_validation} per cell of the bounded
    `ranges`, from a spreadsheets.get(includeGridData) response."""
    seen: dict[tuple[str, int, int], dict] = {}
    for sheet in sheets:
        title = sheet.get("properties", {}).get("title")
        for block in sheet.get("data", []) or []:
            r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
            for ri, row in enumerate(block.get("rowData", []) or []):
                for ci, cell in enumerate(row.get("values", []) or []):
                    seen[(title, r0 + ri + 1, c0 + ci + 1)] = cell
    out: dict[str, dict] = {}
    for rng in ranges:
        a1 = parse_a1(rng)
        for row, col in a1.cells():
            cell = seen.get((a1.sheet_title, row, col), {})
            out[cell_a1(a1.sheet_title, row, col)] = {
                "user_entered_format": cell.get("userEnteredFormat"),
                "data_validation": cell.get("dataValidation"),
            }
    return out


def map_google_error(exc: Exception) -> GoogleSheetsError:
    """Translate googleapiclient/google-auth exceptions into this module's
    error types, by duck typing (no hard import of the Google libs).
    Messages never include credentials — HttpError carries only the
    request URL and the API's reason."""
    if isinstance(exc, GoogleSheetsError):
        return exc
    name = type(exc).__name__
    if name in ("RefreshError", "DefaultCredentialsError", "TransportError"):
        return GoogleSheetsAuthError(f"{name}: Google credentials are invalid, expired or unavailable")
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = getattr(exc, "reason", None) or getattr(exc, "_get_reason", lambda: None)() or name
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    msg = f"HTTP {status}: {reason}" if status else f"{name}: {reason}"
    if status == 401:
        return GoogleSheetsAuthError(msg)
    if status == 403:
        lowered = str(reason).lower()
        if "insufficient" in lowered and "scope" in lowered:
            return GoogleInsufficientScope(f"{msg} — re-run `python scripts/google_sheets.py auth` to grant the current scopes")
        return GoogleSheetsPermissionDenied(msg)
    if status == 404:
        return GoogleSheetsNotFound(msg)
    if status == 400 and any(t in str(reason).lower() for t in ("parse range", "exceeds grid", "range")):
        return GoogleSheetsRangeError(msg)
    return GoogleSheetsAPIError(msg)


class GoogleApiSheetsTransport(GoogleSheetsTransport):
    """Official Google Sheets API v4 transport."""

    def __init__(self, service: Any = None, credentials: Any = None, num_retries: int = 2):
        if service is None:
            if credentials is None:
                raise GoogleSheetsAuthError("no credentials supplied — use scripts/lib/google_sheets_auth.py build_real_transport()")
            try:
                from googleapiclient.discovery import build  # type: ignore
            except ImportError as e:  # pragma: no cover - depends on local install
                raise GoogleSheetsDependencyMissing("google-api-python-client is not installed: pip install -r requirements-google.txt") from e
            service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._service = service
        self._num_retries = num_retries

    def _execute(self, request: Any) -> dict:
        try:
            return request.execute(num_retries=self._num_retries)
        except Exception as e:  # noqa: BLE001 - every failure is mapped, none swallowed
            raise map_google_error(e) from e

    def get_spreadsheet_metadata(self, spreadsheet_id: str) -> dict:
        resp = self._execute(
            self._service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields=_METADATA_FIELDS, includeGridData=False)
        )
        props = resp.get("properties", {})
        sheets = []
        for s in resp.get("sheets", []):
            p = s.get("properties", {})
            g = p.get("gridProperties", {})
            sheets.append({
                "sheet_id": p.get("sheetId"),
                "title": p.get("title"),
                "index": p.get("index"),
                "row_count": g.get("rowCount"),
                "column_count": g.get("columnCount"),
                "frozen_row_count": g.get("frozenRowCount", 0),
                "frozen_column_count": g.get("frozenColumnCount", 0),
                "hidden": bool(p.get("hidden", False)),
            })
        return {
            "spreadsheet_id": resp.get("spreadsheetId", spreadsheet_id),
            "title": props.get("title"),
            "locale": props.get("locale"),
            "time_zone": props.get("timeZone"),
            "sheets": sheets,
        }

    def get_values(self, spreadsheet_id: str, ranges: list[str], value_render: str) -> list[dict]:
        if value_render not in VALUE_RENDER_OPTIONS:
            raise ValueError(f"invalid value_render: {value_render!r}")
        kwargs = {"spreadsheetId": spreadsheet_id, "ranges": list(ranges), "valueRenderOption": value_render, "majorDimension": "ROWS"}
        if value_render != "FORMATTED_VALUE":
            kwargs["dateTimeRenderOption"] = "FORMATTED_STRING"
        resp = self._execute(self._service.spreadsheets().values().batchGet(**kwargs))
        value_ranges = resp.get("valueRanges", [])
        if len(value_ranges) != len(ranges):
            raise GoogleSheetsAPIError(f"batchGet returned {len(value_ranges)} ranges for {len(ranges)} requested")
        out = []
        for requested, vr in zip(ranges, value_ranges):
            out.append({
                "requested_range": requested,
                "returned_range": vr.get("range", requested),
                "values": pad_grid(vr.get("values", []), parse_a1(requested)),
            })
        return out

    def get_structure(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        resp = self._execute(
            self._service.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=list(ranges), includeGridData=True, fields=_STRUCTURE_FIELDS)
        )
        return fingerprint_structure(resp.get("sheets", []), ranges)

    def write_values(self, spreadsheet_id: str, data: list[dict], value_input_option: str) -> dict:
        if value_input_option not in VALUE_INPUT_OPTIONS:
            raise ValueError(f"invalid value_input_option: {value_input_option!r}")
        body = {
            "valueInputOption": value_input_option,
            "includeValuesInResponse": False,
            "data": [{"range": d["range"], "majorDimension": "ROWS", "values": d["values"]} for d in data],
        }
        resp = self._execute(self._service.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id, body=body))
        return {
            "updated_cells": resp.get("totalUpdatedCells", 0),
            "updated_ranges": [r.get("updatedRange") for r in resp.get("responses", [])],
        }

    def clear_values(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        resp = self._execute(self._service.spreadsheets().values().batchClear(spreadsheetId=spreadsheet_id, body={"ranges": list(ranges)}))
        return {"cleared_ranges": list(resp.get("clearedRanges", []))}

    def get_cell_formats(self, spreadsheet_id: str, ranges: list[str]) -> dict[str, dict]:
        resp = self._execute(
            self._service.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=list(ranges), includeGridData=True, fields=_CELL_FORMAT_FIELDS)
        )
        return cell_formats_from_grid(resp.get("sheets", []), ranges)

    def set_number_formats(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        body = {"requests": [
            {"repeatCell": {
                "range": grid_range(r["sheet_id"], parse_a1(r["range"])),
                "cell": {"userEnteredFormat": {"numberFormat": r["number_format"]}},
                "fields": "userEnteredFormat.numberFormat",
            }}
            for r in requests
        ]}
        self._execute(self._service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body))
        return {"updated_ranges": [r["range"] for r in requests]}

    def get_sheet_snapshot(self, spreadsheet_id: str, sheet_title: str) -> dict:
        resp = self._execute(self._service.spreadsheets().get(
            spreadsheetId=spreadsheet_id, ranges=[quote_sheet_title(sheet_title)], includeGridData=True, fields=_SHEET_SNAPSHOT_FIELDS))
        sheets = resp.get("sheets", [])
        if not sheets:
            raise GoogleSheetsRangeError(f"HTTP 400: Unable to parse range: {sheet_title}")
        return normalize_sheet_snapshot(sheets[0])

    def duplicate_sheet(self, spreadsheet_id: str, source_sheet_id: int, new_sheet_title: str, insert_index: int) -> dict:
        body = {"requests": [{"duplicateSheet": {"sourceSheetId": source_sheet_id, "insertSheetIndex": insert_index, "newSheetName": new_sheet_title}}]}
        resp = self._execute(self._service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body))
        props = (((resp.get("replies") or [{}])[0].get("duplicateSheet") or {}).get("properties")) or {}
        return {"sheet_id": props.get("sheetId"), "title": props.get("title"), "index": props.get("index")}

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        return self._execute(self._service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}))


# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


def _user_entered(value: Any) -> tuple[Any, Optional[str]]:
    """Minimal USER_ENTERED emulation: '=...' becomes a formula, plain
    numeric strings become numbers, TRUE/FALSE become booleans."""
    if isinstance(value, str):
        if value.startswith("="):
            return None, value
        if value.upper() in ("TRUE", "FALSE"):
            return value.upper() == "TRUE", None
        try:
            return (int(value) if value.strip().lstrip("-").isdigit() else float(value)), None
        except ValueError:
            return value, None
    return value, None


class FakeGoogleSheetsTransport(GoogleSheetsTransport):
    """In-memory spreadsheets for tests and dry runs.

    Cells are stored as {"value", "formula", "format", "data_validation"}.
    Formula results are not computed: an UNFORMATTED/FORMATTED read of a
    formula cell returns its `value` (settable in fixtures, "" otherwise).

    Formatting side effects mirror what was observed on the real API: a
    RAW write of "" or of a string drops format["numberFormat"] (other
    format keys and the data validation stay); numbers keep it;
    clear_values keeps everything but the content. USER_ENTERED text and
    formula writes were not measured and keep the format here.

    Hooks for failure injection: `auth_error`, `fail_next`, and
    `after_write` (called with the transport after each write — used to
    simulate a misbehaving remote that touches cells outside the patch).
    """

    def __init__(self) -> None:
        self._books: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.write_calls: list[dict] = []
        self.clear_calls: list[dict] = []
        self.format_calls: list[dict] = []
        self.structure_calls: list[dict] = []
        self.auth_error = False
        self.fail_next: Optional[Exception] = None
        self.after_write: Optional[Callable[["FakeGoogleSheetsTransport"], None]] = None

    # -- fixture helpers ----------------------------------------------------
    def add_spreadsheet(self, spreadsheet_id: str, title: str, sheets: dict[str, dict], *, locale: str = "pt_BR", time_zone: str = "America/Sao_Paulo") -> None:
        """sheets: {title: {"cells": {"A1": value | "=formula"}, "row_count": 100,
        "column_count": 26, "merges": [...], "formats": {"A1": {...}},
        "validations": {"A1": {...}}}}"""
        book = {"title": title, "locale": locale, "time_zone": time_zone, "sheets": {}}
        for index, (sheet_title, spec) in enumerate(sheets.items()):
            sheet = {
                "sheet_id": 1000 + index, "index": index,
                "row_count": spec.get("row_count", 100), "column_count": spec.get("column_count", 26),
                "hidden": spec.get("hidden", False),
                "merges": copy.deepcopy(spec.get("merges", [])),
                "conditional_formats": copy.deepcopy(spec.get("conditional_formats", [])),
                "column_sizes": copy.deepcopy(spec.get("column_sizes", [])),
                "frozen_row_count": spec.get("frozen_row_count", 0),
                "cells": {},
            }
            book["sheets"][sheet_title] = sheet
            for ref, raw in spec.get("cells", {}).items():
                row, col = self._ref(sheet_title, ref)
                if isinstance(raw, str) and raw.startswith("="):
                    sheet["cells"][(row, col)] = {"value": spec.get("computed", {}).get(ref, ""), "formula": raw}
                else:
                    sheet["cells"][(row, col)] = {"value": raw, "formula": None}
            for ref, fmt in spec.get("formats", {}).items():
                row, col = self._ref(sheet_title, ref)
                sheet["cells"].setdefault((row, col), {"value": None, "formula": None})["format"] = copy.deepcopy(fmt)
            for ref, rule in spec.get("validations", {}).items():
                row, col = self._ref(sheet_title, ref)
                sheet["cells"].setdefault((row, col), {"value": None, "formula": None})["data_validation"] = copy.deepcopy(rule)
        self._books[spreadsheet_id] = book

    @staticmethod
    def _ref(sheet_title: str, ref: str) -> tuple[int, int]:
        a1 = parse_a1(f"{quote_sheet_title(sheet_title)}!{ref}")
        return a1.start_row, a1.start_col

    def cell(self, spreadsheet_id: str, sheet_title: str, ref: str) -> dict:
        row, col = self._ref(sheet_title, ref)
        return copy.deepcopy(self._books[spreadsheet_id]["sheets"][sheet_title]["cells"].get((row, col), {"value": None, "formula": None}))

    def set_cell(self, spreadsheet_id: str, sheet_title: str, ref: str, raw: Any) -> None:
        row, col = self._ref(sheet_title, ref)
        cells = self._books[spreadsheet_id]["sheets"][sheet_title]["cells"]
        fmt = cells.get((row, col), {}).get("format")
        if isinstance(raw, str) and raw.startswith("="):
            cells[(row, col)] = {"value": "", "formula": raw}
        else:
            cells[(row, col)] = {"value": raw, "formula": None}
        if fmt is not None:
            cells[(row, col)]["format"] = fmt

    def set_format(self, spreadsheet_id: str, sheet_title: str, ref: str, fmt: dict) -> None:
        row, col = self._ref(sheet_title, ref)
        cells = self._books[spreadsheet_id]["sheets"][sheet_title]["cells"]
        cells.setdefault((row, col), {"value": None, "formula": None})["format"] = copy.deepcopy(fmt)

    # -- internals ------------------------------------------------------------
    def _enter(self, op: str, spreadsheet_id: str) -> dict:
        self.calls.append((op, spreadsheet_id))
        if self.auth_error:
            raise GoogleSheetsAuthError("fake: credentials rejected")
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc
        book = self._books.get(spreadsheet_id)
        if book is None:
            raise GoogleSheetsNotFound(f"HTTP 404: Requested entity was not found ({spreadsheet_id})")
        return book

    @staticmethod
    def _resolve(book: dict, rng: str) -> tuple[dict, A1Range]:
        try:
            a1 = parse_a1(rng)
        except A1Error as e:
            raise GoogleSheetsRangeError(f"HTTP 400: Unable to parse range: {rng} ({e})") from e
        sheet = book["sheets"].get(a1.sheet_title)
        if sheet is None:
            raise GoogleSheetsRangeError(f"HTTP 400: Unable to parse range: {rng}")
        if (a1.end_row or a1.start_row or 0) > sheet["row_count"] or (a1.end_col or a1.start_col or 0) > sheet["column_count"]:
            raise GoogleSheetsRangeError(f"HTTP 400: Range ({rng}) exceeds grid limits")
        return sheet, a1

    @staticmethod
    def _render(cell: Optional[dict], value_render: str) -> Any:
        if cell is None:
            return ""
        if value_render == "FORMULA" and cell.get("formula"):
            return cell["formula"]
        value = cell.get("value")
        if value is None:
            return ""
        if value_render == "FORMATTED_VALUE":
            if isinstance(value, bool):
                return "TRUE" if value else "FALSE"
            return str(value)
        return value

    # -- interface --------------------------------------------------------------
    def get_spreadsheet_metadata(self, spreadsheet_id: str) -> dict:
        book = self._enter("get_spreadsheet_metadata", spreadsheet_id)
        return {
            "spreadsheet_id": spreadsheet_id, "title": book["title"], "locale": book["locale"], "time_zone": book["time_zone"],
            "sheets": [
                {
                    "sheet_id": s["sheet_id"], "title": t, "index": s["index"], "row_count": s["row_count"],
                    "column_count": s["column_count"], "frozen_row_count": 0, "frozen_column_count": 0, "hidden": s["hidden"],
                }
                for t, s in sorted(book["sheets"].items(), key=lambda kv: kv[1]["index"])
            ],
        }

    def get_values(self, spreadsheet_id: str, ranges: list[str], value_render: str) -> list[dict]:
        if value_render not in VALUE_RENDER_OPTIONS:
            raise ValueError(f"invalid value_render: {value_render!r}")
        book = self._enter("get_values", spreadsheet_id)
        resolved = [self._resolve(book, r) for r in ranges]  # whole batch fails on one bad range, like the API
        out = []
        for rng, (sheet, a1) in zip(ranges, resolved):
            if a1.is_bounded:
                r0, c0, r1, c1 = a1.start_row, a1.start_col, a1.end_row, a1.end_col
            else:
                used = [rc for rc, c in sheet["cells"].items() if a1.contains(*rc) and (c.get("formula") or c.get("value") not in (None, ""))]
                r0 = a1.start_row or 1
                c0 = a1.start_col or 1
                r1 = a1.end_row or max([r for r, _ in used], default=r0 - 1)
                c1 = a1.end_col or max([c for _, c in used], default=c0 - 1)
            values = [[self._render(sheet["cells"].get((r, c)), value_render) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
            # trim like the real API, then pad bounded ranges back
            while values and all(v == "" for v in values[-1]):
                values.pop()
            values = [self._rtrim(row) for row in values]
            returned = A1Range(a1.sheet_title, r0, c0, max(r1, r0), max(c1, c0)).to_a1()
            out.append({"requested_range": rng, "returned_range": returned, "values": pad_grid(values, a1)})
        return out

    @staticmethod
    def _rtrim(row: list) -> list:
        row = list(row)
        while row and row[-1] == "":
            row.pop()
        return row

    def get_structure(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        book = self._enter("get_structure", spreadsheet_id)
        titles = []
        for r in ranges:
            _, a1 = self._resolve(book, r)
            if a1.sheet_title not in titles:
                titles.append(a1.sheet_title)
        sheets = []
        for t in titles:
            s = book["sheets"][t]
            data = [
                {"startRow": r - 1, "startColumn": c - 1, "rowData": [{"values": [self._grid_cell(cell)]}]}
                for (r, c), cell in s["cells"].items()
                if cell.get("format") is not None or cell.get("data_validation") is not None
            ]
            sheets.append({
                "properties": {"sheetId": s["sheet_id"], "title": t, "index": s["index"], "gridProperties": {"rowCount": s["row_count"], "columnCount": s["column_count"]}},
                "merges": s["merges"], "conditionalFormats": s["conditional_formats"], "data": data,
            })
        return fingerprint_structure(sheets, ranges)

    def write_values(self, spreadsheet_id: str, data: list[dict], value_input_option: str) -> dict:
        if value_input_option not in VALUE_INPUT_OPTIONS:
            raise ValueError(f"invalid value_input_option: {value_input_option!r}")
        book = self._enter("write_values", spreadsheet_id)
        resolved = [(self._resolve(book, d["range"]), d["values"]) for d in data]
        updated = 0
        ranges_out = []
        for (sheet, a1), values in resolved:
            for ri, row in enumerate(values):
                for ci, raw in enumerate(row):
                    if raw is None:
                        continue  # API semantics: null skips the cell
                    key = (a1.start_row + ri, a1.start_col + ci)
                    existing = sheet["cells"].get(key, {})
                    if raw == "":
                        value, formula = None, None
                    elif value_input_option == "USER_ENTERED":
                        value, formula = _user_entered(raw)
                        value = "" if formula else value
                    else:
                        value, formula = raw, None
                    new = {"value": value, "formula": formula}
                    for keep in ("format", "data_validation"):
                        if keep in existing:
                            new[keep] = copy.deepcopy(existing[keep])
                    if value_input_option == "RAW" and isinstance(raw, str) and new.get("format"):
                        new["format"].pop("numberFormat", None)  # observed real-API side effect
                        if not new["format"]:
                            del new["format"]
                    sheet["cells"][key] = new
                    updated += 1
            ranges_out.append(a1.to_a1())
        self.write_calls.append({"spreadsheet_id": spreadsheet_id, "value_input_option": value_input_option, "data": copy.deepcopy(data)})
        if self.after_write is not None:
            self.after_write(self)
        return {"updated_cells": updated, "updated_ranges": ranges_out}

    def clear_values(self, spreadsheet_id: str, ranges: list[str]) -> dict:
        book = self._enter("clear_values", spreadsheet_id)
        resolved = [self._resolve(book, r) for r in ranges]
        for sheet, a1 in resolved:
            for key in a1.cells():
                cell = sheet["cells"].get(key)
                if cell is not None:
                    cell["value"], cell["formula"] = None, None
        self.clear_calls.append({"spreadsheet_id": spreadsheet_id, "ranges": list(ranges)})
        if self.after_write is not None:
            self.after_write(self)
        return {"cleared_ranges": [a1.to_a1() for _, a1 in resolved]}

    @staticmethod
    def _grid_cell(cell: dict) -> dict:
        out = {}
        if cell.get("format") is not None:
            out["userEnteredFormat"] = copy.deepcopy(cell["format"])
        if cell.get("data_validation") is not None:
            out["dataValidation"] = copy.deepcopy(cell["data_validation"])
        return out

    def get_cell_formats(self, spreadsheet_id: str, ranges: list[str]) -> dict[str, dict]:
        book = self._enter("get_cell_formats", spreadsheet_id)
        sheets = []
        for rng in ranges:
            sheet, a1 = self._resolve(book, rng)
            sheets.append({
                "properties": {"title": a1.sheet_title},
                "data": [
                    {"startRow": r - 1, "startColumn": c - 1, "rowData": [{"values": [self._grid_cell(cell)]}]}
                    for (r, c), cell in sheet["cells"].items() if a1.contains(r, c)
                ],
            })
        return cell_formats_from_grid(sheets, ranges)

    def set_number_formats(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        book = self._enter("set_number_formats", spreadsheet_id)
        resolved = [(self._resolve(book, r["range"]), r) for r in requests]
        for (sheet, a1), req in resolved:
            if req["sheet_id"] != sheet["sheet_id"]:
                raise GoogleSheetsRangeError(f"HTTP 400: sheetId {req['sheet_id']} does not match {a1.sheet_title!r}")
            for key in a1.cells():
                cell = sheet["cells"].setdefault(key, {"value": None, "formula": None})
                fmt = cell.get("format") or {}
                fmt["numberFormat"] = copy.deepcopy(req["number_format"])
                cell["format"] = fmt
        self.format_calls.append({"spreadsheet_id": spreadsheet_id, "requests": copy.deepcopy(requests)})
        if self.after_write is not None:
            self.after_write(self)
        return {"updated_ranges": [r["range"] for r in requests]}

    @staticmethod
    def _user_entered_value(cell: dict) -> Optional[dict]:
        if cell.get("formula"):
            return {"formulaValue": cell["formula"]}
        v = cell.get("value")
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, (int, float)):
            return {"numberValue": v}
        return {"stringValue": v}

    def get_sheet_snapshot(self, spreadsheet_id: str, sheet_title: str) -> dict:
        book = self._enter("get_sheet_snapshot", spreadsheet_id)
        s = book["sheets"].get(sheet_title)
        if s is None:
            raise GoogleSheetsRangeError(f"HTTP 400: Unable to parse range: {sheet_title}")
        row_data: dict[int, dict[int, dict]] = {}
        for (r, c), cell in s["cells"].items():
            grid_cell = self._grid_cell(cell)
            uev = self._user_entered_value(cell)
            if uev is not None:
                grid_cell["userEnteredValue"] = uev
            row_data.setdefault(r, {})[c] = grid_cell
        n_rows = max(row_data, default=0)
        rows = []
        for r in range(1, n_rows + 1):
            cols = row_data.get(r, {})
            rows.append({"values": [cols.get(c, {}) for c in range(1, max(cols, default=0) + 1)]})
        sheet = {
            "properties": {"sheetId": s["sheet_id"], "title": sheet_title, "index": s["index"], "hidden": s["hidden"],
                           "gridProperties": {"rowCount": s["row_count"], "columnCount": s["column_count"], "frozenRowCount": s.get("frozen_row_count", 0)}},
            "merges": [dict(m, sheetId=s["sheet_id"]) for m in s["merges"]],
            "conditionalFormats": copy.deepcopy(s["conditional_formats"]),
            "data": [{"startRow": 0, "startColumn": 0, "rowData": rows,
                      "columnMetadata": [{"pixelSize": px} for px in s.get("column_sizes", [])]}],
        }
        return normalize_sheet_snapshot(sheet)

    def duplicate_sheet(self, spreadsheet_id: str, source_sheet_id: int, new_sheet_title: str, insert_index: int) -> dict:
        book = self._enter("duplicate_sheet", spreadsheet_id)
        source = next((s for s in book["sheets"].values() if s["sheet_id"] == source_sheet_id), None)
        if source is None:
            raise GoogleSheetsRangeError(f"HTTP 400: No grid with id: {source_sheet_id}")
        if new_sheet_title in book["sheets"]:  # API semantics: duplicate names are rejected
            raise GoogleSheetsAPIError(f"HTTP 400: A sheet with the name \"{new_sheet_title}\" already exists.")
        new = copy.deepcopy(source)
        new["sheet_id"] = max(s["sheet_id"] for s in book["sheets"].values()) + 1
        index = min(insert_index, len(book["sheets"]))
        for s in book["sheets"].values():
            if s["index"] >= index:
                s["index"] += 1
        new["index"] = index
        book["sheets"][new_sheet_title] = new
        self.structure_calls.append({"spreadsheet_id": spreadsheet_id, "duplicate_sheet": {"source_sheet_id": source_sheet_id, "new_sheet_title": new_sheet_title, "insert_index": insert_index}})
        if self.after_write is not None:
            self.after_write(self)
        return {"sheet_id": new["sheet_id"], "title": new_sheet_title, "index": index}

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        self._enter("batch_update", spreadsheet_id)
        raise GoogleSheetsAPIError("fake transport does not emulate structural batch updates")
