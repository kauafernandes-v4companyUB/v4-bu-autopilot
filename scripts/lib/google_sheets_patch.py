"""Reference logic backing skills/update-google-sheet/SKILL.md.

Materializes a structured, previously prepared patch
(schemas/google-sheet-patch.schema.json) on one client's declared
spreadsheet. It never decides *what* to write — it only validates,
previews, and (with explicit, hash-locked approval) applies exactly the
approved cell changes, then re-reads and verifies.

Guarantees:
- preview performs zero writes;
- apply re-reads live state, recomputes base_state_hash/preview_hash and
  aborts on any drift (STALE_PREVIEW) — the patch is never adapted;
- a formula cell is never overwritten, cleared or replaced unless the
  operation sets replace_existing_formula=true (and that is in the
  approved preview);
- content is written with values.batchUpdate and cleared with
  values.batchClear (never by writing "" — on the real API that also
  removes the cell's number format); formatting, merges, validations and
  sizes are fingerprinted before and verified after;
- the only formatting write is set_number_format (repeatCell restricted to
  userEnteredFormat.numberFormat); its cells are verified to have exactly
  the requested number format and every other format property unchanged;
- formulas outside the patch on every touched tab are verified intact;
- the only structural operation is duplicate_sheet (native duplicateSheet,
  alone in its patch): a destination that already exists is never
  overwritten; after the copy, the new tab must equal the source snapshot
  (identity aside) and the source and every other tab must be unchanged;
- replaying an already-applied patch is no_change with zero writes.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional

from scripts.lib import approval as ap
from scripts.lib.a1_notation import A1Error, cell_a1, col_to_letters, parse_a1, quote_sheet_title
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339
from scripts.lib.google_sheets_sources import SheetSourceError, resolve_sheet_binding
from scripts.lib.google_sheets_transport import (
    GoogleSheetsError,
    GoogleSheetsTransport,
    sheet_content,
    sheet_content_sha256,
    snapshot_differences,
)
from scripts.lib.receipt import build_effect, build_receipt

SCHEMA_VERSION = "1.0.0"
SKILL = "update-google-sheet"
OP_TYPES = ("write_value", "write_formula", "clear_value", "set_number_format", "duplicate_sheet")
NUMBER_FORMAT_TYPES = ("TEXT", "NUMBER", "PERCENT", "CURRENCY", "DATE", "TIME", "DATE_TIME", "SCIENTIFIC")
METHOD_WRITE = "values.batchUpdate"
METHOD_CLEAR = "values.batchClear"
METHOD_NUMBER_FORMAT = "spreadsheets.batchUpdate:repeatCell(userEnteredFormat.numberFormat)"
METHOD_DUPLICATE = "spreadsheets.batchUpdate:duplicateSheet"
MAX_SHEET_TITLE = 100
APPROVAL_ITEM_TYPE = "google_sheet_patch"
APPROVAL_SOURCE_TYPE = "google_sheet_preview"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _notice(code: str, message: str, *, op_id: Optional[str] = None, cell: Optional[str] = None) -> dict:
    n = {"code": code, "message": message}
    if op_id is not None:
        n["op_id"] = op_id
    if cell is not None:
        n["cell"] = cell
    return n


def _strip_outside_strings(formula: str) -> str:
    out, in_str = [], False
    for ch in formula:
        if ch == '"':
            in_str = not in_str
            out.append(ch)
        elif in_str:
            out.append(ch)
        elif not ch.isspace():
            out.append(ch.upper())
    return "".join(out)


def formulas_equal(a: Optional[str], b: Optional[str]) -> bool:
    """Google normalizes formulas (function-name case, spacing). Compare
    exactly, then modulo case/whitespace outside string literals."""
    if a is None or b is None:
        return a is b
    return a.strip() == b.strip() or _strip_outside_strings(a) == _strip_outside_strings(b)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def values_equal(current: Any, formatted: Any, desired: Any, input_option: str) -> bool:
    if desired in (None, ""):
        return current in (None, "")
    if isinstance(desired, bool) or isinstance(current, bool):
        return isinstance(desired, bool) and isinstance(current, bool) and desired == current
    if _is_number(desired) and _is_number(current):
        return math.isclose(float(desired), float(current), rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(desired, str) and isinstance(current, str) and desired == current:
        return True
    if input_option == "USER_ENTERED" and isinstance(desired, str):
        if formatted == desired:
            return True
        if _is_number(current):
            try:
                return math.isclose(float(desired), float(current), rel_tol=1e-9, abs_tol=1e-12)
            except ValueError:
                return False
    return False


def _cell_state(value: Any, formatted: Any, formula_render: Any) -> dict:
    formula = formula_render if isinstance(formula_render, str) and formula_render.startswith("=") else None
    return {"value": None if value == "" else value, "formatted_value": None if formatted == "" else formatted, "formula": formula}


def _number_format(nf: Any) -> Optional[dict]:
    """Canonical number format: {type, pattern?}; empty pattern == absent."""
    if not isinstance(nf, dict) or not nf.get("type"):
        return None
    out = {"type": nf["type"]}
    if nf.get("pattern"):
        out["pattern"] = nf["pattern"]
    return out


def _matches(state: dict, desired: dict) -> bool:
    kind = desired["kind"]
    if kind == "number_format":
        return _number_format(state.get("number_format")) == desired["number_format"]
    if kind == "formula":
        return formulas_equal(state["formula"], desired["formula"])
    if state["formula"] is not None:
        return False
    if kind == "empty":
        return state["value"] is None
    return values_equal(state["value"], state["formatted_value"], desired["value"], desired["input_option"])


def approval_item_payload(preview: dict) -> dict:
    """The exact payload an operator approves for a patch: hash-locked to
    the preview (scripts/lib/approval.py)."""
    return {
        "patch_id": preview["patch_id"],
        "client_id": preview["client_id"],
        "spreadsheet_id": preview["spreadsheet_id"],
        "base_state_hash": preview["base_state_hash"],
        "preview_hash": preview["preview_hash"],
    }


def build_patch_approval_candidate(preview: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    """status=draft candidate only — becomes real exclusively through
    approval.apply_operator_decision on an explicit operator request."""
    if preview.get("mode") != "preview" or preview.get("status") != "success" or not preview.get("preview_hash"):
        raise ap.ApprovalError("only a successful preview with a preview_hash can be proposed for approval")
    return ap.build_approval_candidate(
        approval_id=approval_id,
        client_id=preview["client_id"],
        quarter_id=None,
        created_at=created_at,
        source_artifact_type=APPROVAL_SOURCE_TYPE,
        source_artifact_id=f"{preview['patch_id']}:{preview['preview_hash'][:16]}",
        source_artifact=preview,
        source_artifact_path=preview_path,
        candidate_items=[{"item_id": preview["patch_id"], "item_type": APPROVAL_ITEM_TYPE, "payload": approval_item_payload(preview)}],
    )


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------


def normalize_operations(patch: dict, binding_tab_allowed: Callable[[str], bool]) -> tuple[list[dict], list[dict]]:
    """Returns (normalized_operations, errors). Pure — no transport."""
    errors: list[dict] = []
    normalized: list[dict] = []
    allow_clear = bool((patch.get("permissions") or {}).get("allow_clear", False))
    seen_ops: set[str] = set()
    owners: dict[str, str] = {}

    ops = patch.get("operations")
    if not isinstance(ops, list) or not ops:
        return [], [_notice("EMPTY_PATCH", "patch has no operations")]

    for op in ops:
        op_id = op.get("op_id")
        op_type = op.get("type")
        if not op_id:
            errors.append(_notice("INVALID_OPERATION", "operation without op_id"))
            continue
        if op_id in seen_ops:
            errors.append(_notice("DUPLICATE_OP_ID", f"op_id {op_id!r} appears more than once", op_id=op_id))
            continue
        seen_ops.add(op_id)
        if op_type not in OP_TYPES:
            errors.append(_notice("UNSUPPORTED_OPERATION", f"operation type {op_type!r} is not supported (the only structural operation is duplicate_sheet; the only formatting operation is set_number_format)", op_id=op_id))
            continue
        if op_type == "duplicate_sheet":
            src, new, idx = op.get("source_sheet_title"), op.get("new_sheet_title"), op.get("insert_index")
            if not isinstance(src, str) or not src or not isinstance(new, str) or not new.strip() or len(new) > MAX_SHEET_TITLE or new == src:
                errors.append(_notice("INVALID_OPERATION", f"duplicate_sheet needs source_sheet_title and a different, non-empty new_sheet_title (≤ {MAX_SHEET_TITLE} chars)", op_id=op_id))
                continue
            if idx is not None and (not isinstance(idx, int) or isinstance(idx, bool) or idx < 0):
                errors.append(_notice("INVALID_OPERATION", "insert_index must be a non-negative integer", op_id=op_id))
                continue
            if not binding_tab_allowed(src) or not binding_tab_allowed(new):
                errors.append(_notice("TAB_NOT_ALLOWED", "source and destination tabs must both be allowed by the source's allowed_tabs", op_id=op_id))
                continue
            normalized.append({"op_id": op_id, "type": op_type, "range": quote_sheet_title(src), "sheet_title": src, "input_option": None,
                               "replace_existing_formula": False, "cells": [],
                               "sheet_operation": {"source_sheet_title": src, "new_sheet_title": new, "insert_index": idx}})
            continue
        try:
            a1 = parse_a1(op.get("range", ""))
        except A1Error as e:
            errors.append(_notice("INVALID_RANGE", str(e), op_id=op_id))
            continue
        if not a1.is_bounded:
            errors.append(_notice("INVALID_RANGE", "patch ranges must be bounded (e.g. 'Tab'!B2 or 'Tab'!B2:D5)", op_id=op_id))
            continue
        if not binding_tab_allowed(a1.sheet_title):
            errors.append(_notice("TAB_NOT_ALLOWED", f"tab {a1.sheet_title!r} is not in the source's allowed_tabs", op_id=op_id))
            continue

        input_option = op.get("input_option", "RAW")
        replace = bool(op.get("replace_existing_formula", False))
        if op_type == "write_value":
            grid = op.get("values")
            if input_option not in ("RAW", "USER_ENTERED"):
                errors.append(_notice("INVALID_OPERATION", f"input_option must be RAW or USER_ENTERED, got {input_option!r}", op_id=op_id))
                continue
        elif op_type == "write_formula":
            grid = op.get("formulas")
            input_option = "USER_ENTERED"
        elif op_type == "set_number_format":
            grid = None
            input_option = None
            nf = op.get("number_format")
            if (not isinstance(nf, dict) or set(nf) - {"type", "pattern"} or nf.get("type") not in NUMBER_FORMAT_TYPES
                    or not isinstance(nf.get("pattern", ""), str)):
                errors.append(_notice("INVALID_NUMBER_FORMAT", f"number_format must be {{type: one of {list(NUMBER_FORMAT_TYPES)}, pattern?: string}}", op_id=op_id))
                continue
            number_format = _number_format(nf)
        else:
            grid = None
            input_option = None
            if not allow_clear:
                errors.append(_notice("CLEAR_NOT_AUTHORIZED", "clear_value requires permissions.allow_clear=true in the patch", op_id=op_id))
                continue

        if grid is not None:
            if not isinstance(grid, list) or len(grid) != a1.n_rows or any(not isinstance(r, list) or len(r) != a1.n_cols for r in grid):
                errors.append(_notice("SHAPE_MISMATCH", f"grid must be exactly {a1.n_rows}x{a1.n_cols} for {a1.to_a1()}", op_id=op_id))
                continue

        cells = []
        bad = False
        for idx, (row, col) in enumerate(a1.cells()):
            ref = cell_a1(a1.sheet_title, row, col)
            if op_type == "clear_value":
                desired = {"kind": "empty"}
            elif op_type == "set_number_format":
                desired = {"kind": "number_format", "number_format": number_format}
            else:
                raw = grid[idx // a1.n_cols][idx % a1.n_cols]
                if op_type == "write_formula":
                    if not isinstance(raw, str) or not raw.startswith("="):
                        errors.append(_notice("INVALID_FORMULA", "write_formula cells must be strings starting with '='", op_id=op_id, cell=ref))
                        bad = True
                        continue
                    desired = {"kind": "formula", "formula": raw}
                else:
                    if raw is None or isinstance(raw, (dict, list)):
                        errors.append(_notice("INVALID_VALUE", "write_value cells must be string, number or boolean (use clear_value to empty a cell)", op_id=op_id, cell=ref))
                        bad = True
                        continue
                    if isinstance(raw, str) and raw.startswith("="):
                        errors.append(_notice("VALUE_LOOKS_LIKE_FORMULA", "a value starting with '=' must be declared as write_formula", op_id=op_id, cell=ref))
                        bad = True
                        continue
                    if raw == "":
                        errors.append(_notice("INVALID_VALUE", "empty string is a clear — use clear_value", op_id=op_id, cell=ref))
                        bad = True
                        continue
                    desired = {"kind": "value", "value": raw, "input_option": input_option}
            if ref in owners:
                errors.append(_notice("OVERLAPPING_TARGETS", f"cell is targeted by both {owners[ref]!r} and {op_id!r}", op_id=op_id, cell=ref))
                bad = True
                continue
            owners[ref] = op_id
            cells.append({"cell": ref, "row": row, "col": col, "desired": desired})
        if bad:
            continue
        normalized.append({
            "op_id": op_id,
            "type": op_type,
            "range": a1.to_a1(),
            "sheet_title": a1.sheet_title,
            "input_option": input_option,
            "replace_existing_formula": replace,
            "cells": cells,
        })
    if any(o["type"] == "duplicate_sheet" for o in normalized) and len(ops) > 1:
        errors.append(_notice("DUPLICATE_SHEET_NOT_ALONE", "a duplicate_sheet patch must contain exactly one operation; write to the new tab in a separate patch after it exists"))
    return normalized, errors


# ---------------------------------------------------------------------------
# live state
# ---------------------------------------------------------------------------


def _read_live_state(transport: GoogleSheetsTransport, spreadsheet_id: str, ops: list[dict]) -> dict:
    target_ranges = [op["range"] for op in ops]
    tabs = sorted({op["sheet_title"] for op in ops})
    tab_ranges = [quote_sheet_title(t) for t in tabs]
    values = transport.read_values(spreadsheet_id, target_ranges)
    formatted = transport.read_formatted_values(spreadsheet_id, target_ranges)
    formulas = transport.read_formulas(spreadsheet_id, target_ranges)
    tab_formulas = transport.read_formulas(spreadsheet_id, tab_ranges)
    structure = transport.get_structure(spreadsheet_id, target_ranges)
    formats = transport.get_cell_formats(spreadsheet_id, target_ranges)

    cells: dict[str, dict] = {}
    for i, op in enumerate(ops):
        a1 = parse_a1(op["range"])
        for row, col in a1.cells():
            r, c = row - a1.start_row, col - a1.start_col
            cells[cell_a1(a1.sheet_title, row, col)] = _cell_state(values[i]["values"][r][c], formatted[i]["values"][r][c], formulas[i]["values"][r][c])

    formula_map: dict[str, dict[str, str]] = {}
    for tab, fr in zip(tabs, tab_formulas):
        returned = parse_a1(fr["returned_range"]) if fr.get("returned_range") else None
        r0 = (returned.start_row if returned and returned.start_row else 1)
        c0 = (returned.start_col if returned and returned.start_col else 1)
        found = {}
        for ri, row in enumerate(fr["values"]):
            for ci, v in enumerate(row):
                if isinstance(v, str) and v.startswith("="):
                    found[cell_a1(tab, r0 + ri, c0 + ci)] = v
        formula_map[tab] = found
    return {"cells": cells, "tab_formulas": formula_map, "structure": structure, "formats": formats}


def _user_number_format(live: dict, cell: str) -> Optional[dict]:
    return _number_format(((live["formats"].get(cell) or {}).get("user_entered_format") or {}).get("numberFormat"))


def _target_state(live: dict, op: dict, cell: str) -> dict:
    """Cell state as compared/reported for this operation: set_number_format
    targets also carry their current userEnteredFormat.numberFormat."""
    state = dict(live["cells"][cell])
    if op["type"] == "set_number_format":
        state["number_format"] = _user_number_format(live, cell)
    return state


def _format_without_number_format(entry: Optional[dict]) -> dict:
    entry = entry or {}
    fmt = dict(entry.get("user_entered_format") or {})
    fmt.pop("numberFormat", None)
    return {"format": fmt, "data_validation": entry.get("data_validation")}


def _fingerprint_key(op: dict, c: dict) -> tuple[str, str]:
    """(tab, "B2") — how fingerprint_structure() keys target cells."""
    return op["sheet_title"], f"{col_to_letters(c['col'])}{c['row']}"


def _structure_differences(before: dict, after: dict, excluded: set[tuple[str, str]]) -> list[dict]:
    """Where two structure fingerprints differ, ignoring `excluded` cells."""
    diffs = []
    for tab in sorted(set(before) | set(after)):
        b, a = before.get(tab) or {}, after.get(tab) or {}
        for key in sorted((set(b) | set(a)) - {"cells"}):
            if b.get(key) != a.get(key):
                diffs.append({"sheet": tab, "property": key})
        bc, ac = b.get("cells") or {}, a.get("cells") or {}
        for ref in sorted(set(bc) | set(ac)):
            if (tab, ref) not in excluded and bc.get(ref) != ac.get(ref):
                diffs.append({"sheet": tab, "cell": ref, "property": "cell_format_or_validation"})
    return diffs


def _formulas_outside(formula_map: dict[str, dict[str, str]], targets: set[str]) -> dict[str, dict[str, str]]:
    return {tab: {c: f for c, f in sorted(m.items()) if c not in targets} for tab, m in sorted(formula_map.items())}


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def _base_output(mode: str, client_id: str, patch: dict, generated_at: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "mode": mode,
        "client_id": client_id,
        "patch_id": patch.get("patch_id"),
        "source_id": None,
        "spreadsheet_id": patch.get("spreadsheet_id"),
        "spreadsheet_title": None,
        "generated_at": generated_at,
        "status": "error",
        "operations": [],
        "before": None,
        "after": None,
        "diff": [],
        "mutation_plan": None,
        "base_state_hash": None,
        "preview_hash": None,
        "approval_id": None,
        "applied": None,
        "verification": None,
        "receipt": None,
        "conflicts": [],
        "missing_data": [],
        "warnings": [],
        "errors": [],
    }


def _public_op(op: dict) -> dict:
    out = {k: op[k] for k in ("op_id", "type", "range", "sheet_title", "input_option", "replace_existing_formula")} | {
        "cells": [{"cell": c["cell"], "desired": c["desired"]} for c in op["cells"]]
    }
    if "sheet_operation" in op:
        out["sheet_operation"] = op["sheet_operation"]
    return out


def _sheet_summary(snap: dict) -> dict:
    """What the operator needs to see about a tab before duplicating it."""
    cells = snap["cells"].values()
    dv = [c["dataValidation"] for c in cells if c.get("dataValidation")]
    linked = sum(1 for c in cells if c.get("hyperlink") or any((r.get("format") or {}).get("link") for r in c.get("textFormatRuns", [])))
    merges = [f"{col_to_letters(m['startColumnIndex'] + 1)}{m['startRowIndex'] + 1}:{col_to_letters(m['endColumnIndex'])}{m['endRowIndex']}"
              for m in sorted(snap["merges"], key=lambda m: (m.get("startRowIndex", 0), m.get("startColumnIndex", 0)))]
    return {
        "title": snap["title"], "sheet_id": snap["sheet_id"], "index": snap["index"], "hidden": snap["hidden"], "grid": snap["grid"],
        "non_empty_cells": sum(1 for c in cells if c.get("userEnteredValue")),
        "formulas": sum(1 for c in cells if "formulaValue" in (c.get("userEnteredValue") or {})),
        "formatted_cells": sum(1 for c in cells if c.get("userEnteredFormat")),
        "data_validations": len(dv),
        "checkbox_validations": sum(1 for v in dv if (v.get("condition") or {}).get("type") == "BOOLEAN"),
        "hyperlinked_cells": linked, "notes": sum(1 for c in cells if c.get("note")),
        "merges": merges, "conditional_formats": len(snap["conditional_formats"]), "protected_ranges": len(snap["protected_ranges"]),
        "banded_ranges": len(snap["banded_ranges"]), "basic_filter": snap["basic_filter"] is not None, "charts": snap["charts_count"],
        "column_sizes": [c["size"] for c in snap["column_sizes"]], "content_sha256": sheet_content_sha256(snap),
    }


def _preview_duplicate(transport, out: dict, meta: dict, ops: list[dict], client_id: str, patch: dict) -> tuple[dict, Optional[dict], list[dict]]:
    op = ops[0]
    so = op["sheet_operation"]
    by_title = {s["title"]: s for s in meta["sheets"]}
    src_meta, dst_meta = by_title.get(so["source_sheet_title"]), by_title.get(so["new_sheet_title"])
    try:
        src = transport.get_sheet_snapshot(meta["spreadsheet_id"], so["source_sheet_title"]) if src_meta else None
        dst = transport.get_sheet_snapshot(meta["spreadsheet_id"], so["new_sheet_title"]) if dst_meta else None
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out, None, ops
    insert_index = so["insert_index"] if so["insert_index"] is not None else (src_meta["index"] + 1 if src_meta else None)
    if src is None:
        out["conflicts"].append(_notice("SOURCE_SHEET_NOT_FOUND", f"tab {so['source_sheet_title']!r} does not exist", op_id=op["op_id"]))
    already_done = src is not None and dst is not None and sheet_content(dst) == sheet_content(src)
    if dst is not None and not already_done:
        out["conflicts"].append(_notice("DESTINATION_EXISTS", f"tab {so['new_sheet_title']!r} already exists and is not an identical duplicate — never overwritten", op_id=op["op_id"]))

    base_state = {
        "spreadsheet_id": meta["spreadsheet_id"], "title": meta["title"],
        "sheets": [{"sheet_id": s["sheet_id"], "title": s["title"], "index": s["index"]} for s in sorted(meta["sheets"], key=lambda s: s["index"])],
        "insert_index": insert_index,
        "source_snapshot": src,
        "destination_snapshot_sha256": sheet_content_sha256(dst) if dst else None,
    }
    base_state_hash = content_sha256(base_state)
    will_write = not out["conflicts"] and not already_done
    out["before"], out["after"], out["diff"] = {}, {}, []
    out["base_state_hash"] = base_state_hash
    out["sheet_plan"] = {
        "operation": "duplicate_sheet", "spreadsheet_id": meta["spreadsheet_id"], "spreadsheet_title": meta["title"],
        "source": _sheet_summary(src) if src else {"title": so["source_sheet_title"], "exists": False},
        "destination": {"title": so["new_sheet_title"], "exists": dst is not None, "insert_index": insert_index,
                        "identical_to_source": already_done if dst is not None else None},
        "existing_sheets": [s["title"] for s in base_state["sheets"]],
        "expected_effect": (f"native duplicateSheet creates tab {so['new_sheet_title']!r} at index {insert_index} as a copy of {so['source_sheet_title']!r} "
                            "(values, formulas, formatting, sizes, merges, validations, links, notes); no existing tab is modified" if will_write
                            else "no write"),
    }
    out["mutation_plan"] = {
        "will_write": will_write,
        "write_requests": [{"op_id": op["op_id"], "range": op["range"], "method": METHOD_DUPLICATE, "value_input_option": None}] if will_write else [],
        "formula_replacements": [], "cells_to_change": 0, "content_only": False,
    }
    out["preview_hash"] = content_sha256({
        "client_id": client_id, "patch_id": patch["patch_id"], "spreadsheet_id": meta["spreadsheet_id"], "base_state_hash": base_state_hash,
        "operations": out["operations"], "after": {"new_sheet_title": so["new_sheet_title"], "insert_index": insert_index,
                                                   "source_content_sha256": sheet_content_sha256(src) if src else None},
        "formula_replacements": [],
    })
    out["status"] = "conflict" if out["conflicts"] else ("no_change" if already_done else "success")
    return out, base_state, ops


def _verify_duplicate(transport, spreadsheet_id: str, op: dict, base_state: dict, created: Optional[dict]) -> dict:
    so = op["sheet_operation"]
    meta = transport.get_spreadsheet_metadata(spreadsheet_id)
    by_title = {s["title"]: s for s in meta["sheets"]}
    src_now = transport.get_sheet_snapshot(spreadsheet_id, so["source_sheet_title"]) if so["source_sheet_title"] in by_title else None
    dst_now = transport.get_sheet_snapshot(spreadsheet_id, so["new_sheet_title"]) if so["new_sheet_title"] in by_title else None
    src_before = base_state["source_snapshot"]
    differences = snapshot_differences(src_before, dst_now) if dst_now else [{"property": "destination_missing"}]
    # index may legitimately shift when the copy is inserted before the source
    source_unchanged = src_now is not None and src_now["sheet_id"] == src_before["sheet_id"] and sheet_content(src_now) == sheet_content(src_before)
    before_ids = {(s["sheet_id"], s["title"]) for s in base_state["sheets"]}
    now_ids = {(s["sheet_id"], s["title"]) for s in meta["sheets"]}
    other_sheets_intact = before_ids <= now_ids and len(now_ids - before_ids) == 1
    structure_differences = [] if source_unchanged else [{"sheet": so["source_sheet_title"], "property": "source_changed"}]
    if not other_sheets_intact:
        structure_differences.append({"property": "sheet_list", "before": sorted(t for _, t in before_ids), "after": sorted(t for _, t in now_ids)})
    return {
        "targets_match": dst_now is not None and not differences,
        "formulas_outside_patch_intact": source_unchanged,
        "structure_preserved": source_unchanged and other_sheets_intact,
        "mismatches": differences,
        "changed_formulas_outside_patch": [],
        "structure_differences": structure_differences,
        "duplicate_sheet": {
            "created": created, "destination_found": dst_now is not None,
            "destination_index": by_title.get(so["new_sheet_title"], {}).get("index"),
            "content_equal_to_source": dst_now is not None and not differences,
            "source_unchanged": source_unchanged, "other_sheets_intact": other_sheets_intact,
            "source_content_sha256": sheet_content_sha256(src_before),
            "destination_content_sha256": sheet_content_sha256(dst_now) if dst_now else None,
        },
    }


def _desired_to_after(desired: dict, state: dict) -> dict:
    if desired["kind"] == "number_format":
        return {"value": state["value"], "formula": state["formula"], "number_format": desired["number_format"]}
    if desired["kind"] == "formula":
        return {"value": None, "formula": desired["formula"]}
    if desired["kind"] == "empty":
        return {"value": None, "formula": None}
    return {"value": desired["value"], "formula": None}


def _preview_internal(transport, *, client_id, patch, sources_doc, mode, clock) -> tuple[dict, Optional[dict], list[dict]]:
    generated_at = clock()
    out = _base_output(mode, client_id, patch, generated_at)
    problem = future_timestamp_problem(generated_at)
    if problem:
        out["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))

    if not patch.get("patch_id"):
        out["errors"].append(_notice("INVALID_PATCH", "patch_id is required"))
        return out, None, []
    if patch.get("client_id") != client_id:
        out["errors"].append(_notice("CLIENT_ISOLATION", f"patch belongs to client {patch.get('client_id')!r}, not {client_id!r}"))
        return out, None, []
    try:
        binding = resolve_sheet_binding(sources_doc, client_id, source_id=patch.get("source_id"), spreadsheet_locator=patch.get("spreadsheet_id"))
    except SheetSourceError as e:
        out["errors"].append(_notice(e.code, e.message))
        return out, None, []
    out["source_id"] = binding.source_id
    out["spreadsheet_id"] = binding.spreadsheet_id
    if not binding.writable:
        out["errors"].append(_notice("SOURCE_NOT_WRITABLE", f"source {binding.source_id!r} is not declared writable (google_sheet.writable=true) in sources.json"))
        return out, None, []
    if binding.contains_multiple_clients:
        out["errors"].append(_notice("CLIENT_ISOLATION", "writes to a source declared as containing multiple clients are not allowed"))
        return out, None, []

    ops, op_errors = normalize_operations(patch, binding.tab_allowed)
    if op_errors:
        out["errors"].extend(op_errors)
        out["operations"] = [_public_op(o) for o in ops]
        return out, None, []
    out["operations"] = [_public_op(o) for o in ops]

    try:
        meta = transport.get_spreadsheet_metadata(binding.spreadsheet_id)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out, None, ops
    out["spreadsheet_title"] = meta["title"]
    if meta["spreadsheet_id"] != binding.spreadsheet_id or (binding.expected_title is not None and meta["title"] != binding.expected_title):
        out["errors"].append(_notice("WRONG_SPREADSHEET", f"spreadsheet {meta['spreadsheet_id']!r} titled {meta['title']!r} does not match the declared source"))
        return out, None, ops

    if ops and ops[0]["type"] == "duplicate_sheet":
        return _preview_duplicate(transport, out, meta, ops, client_id, patch)

    sheets = {s["title"]: s for s in meta["sheets"]}
    for op in ops:
        sheet = sheets.get(op["sheet_title"])
        a1 = parse_a1(op["range"])
        if sheet is None:
            out["errors"].append(_notice("SHEET_NOT_FOUND", f"tab {op['sheet_title']!r} does not exist", op_id=op["op_id"]))
        elif a1.end_row > sheet["row_count"] or a1.end_col > sheet["column_count"]:
            out["errors"].append(_notice("RANGE_OUT_OF_GRID", f"{op['range']} exceeds the tab grid — growing the grid is a structural change, not allowed", op_id=op["op_id"]))
    if out["errors"]:
        return out, None, ops

    try:
        live = _read_live_state(transport, binding.spreadsheet_id, ops)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out, None, ops

    targets = {c["cell"] for op in ops for c in op["cells"]}
    before, after, diff, replacements = {}, {}, [], []
    for op in ops:
        resets = []
        for c in op["cells"]:
            state = _target_state(live, op, c["cell"])
            before[c["cell"]] = state
            after[c["cell"]] = _desired_to_after(c["desired"], state)
            if _matches(state, c["desired"]):
                continue
            if op["type"] == "set_number_format":
                # formatting only: value and formula are never touched
                diff.append({"cell": c["cell"], "op_id": op["op_id"], "change": "number_format_set", "before": state, "after": after[c["cell"]]})
                continue
            if state["formula"] is not None:
                if not op["replace_existing_formula"]:
                    code = "FORMULA_REPLACE_NOT_DECLARED" if op["type"] == "write_formula" else "FORMULA_OVERWRITE_BLOCKED"
                    out["conflicts"].append(_notice(code, f"cell holds formula {state['formula']!r}; the operation does not declare replace_existing_formula=true", op_id=op["op_id"], cell=c["cell"]))
                    continue
                replacements.append({"cell": c["cell"], "op_id": op["op_id"], "existing_formula": state["formula"]})
            change = {"write_value": "value_written", "write_formula": "formula_written", "clear_value": "cleared"}[op["type"]]
            if state["formula"] is not None:
                change = "formula_replaced" if op["type"] == "write_formula" else "formula_removed"
            diff.append({"cell": c["cell"], "op_id": op["op_id"], "change": change, "before": state, "after": after[c["cell"]]})
            if (op["type"] == "write_value" and op["input_option"] == "RAW" and isinstance(c["desired"]["value"], str)
                    and _user_number_format(live, c["cell"]) is not None):
                resets.append(c["cell"])
        if resets:
            out["warnings"].append(_notice(
                "NUMBER_FORMAT_WILL_BE_RESET",
                f"{len(resets)} cell(s) with a number format receive a RAW text value; the Sheets API removes their "
                f"userEnteredFormat.numberFormat, so post-write verification will report structure_preserved=false (first: {resets[0]})",
                op_id=op["op_id"], cell=resets[0]))

    base_state = {
        "spreadsheet_id": meta["spreadsheet_id"],
        "title": meta["title"],
        "sheets": [{"sheet_id": sheets[t]["sheet_id"], "title": t, "row_count": sheets[t]["row_count"], "column_count": sheets[t]["column_count"]} for t in sorted({o["sheet_title"] for o in ops})],
        "target_cells": {k: {"value": v["value"], "formula": v["formula"]} for k, v in sorted(before.items())},
        "formulas_outside_patch": _formulas_outside(live["tab_formulas"], targets),
        "structure": live["structure"],
    }
    number_format_cells = {c["cell"] for op in ops if op["type"] == "set_number_format" for c in op["cells"]}
    if number_format_cells:
        # raw formats of the cells whose number format may change: verification
        # proves every OTHER format property and the validation stayed identical.
        base_state["number_format_targets"] = {cell: live["formats"].get(cell) for cell in sorted(number_format_cells)}
    base_state_hash = content_sha256(base_state)
    changed_ops = sorted({d["op_id"] for d in diff})
    method = {"write_value": METHOD_WRITE, "write_formula": METHOD_WRITE, "clear_value": METHOD_CLEAR, "set_number_format": METHOD_NUMBER_FORMAT}
    write_requests = [
        {"op_id": op["op_id"], "range": op["range"], "method": method[op["type"]], "value_input_option": op["input_option"]}
        for op in ops if op["op_id"] in changed_ops
    ]
    out["before"] = before
    out["after"] = after
    out["diff"] = diff
    out["base_state_hash"] = base_state_hash
    out["mutation_plan"] = {
        "will_write": bool(diff) and not out["conflicts"],
        "write_requests": write_requests,
        "formula_replacements": replacements,
        "cells_to_change": len(diff),
        "content_only": not any(d["change"] == "number_format_set" for d in diff),
    }
    out["preview_hash"] = content_sha256({
        "client_id": client_id,
        "patch_id": patch["patch_id"],
        "spreadsheet_id": binding.spreadsheet_id,
        "base_state_hash": base_state_hash,
        "operations": out["operations"],
        "after": after,
        "formula_replacements": replacements,
    })
    if out["conflicts"]:
        out["status"] = "conflict"
    elif not diff:
        out["status"] = "no_change"
    else:
        out["status"] = "success"
    return out, base_state, ops


def preview_patch(transport: GoogleSheetsTransport, *, client_id: str, patch: dict, sources_doc: Optional[dict], clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    out, _, _ = _preview_internal(transport, client_id=client_id, patch=patch, sources_doc=sources_doc, mode="preview", clock=clock)
    return out


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _write_payload(op: dict) -> list[list]:
    """values.batchUpdate grid for write_value/write_formula only. Clears
    never go through here: writing "" would also drop the number format."""
    a1 = parse_a1(op["range"])
    grid = [[None] * a1.n_cols for _ in range(a1.n_rows)]
    for c in op["cells"]:
        d = c["desired"]
        grid[c["row"] - a1.start_row][c["col"] - a1.start_col] = d["formula"] if d["kind"] == "formula" else d["value"]
    return grid


def _verify(transport, spreadsheet_id: str, ops: list[dict], base_state: dict) -> dict:
    live = _read_live_state(transport, spreadsheet_id, ops)
    targets = {c["cell"] for op in ops for c in op["cells"]}
    mismatches = []
    for op in ops:
        for c in op["cells"]:
            state = _target_state(live, op, c["cell"])
            if not _matches(state, c["desired"]):
                mismatches.append({"cell": c["cell"], "expected": _desired_to_after(c["desired"], state), "observed": state})

    # Structure: identical except the number format of set_number_format cells,
    # whose remaining format properties and validation must stay identical.
    number_format_ops = [op for op in ops if op["type"] == "set_number_format"]
    excluded = {_fingerprint_key(op, c) for op in number_format_ops for c in op["cells"]}
    structure_differences = _structure_differences(base_state["structure"], live["structure"], excluded)
    for op in number_format_ops:
        for c in op["cells"]:
            before_entry = base_state["number_format_targets"].get(c["cell"])
            if _format_without_number_format(before_entry) != _format_without_number_format(live["formats"].get(c["cell"])):
                structure_differences.append({"sheet": op["sheet_title"], "cell": _fingerprint_key(op, c)[1], "property": "format_other_than_number_format"})

    outside_now = _formulas_outside(live["tab_formulas"], targets)
    changed_formulas = []
    for tab, before_map in base_state["formulas_outside_patch"].items():
        now_map = outside_now.get(tab, {})
        for cell in sorted(set(before_map) | set(now_map)):
            if before_map.get(cell) != now_map.get(cell):
                changed_formulas.append({"cell": cell, "before": before_map.get(cell), "after": now_map.get(cell)})
    return {
        "targets_match": not mismatches,
        "formulas_outside_patch_intact": not changed_formulas,
        "structure_preserved": not structure_differences,
        "mismatches": mismatches,
        "changed_formulas_outside_patch": changed_formulas,
        "structure_differences": structure_differences,
    }


def apply_patch(
    transport: GoogleSheetsTransport,
    *,
    client_id: str,
    patch: dict,
    sources_doc: Optional[dict],
    approved_preview: Optional[dict],
    approval: Optional[dict],
    clock: Callable[[], str] = utc_now_rfc3339,
) -> dict:
    fresh, base_state, ops = _preview_internal(transport, client_id=client_id, patch=patch, sources_doc=sources_doc, mode="apply", clock=clock)
    fresh["approval_id"] = (approval or {}).get("approval_id")

    # 1. explicit, hash-locked approval of a matching preview — checked before any write.
    gate: list[dict] = []
    if approved_preview is None:
        gate.append(_notice("NO_PREVIEW", "apply requires the approved preview output"))
    elif approved_preview.get("mode") != "preview" or approved_preview.get("status") != "success" or not approved_preview.get("preview_hash"):
        gate.append(_notice("NO_PREVIEW", "the supplied preview is not an applicable preview (mode=preview, status=success, preview_hash present)"))
    elif (approved_preview.get("client_id"), approved_preview.get("patch_id")) != (client_id, patch.get("patch_id")):
        gate.append(_notice("PATCH_MISMATCH", "approved preview belongs to a different client or patch"))
    if approval is None:
        gate.append(_notice("NO_APPROVAL", "apply requires an explicit operator approval record (schemas/approval.schema.json)"))
    elif approved_preview is not None and not gate:
        if approval.get("client_id") != client_id:
            gate.append(_notice("CLIENT_ISOLATION", "approval belongs to a different client"))
        else:
            item_id = patch.get("patch_id")
            covered = [i for i in approval.get("scope", {}).get("approved_items", []) if i.get("item_id") == item_id and i.get("item_type") == APPROVAL_ITEM_TYPE]
            if not covered:
                gate.append(_notice("NO_APPROVAL", f"approval does not cover patch {item_id!r}"))
            else:
                checks = ap.validate_approval(approval, approved_preview, {item_id: approval_item_payload(approved_preview)})
                bad = [c for c in checks if c.item_id == item_id and not c.ok]
                if bad:
                    gate.append(_notice("STALE_APPROVAL", bad[0].reason))
    if gate:
        fresh["errors"] = gate + fresh["errors"]
        fresh["status"] = "error"
        return fresh

    if fresh["errors"]:
        fresh["status"] = "error"
        return fresh

    # 2. idempotency: desired state already holds -> no_change, zero writes.
    if fresh["status"] == "no_change":
        fresh["mutation_plan"]["will_write"] = False
        return fresh

    # 3. drift detection — never adapt the patch.
    if fresh["preview_hash"] != approved_preview["preview_hash"]:
        code = "STALE_PREVIEW" if fresh["base_state_hash"] != approved_preview.get("base_state_hash") else "PATCH_MISMATCH"
        fresh["conflicts"].insert(0, _notice(code, "live spreadsheet state or normalized patch differs from the approved preview — re-run preview and re-approve"))
        fresh["status"] = "conflict"
        fresh["mutation_plan"]["will_write"] = False
        return fresh
    if fresh["status"] == "conflict":
        fresh["mutation_plan"]["will_write"] = False
        return fresh

    # 4. writes, in order: values.batchClear, values.batchUpdate RAW, then
    #    USER_ENTERED, then number formats. Stops at the first failure.
    changed = {w["op_id"] for w in fresh["mutation_plan"]["write_requests"]}
    changed_ops = [op for op in ops if op["op_id"] in changed]
    sheet_ids = {s["title"]: s["sheet_id"] for s in base_state["sheets"]}
    clears = [op["range"] for op in changed_ops if op["type"] == "clear_value"]
    groups: dict[str, list[dict]] = {"RAW": [], "USER_ENTERED": []}
    for op in changed_ops:
        if op["type"] in ("write_value", "write_formula"):
            groups[op["input_option"]].append({"range": op["range"], "values": _write_payload(op)})
    number_formats = [
        {"sheet_id": sheet_ids[op["sheet_title"]], "range": op["range"], "number_format": op["cells"][0]["desired"]["number_format"]}
        for op in changed_ops if op["type"] == "set_number_format"
    ]
    n_cells = lambda rng: parse_a1(rng).n_rows * parse_a1(rng).n_cols  # noqa: E731
    steps = []
    if clears:
        steps.append((METHOD_CLEAR, None, clears, lambda: transport.clear_values(fresh["spreadsheet_id"], clears)))
    for option in ("RAW", "USER_ENTERED"):
        if groups[option]:
            steps.append((METHOD_WRITE, option, [g["range"] for g in groups[option]],
                          lambda option=option: transport.write_values(fresh["spreadsheet_id"], groups[option], option)))
    if number_formats:
        steps.append((METHOD_NUMBER_FORMAT, None, [r["range"] for r in number_formats],
                      lambda: transport.set_number_formats(fresh["spreadsheet_id"], number_formats)))
    duplicate_op = next((op for op in changed_ops if op["type"] == "duplicate_sheet"), None)
    if duplicate_op is not None:
        so = duplicate_op["sheet_operation"]
        steps.append((METHOD_DUPLICATE, None, [duplicate_op["range"]],
                      lambda: transport.duplicate_sheet(fresh["spreadsheet_id"], base_state["source_snapshot"]["sheet_id"],
                                                        so["new_sheet_title"], base_state["insert_index"])))
    sent, updated_cells, write_error, created = [], 0, None, None
    for method_name, option, ranges, call in steps:
        try:
            resp = call()
        except GoogleSheetsError as e:
            write_error = e
            break
        sent.append({"method": method_name, "value_input_option": option, "ranges": ranges})
        if method_name == METHOD_DUPLICATE:
            created = resp
        else:
            updated_cells += resp["updated_cells"] if method_name == METHOD_WRITE else sum(n_cells(r) for r in ranges)
    applied_at = clock()
    fresh["applied"] = {"applied_at": applied_at, "write_requests_sent": sent, "updated_cells": updated_cells}
    if duplicate_op is not None:
        fresh["applied"]["created_sheet"] = created
    problem = future_timestamp_problem(applied_at)
    if problem:
        fresh["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))

    # 5. re-read and verify.
    try:
        if duplicate_op is not None:
            fresh["verification"] = _verify_duplicate(transport, fresh["spreadsheet_id"], duplicate_op, base_state, created)
        else:
            fresh["verification"] = _verify(transport, fresh["spreadsheet_id"], ops, base_state)
    except GoogleSheetsError as e:
        fresh["errors"].append(_notice("VERIFICATION_UNAVAILABLE", f"post-write re-read failed: {e}"))
        fresh["verification"] = None

    if write_error is not None:
        partial = " (an earlier write request already succeeded — the sheet may be partially updated; see verification)" if sent else ""
        fresh["errors"].insert(0, _notice(write_error.code, f"write failed: {write_error}{partial}"))
        fresh["status"] = "error"
    elif fresh["verification"] is None:
        fresh["status"] = "error"
    elif all(fresh["verification"][k] for k in ("targets_match", "formulas_outside_patch_intact", "structure_preserved")):
        fresh["status"] = "success"
    else:
        fresh["conflicts"].append(_notice("VERIFICATION_FAILED", "post-write verification found differences — see verification"))
        fresh["status"] = "conflict"

    receipt_status = {"success": "success", "conflict": "partial", "error": "failed"}[fresh["status"]]
    fresh["receipt"] = build_receipt(
        receipt_id=f"gsheet-{patch['patch_id']}-{fresh['preview_hash'][:12]}",
        action=SKILL,
        client_id=client_id,
        executed_at=applied_at,
        input_payload={"operations": fresh["operations"], "preview_hash": fresh["preview_hash"]},
        approval_id=approval.get("approval_id"),
        status=receipt_status,
        effects=[build_effect(
            target=f"google_sheets:{fresh['spreadsheet_id']}",
            operation="+".join(dict.fromkeys(
                {METHOD_WRITE: "values_batch_update", METHOD_CLEAR: "values_batch_clear", METHOD_NUMBER_FORMAT: "number_format_repeat_cell",
                 METHOD_DUPLICATE: "duplicate_sheet"}[s["method"]]
                for s in sent
            )) or "none",
            before=fresh["before"] if duplicate_op is None else {"sheets": base_state["sheets"]},
            after=fresh["after"] if duplicate_op is None else {"created_sheet": created, "verification": fresh["verification"]},
            external_id=fresh["spreadsheet_id"],
            external_url=f"https://docs.google.com/spreadsheets/d/{fresh['spreadsheet_id']}",
        )],
        warnings=[w["message"] for w in fresh["warnings"]],
        errors=[e["message"] for e in fresh["errors"]],
    )
    return fresh
