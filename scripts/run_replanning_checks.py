#!/usr/bin/env python3
"""Deterministic preflight/postflight checks for the "replaneje <client>"
workflow (operation/replanning-rules.md).

This script does NOT reason about a client's situation — that's Claude/
Codex executing skills/{build-context-pack,diagnose-client,calculate-gap,
identify-priorities,replan-client,audit-plan,generate-tasks}/SKILL.md.
This script only: resolves paths, checks the registry has the pipeline
implemented, and — when replanning artifacts already exist on disk in
`<workspace>/context/generated/<client_id>/replanning/` — validates each
against its schema, lints cross-artifact structural invariants
(scripts/lib/replanning_lint.py), and verifies the artifact_ref hash
chain (scripts/lib/artifact_hash.py) hasn't gone stale.

Usage:
    python scripts/run_replanning_checks.py <client_id> [--workspace PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

from scripts.lib import artifact_hash, replanning_lint  # noqa: E402
from scripts.lib.workspace import resolve_workspace  # noqa: E402

PIPELINE = [
    "build-context-pack", "diagnose-client", "calculate-gap",
    "identify-priorities", "replan-client", "audit-plan", "generate-tasks",
]

ARTIFACT_FILES = {
    "context-pack.json": ("skills/build-context-pack/output.schema.json", None),
    "diagnosis.json": ("skills/diagnose-client/output.schema.json", "diagnosis"),
    "gaps.json": ("skills/calculate-gap/output.schema.json", "gaps"),
    "priorities.json": ("skills/identify-priorities/output.schema.json", "priorities"),
    "replanning.json": ("skills/replan-client/output.schema.json", "replanning"),
    "audit.json": ("skills/audit-plan/output.schema.json", "audit"),
    "task-proposals.json": ("skills/generate-tasks/output.schema.json", "task_proposals"),
}


def _schema_registry() -> Registry:
    resources = []
    for f in sorted(REPO_ROOT.glob("schemas/*.json")) + sorted(REPO_ROOT.glob("skills/*/output.schema.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if "$id" in data:
            resources.append((data["$id"], Resource.from_contents(data)))
    return Registry().with_resources(resources)


def check_registry_implements_pipeline() -> tuple[bool, list[str]]:
    registry = json.loads((REPO_ROOT / "skills" / "registry.json").read_text(encoding="utf-8"))
    implemented = {e["id"] for e in registry["skills"] if e["implemented"]}
    missing = [s for s in PIPELINE if s not in implemented]
    return (not missing), missing


def validate_artifact(name: str, path: Path, registry: Registry) -> list[str]:
    schema_rel, _ = ARTIFACT_FILES[name]
    schema = json.loads((REPO_ROOT / schema_rel).read_text(encoding="utf-8"))
    instance = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    return [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(instance)]


def lint_and_check_chain(replanning_dir: Path) -> dict[str, list[str]]:
    problems: dict[str, list[str]] = {}
    loaded = {}
    for name in ARTIFACT_FILES:
        p = replanning_dir / name
        if p.is_file():
            loaded[name] = json.loads(p.read_text(encoding="utf-8"))

    if "context-pack.json" in loaded:
        issues = replanning_lint.lint_context_pack(loaded["context-pack.json"])
        if issues:
            problems["context-pack.json"] = issues

    if "diagnosis.json" in loaded and "context-pack.json" in loaded:
        issues = replanning_lint.lint_diagnosis(loaded["diagnosis.json"], loaded["context-pack.json"])
        chk = artifact_hash.verify_artifact_ref(loaded["diagnosis.json"]["context_pack_ref"], loaded["context-pack.json"])
        if not chk.ok:
            issues.append(f"stale context_pack_ref: {chk.reason}")
        if issues:
            problems["diagnosis.json"] = issues

    if "gaps.json" in loaded and "context-pack.json" in loaded:
        issues = replanning_lint.lint_gaps(loaded["gaps.json"], loaded["context-pack.json"])
        if issues:
            problems["gaps.json"] = issues

    if "priorities.json" in loaded and "diagnosis.json" in loaded and "gaps.json" in loaded:
        issues = replanning_lint.lint_priorities(loaded["priorities.json"], loaded["diagnosis.json"], loaded["gaps.json"])
        if issues:
            problems["priorities.json"] = issues

    if "replanning.json" in loaded and "priorities.json" in loaded and "context-pack.json" in loaded:
        issues = replanning_lint.lint_replanning(loaded["replanning.json"], loaded["priorities.json"], loaded["context-pack.json"])
        if issues:
            problems["replanning.json"] = issues

    if "audit.json" in loaded:
        issues = replanning_lint.lint_audit(loaded["audit.json"])
        if issues:
            problems["audit.json"] = issues

    if "task-proposals.json" in loaded and "replanning.json" in loaded:
        issues = replanning_lint.lint_task_proposals(loaded["task-proposals.json"], loaded["replanning.json"])
        if issues:
            problems["task-proposals.json"] = issues

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    print(f"REPLANNING CHECKS — {args.client_id}")
    print()

    ok, missing = check_registry_implements_pipeline()
    print(f"Registry implements pipeline: {'PASS' if ok else 'FAIL'}")
    if missing:
        print(f"  missing: {missing}")
        return 1

    ws = resolve_workspace(required=False, override=args.workspace)
    if ws is None:
        print("Workspace: SKIP (no workspace configured — nothing to validate on disk)")
        return 0

    replanning_dir = ws.client_generated_dir(args.client_id) / "replanning"
    if not replanning_dir.is_dir():
        print(f"Artifacts: SKIP (no {replanning_dir} yet)")
        return 0

    registry = _schema_registry()
    any_fail = False
    for name in ARTIFACT_FILES:
        p = replanning_dir / name
        if not p.is_file():
            print(f"  {name}: SKIP (not generated yet)")
            continue
        errors = validate_artifact(name, p, registry)
        if errors:
            any_fail = True
            print(f"  {name}: FAIL (schema)")
            for e in errors[:5]:
                print(f"    - {e}")
        else:
            print(f"  {name}: PASS (schema)")

    chain_problems = lint_and_check_chain(replanning_dir)
    for name, issues in chain_problems.items():
        any_fail = True
        print(f"  {name}: FAIL (lint/chain)")
        for i in issues[:5]:
            print(f"    - {i}")

    print()
    print("Overall:", "FAIL" if any_fail else "PASS")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
