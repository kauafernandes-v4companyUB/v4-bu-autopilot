#!/usr/bin/env python3
"""Operator CLI for skills/export-creative-performance-to-google-sheet/SKILL.md.

    python scripts/creative_performance_sheet_export.py dry-run --client <id> [--client <id> ...] | --report <path> ...
    python scripts/creative_performance_sheet_export.py preview --request request.json [--out preview.json]
    python scripts/creative_performance_sheet_export.py approve --preview preview.json --approved-by <operador> [--approval-id ID]
    python scripts/creative_performance_sheet_export.py apply   --request request.json --preview preview.json --approval approval.json

`dry-run` is local only: it loads the scoped creative-performance.json
reports and plans the five managed tabs against an EMPTY sheet — no
transport, no destination, no Google call. `preview` reads the declared BU
destination (<workspace>/bu/sources.json) and never writes. `approve`
records an EXPLICIT operator approval of one preview (hash-locked).
`apply` re-plans, refuses on any drift and delegates the write to
update-google-sheet. Outputs default to
<workspace>/context/generated/bu/google-sheets/creative-performance-export/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from scripts.lib import approval as ap  # noqa: E402
from scripts.lib import creative_performance_sheet_export as ex  # noqa: E402
from scripts.lib.exec_clock import utc_now_rfc3339  # noqa: E402
from scripts.lib.google_sheets_patch import build_patch_approval_candidate  # noqa: E402
from scripts.lib.google_sheets_sources import BU_SCOPE_ID, load_bu_sources  # noqa: E402
from scripts.lib.workspace import require_workspace  # noqa: E402


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(result: dict, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {target}")
    print(json.dumps({k: result.get(k) for k in ("mode", "status", "phase", "summary", "tabs_to_create", "headers_to_create", "preview_hash")}
                     | {"conflicts": [c["code"] for c in result.get("conflicts", [])], "errors": [e["code"] for e in result.get("errors", [])]},
                     ensure_ascii=False, indent=2))


def cmd_dry_run(args, ws) -> int:
    scope = {k: v for k, v in (("client_ids", args.client), ("report_paths", args.report)) if v}
    loaded, errors = ex.load_reports(ws.root, ex.discover_reports(ws.root, scope), report_validator=_validator(ex.REPORT_SCHEMA_PATH))
    rows = {t["key"]: [] for t in ex.TABS}
    for r in loaded:
        for k, v in ex.report_rows(r["ref"], r["report"]).items():
            rows[k] += v
    exported = {(r["ref"]["client_id"], r["ref"]["creative_id"]) for r in loaded}
    plans = {t["key"]: ex.plan_tab(t, None, rows[t["key"]], exported, None) for t in ex.TABS}
    print(json.dumps({"mode": "dry-run (local, empty sheet, no Google)", "reports": [r["ref"] for r in loaded],
                      "errors": errors, "inserts": {k: len(p["inserts"]) for k, p in plans.items()},
                      "conflicts": [c for p in plans.values() for c in p["conflicts"]]}, ensure_ascii=False, indent=2))
    return 0 if not errors and not any(p["conflicts"] for p in plans.values()) else 1


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap_.add_argument("--workspace", default=None)
    sub = ap_.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dry-run")
    p.add_argument("--client", action="append", default=[])
    p.add_argument("--report", action="append", default=[])
    for name in ("preview", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--request", required=True)
        p.add_argument("--out", default=None)
        if name == "apply":
            p.add_argument("--preview", required=True)
            p.add_argument("--approval", required=True)
    p = sub.add_parser("approve", help="record an EXPLICIT operator approval of one export preview")
    p.add_argument("--preview", required=True)
    p.add_argument("--approved-by", required=True)
    p.add_argument("--approval-id", default=None)
    p.add_argument("--out", default=None)
    args = ap_.parse_args(argv)
    ws = require_workspace(args.workspace)
    if args.cmd == "dry-run":
        return cmd_dry_run(args, ws)
    out_dir = ws.generated_dir / BU_SCOPE_ID / "google-sheets" / "creative-performance-export"
    if args.cmd == "approve":
        preview = _load(args.preview)
        pv = preview.get("patch_preview") or {}
        now = utc_now_rfc3339()
        candidate = build_patch_approval_candidate(pv, approval_id=args.approval_id or f"appr-{pv.get('patch_id')}", created_at=now,
                                                   preview_path=Path(args.preview).name)
        record = ap.apply_operator_decision(candidate, approved_at=now, approved_by=args.approved_by, approve_item_ids=[pv["patch_id"]])
        target = Path(args.out) if args.out else Path(args.preview).with_name(f"{pv['patch_id']}-approval.json")
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"approval {record['approval_id']} ({record['status']}) written: {target}")
        return 0
    from scripts.lib.google_sheets_auth import build_real_transport  # optional Google dependencies, loaded only here

    request = _load(args.request)
    errors = [f"{list(e.path)}: {e.message}" for e in _validator(ex.INPUT_SCHEMA_PATH).iter_errors(request)]
    if errors:
        print("invalid request:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    common = dict(workspace_root=ws.root, request=request, bu_sources=load_bu_sources(ws.root), report_validator=_validator(ex.REPORT_SCHEMA_PATH))
    if args.cmd == "preview":
        result = ex.preview_export(build_real_transport(), **common)
        _emit(result, Path(args.out) if args.out else out_dir / f"{request['export_id']}-{result['phase'] or 'none'}-preview.json")
    else:
        result = ex.apply_export(build_real_transport(), approved_export_preview=_load(args.preview), approval=_load(args.approval), **common)
        _emit(result, Path(args.out) if args.out else out_dir / f"{request['export_id']}-{result['phase'] or 'none'}-apply.json")
    return 0 if result["status"] in ("success", "no_change") else 1


if __name__ == "__main__":
    raise SystemExit(main())
