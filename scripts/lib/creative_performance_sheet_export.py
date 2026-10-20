"""Deterministic support for skills/export-creative-performance-to-google-sheet/SKILL.md.

An ACTION that projects final creative-performance.json reports (the source
of truth, produced by document-winning-creative) onto five MANAGED tabs of
one operational Google Sheet declared in the BU registry. The sheet is a
derived view: nothing is ever read back from it into a report.

It does not write anything itself. It only:

- loads exactly the reports the operator scoped (client_ids and/or explicit
  report paths) — JSON only, never the Markdown, never assets/CSV/frames;
- turns each report into rows (one creative row, one row per observed
  pattern, hypothesis, do-not-generalize item and source), keeping provided
  vs derived metrics, the original result type, hypotheses as hypotheses and
  absent values as EMPTY cells (never 0);
- reads the managed tabs and plans an idempotent upsert keyed by
  client_id + creative_id (+ item id): INSERT / UPDATE (report_sha256
  changed, with the cells that change) / NO_CHANGE; never deletes rows;
- emits a google-sheet patch for update-google-sheet — add_sheet for missing
  managed tabs first (structure phase), then header + row cells (content
  phase) — whose preview/approval/apply/verification is the existing
  hash-locked flow (scripts/lib/google_sheets_patch.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.a1_notation import col_to_letters, quote_sheet_title
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339
from scripts.lib.google_sheets_patch import apply_patch, preview_patch
from scripts.lib.google_sheets_sources import BU_SCOPE_ID, SheetSourceError, resolve_sheet_binding
from scripts.lib.google_sheets_transport import GoogleSheetsError, GoogleSheetsTransport

SKILL = "export-creative-performance-to-google-sheet"
SCHEMA_VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / SKILL
INPUT_SCHEMA_PATH = SKILL_DIR / "input.schema.json"
OUTPUT_SCHEMA_PATH = SKILL_DIR / "output.schema.json"
REPORT_SCHEMA_PATH = REPO_ROOT / "skills" / "document-winning-creative" / "output.schema.json"
REPORT_RELATIVE = re.compile(r"^context/generated/([a-z0-9][a-z0-9._-]{0,79})/creative-performance/([a-z0-9][a-z0-9._-]{0,79})/creative-performance\.json$")
DEFAULT_NEW_TAB_ROWS = 1000
NEW_TAB_ROW_HEADROOM = 200

# Managed layout. Titles are what the operator sees; keys are stable ids.
CREATIVE_METRIC_COLUMNS = (  # sheet column -> report metric_key(s)
    ("investimento", ("spend",)), ("impressoes", ("impressions",)), ("alcance", ("reach",)), ("frequencia", ("frequency",)),
    ("cliques", ("clicks",)), ("ctr_percent", ("ctr",)), ("cpc", ("cpc",)), ("cpm", ("cpm",)), ("mensagens", ("messages",)),
    ("custo_por_mensagem", ("cost_per_message",)), ("leads", ("leads",)), ("cpl", ("cpl",)), ("sql", ("sql",)), ("vendas", ("sales",)),
    ("custo_por_resultado", ("cost_per_result", "custo_por_resultado", "custo_por_resultados")),
)
TABS = (
    {"key": "creatives", "title": "CRIATIVOS CAMPEÕES", "key_columns": ("client_id", "creative_id"),
     "columns": ("client_id", "creative_id", "periodo_inicio", "periodo_fim", "origem_vencedor", "anuncio", "conjunto", "campanha",
                 "resultado_valor", "resultado_tipo_original", "resultado_rotulo")
                + tuple(c for c, _ in CREATIVE_METRIC_COLUMNS)
                + ("metricas_derivadas", "tipo_asset", "formato_orientacao", "duracao_segundos", "post_url", "avisos", "generated_at", "report_sha256")},
    {"key": "patterns", "title": "PADRÕES OBSERVADOS", "key_columns": ("client_id", "creative_id", "pattern_id"),
     "columns": ("client_id", "creative_id", "pattern_id", "dimensao", "descricao", "status", "fonte_evidencia", "referencia_asset",
                 "generated_at", "report_sha256")},
    {"key": "hypotheses", "title": "HIPÓTESES", "key_columns": ("client_id", "creative_id", "hypothesis_id"),
     "columns": ("client_id", "creative_id", "hypothesis_id", "classe", "hipotese", "confianca", "elementos_suporte", "teste_sugerido",
                 "generated_at", "report_sha256")},
    {"key": "do_not_generalize", "title": "NÃO GENERALIZAR", "key_columns": ("client_id", "creative_id", "item_id"),
     "columns": ("client_id", "creative_id", "item_id", "classe", "descricao", "elementos_relacionados", "generated_at", "report_sha256")},
    {"key": "sources", "title": "FONTES", "key_columns": ("client_id", "creative_id", "source_id"),
     "columns": ("client_id", "creative_id", "source_id", "tipo_fonte", "referencia", "sha256", "papel", "generated_at", "report_sha256")},
)
TAB_BY_KEY = {t["key"]: t for t in TABS}


class ExportError(ValueError):
    pass


def _notice(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **{k: v for k, v in extra.items() if v is not None}}


def _safe_relative(path: Optional[str]) -> Optional[str]:
    """A workspace-relative POSIX path, or None when it could leak a machine path."""
    if not isinstance(path, str) or not path or path.startswith(("/", "\\", "~")) or "\\" in path or re.match(r"^[A-Za-z]:", path):
        return None
    return None if ".." in path.split("/") else path


# ---------------------------------------------------------------------------
# reports -> rows
# ---------------------------------------------------------------------------


def discover_reports(workspace_root: Path, scope: dict) -> list[str]:
    """Workspace-relative report paths for the operator's scope. client_ids
    means every final report of those clients (explicit per-client request);
    report_paths are taken as given. Never a silent 'all clients'."""
    root = Path(workspace_root)
    paths: list[str] = []
    for cid in scope.get("client_ids") or []:
        if cid == BU_SCOPE_ID or not re.match(r"^[a-z0-9][a-z0-9._-]{0,79}$", cid):
            raise ExportError(f"invalid client_id {cid!r} in scope")
        base = root / "context" / "generated" / cid / "creative-performance"
        paths += sorted(p.relative_to(root).as_posix() for p in base.glob("*/creative-performance.json"))
    for p in scope.get("report_paths") or []:
        if p not in paths:
            paths.append(p)
    if not paths:
        raise ExportError("the scope selects no creative-performance.json report")
    return paths


def load_reports(workspace_root: Path, paths: list[str], *, report_validator=None) -> tuple[list[dict], list[dict]]:
    """[(ref, report)], errors. Reads ONLY the JSON reports."""
    root = Path(workspace_root)
    loaded, errors = [], []
    for rel in paths:
        m = REPORT_RELATIVE.match(rel or "")
        if not m:
            errors.append(_notice("INVALID_REPORT_PATH", f"{rel!r} is not context/generated/<client>/creative-performance/<creative>/creative-performance.json"))
            continue
        path = root / rel
        if not path.is_file():
            errors.append(_notice("REPORT_NOT_FOUND", f"{rel} does not exist"))
            continue
        raw = path.read_bytes()
        try:
            report = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            errors.append(_notice("INVALID_REPORT", f"{rel}: not valid UTF-8 JSON ({e})"))
            continue
        if report_validator is not None:
            bad = [f"{list(e.path)}: {e.message}" for e in sorted(report_validator.iter_errors(report), key=lambda e: list(e.path))]
            if bad:
                errors.append(_notice("INVALID_REPORT", f"{rel}: {bad[:3]}"))
                continue
        if (report.get("client_id"), report.get("creative_id")) != (m.group(1), m.group(2)):
            errors.append(_notice("CLIENT_ISOLATION", f"{rel}: report identity {report.get('client_id')}/{report.get('creative_id')} does not match its path"))
            continue
        loaded.append({"ref": {"client_id": report["client_id"], "creative_id": report["creative_id"], "path": rel,
                               "file_sha256": hashlib.sha256(raw).hexdigest(), "report_sha256": content_sha256(report)},
                       "report": report})
    keys = [(r["ref"]["client_id"], r["ref"]["creative_id"]) for r in loaded]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(_notice("DUPLICATE_REPORT_KEY", f"{k[0]}/{k[1]} is selected more than once"))
    return loaded, errors


def _metric_lookup(report: dict) -> dict[str, tuple[Any, str]]:
    """metric_key -> (value, PROVIDED_METRIC|DERIVED_METRIC); absent values are left out."""
    out: dict[str, tuple[Any, str]] = {}
    for m in report["provided_metrics"]:
        if m["value"] is not None:
            out[m["metric_key"]] = (m["value"], "PROVIDED_METRIC")
    for d in report["derived_metrics"]:
        out.setdefault(d["metric_key"], (d["value"], "DERIVED_METRIC"))
    return out


def _codes(warnings: list[str]) -> Optional[str]:
    codes = list(dict.fromkeys(w.split(":", 1)[0].strip() for w in warnings if w))
    return "; ".join(codes) or None


def report_rows(ref: dict, report: dict) -> dict[str, list[dict]]:
    """Rows per managed tab. None = empty cell (never 0)."""
    stamp = {"generated_at": report["generated_at"], "report_sha256": ref["report_sha256"]}
    ident = {"client_id": report["client_id"], "creative_id": report["creative_id"]}
    metrics = _metric_lookup(report)
    sel = (report.get("metric_row_selection") or {}).get("selected_row") or {}
    result = sel.get("result") or {}
    creative: dict[str, Any] = dict(ident)
    creative.update(periodo_inicio=report["period"]["start_date"], periodo_fim=report["period"]["end_date"],
                    origem_vencedor=report["winner_status"]["source"], anuncio=sel.get("ad_name"), conjunto=sel.get("ad_set_name"),
                    campanha=sel.get("campaign_name") or (report.get("campaign_context") or {}).get("campaign_name"),
                    resultado_valor=result.get("value"), resultado_tipo_original=result.get("source_result_type"),
                    resultado_rotulo=result.get("normalized_label"))
    derived_cols = []
    for col, keys in CREATIVE_METRIC_COLUMNS:
        hit = next((metrics[k] for k in keys if k in metrics), None)
        creative[col] = hit[0] if hit else None
        if hit and hit[1] == "DERIVED_METRIC":
            derived_cols.append(col)
    first = next((a for a in report["asset_metadata"] if a["status"] == "loaded"), report["asset_metadata"][0] if report["asset_metadata"] else None)
    fmt = " ".join(x for x in (first.get("orientation"), first.get("aspect_ratio")) if x) if first else None
    creative.update(metricas_derivadas=", ".join(derived_cols) or None, tipo_asset=first["kind"] if first else None,
                    formato_orientacao=fmt or None,
                    duracao_segundos=first.get("duration_seconds") if first and first["kind"] == "video" else None,
                    post_url=(report.get("post_reference") or {}).get("url"), avisos=_codes(report["warnings"]), **stamp)

    assets = {a["asset_id"]: a for a in report["asset_metadata"]}
    sources = {s["source_id"]: s for s in report["sources_used"]}
    patterns = []
    for e in report["observed_elements"]:
        if e["status"] != "OBSERVED":
            continue
        asset = assets.get(e.get("asset_id") or "")
        src = sources.get(asset["source_id"]) if asset else None
        patterns.append(dict(ident, pattern_id=e["element_id"], dimensao=e["dimension"], descricao=e["description"], status=e["status"],
                             fonte_evidencia=(f"{asset['source_id']} {Path(asset['path']).name}" if asset and src else None),
                             referencia_asset=" · ".join(x for x in (e.get("asset_id"), e.get("location")) if x) or None, **stamp))
    dims = {e["element_id"]: e["dimension"] for e in report["observed_elements"]}
    hypotheses = [dict(ident, hypothesis_id=h["id"], classe=h["learning_class"], hipotese=h["statement"], confianca=h["confidence"],
                       elementos_suporte=", ".join(f"{x} ({dims.get(x, '?')})" for x in h["based_on_elements"]),
                       teste_sugerido=h.get("test_suggestion"), **stamp) for h in report["replication_hypotheses"]]
    dng = [dict(ident, item_id=d["id"], classe=d["learning_class"], descricao=d["statement"],
                elementos_relacionados=", ".join(d.get("related_elements") or []) or None, **stamp) for d in report["do_not_generalize"]]
    sha_by_path = {a["path"]: a["sha256"] for a in report["asset_metadata"]}
    src_rows = [dict(ident, source_id=s["source_id"], tipo_fonte=s["kind"], referencia=_safe_relative(s["path"]),
                     sha256=sha_by_path.get(s["path"]), papel=s["used_for"], **stamp) for s in report["sources_used"]]
    return {"creatives": [creative], "patterns": patterns, "hypotheses": hypotheses, "do_not_generalize": dng, "sources": src_rows}


# ---------------------------------------------------------------------------
# upsert planning against the live managed tabs
# ---------------------------------------------------------------------------


def _blank(v: Any) -> bool:
    return v is None or v == ""


def _same(current: Any, desired: Any) -> bool:
    if _blank(current) and _blank(desired):
        return True
    if isinstance(current, (int, float)) and isinstance(desired, (int, float)) and not isinstance(current, bool) and not isinstance(desired, bool):
        return float(current) == float(desired)
    return current == desired


def _read_tab(transport: GoogleSheetsTransport, spreadsheet_id: str, sheet: dict, tab: dict) -> list[list]:
    last = col_to_letters(len(tab["columns"]))
    [block] = transport.read_values(spreadsheet_id, [f"{quote_sheet_title(tab['title'])}!A1:{last}{sheet['row_count']}"])
    return block["values"]


def plan_tab(tab: dict, grid: Optional[list[list]], desired_rows: list[dict], exported_reports: set[tuple[str, str]],
             sheet_meta: Optional[dict]) -> dict:
    """Pure planning for one managed tab. grid None = tab does not exist yet."""
    cols, keys = tab["columns"], tab["key_columns"]
    n = len(cols)
    plan = {"key": tab["key"], "title": tab["title"], "exists": grid is not None, "header": None, "inserts": [], "updates": [],
            "no_changes": [], "orphans": [], "conflicts": [], "warnings": [], "cells": [], "last_row_needed": 1}
    grid = [list(r[:n]) + [None] * (n - len(r[:n])) for r in (grid or [])]
    header = grid[0] if grid else [None] * n
    data = grid[1:]
    has_data = any(not _blank(v) for r in data for v in r)
    if all(_blank(v) for v in header):
        if has_data:
            plan["conflicts"].append(_notice("SCHEMA_MISMATCH", f"{tab['title']}: data rows exist below an empty header — not writing"))
            return plan
        plan["header"] = "create"
        plan["cells"].append({"row": 1, "values": list(cols)})
    elif [str(v) if not _blank(v) else "" for v in header] != list(cols):
        plan["conflicts"].append(_notice("SCHEMA_MISMATCH", f"{tab['title']}: header differs from the managed layout {list(cols)} — not reorganizing an existing sheet"))
        return plan
    else:
        plan["header"] = "ok"

    existing: dict[tuple, int] = {}
    last_used = 1
    key_idx = [cols.index(k) for k in keys]
    for i, row in enumerate(data, start=2):
        if all(_blank(v) for v in row):
            continue
        last_used = i
        key = tuple(row[j] for j in key_idx)
        if any(_blank(k) for k in key):
            plan["conflicts"].append(_notice("CORRUPTED_KEY", f"{tab['title']} row {i}: managed row without a complete key {list(keys)}", row=i))
            continue
        key = tuple(str(k) for k in key)
        if key in existing:
            plan["conflicts"].append(_notice("DUPLICATE_LOGICAL_KEY", f"{tab['title']}: key {list(key)} appears in rows {existing[key]} and {i}", row=i))
            continue
        existing[key] = i
    if plan["conflicts"]:
        return plan

    sha_col = cols.index("report_sha256")
    next_row = last_used + 1
    desired_keys = set()
    for rec in desired_rows:
        key = tuple(str(rec[k]) for k in keys)
        desired_keys.add(key)
        values = [rec.get(c) for c in cols]
        for c, v in zip(cols, values):
            if isinstance(v, str) and v.startswith("="):
                plan["conflicts"].append(_notice("UNSAFE_CELL_TEXT", f"{tab['title']} {list(key)} column {c!r} starts with '=' and would be read as a formula"))
        if key not in existing:
            plan["inserts"].append({"key": list(key), "row": next_row})
            plan["cells"].append({"row": next_row, "values": values, "mode": "insert"})
            next_row += 1
            continue
        row_no = existing[key]
        current = data[row_no - 2]
        if _same(current[sha_col], rec["report_sha256"]):
            plan["no_changes"].append({"key": list(key), "row": row_no})
            if any(not _same(a, b) for a, b in zip(current, values)):
                plan["warnings"].append(_notice("MANAGED_CELLS_EDITED", f"{tab['title']} row {row_no}: cells differ from the report although report_sha256 is unchanged — left as is", row=row_no))
            continue
        changed = [{"column": c, "before": current[j], "after": values[j]} for j, c in enumerate(cols) if not _same(current[j], values[j])]
        plan["updates"].append({"key": list(key), "row": row_no, "cells_changed": changed})
        plan["cells"].append({"row": row_no, "values": values, "mode": "update", "current": current})
    for key, row_no in existing.items():
        if (key[0], key[1]) in exported_reports and key not in desired_keys:
            plan["orphans"].append({"key": list(key), "row": row_no})
            plan["warnings"].append(_notice("ORPHAN_ROW", f"{tab['title']} row {row_no}: {list(key)} is no longer in its report — kept (rows are never deleted)", row=row_no))
    plan["last_row_needed"] = max([1] + [c["row"] for c in plan["cells"]])
    if sheet_meta is not None and (plan["last_row_needed"] > sheet_meta["row_count"] or n > sheet_meta["column_count"]):
        plan["conflicts"].append(_notice("GRID_TOO_SMALL", f"{tab['title']}: needs {plan['last_row_needed']} rows × {n} columns, tab has "
                                                           f"{sheet_meta['row_count']} × {sheet_meta['column_count']} — growing a grid is structural and not automated"))
    return plan


def _runs(values: list, wanted: Callable[[int], bool]) -> list[tuple[int, int]]:
    """Contiguous [start, end] column indexes (0-based, inclusive) where wanted(i)."""
    out, start = [], None
    for i in range(len(values) + 1):
        if i < len(values) and wanted(i):
            start = i if start is None else start
        elif start is not None:
            out.append((start, i - 1))
            start = None
    return out


def content_operations(tab: dict, plan: dict) -> tuple[list[dict], bool]:
    """update-google-sheet operations for one tab: header, inserted rows
    (non-empty runs only — empty stays empty) and updated rows (changed runs;
    values that became absent are cleared, never written as 0 or '')."""
    q = quote_sheet_title(tab["title"])
    ops, clears = [], False
    for cell in plan["cells"]:
        values, row = cell["values"], cell["row"]
        current = cell.get("current")
        if cell.get("mode") == "update":
            write = lambda i: not _blank(values[i]) and not _same(current[i], values[i])  # noqa: E731
            clear = lambda i: _blank(values[i]) and not _blank(current[i])  # noqa: E731
        else:
            write = lambda i: not _blank(values[i])  # noqa: E731
            clear = lambda i: False  # noqa: E731
        for a, b in _runs(values, write):
            ops.append({"op_id": f"{tab['key']}-r{row}-{col_to_letters(a + 1)}", "type": "write_value", "input_option": "RAW",
                        "range": f"{q}!{col_to_letters(a + 1)}{row}:{col_to_letters(b + 1)}{row}", "values": [values[a:b + 1]]})
        for a, b in _runs(values, clear):
            clears = True
            ops.append({"op_id": f"{tab['key']}-r{row}-{col_to_letters(a + 1)}-clear", "type": "clear_value",
                        "range": f"{q}!{col_to_letters(a + 1)}{row}:{col_to_letters(b + 1)}{row}"})
    return ops, clears


# ---------------------------------------------------------------------------
# preview / apply
# ---------------------------------------------------------------------------


def _base(mode: str, request: dict, generated_at: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "skill": SKILL, "mode": mode, "export_id": request.get("export_id"), "generated_at": generated_at,
            "status": "error", "phase": None, "destination": None, "reports": [], "tabs": [], "summary": None, "changes": [],
            "tabs_to_create": [], "headers_to_create": [], "patch": None, "patch_preview": None, "base_state_hash": None,
            "preview_hash": None, "apply_result": None, "post_apply": None, "conflicts": [], "warnings": [], "errors": []}


def _plan_export(transport, workspace_root, request, bu_sources, *, report_validator, mode, clock):
    out = _base(mode, request, clock())
    problem = future_timestamp_problem(out["generated_at"])
    if problem:
        out["warnings"].append(_notice("EXECUTION_TIMESTAMP_IN_FUTURE", problem))
    dest = request.get("destination") or {}
    try:
        binding = resolve_sheet_binding(bu_sources, BU_SCOPE_ID, source_id=dest.get("source_id"), spreadsheet_locator=dest.get("spreadsheet_id"))
    except SheetSourceError as e:
        out["errors"].append(_notice(e.code, e.message))
        return out, None
    out["destination"] = {"source_id": binding.source_id, "spreadsheet_id": binding.spreadsheet_id, "spreadsheet_title": None}
    if binding.registry_scope != "bu" or binding.scope != "bu" or not binding.allowed_client_ids or not binding.writable:
        out["errors"].append(_notice("DESTINATION_NOT_ALLOWED", "the destination must be a writable scope 'bu' entry of the BU registry with allowed_client_ids"))
        return out, None
    try:
        paths = discover_reports(workspace_root, request.get("scope") or {})
    except ExportError as e:
        out["errors"].append(_notice("INVALID_SCOPE", str(e)))
        return out, None
    loaded, errs = load_reports(workspace_root, paths, report_validator=report_validator)
    out["errors"] += errs
    scoped = set((request.get("scope") or {}).get("client_ids") or [])
    for r in loaded:
        cid = r["ref"]["client_id"]
        if scoped and cid not in scoped:
            out["errors"].append(_notice("CLIENT_ISOLATION", f"{r['ref']['path']} belongs to {cid!r}, outside scope.client_ids"))
        if cid not in binding.allowed_client_ids:
            out["errors"].append(_notice("CLIENT_NOT_ALLOWED", f"client {cid!r} is not in the destination's allowed_client_ids"))
    out["reports"] = [r["ref"] for r in loaded]
    if out["errors"]:
        return out, None

    try:
        meta = transport.get_spreadsheet_metadata(binding.spreadsheet_id)
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out, None
    out["destination"]["spreadsheet_title"] = meta["title"]
    if meta["spreadsheet_id"] != binding.spreadsheet_id or (binding.expected_title is not None and meta["title"] != binding.expected_title):
        out["errors"].append(_notice("WRONG_SPREADSHEET", f"spreadsheet {meta['spreadsheet_id']!r} titled {meta['title']!r} does not match the declared destination"))
        return out, None

    rows = {t["key"]: [] for t in TABS}
    for r in loaded:
        for k, v in report_rows(r["ref"], r["report"]).items():
            rows[k] += v
    exported = {(r["ref"]["client_id"], r["ref"]["creative_id"]) for r in loaded}
    sheets = {s["title"]: s for s in meta["sheets"]}
    plans = []
    try:
        for tab in TABS:
            sheet = sheets.get(tab["title"])
            grid = _read_tab(transport, binding.spreadsheet_id, sheet, tab) if sheet else None
            plans.append((tab, plan_tab(tab, grid, rows[tab["key"]], exported, sheet)))
    except GoogleSheetsError as e:
        out["errors"].append(_notice(e.code, str(e)))
        return out, None

    missing = [tab for tab, p in plans if not p["exists"]]
    out["tabs"] = [{"key": p["key"], "title": p["title"], "exists": p["exists"], "header": p["header"], "inserts": len(p["inserts"]),
                    "updates": len(p["updates"]), "no_changes": len(p["no_changes"]), "orphans": len(p["orphans"])} for _, p in plans]
    out["summary"] = {"reports": len(loaded), "basis": "planned_after_structure" if missing else "live",
                      **{kind: {p["key"]: len(p[kind]) for _, p in plans} for kind in ("inserts", "updates", "no_changes", "orphans")}}
    out["changes"] = [{"tab": p["key"], "action": "INSERT", "key": x["key"], "row": x["row"]} for _, p in plans for x in p["inserts"]] + \
                     [{"tab": p["key"], "action": "UPDATE", "key": x["key"], "row": x["row"], "cells_changed": x["cells_changed"]} for _, p in plans for x in p["updates"]]
    out["tabs_to_create"] = [t["title"] for t in missing]
    out["headers_to_create"] = [p["title"] for _, p in plans if p["header"] == "create"]
    for _, p in plans:
        out["conflicts"] += p["conflicts"]
        out["warnings"] += p["warnings"]
    if out["conflicts"]:
        out["status"] = "conflict"
        return out, None

    data_clients = sorted({r["ref"]["client_id"] for r in loaded})
    patch_base = {"schema_version": "1.0.0", "client_id": BU_SCOPE_ID, "source_id": binding.source_id,
                  "spreadsheet_id": binding.spreadsheet_id, "prepared_by": SKILL, "data_client_ids": data_clients}
    if missing:
        out["phase"] = "structure"
        patch = dict(patch_base, patch_id=f"cpx-{request['export_id']}-structure", operations=[
            {"op_id": f"add-{t['key']}", "type": "add_sheet", "new_sheet_title": t["title"], "frozen_row_count": 1,
             "row_count": max(DEFAULT_NEW_TAB_ROWS, 1 + len(rows[t["key"]]) + NEW_TAB_ROW_HEADROOM), "column_count": len(t["columns"])}
            for t in missing])
    else:
        out["phase"] = "content"
        ops, clears = [], False
        for tab, p in plans:
            o, c = content_operations(tab, p)
            ops += o
            clears = clears or c
        if not ops:
            out["status"] = "no_change"
            return out, None
        patch = dict(patch_base, patch_id=f"cpx-{request['export_id']}-content", operations=ops)
        if clears:
            patch["permissions"] = {"allow_clear": True}
    out["patch"] = patch
    return out, binding


def preview_export(transport: GoogleSheetsTransport, *, workspace_root: Path, request: dict, bu_sources: Optional[dict],
                   report_validator=None, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Zero writes. The underlying update-google-sheet preview carries the
    hash lock (base_state_hash/preview_hash) that the operator approves."""
    out, _ = _plan_export(transport, workspace_root, request, bu_sources, report_validator=report_validator, mode="preview", clock=clock)
    if out["patch"] is None:
        return out
    pv = preview_patch(transport, client_id=BU_SCOPE_ID, patch=out["patch"], sources_doc=bu_sources, clock=clock)
    out["patch_preview"] = pv
    out["base_state_hash"], out["preview_hash"] = pv["base_state_hash"], pv["preview_hash"]
    out["conflicts"] += pv["conflicts"]
    out["errors"] += pv["errors"]
    out["warnings"] += pv["warnings"]
    out["status"] = pv["status"]
    return out


