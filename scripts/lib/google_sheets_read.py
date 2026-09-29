"""Reference logic backing skills/read-google-sheet/SKILL.md — a
read-only, range-limited snapshot of one client's declared spreadsheet.

Never writes, never interprets the content (no metric mapping, no
diagnosis). Reading a sheet is not authorization to write to it.
"""

from __future__ import annotations

from typing import Callable, Optional

from scripts.lib.a1_notation import A1Error, cell_a1, col_to_letters, parse_a1
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339
from scripts.lib.google_sheets_sources import SheetSourceError, resolve_sheet_binding
from scripts.lib.google_sheets_transport import GoogleSheetsError, GoogleSheetsTransport

SCHEMA_VERSION = "1.0.0"
SKILL = "read-google-sheet"


def _notice(code: str, message: str, range_: Optional[str] = None) -> dict:
    n = {"code": code, "message": message}
    if range_ is not None:
        n["range"] = range_
    return n


def _empty_output(client_id: str, generated_at: str, requested: list[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "client_id": client_id,
        "generated_at": generated_at,
        "status": "error",
        "source": None,
        "tabs": [],
        "requested_ranges": list(requested),
        "ranges": [],
        "missing_data": [],
        "warnings": [],
        "errors": [],
    }


def read_google_sheet(
    transport: GoogleSheetsTransport,
    *,
    client_id: str,
    sources_doc: Optional[dict],
    ranges: list[str],
    source_id: Optional[str] = None,
    spreadsheet_locator: Optional[str] = None,
    include_formatted: bool = False,
    clock: Callable[[], str] = utc_now_rfc3339,
) -> dict:
    generated_at = clock()
    out = _empty_output(client_id, generated_at, ranges)

    problem = future_timestamp_problem(generated_at)
    if problem:
        out["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))

    if not ranges:
        out["errors"].append(_notice("NO_RANGES_REQUESTED", "at least one range or tab must be requested explicitly"))
        return out

    try:
        binding = resolve_sheet_binding(sources_doc, client_id, source_id=source_id, spreadsheet_locator=spreadsheet_locator)
    except SheetSourceError as e:
        out["errors"].append(_notice(e.code, e.message))
        return out
    if binding.contains_multiple_clients:
        out["warnings"].append(_notice("MULTI_CLIENT_SOURCE", "source is declared as containing multiple clients — only the requested ranges were read; isolation inside the sheet is the caller's responsibility"))

    try:
        meta = transport.get_spreadsheet_metadata(binding.spreadsheet_id)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out

    observed_at = generated_at
    out["source"] = {
        "source_id": binding.source_id,
        "spreadsheet_id": meta["spreadsheet_id"],
        "spreadsheet_title": meta["title"],
        "expected_title": binding.expected_title,
        "locale": meta.get("locale"),
        "time_zone": meta.get("time_zone"),
        "observed_at": observed_at,
        "source_date": None,
    }
    out["tabs"] = [dict(s) for s in meta["sheets"]]

    if meta["spreadsheet_id"] != binding.spreadsheet_id:
        out["errors"].append(_notice("WRONG_SPREADSHEET", "API returned a different spreadsheet id than the declared source"))
        return out
    if binding.expected_title is not None and meta["title"] != binding.expected_title:
        out["errors"].append(_notice("WRONG_SPREADSHEET", f"spreadsheet title {meta['title']!r} does not match expected_title {binding.expected_title!r}"))
        return out

    sheets = {s["title"]: s for s in meta["sheets"]}
    valid: list[str] = []
    for rng in ranges:
        try:
            a1 = parse_a1(rng)
        except A1Error as e:
            out["errors"].append(_notice("INVALID_RANGE", str(e), rng))
            continue
        if not binding.tab_allowed(a1.sheet_title):
            out["errors"].append(_notice("TAB_NOT_ALLOWED", f"tab {a1.sheet_title!r} is not in the source's allowed_tabs", rng))
            continue
        sheet = sheets.get(a1.sheet_title)
        if sheet is None:
            out["missing_data"].append(_notice("SHEET_NOT_FOUND", f"tab {a1.sheet_title!r} does not exist in the spreadsheet", rng))
            continue
        if (a1.end_row or a1.start_row or 0) > sheet["row_count"] or (a1.end_col or a1.start_col or 0) > sheet["column_count"]:
            out["missing_data"].append(_notice("RANGE_OUT_OF_GRID", f"range exceeds the tab grid ({sheet['row_count']} rows x {sheet['column_count']} cols)", rng))
            continue
        valid.append(rng)

    if not valid:
        out["status"] = "error"
        if not out["errors"] and not out["missing_data"]:
            out["errors"].append(_notice("NO_READABLE_RANGE", "none of the requested ranges could be read"))
        return out

    try:
        values = transport.read_values(binding.spreadsheet_id, valid)
        formulas = transport.read_formulas(binding.spreadsheet_id, valid)
        formatted = transport.read_formatted_values(binding.spreadsheet_id, valid) if include_formatted else None
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out

    for i, rng in enumerate(valid):
        a1 = parse_a1(rng)
        vals = values[i]["values"]
        forms = formulas[i]["values"]
        returned = parse_a1(values[i]["returned_range"]) if values[i]["returned_range"] else a1
        r0 = a1.start_row or returned.start_row or 1
        c0 = a1.start_col or returned.start_col or 1
        formula_cells = []
        for ri, row in enumerate(forms):
            for ci, v in enumerate(row):
                if isinstance(v, str) and v.startswith("="):
                    formula_cells.append({"cell": f"{col_to_letters(c0 + ci)}{r0 + ri}", "a1": cell_a1(a1.sheet_title, r0 + ri, c0 + ci), "formula": v})
        entry = {
            "requested_range": rng,
            "returned_range": values[i]["returned_range"],
            "sheet_title": a1.sheet_title,
            "bounded": a1.is_bounded,
            "row_count": len(vals),
            "column_count": max((len(r) for r in vals), default=0),
            "values": vals,
            "formatted_values": formatted[i]["values"] if formatted is not None else None,
            "formulas": formula_cells,
        }
        entry["content_sha256"] = content_sha256({"values": vals, "formulas": formula_cells})
        out["ranges"].append(entry)
        if not a1.is_bounded:
            out["warnings"].append(_notice("RANGE_TRIMMED", "open/whole-tab range: the API omits trailing empty rows/columns", rng))

    out["status"] = "partial" if (out["missing_data"] or out["errors"]) else "success"
    return out
