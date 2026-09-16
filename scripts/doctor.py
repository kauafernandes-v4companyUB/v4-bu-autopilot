#!/usr/bin/env python3
"""V4 BU Autopilot — project health check.

    python scripts/doctor.py
    python scripts/doctor.py --workspace /path/to/v4-bu-workspace-private

Runs entirely against the engine repository when no workspace is
configured/reachable (a public clone) — in that mode "Workspace" reports
SKIP, everything else must still PASS. When a workspace is available, it
is validated in full (every client's canonical files against their
schemas, cross-references, isolation).

Exit code 0 = healthy. Non-zero = at least one check FAILed (SKIP never
causes a non-zero exit).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402
from jsonschema.exceptions import SchemaError  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

from scripts.lib.workspace import resolve_workspace  # noqa: E402
from scripts.run_replanning_checks import ARTIFACT_FILES, lint_and_check_chain, validate_artifact  # noqa: E402

RESULTS: list[tuple[str, str, list[str]]] = []  # (label, status, details)


def check(label: str) -> Callable:
    def decorator(fn: Callable[[], tuple[str, list[str]]]):
        try:
            status, details = fn()
        except Exception as e:  # a check itself blowing up is a FAIL, not a crash
            status, details = "FAIL", [f"check raised {type(e).__name__}: {e}"]
        RESULTS.append((label, status, details))
        return fn

    return decorator


def _schema_files() -> list[Path]:
    return sorted(REPO_ROOT.glob("schemas/*.json")) + sorted(REPO_ROOT.glob("skills/*/output.schema.json"))


def _schema_registry() -> Registry:
    resources = []
    for f in _schema_files():
        data = json.loads(f.read_text(encoding="utf-8"))
        if "$id" in data:
            resources.append((data["$id"], Resource.from_contents(data)))
    return Registry().with_resources(resources)


def _validate(instance: dict, schema_path: Path, registry: Registry) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    return [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(instance)]


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [l for l in out.stdout.splitlines() if l]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_repository() -> tuple[str, list[str]]:
    problems = []
    if not (REPO_ROOT / ".git").exists():
        problems.append("not a git repository")
    for expected in ["skills", "schemas", "scripts", "tests", "docs", "operation", "examples", "templates"]:
        if not (REPO_ROOT / expected).is_dir():
            problems.append(f"missing expected directory: {expected}/")
    return ("FAIL" if problems else "PASS"), problems


def check_workspace(ws_override: str | None) -> tuple[str, list[str], object]:
    ws = resolve_workspace(required=False, override=ws_override)
    if ws is None:
        return "SKIP", ["V4_BU_WORKSPACE_ROOT not set or not a valid workspace — engine-only mode"], None
    return "PASS", [f"workspace: {ws.root}"], ws


def check_schemas(registry: Registry) -> tuple[str, list[str]]:
    problems = []
    files = _schema_files()
    if not files:
        return "FAIL", ["no schema files found"]
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f}: invalid JSON ({e})")
            continue
        try:
            Draft202012Validator.check_schema(data)
        except SchemaError as e:
            problems.append(f"{f}: invalid Draft 2020-12 schema ({e})")
    return ("FAIL" if problems else "PASS"), problems


def check_skill_registry(registry: Registry) -> tuple[str, list[str]]:
    problems = []
    registry_path = REPO_ROOT / "skills" / "registry.json"
    if not registry_path.is_file():
        return "FAIL", ["skills/registry.json is missing"]
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    errors = _validate(data, REPO_ROOT / "schemas" / "skills-registry.schema.json", registry)
    problems.extend(errors)

    registered_implemented = {e["id"] for e in data["skills"] if e["implemented"]}
    real_dirs = {p.parent.name for p in (REPO_ROOT / "skills").glob("*/SKILL.md") if p.parent.name != "_template"}
    missing = real_dirs - registered_implemented
    if missing:
        problems.append(f"skill directories not registered as implemented: {sorted(missing)}")
    stale = registered_implemented - real_dirs
    if stale:
        problems.append(f"registry claims implemented but directory/SKILL.md missing: {sorted(stale)}")
    return ("FAIL" if problems else "PASS"), problems


def check_workflow_registry(registry: Registry) -> tuple[str, list[str]]:
    problems = []
    registry_path = REPO_ROOT / "workflows" / "registry.json"
    if not registry_path.is_file():
        return "FAIL", ["workflows/registry.json is missing"]
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    errors = _validate(data, REPO_ROOT / "schemas" / "workflow-registry.schema.json", registry)
    problems.extend(errors)

    skills_registry_path = REPO_ROOT / "skills" / "registry.json"
    known_skill_ids: set[str] = set()
    implemented_skill_ids: set[str] = set()
    if skills_registry_path.is_file():
        skill_entries = json.loads(skills_registry_path.read_text(encoding="utf-8"))["skills"]
        known_skill_ids = {e["id"] for e in skill_entries}
        implemented_skill_ids = {e["id"] for e in skill_entries if e["implemented"]}

    ids_seen: set[str] = set()
    for wf in data.get("workflows", []):
        if wf["workflow_id"] in ids_seen:
            problems.append(f"duplicate workflow_id: {wf['workflow_id']}")
        ids_seen.add(wf["workflow_id"])
        unknown_steps = set(wf["steps"]) - known_skill_ids
        if unknown_steps:
            problems.append(f"workflow {wf['workflow_id']!r} references unknown skill_id(s) in steps: {sorted(unknown_steps)}")
        if wf["status"] == "implemented":
            unimplemented = [s for s in wf["steps"] if s not in implemented_skill_ids]
            if unimplemented:
                problems.append(f"workflow {wf['workflow_id']!r} is status=implemented but references non-implemented skill(s): {unimplemented}")

    return ("FAIL" if problems else "PASS"), problems


def check_approval_schema(registry: Registry) -> tuple[str, list[str]]:
    problems = []
    for f in ["schemas/approval.schema.json", "schemas/action-receipt.schema.json", "schemas/operator-inbox.schema.json", "schemas/workflow-report.schema.json"]:
        p = REPO_ROOT / f
        if not p.is_file():
            problems.append(f"missing required schema: {f}")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(data)
        except (json.JSONDecodeError, SchemaError) as e:
            problems.append(f"{f}: invalid ({e})")
    return ("FAIL" if problems else "PASS"), problems


def check_skill_contracts() -> tuple[str, list[str]]:
    problems = []
    for skill_md in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
        if skill_md.parent.name == "_template":
            continue
        text = skill_md.read_text(encoding="utf-8")
        skill_id = skill_md.parent.name
        output_schema = skill_md.parent / "output.schema.json"
        if not output_schema.is_file():
            problems.append(f"{skill_id}: missing output.schema.json")
            continue
        try:
            json.loads(output_schema.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{skill_id}: output.schema.json invalid JSON ({e})")
        lowered = text.lower()
        if not any(tok in lowered for tok in ["categoria:", "class:", "classe:"]):
            problems.append(f"{skill_id}: SKILL.md does not declare a category/class")
        if not any(tok in lowered for tok in ["versão:", "version:"]):
            problems.append(f"{skill_id}: SKILL.md does not declare a version")
        if "side effect" not in lowered:
            problems.append(f"{skill_id}: SKILL.md does not declare side effects")
    return ("FAIL" if problems else "PASS"), problems


def check_private_tracking() -> tuple[str, list[str]]:
    tracked = _tracked_files()
    offenders = [f for f in tracked if f == "private" or f.startswith("private/")]
    return ("FAIL" if offenders else "PASS"), offenders


def check_generated_tracking() -> tuple[str, list[str]]:
    tracked = _tracked_files()
    offenders = [f for f in tracked if f.startswith("context/generated/")]
    return ("FAIL" if offenders else "PASS"), offenders


def check_secrets_hygiene() -> tuple[str, list[str]]:
    tracked = _tracked_files()
    problems = []
    problems += [f for f in tracked if Path(f).name == ".env"]
    problems += [f for f in tracked if Path(f).suffix in (".pem", ".key")]
    problems += [f for f in tracked if f == "clients" or f.startswith("clients/")]
    problems += [f for f in tracked if "walmaq" in f.lower()]
    return ("FAIL" if problems else "PASS"), problems


def check_replanning_artifacts(ws) -> tuple[str, list[str]]:
    """When a workspace is available, validate any existing transient
    Intelligence artifacts (<workspace>/context/generated/<client_id>/
    replanning/*.json) against their schemas and cross-artifact lint
    rules (scripts/lib/replanning_lint.py). Never asserts anything about
    canonical mutation — that's out of scope for a read-only integrity
    check; this only checks the artifacts that already exist are
    internally consistent."""
    if ws is None or not ws.clients_dir.is_dir():
        return "SKIP", ["no workspace"]

    client_dirs = [p for p in ws.clients_dir.iterdir() if p.is_dir()]
    if not client_dirs:
        return "SKIP", ["workspace has no clients/<id> directories yet"]

    problems = []
    any_artifacts_found = False
    for client_dir in sorted(client_dirs):
        client_id = client_dir.name
        replanning_dir = ws.client_generated_dir(client_id) / "replanning"
        if not replanning_dir.is_dir():
            continue
        for name in ARTIFACT_FILES:
            p = replanning_dir / name
            if not p.is_file():
                continue
            any_artifacts_found = True
            errors = validate_artifact(name, p, _schema_registry())
            if errors:
                problems.append(f"{client_id}/{name}: schema errors: {errors[:2]}")
        chain_problems = lint_and_check_chain(replanning_dir)
        for name, issues in chain_problems.items():
            any_artifacts_found = True
            problems.append(f"{client_id}/{name}: lint/chain: {issues[:2]}")

    if not any_artifacts_found:
        return "SKIP", ["no replanning artifacts on disk for any client yet"]
    return ("FAIL" if problems else "PASS"), problems


def check_client_workspace_integrity(ws, registry: Registry) -> dict[str, tuple[str, list[str]]]:
    """Returns a dict of sub-check-label -> (status, details) covering
    client isolation, evidence, quarter, ROPRE, task and source-reference
    integrity across every client directory in the workspace."""
    results = {
        "Client isolation": ("PASS", []),
        "Evidence integrity": ("PASS", []),
        "Quarter integrity": ("PASS", []),
        "ROPRE integrity": ("PASS", []),
        "Task integrity": ("PASS", []),
        "Source references": ("PASS", []),
    }
    if ws is None:
        return {k: ("SKIP", ["no workspace"]) for k in results}

    client_dirs = [p for p in ws.clients_dir.iterdir() if p.is_dir()] if ws.clients_dir.is_dir() else []
    if not client_dirs:
        return {k: ("SKIP", ["workspace has no clients/<id> directories yet"]) for k in results}

    problems = {k: [] for k in results}

    for client_dir in sorted(client_dirs):
        client_id = client_dir.name

        sources_by_id = set()
        sources_path = client_dir / "sources.json"
        if sources_path.is_file():
            sources_data = json.loads(sources_path.read_text(encoding="utf-8"))
            sources_by_id = {s["source_id"] for s in sources_data.get("sources", [])}

        evidence_path = client_dir / "evidence.json"
        known_evidence_ids: set[str] = set()
        if evidence_path.is_file():
            evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))
            errs = _validate(evidence_data, REPO_ROOT / "schemas" / "client-evidence.schema.json", registry)
            if errs:
                problems["Evidence integrity"].append(f"{client_id}/evidence.json: {errs[:3]}")
            ids = [e["evidence_id"] for e in evidence_data.get("evidences", [])]
            if len(ids) != len(set(ids)):
                problems["Evidence integrity"].append(f"{client_id}/evidence.json: duplicate evidence_id(s)")
            known_evidence_ids = set(ids)
            for e in evidence_data.get("evidences", []):
                if e.get("client_id") != client_id:
                    problems["Client isolation"].append(
                        f"{client_id}/evidence.json: entry {e.get('evidence_id')} has client_id={e.get('client_id')!r}"
                    )
                sid = e.get("source_id")
                if sid is not None and sid not in sources_by_id:
                    problems["Source references"].append(
                        f"{client_id}/evidence.json: evidence {e.get('evidence_id')} references unknown source_id {sid!r}"
                    )

        quarters_dir = client_dir / "quarters"
        if quarters_dir.is_dir():
            for qdir in sorted(p for p in quarters_dir.iterdir() if p.is_dir()):
                plan_path = qdir / "plan.json"
                if plan_path.is_file():
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    errs = _validate(plan, REPO_ROOT / "schemas" / "quarter-plan.schema.json", registry)
                    if errs:
                        problems["Quarter integrity"].append(f"{client_id}/{qdir.name}/plan.json: {errs[:3]}")
                    elif plan.get("client_id") != client_id or plan.get("quarter_id") != qdir.name:
                        problems["Client isolation"].append(f"{client_id}/{qdir.name}/plan.json: identity mismatch")

                monitoring_path = qdir / "monitoring.json"
                if monitoring_path.is_file():
                    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
                    errs = _validate(monitoring, REPO_ROOT / "schemas" / "quarter-monitoring.schema.json", registry)
                    if errs:
                        problems["Quarter integrity"].append(f"{client_id}/{qdir.name}/monitoring.json: {errs[:3]}")
                    for m in monitoring.get("media_monitoring", []):
                        for eid in m.get("evidence_ids", []):
                            if known_evidence_ids and eid not in known_evidence_ids:
                                problems["Evidence integrity"].append(
                                    f"{client_id}/{qdir.name}/monitoring.json: media record references unresolved evidence_id {eid}"
                                )

                for checkin_path in sorted((qdir / "check-ins").glob("*.json")) if (qdir / "check-ins").is_dir() else []:
                    checkin = json.loads(checkin_path.read_text(encoding="utf-8"))
                    errs = _validate(checkin, REPO_ROOT / "schemas" / "check-in-ropre.schema.json", registry)
                    if errs:
                        problems["ROPRE integrity"].append(f"{client_id}/{qdir.name}/check-ins/{checkin_path.name}: {errs[:3]}")

        tasks_path = client_dir / "tasks.json"
        if tasks_path.is_file():
            tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
            errs = _validate(tasks, REPO_ROOT / "schemas" / "task-ledger.schema.json", registry)
            if errs:
                problems["Task integrity"].append(f"{client_id}/tasks.json: {errs[:3]}")
            task_ids = [t["task_id"] for t in tasks.get("tasks", [])]
            if len(task_ids) != len(set(task_ids)):
                problems["Task integrity"].append(f"{client_id}/tasks.json: duplicate task_id(s)")
            external_ids = [
                t["external"]["external_id"]
                for t in tasks.get("tasks", [])
                if t.get("external") and t["external"].get("external_id")
            ]
            if len(external_ids) != len(set(external_ids)):
                problems["Task integrity"].append(f"{client_id}/tasks.json: duplicate external.external_id — two local tasks bound to the same eKyte task")
            for t in tasks.get("tasks", []):
                if t.get("client_id") != client_id:
                    problems["Client isolation"].append(f"{client_id}/tasks.json: task {t.get('task_id')} has client_id={t.get('client_id')!r}")

    for label, details in problems.items():
        if details:
            results[label] = ("FAIL", details)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=None, help="workspace root (default: $V4_BU_WORKSPACE_ROOT)")
    args = parser.parse_args()

    print("V4 BU AUTOPILOT DOCTOR")
    print()

    registry = _schema_registry()

    check("Repository")(lambda: check_repository())
    ws_status, ws_details, ws = check_workspace(args.workspace)
    RESULTS.append(("Workspace", ws_status, ws_details))
    check("Schemas")(lambda: check_schemas(registry))
    check("Skill registry")(lambda: check_skill_registry(registry))
    check("Workflow registry")(lambda: check_workflow_registry(registry))
    check("Approval schemas")(lambda: check_approval_schema(registry))
    check("Skill contracts")(lambda: check_skill_contracts())

    for label, (status, details) in check_client_workspace_integrity(ws, registry).items():
        RESULTS.append((label, status, details))

    check("Replanning artifacts")(lambda: check_replanning_artifacts(ws))
    check("Private tracking")(lambda: check_private_tracking())
    check("Generated tracking")(lambda: check_generated_tracking())
    check("Secrets hygiene")(lambda: check_secrets_hygiene())

    order = [
        "Repository", "Workspace", "Schemas", "Skill registry", "Workflow registry",
        "Approval schemas", "Skill contracts",
        "Client isolation", "Evidence integrity", "Quarter integrity", "ROPRE integrity",
        "Task integrity", "Source references", "Replanning artifacts", "Private tracking",
        "Generated tracking", "Secrets hygiene",
    ]
    by_label = {label: (status, details) for label, status, details in RESULTS}

    any_fail = False
    passed = 0
    for label in order:
        status, details = by_label.get(label, ("SKIP", ["not run"]))
        dots = "." * (26 - len(label))
        print(f"{label} {dots} {status}")
        if status == "FAIL":
            any_fail = True
            for d in details[:5]:
                print(f"    - {d}")
        elif status == "PASS":
            passed += 1

    print()
    print(f"{passed} checks passed.")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
