"""operational-playbook: project approved Autopilot actions onto the period's
playbook tab (skills/operational-playbook/SKILL.md).

Sections (each a bounded 4-column block: statement, date, reference, status):
  CONFIRMED_ACTION             tasks, scheduled/approved operations, active decisions,
                               seasonal items explicitly approved
  RECOMMENDATION               seasonal PLANNING_RECOMMENDATION not approved
  CLIENT_CONFIRMATION_REQUIRED seasonal CLIENT_CONFIRMATION_REQUIRED
  DEPENDENCY                   deferred operations
  DECISION_REQUIRED            decision_pending operations
A recommendation never becomes a confirmed action (or a task) silently.

Dates come only from a task due_at, an operation scheduled_for, or an
explicit ISO date on an item; anything else ("last week of the month")
stays empty. Lifecycle: duplicate the template tab once (stable target
title, identity proven by the persisted duplicate receipt), then patch the
content; each is a separate update-google-sheet preview/approval/apply.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from scripts.lib import sheet_modules as sh
from scripts.lib.a1_notation import parse_a1

MODULE = "operational-playbook"
SECTIONS = ("CONFIRMED_ACTION", "RECOMMENDATION", "CLIENT_CONFIRMATION_REQUIRED", "DEPENDENCY", "DECISION_REQUIRED")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _date(value) -> str:
    return value if isinstance(value, str) and ISO_DATE.match(value) else ""


def collect_items(client_dir: Path, quarter_id: str, seasonal_items: Iterable[dict] = (),
                  approved_recommendation_ids: Iterable[str] = ()) -> list[dict]:
    """Canonical (and explicitly approved) items, each classified into exactly one section."""
    approved = set(approved_recommendation_ids)
    items = []
    for t in (_load(client_dir / "tasks.json") or {}).get("tasks", []):
        if t.get("quarter_id") == quarter_id and t["status"] in ("pending", "completed"):
            items.append({"section": "CONFIRMED_ACTION", "statement": t["title"], "date": _date(t.get("due_at")),
                          "reference": t["task_id"], "status": t["status"]})
    for o in (_load(client_dir / "operations.json") or {}).get("operations", []):
        if o.get("quarter_id") != quarter_id:
            continue
        kind, status = o.get("type"), o.get("status")
        if kind == "scheduled" and status in ("scheduled", "completed"):
            items.append({"section": "CONFIRMED_ACTION", "statement": o["statement"], "date": _date(o.get("scheduled_for")),
                          "reference": o["operation_id"], "status": status})
        elif kind == "external_approved" and status == "approved":
            items.append({"section": "CONFIRMED_ACTION", "statement": o["statement"], "date": "", "reference": o["operation_id"],
                          "status": "approved, waiting execution channel"})
        elif kind == "decision_pending" and status in ("pending", "active"):
            items.append({"section": "DECISION_REQUIRED", "statement": o["statement"], "date": "", "reference": o["operation_id"], "status": status})
        elif kind == "deferred" and status == "deferred":
            gate = (o.get("deferred_until") or {}).get("description") or ""
            items.append({"section": "DEPENDENCY", "statement": o["statement"], "date": "", "reference": o["operation_id"],
                          "status": f"deferred: {gate}".strip(": ")})
    for d in (_load(client_dir / "decisions.json") or {}).get("decisions", []):
        if d.get("status") == "active":
            items.append({"section": "CONFIRMED_ACTION", "statement": d["statement"], "date": _date(d.get("effective_date")),
                          "reference": d["decision_id"], "status": "decided"})
    for s in seasonal_items:
        cls, sid = s.get("classification"), s["element_id"]
        if cls == "PLANNING_RECOMMENDATION":
            section = "CONFIRMED_ACTION" if sid in approved else "RECOMMENDATION"
        elif cls == "CLIENT_CONFIRMATION_REQUIRED":
            section = "CLIENT_CONFIRMATION_REQUIRED"
        elif cls == "CONFIRMED_OPERATIONAL_DECISION":
            section = "CONFIRMED_ACTION"
        else:
            continue
        items.append({"section": section, "statement": s["statement"], "date": _date(s.get("date")), "reference": sid,
                      "status": "approved recommendation" if section == "CONFIRMED_ACTION" and cls == "PLANNING_RECOMMENDATION" else cls.lower()})
    return items


def prepare(transport, *, client_dir: Path, client_id: str, items: list[dict]) -> dict:
    contract, sources_doc, problems = sh.load_contract(client_dir, client_id, MODULE)
    cfg = (contract or {}).get("playbook", {})
    target = cfg.get("target_tab", "unknown")
    dup_id = sh.safe_id("playbook", client_id, target, "duplicate")
    content_id = sh.safe_id("playbook", client_id, target, "content")
    if problems:
        return sh.business_result(MODULE, client_id, content_id, "CONFIG_REQUIRED", problems=problems)
    blocks = {name: parse_a1(rng) for name, rng in cfg["sections"].items()}
    bad = [n for n, b in blocks.items() if b.sheet_title != target or b.n_cols != 4]
    if bad:
        return sh.business_result(MODULE, client_id, content_id, "CONFIG_REQUIRED",
                                  problems=[sh.notice("SECTION_RANGE", f"sections {bad} must be 4-column blocks on {target!r}")])
    by_section = {s: [i for i in items if i["section"] == s] for s in SECTIONS}
    overflow = [s for s in SECTIONS if len(by_section[s]) > blocks[s].n_rows]
    if overflow:
        return sh.business_result(MODULE, client_id, content_id, "CONFIG_REQUIRED",
                                  problems=[sh.notice("SECTION_OVERFLOW", f"more items than rows in {overflow}; never truncated")])

    _, read_problems, tabs = sh.read_cells(transport, client_id=client_id, sources_doc=sources_doc, source_id=contract["source_id"],
                                           ranges=[f"'{cfg['template_tab']}'!A1"])
    if read_problems:
        return sh.business_result(MODULE, client_id, content_id, "CONFLICT_REVIEW_REQUIRED", problems=read_problems)
    suffixed = [t for t in tabs if t != target and (t.startswith(f"{target} (") or t in (f"Cópia de {target}", f"Copy of {target}"))]
    if suffixed:
        return sh.business_result(MODULE, client_id, content_id, "CONFLICT_REVIEW_REQUIRED",
                                  problems=[sh.notice("SUFFIXED_DUPLICATE", f"tabs {suffixed} look like extra copies of {target!r}; review manually")])
    duplicate_receipt = sh.find_receipt(client_dir, dup_id)
    if target not in tabs:
        if duplicate_receipt:
            return sh.business_result(MODULE, client_id, content_id, "CONFLICT_REVIEW_REQUIRED",
                                      problems=[sh.notice("TARGET_REMOVED", f"{target!r} was created by this module but no longer exists")])
        patch = sh.build_patch(patch_id=dup_id, client_id=client_id, source_id=contract["source_id"], module=MODULE,
                               operations=[{"op_id": "dup", "type": "duplicate_sheet", "source_sheet_title": cfg["template_tab"],
                                            "new_sheet_title": target}])
        return sh.preview_via_update_google_sheet(
            transport, module=MODULE, client_id=client_id, business_operation_id=dup_id, sources_doc=sources_doc, patch=patch,
            human_lines=lambda pv: [f"create sheet: YES ({cfg['template_tab']!r} -> {target!r})"], details={"phase": "duplicate"})
    if duplicate_receipt is None:
        return sh.business_result(MODULE, client_id, content_id, "CONFLICT_REVIEW_REQUIRED",
                                  problems=[sh.notice("TARGET_EXISTS_UNTRACKED", f"{target!r} exists but was not created by this module (no duplicate receipt); review manually")])

    header_ranges = [e["range"] for e in contract.get("header_expectations", [])]
    if header_ranges:
        cells, rp, _ = sh.read_cells(transport, client_id=client_id, sources_doc=sources_doc, source_id=contract["source_id"], ranges=header_ranges)
        conflicts = rp + sh.header_conflicts(cells, contract["header_expectations"])
        if conflicts:
            return sh.business_result(MODULE, client_id, content_id, "CONFLICT_REVIEW_REQUIRED", problems=conflicts)
    ops = []
    for s in SECTIONS:
        block = blocks[s]
        rows = [[i["statement"], i["date"], i["reference"], i["status"]] for i in by_section[s]]
        rows += [["", "", "", ""]] * (block.n_rows - len(rows))
        for ri, row in enumerate(rows):
            for ci, value in enumerate(row):
                ref = sh.cell_ref(target, block.start_row + ri, block.start_col + ci)
                op_id = f"{s.lower()}-r{ri + 1}c{ci + 1}"
                # an empty cell is an explicit clear (update-google-sheet contract), never a "" write
                ops.append({"op_id": op_id, "type": "clear_value", "range": ref} if value == "" else
                           {"op_id": op_id, "type": "write_value", "range": ref, "values": [[value]], "input_option": "RAW"})
    patch = sh.build_patch(patch_id=content_id, client_id=client_id, source_id=contract["source_id"], operations=ops, module=MODULE)
    patch["permissions"] = {"allow_clear": True}  # the module owns these blocks; clearing stale rows is declared, not implicit

    def human(_pv: dict) -> list[str]:
        lines = ["create sheet: NO (already created by this module)"]
        for s in SECTIONS:
            lines += [f"{s}: {i['statement']}" + (f" ({i['date']})" if i["date"] else " (no date)") for i in by_section[s]]
        return lines

    return sh.preview_via_update_google_sheet(transport, module=MODULE, client_id=client_id, business_operation_id=content_id,
                                              sources_doc=sources_doc, patch=patch, human_lines=human,
                                              details={"phase": "content", "sections": {s: len(by_section[s]) for s in SECTIONS},
                                                       "duplicate_receipt": duplicate_receipt["receipt_id"]})
