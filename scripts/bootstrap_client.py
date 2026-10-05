#!/usr/bin/env python3
"""Scaffold a new client's canonical memory tree from templates/client/.

Usage:
    python scripts/bootstrap_client.py <client_id> --workspace /path/to/workspace
    python scripts/bootstrap_client.py <client_id>   # uses $V4_BU_WORKSPACE_ROOT

Never invents commercial data. Every generated file comes verbatim from
templates/client/ (schema-valid, unknown/null/empty values only), with
only "__CLIENT_ID__" / "__DISPLAY_NAME__" / "__BOOTSTRAP_TIMESTAMP__"
placeholders substituted. __BOOTSTRAP_TIMESTAMP__ is an execution
timestamp (CLAUDE.md section 26): the real UTC system clock at the moment
bootstrap writes the file — used where the canonical schema requires a
write timestamp (tasks.json.updated_at), never a fixed or inferred date.

Safety: a file that already exists and differs from what the template
would produce is never overwritten, even with --force. --force only
allows bootstrap to proceed past "client directory already exists" and
to (re)write files that are missing or byte-identical to the template
render — it never destroys real canonical data. The one exception is a file that
is byte-identical to a render of a PREVIOUS, known-invalid template
version (LEGACY_RENDERS) — i.e. never touched since bootstrap — which
--force upgrades to the current template.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = REPO_ROOT / "templates" / "client"

sys.path.insert(0, str(REPO_ROOT))
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339  # noqa: E402
from scripts.lib.workspace import (  # noqa: E402
    WorkspaceError,
    resolve_workspace,
)

TIMESTAMP_PLACEHOLDER = "__BOOTSTRAP_TIMESTAMP__"
_RFC3339_UTC = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"

# Renders of earlier template versions that were invalid against their
# canonical schema. A file still byte-identical to one of these was never
# touched after bootstrap, so --force may safely upgrade it.
LEGACY_RENDERS = {
    "tasks.json": [
        # updated_at: null violated schemas/task-ledger.schema.json (required date-time)
        '{\n  "schema_version": "1.0.0",\n  "client_id": "__CLIENT_ID__",\n  "updated_at": null,\n  "tasks": []\n}\n',
    ],
}


def render(text: str, client_id: str, display_name: str, timestamp: str | None = None) -> str:
    rendered = text.replace("__CLIENT_ID__", client_id).replace(
        "__DISPLAY_NAME__", display_name
    )
    if timestamp is not None:
        rendered = rendered.replace(TIMESTAMP_PLACEHOLDER, timestamp)
    return rendered


def matches_template(existing: str, template_render: str) -> bool:
    """True when `existing` equals the template render for any real
    bootstrap timestamp (template_render still holds the placeholder)."""
    if TIMESTAMP_PLACEHOLDER not in template_render:
        return existing == template_render
    pattern = re.escape(template_render).replace(re.escape(TIMESTAMP_PLACEHOLDER), _RFC3339_UTC)
    return re.fullmatch(pattern, existing) is not None


def is_legacy_render(rel_path: Path, existing: str, client_id: str, display_name: str) -> bool:
    return any(existing == render(t, client_id, display_name) for t in LEGACY_RENDERS.get(rel_path.as_posix(), []))


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

    written, skipped_existing, protected, validated, upgraded = [], [], [], [], []
    timestamp = utc_now_rfc3339()
    problem = future_timestamp_problem(timestamp)
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 4

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
        template_render = render(src.read_text(encoding="utf-8"), client_id, display_name)
        rendered = render(template_render, client_id, display_name, timestamp)

        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            existing = dest.read_text(encoding="utf-8")
            if matches_template(existing, template_render):
                skipped_existing.append(str(rel_path))
            elif force and is_legacy_render(rel_path, existing, client_id, display_name):
                dest.write_text(rendered, encoding="utf-8")
                written.append(str(rel_path))
                upgraded.append(str(rel_path))
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
        print(f"  + {p}" + ("  (upgraded from untouched legacy template render)" if p in upgraded else ""))
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


CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def _expected_files(client_id: str, display_name: str) -> dict[str, str]:
    """Template renders (timestamp placeholder kept) per relative path."""
    out = {}
    for rel_path in iter_template_files():
        src = TEMPLATE_ROOT / rel_path
        out[rel_path.as_posix()] = "" if rel_path.name == ".gitkeep" else render(src.read_text(encoding="utf-8"), client_id, display_name)
    return out


def _with_initial_sources(render_text: str, initial_sources: list[dict] | None) -> str:
    if not initial_sources:
        return render_text
    doc = json.loads(render_text)
    doc["sources"] = list(initial_sources)
    return json.dumps(doc, ensure_ascii=False, indent=2) + chr(10)


def bootstrap_client(
    client_id: str,
    *,
    display_name: str | None = None,
    workspace_root: str | None = None,
    initial_sources: list[dict] | None = None,
    initial_context: str | None = None,
) -> dict:
    """Single replicable bootstrap entry point (docs/workflows/new-client.md).

    Returns {"status": CREATED | NO_CHANGE | CONFLICT | ERROR, ...}. Never
    creates a Quarter, SMART, media plan, task, decision or evidence, and
    never overwrites an existing client: an existing client identical to the
    bootstrap render is NO_CHANGE, any other existing client is CONFLICT.
    `initial_sources` (declarations only) go to sources.json after schema
    validation; `initial_context` is operator text stored as RAW under
    private/clients/<client_id>/client-context/ for source intake — it never
    becomes canonical memory by existing.
    """
    if not isinstance(client_id, str) or not CLIENT_ID_RE.fullmatch(client_id):
        return {"status": "ERROR", "code": "INVALID_CLIENT_ID", "message": f"{client_id!r} must match {CLIENT_ID_RE.pattern}"}
    try:
        ws = resolve_workspace(required=True, override=workspace_root, create_if_missing=True)
    except WorkspaceError as e:
        return {"status": "ERROR", "code": "WORKSPACE", "message": str(e)}
    display_name = display_name or client_id
    client_dir = ws.client_dir(client_id)
    expected = _expected_files(client_id, display_name)
    expected["sources.json"] = _with_initial_sources(expected["sources.json"], initial_sources)
    if initial_sources:
        from scripts.lib import canonical_action as ca

        errs = ca.schema_errors(json.loads(expected["sources.json"]), "schemas/client-sources.schema.json")
        ids = [s.get("source_id") for s in initial_sources]
        if errs or len(ids) != len(set(ids)):
            return {"status": "ERROR", "code": "INVALID_INITIAL_SOURCES", "message": "; ".join(errs[:3]) or "duplicate source_id"}
    context_rel = Path("private") / "clients" / client_id / "client-context" / "initial-context.md"

    if client_dir.exists():
        present = {p.relative_to(client_dir).as_posix() for p in client_dir.rglob("*") if p.is_file()}
        diverged = sorted(rel for rel, text in expected.items()
                          if rel not in present or not matches_template((client_dir / rel).read_text(encoding="utf-8"), text))
        extra = sorted(present - set(expected))
        context_path = ws.root / context_rel
        if initial_context is not None and context_path.is_file() and context_path.read_text(encoding="utf-8") != initial_context:
            diverged.append(context_rel.as_posix())
        if diverged or extra:
            return {"status": "CONFLICT", "code": "CLIENT_EXISTS_DIVERGENT", "client_dir": str(client_dir),
                    "diverged": diverged, "extra": extra}
        return {"status": "NO_CHANGE", "client_dir": str(client_dir), "written": []}

    timestamp = utc_now_rfc3339()
    problem = future_timestamp_problem(timestamp)
    if problem:
        return {"status": "ERROR", "code": "FUTURE_TIMESTAMP", "message": problem}
    written = []
    for rel, text in expected.items():
        dest = client_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = text.replace(TIMESTAMP_PLACEHOLDER, timestamp)
        dest.write_text(content, encoding="utf-8")
        if dest.suffix == ".json":
            json.loads(content)
        written.append(rel)
    for rel in ("quarters", "history"):
        (client_dir / rel).mkdir(parents=True, exist_ok=True)
    if initial_context is not None:
        context_path = ws.root / context_rel
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(initial_context, encoding="utf-8")
        written.append(context_rel.as_posix())
    return {"status": "CREATED", "client_dir": str(client_dir), "written": written}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", help="lowercase, hyphen/underscore-safe client id, e.g. 'acme'")
    parser.add_argument("--workspace", default=None, help="workspace root (default: $V4_BU_WORKSPACE_ROOT)")
    parser.add_argument("--display-name", default=None, help="human display name (default: client_id)")
    parser.add_argument("--force", action="store_true", help="legacy: fill in only missing/untouched template files of an existing client")
    parser.add_argument("--initial-context", default=None, help="path to an operator-written context file, stored as RAW for source intake")
    args = parser.parse_args()

    if not args.client_id or "/" in args.client_id or ".." in args.client_id:
        print("ERROR: invalid client_id", file=sys.stderr)
        return 2
    if args.force:
        return bootstrap(args.client_id, args.workspace, args.display_name, args.force)

    context = Path(args.initial_context).read_text(encoding="utf-8") if args.initial_context else None
    result = bootstrap_client(args.client_id, display_name=args.display_name, workspace_root=args.workspace, initial_context=context)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"CREATED": 0, "NO_CHANGE": 0, "CONFLICT": 1}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
