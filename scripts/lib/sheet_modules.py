"""Shared primitives of the Sheets business modules (metrics-sheet,
operational-playbook, creative-performance-export).

A business module only turns canonical Autopilot state into a patch
(schemas/google-sheet-patch.schema.json). Reading goes through the
read-google-sheet SOURCE (`read_google_sheet`); preview, approval, apply,
stale detection, post-write verification and the receipt are the
update-google-sheet ACTION (`preview_patch` / `apply_patch`). This module
never calls a transport method, an HTTP client or a Google API itself.

Business statuses: NO_CHANGE, PATCH_READY, CONFLICT_REVIEW_REQUIRED,
CONFIG_REQUIRED. The update-google-sheet receipt is the authority; it is
persisted unchanged in clients/<client_id>/receipts/ and the business
result only references it (no parallel ledger).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import approval as ap
from scripts.lib import canonical_action as ca
from scripts.lib.a1_notation import col_to_letters, letters_to_col, parse_a1  # noqa: F401 (re-exported for modules)
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import utc_now_rfc3339
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch
from scripts.lib.google_sheets_read import read_google_sheet
from scripts.lib.google_sheets_sources import SheetSourceError, load_client_sources, resolve_sheet_binding

NOT_AVAILABLE = "NOT_AVAILABLE"
CONTRACT_DIR = "sheet-contracts"


def notice(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def load_contract(client_dir: Path, client_id: str, module: str) -> tuple[Optional[dict], Optional[dict], list[dict]]:
    """Returns (contract, sources_doc, problems). Any problem means CONFIG_REQUIRED."""
    path = client_dir / CONTRACT_DIR / f"{module}.json"
    sources_doc = load_client_sources(client_dir)
    if not path.is_file():
        return None, sources_doc, [notice("CONTRACT_MISSING", f"clients/{client_id}/{CONTRACT_DIR}/{module}.json does not exist")]
    contract = json.loads(path.read_text(encoding="utf-8"))
    errs = ca.schema_errors(contract, "schemas/sheet-module-contract.schema.json")
    if errs:
        return None, sources_doc, [notice("CONTRACT_INVALID", "; ".join(errs[:3]))]
    if contract["client_id"] != client_id or contract["module"] != module:
        return None, sources_doc, [notice("CONTRACT_IDENTITY", "contract belongs to another client or module")]
    try:
        binding = resolve_sheet_binding(sources_doc, client_id, source_id=contract["source_id"])
    except SheetSourceError as e:
        return None, sources_doc, [notice(e.code, e.message)]
    if not binding.writable:
        return None, sources_doc, [notice("SOURCE_NOT_WRITABLE", f"source {contract['source_id']!r} is not declared writable")]
    return contract, sources_doc, []


def read_cells(transport, *, client_id: str, sources_doc: dict, source_id: str, ranges: list[str]) -> tuple[dict, list[dict], list[str]]:
    """Read through the read-google-sheet SOURCE. Returns
    ({'Tab'!A1: value}, problems, existing_tabs). Unreadable tabs are problems."""
    out = read_google_sheet(transport, client_id=client_id, sources_doc=sources_doc, ranges=ranges, source_id=source_id)
    problems = [notice(e["code"], e["message"]) for e in out["errors"]] + [notice(m["code"], m["message"]) for m in out["missing_data"]]
    cells: dict = {}
    for entry in out["ranges"]:
        a1 = parse_a1(entry["requested_range"])
        for ri, row in enumerate(entry["values"]):
            for ci, value in enumerate(row):
                cells[cell_ref(a1.sheet_title, a1.start_row + ri, a1.start_col + ci)] = value
    return cells, problems, [t["title"] for t in out["tabs"]]


def cell_ref(tab: str, row: int, col: int) -> str:
    """Always-quoted single-cell reference, the form contracts use."""
    return f"'{tab}'!{col_to_letters(col)}{row}"


def header_conflicts(cells: dict, expectations: list[dict]) -> list[dict]:
    return [notice("HEADER_MISMATCH", f"{e['range']} is {cells.get(e['range'])!r}, contract expects {e['value']!r} — the sheet structure changed")
            for e in expectations or [] if cells.get(e["range"]) != e["value"]]


def build_patch(*, patch_id: str, client_id: str, source_id: str, operations: list[dict], module: str, notes: Optional[str] = None) -> dict:
    return {"schema_version": "1.0.0", "patch_id": patch_id, "client_id": client_id, "source_id": source_id,
            "prepared_by": {"skill": module, "artifact_ref": None, "notes": notes}, "operations": operations}


def business_result(module: str, client_id: str, business_operation_id: str, status: str, *, human_preview=None, patch=None,
                    sheet_preview=None, problems=None, details=None) -> dict:
    return {"schema_version": "1.0.0", "skill": module, "client_id": client_id, "business_operation_id": business_operation_id,
            "generated_at": utc_now_rfc3339(), "status": status, "human_preview": human_preview or [],
            "patch": patch, "patch_hash": content_sha256(patch) if patch else None, "sheet_preview": sheet_preview,
            "problems": problems or [], "details": details or {}}


def preview_via_update_google_sheet(transport, *, module: str, client_id: str, business_operation_id: str, sources_doc: dict,
                                    patch: dict, human_lines: Callable[[dict], list[str]], details: Optional[dict] = None) -> dict:
    """Delegate the hash-bound preview to update-google-sheet and classify it."""
    sheet_pv = preview_patch(transport, client_id=client_id, patch=patch, sources_doc=sources_doc)
    status = {"success": "PATCH_READY", "no_change": "NO_CHANGE"}.get(sheet_pv["status"], "CONFLICT_REVIEW_REQUIRED")
    problems = [notice(n["code"], n["message"]) for n in sheet_pv["conflicts"] + sheet_pv["errors"]]
    return business_result(module, client_id, business_operation_id, status, human_preview=human_lines(sheet_pv) if status == "PATCH_READY" else [],
                           patch=patch, sheet_preview=sheet_pv, problems=problems, details=details)


def build_approval(business_preview: dict, *, approval_id: str, approved_by: str, created_at: str, approved_at: str) -> dict:
    """The operator approves the exact update-google-sheet preview (that
    ACTION's approval contract); the business module adds nothing to it."""
    sheet_pv = business_preview["sheet_preview"]
    cand = build_patch_approval_candidate(sheet_pv, approval_id=approval_id, created_at=created_at,
                                          preview_path=f"context/generated/{business_preview['client_id']}/{business_preview['skill']}/{business_preview['business_operation_id']}.json")
    return ap.apply_operator_decision(cand, approved_at=approved_at, approved_by=approved_by, approve_item_ids=[sheet_pv["patch_id"]])


def execute(transport, *, client_dir: Path, business_preview: dict, approval: Optional[dict]) -> dict:
    """update-google-sheet APPLY (gate, writes, verification, receipt), then
    persist that receipt in clients/<client_id>/receipts/ and return the
    business reference to it."""
    if business_preview["status"] == "NO_CHANGE":
        return {**business_preview, "status": "NO_CHANGE", "google_receipt_ref": None, "verification": None, "approval_ref": None}
    if business_preview["status"] != "PATCH_READY":
        return {**business_preview, "google_receipt_ref": None, "verification": None, "approval_ref": None}
    client_id = business_preview["client_id"]
    sources_doc = load_client_sources(client_dir)
    applied = apply_patch(transport, client_id=client_id, patch=business_preview["patch"], sources_doc=sources_doc,
                          approved_preview=business_preview["sheet_preview"], approval=approval)
    receipt = applied.get("receipt")
    ref = None
    if receipt:
        rel = f"receipts/{receipt['receipt_id']}.json"
        existing = client_dir / rel
        if not existing.is_file():
            ca.atomic_multi_write(client_dir, {rel: ca.serialize_json(receipt)})
        ref = f"clients/{client_id}/{rel}"
    status = {"success": "APPLIED", "no_change": "NO_CHANGE"}.get(applied["status"], "CONFLICT_REVIEW_REQUIRED")
    return {**business_preview, "status": status, "sheet_apply": applied, "google_receipt_ref": ref,
            "approval_ref": (approval or {}).get("approval_id"), "verification": applied.get("verification"),
            "problems": business_preview["problems"] + [notice(n["code"], n["message"]) for n in applied["conflicts"] + applied["errors"]]}


def find_receipt(client_dir: Path, patch_id: str) -> Optional[dict]:
    """The persisted update-google-sheet receipt of a successful apply of `patch_id`, if any."""
    d = client_dir / "receipts"
    for p in sorted(d.glob(f"gsheet-{patch_id}-*.json")) if d.is_dir() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("action") == "update-google-sheet" and r.get("status") == "success":
            return r
    return None


def safe_id(*parts: str) -> str:
    """patch_id-safe identifier from free text parts."""
    import re

    raw = "-".join(parts).lower()
    return re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-.") or "x"
