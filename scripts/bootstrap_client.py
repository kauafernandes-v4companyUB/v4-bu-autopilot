#!/usr/bin/env python3
"""Scaffold a new client's canonical memory tree from templates/client/.

Usage:
    python scripts/bootstrap_client.py <client_id> --workspace /path/to/workspace
    python scripts/bootstrap_client.py <client_id>   # uses $V4_BU_WORKSPACE_ROOT

Never invents commercial data. Every generated file comes verbatim from
templates/client/ (schema-valid, unknown/null/empty values only), with
only "__CLIENT_ID__" / "__DISPLAY_NAME__" placeholders substituted.

Safety: a file that already exists and differs from what the template
would produce is never overwritten, even with --force. --force only
allows bootstrap to proceed past "client directory already exists" and
to (re)write files that are missing or byte-identical to the template
render — it never destroys real canonical data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = REPO_ROOT / "templates" / "client"

sys.path.insert(0, str(REPO_ROOT))
from scripts.lib.workspace import (  # noqa: E402
    WorkspaceError,
    resolve_workspace,
)


def render(text: str, client_id: str, display_name: str) -> str:
    return text.replace("__CLIENT_ID__", client_id).replace(
        "__DISPLAY_NAME__", display_name
    )


def iter_template_files():
    for path in sorted(TEMPLATE_ROOT.rglob("*")):
        if path.is_file():
            yield path.relative_to(TEMPLATE_ROOT)


def validate_json_if_applicable(path: Path) -> None:
    if path.suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            json.load(f)  # raises on invalid JSON


def bootstrap(client_id: str, workspace_root: str | None, display_name: str | None, force: bool) -> int:
    try:
        ws = resolve_workspace(required=True, override=workspace_root, create_if_missing=True)
    except WorkspaceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    display_name = display_name or client_id
    client_dir = ws.client_dir(client_id)
    already_existed = client_dir.is_dir()

    if already_existed and not force:
        print(
            f"ERROR: {client_dir} already exists. Re-run with --force to "
            f"fill in only missing/untouched files (existing customized "
            f"files are never overwritten).",
            file=sys.stderr,
        )
        return 1

    written, skipped_existing, protected, validated = [], [], [], []

    for rel_path in iter_template_files():
        if rel_path.name == ".gitkeep":
            dest = client_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_text("")
                written.append(str(rel_path))
            continue

        src = TEMPLATE_ROOT / rel_path
        dest = client_dir / rel_path
        rendered = render(src.read_text(encoding="utf-8"), client_id, display_name)

        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            existing = dest.read_text(encoding="utf-8")
            if existing == rendered:
                skipped_existing.append(str(rel_path))
            else:
                protected.append(str(rel_path))
            continue

        dest.write_text(rendered, encoding="utf-8")
        written.append(str(rel_path))

    # also ensure quarters/ and history/ exist even if template had no
    # other files there yet
    (client_dir / "quarters").mkdir(parents=True, exist_ok=True)
    (client_dir / "history").mkdir(parents=True, exist_ok=True)

    for rel_path in written:
        dest = client_dir / rel_path
        try:
            validate_json_if_applicable(dest)
            validated.append(rel_path)
        except json.JSONDecodeError as e:
            print(f"ERROR: generated file is not valid JSON: {dest} ({e})", file=sys.stderr)
            return 3

    print(f"V4 BU AUTOPILOT — bootstrap client '{client_id}'")
    print(f"Workspace: {ws.root}")
    print(f"Client dir: {client_dir}")
    print()
    print(f"Written ({len(written)}):")
    for p in written:
        print(f"  + {p}")
    if skipped_existing:
        print(f"Already present, identical to template ({len(skipped_existing)}):")
        for p in skipped_existing:
            print(f"  = {p}")
    if protected:
        print(f"PROTECTED — existing content differs from template, NOT overwritten ({len(protected)}):")
        for p in protected:
            print(f"  ! {p}")
    print()
    print(f"JSON validated: {len(validated)}/{len(written)} newly written files")
    print("Done." if not protected else "Done, with protected files left untouched (see above).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", help="lowercase, hyphen/underscore-safe client id, e.g. 'acme'")
    parser.add_argument("--workspace", default=None, help="workspace root (default: $V4_BU_WORKSPACE_ROOT)")
    parser.add_argument("--display-name", default=None, help="human display name (default: client_id)")
    parser.add_argument("--force", action="store_true", help="proceed even if client dir already exists")
    args = parser.parse_args()

    if not args.client_id or "/" in args.client_id or ".." in args.client_id:
        print("ERROR: invalid client_id", file=sys.stderr)
        return 2

    return bootstrap(args.client_id, args.workspace, args.display_name, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