def apply_export(transport: GoogleSheetsTransport, *, workspace_root: Path, request: dict, bu_sources: Optional[dict],
                 approved_export_preview: Optional[dict], approval: Optional[dict], report_validator=None,
                 clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Re-plans from the reports and the live sheet; refuses when any source
    report or the planned patch changed since the approved preview; then
    delegates to update-google-sheet apply (approval gate, drift check,
    writes, re-read verification) and re-plans once more to confirm."""
    out, _ = _plan_export(transport, workspace_root, request, bu_sources, report_validator=report_validator, mode="apply", clock=clock)
    prev = approved_export_preview or {}
    if not prev or prev.get("mode") != "preview" or prev.get("status") != "success" or not prev.get("patch"):
        out["errors"].insert(0, _notice("NO_PREVIEW", "apply requires the approved, successful export preview"))
        out["status"] = "error"
        return out
    if out["errors"]:
        out["status"] = "error"
        return out
    if prev.get("phase") == "structure" and out["phase"] != "structure" and not out["tabs_to_create"]:
        out["status"] = "no_change"  # the approved structure step is already in place: zero writes
        out["warnings"].append(_notice("STRUCTURE_ALREADY_PRESENT", "every managed tab already exists — run a new preview for the content phase"))
        return out
    if out["status"] == "no_change" and prev.get("phase") == "content":
        return out  # replay of an applied content step: desired state already holds, zero writes
    before = {(r["client_id"], r["creative_id"]): r for r in prev.get("reports", [])}
    now = {(r["client_id"], r["creative_id"]): r for r in out["reports"]}
    changed = sorted(f"{k[0]}/{k[1]}" for k in set(before) | set(now)
                     if (before.get(k) or {}).get("file_sha256") != (now.get(k) or {}).get("file_sha256"))
    if changed:
        out["conflicts"].insert(0, _notice("SOURCE_REPORT_CHANGED", f"report(s) changed since the approved preview: {changed} — re-run preview and re-approve"))
        out["status"] = "conflict"
        return out
    if out["patch"] != prev["patch"]:
        out["conflicts"].insert(0, _notice("STALE_PREVIEW", "the managed tabs or the planned patch changed since the approved preview — re-run preview and re-approve"))
        out["status"] = "conflict"
        return out
    result = apply_patch(transport, client_id=BU_SCOPE_ID, patch=out["patch"], sources_doc=bu_sources,
                         approved_preview=prev.get("patch_preview"), approval=approval, clock=clock)
    out["apply_result"] = result
    out["base_state_hash"], out["preview_hash"] = result.get("base_state_hash"), result.get("preview_hash")
    out["status"] = result["status"]
    out["conflicts"] += result["conflicts"]
    out["errors"] += result["errors"]
    if result["status"] == "success":
        after, _ = _plan_export(transport, workspace_root, request, bu_sources, report_validator=report_validator, mode="preview", clock=clock)
        out["post_apply"] = {"next_phase": after["phase"] if after["status"] != "no_change" else None, "status": after["status"],
                             "summary": after["summary"],
                             "content_converged": out["phase"] == "content" and after["status"] == "no_change"}
        if out["phase"] == "content" and after["status"] != "no_change":
            out["conflicts"].append(_notice("POST_APPLY_NOT_CONVERGED", "re-reading the sheet after apply does not give NO_CHANGE for every exported row"))
            out["status"] = "conflict"
    return out
