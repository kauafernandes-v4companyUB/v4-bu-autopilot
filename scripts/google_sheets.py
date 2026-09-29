#!/usr/bin/env python3
"""Google Sheets operator CLI (skills/read-google-sheet, skills/update-google-sheet).

    python scripts/google_sheets.py auth                      # one-time interactive OAuth login
    python scripts/google_sheets.py auth-status               # config check, never prints secrets
    python scripts/google_sheets.py read    --client <id> --source-id <sid> --range "'Tab'!A1:D20"
    python scripts/google_sheets.py preview --client <id> --patch patch.json
    python scripts/google_sheets.py approve --preview preview.json --approval-id <id> --approved-by <operator>
    python scripts/google_sheets.py apply   --client <id> --patch patch.json --preview preview.json --approval approval.json

    python scripts/google_sheets.py file-metadata <file_id>
    python scripts/google_sheets.py convert-xlsx <file_id> --name "..." [--folder <folder_id>] [--apply]
    python scripts/google_sheets.py copy-sheet   <file_id> --name "..." [--folder <folder_id>] [--apply]

Drive lifecycle commands (file-metadata / convert-xlsx / copy-sheet) only
resolve and create FILES; they plan by default and create a new file only
with --apply. They never modify, move or delete the original.

`approve` records an explicit operator decision — run it only when the
operator has explicitly approved that exact preview. `apply` is the only
command that writes to Google Sheets.

Client sources come from $V4_BU_WORKSPACE_ROOT/clients/<id>/sources.json;
outputs go to $V4_BU_WORKSPACE_ROOT/context/generated/<id>/google-sheets/
unless --out is given. Real spreadsheet ids never live in this repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import approval as ap  # noqa: E402
from scripts.lib.exec_clock import utc_now_rfc3339  # noqa: E402
from scripts.lib.google_drive_lifecycle import inspect_file, run_operation  # noqa: E402
from scripts.lib.google_sheets_auth import (  # noqa: E402
    build_real_drive_transport,
    build_real_transport,
    load_auth_config,
    run_oauth_login,
    token_scope_status,
)
from scripts.lib.google_sheets_patch import apply_patch, build_patch_approval_candidate, preview_patch  # noqa: E402
from scripts.lib.google_sheets_read import read_google_sheet  # noqa: E402
from scripts.lib.google_sheets_sources import load_client_sources  # noqa: E402
from scripts.lib.google_sheets_transport import GoogleSheetsError  # noqa: E402
from scripts.lib.workspace import require_workspace  # noqa: E402


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(result: dict, out: str | None, default_path: Path | None) -> None:
    target = Path(out) if out else default_path
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"written: {target}")
    summary = {k: result.get(k) for k in ("skill", "mode", "status", "patch_id", "preview_hash", "approval_id") if k in result}
    summary["errors"] = [e.get("code") for e in result.get("errors", [])] if isinstance(result.get("errors"), list) else result.get("errors")
    summary["conflicts"] = [c.get("code") for c in result.get("conflicts", [])] if "conflicts" in result else None
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _client_context(args) -> tuple[dict | None, Path]:
    ws = require_workspace(args.workspace)
    return load_client_sources(ws.client_dir(args.client)), ws.client_generated_dir(args.client) / "google-sheets"


def cmd_auth(args) -> int:
    path = run_oauth_login(load_auth_config())
    print(f"OAuth token stored outside the repository at: {path}")
    return 0


def cmd_auth_status(args) -> int:
    cfg = load_auth_config()
    print(json.dumps({
        "mode": cfg.mode,
        "client_secrets_configured": bool(cfg.client_secrets_path and cfg.client_secrets_path.is_file()),
        "token_present": bool(cfg.token_path and cfg.token_path.is_file()),
        "service_account_configured": bool(cfg.service_account_path and cfg.service_account_path.is_file()),
        **token_scope_status(cfg),
    }, indent=2))
    return 0


def cmd_file_metadata(args) -> int:
    result = inspect_file(build_real_drive_transport(), args.file_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


def _lifecycle(args, operation: str) -> int:
    result = run_operation(
        build_real_drive_transport(), operation=operation, source_file_id=args.file_id, name=args.name,
        destination_folder_id=args.folder, mode="apply" if args.apply else "plan",
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] in ("planned", "created", "no_change") else 1


def cmd_convert_xlsx(args) -> int:
    return _lifecycle(args, "convert_xlsx")


def cmd_copy_sheet(args) -> int:
    return _lifecycle(args, "copy_sheet")


def cmd_read(args) -> int:
    sources, out_dir = _client_context(args)
    result = read_google_sheet(
        build_real_transport(), client_id=args.client, sources_doc=sources, ranges=args.range,
        source_id=args.source_id, spreadsheet_locator=args.spreadsheet, include_formatted=args.formatted,
    )
    name = (args.source_id or "sheet") + "-read.json"
    _emit(result, args.out, out_dir / name)
    return 0 if result["status"] in ("success", "partial") else 1


def cmd_preview(args) -> int:
    sources, out_dir = _client_context(args)
    patch = _load_json(args.patch)
    result = preview_patch(build_real_transport(), client_id=args.client, patch=patch, sources_doc=sources)
    _emit(result, args.out, out_dir / f"{patch.get('patch_id', 'patch')}-preview.json")
    return 0 if result["status"] in ("success", "no_change") else 1


def cmd_approve(args) -> int:
    preview = _load_json(args.preview)
    now = utc_now_rfc3339()
    candidate = build_patch_approval_candidate(preview, approval_id=args.approval_id, created_at=now, preview_path=str(Path(args.preview).name))
    record = ap.apply_operator_decision(candidate, approved_at=now, approved_by=args.approved_by, approve_item_ids=[preview["patch_id"]])
    target = Path(args.out) if args.out else Path(args.preview).with_name(f"{preview['patch_id']}-approval.json")
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"approval {record['approval_id']} ({record['status']}) written: {target}")
    return 0


def cmd_apply(args) -> int:
    sources, out_dir = _client_context(args)
    patch = _load_json(args.patch)
    result = apply_patch(
        build_real_transport(), client_id=args.client, patch=patch, sources_doc=sources,
        approved_preview=_load_json(args.preview), approval=_load_json(args.approval),
    )
    _emit(result, args.out, out_dir / f"{patch.get('patch_id', 'patch')}-apply.json")
    return 0 if result["status"] in ("success", "no_change") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="interactive OAuth login (explicit operator step)").set_defaults(fn=cmd_auth)
    sub.add_parser("auth-status", help="show auth configuration state without secrets").set_defaults(fn=cmd_auth_status)

    def client_args(p):
        p.add_argument("--client", required=True)
        p.add_argument("--workspace", default=None)
        p.add_argument("--out", default=None)

    p = sub.add_parser("file-metadata", help="Drive metadata of one file id (mimeType: native Sheet vs .xlsx)")
    p.add_argument("file_id")
    p.set_defaults(fn=cmd_file_metadata)

    for cmd, fn, help_ in (
        ("convert-xlsx", cmd_convert_xlsx, "create a NEW native Google Sheet from an .xlsx (original untouched)"),
        ("copy-sheet", cmd_copy_sheet, "create a NEW copy of a native Google Sheet (original untouched)"),
    ):
        p = sub.add_parser(cmd, help=help_)
        p.add_argument("file_id")
        p.add_argument("--name", required=True)
        p.add_argument("--folder", default=None, help="destination folder id (optional)")
        p.add_argument("--apply", action="store_true", help="actually create the file (default: plan only)")
        p.add_argument("--out", default=None)
        p.set_defaults(fn=fn)

    p = sub.add_parser("read")
    client_args(p)
    p.add_argument("--source-id", default=None)
    p.add_argument("--spreadsheet", default=None, help="spreadsheet id or docs.google.com URL (must be declared in sources.json)")
    p.add_argument("--range", action="append", required=True)
    p.add_argument("--formatted", action="store_true")
    p.set_defaults(fn=cmd_read)

    p = sub.add_parser("preview")
    client_args(p)
    p.add_argument("--patch", required=True)
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("approve", help="record an EXPLICIT operator approval of one preview")
    p.add_argument("--preview", required=True)
    p.add_argument("--approval-id", required=True)
    p.add_argument("--approved-by", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("apply")
    client_args(p)
    p.add_argument("--patch", required=True)
    p.add_argument("--preview", required=True)
    p.add_argument("--approval", required=True)
    p.set_defaults(fn=cmd_apply)

    args = parser.parse_args()
    try:
        return args.fn(args)
    except GoogleSheetsError as e:
        print(f"{e.code}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
