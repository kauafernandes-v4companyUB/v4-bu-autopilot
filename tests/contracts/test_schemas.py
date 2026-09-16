from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def test_all_schemas_are_valid_json(all_schema_files: list[Path]):
    assert all_schema_files, "expected at least one schema file"
    for f in all_schema_files:
        json.loads(f.read_text(encoding="utf-8"))  # raises on invalid JSON


def test_all_schemas_are_valid_draft_2020_12(all_schema_files: list[Path]):
    for f in all_schema_files:
        schema = json.loads(f.read_text(encoding="utf-8"))
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            pytest.fail(f"{f} is not a valid Draft 2020-12 schema: {e}")


def test_all_schemas_declare_2020_12_dollar_schema(all_schema_files: list[Path]):
    for f in all_schema_files:
        schema = json.loads(f.read_text(encoding="utf-8"))
        assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f


QUARTER_ID_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")


def _iter_json_files(base: Path):
    return sorted(base.rglob("*.json"))


def test_demo_client_json_files_are_valid_json(demo_client_dir: Path):
    files = _iter_json_files(demo_client_dir)
    assert files, "expected demo client fixture files"
    for f in files:
        json.loads(f.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "relative_path,schema_name",
    [
        ("evidence.json", "client-evidence.schema.json"),
        ("knowledge.json", "client-knowledge.schema.json"),
        ("quarters/2026-Q1/plan.json", "quarter-plan.schema.json"),
        ("quarters/2026-Q1/monitoring.json", "quarter-monitoring.schema.json"),
        ("tasks.json", "task-ledger.schema.json"),
        ("quarters/2026-Q1/check-ins/demo-2026-01-20.json", "check-in-ropre.schema.json"),
    ],
)
def test_demo_client_fixtures_validate_against_schema(demo_client_dir, repo_root, validate, relative_path, schema_name):
    instance = json.loads((demo_client_dir / relative_path).read_text(encoding="utf-8"))
    errors = validate(instance, repo_root / "schemas" / schema_name)
    assert not errors, f"{relative_path} failed against {schema_name}:\n" + "\n".join(errors)


def test_demo_client_id_consistent_across_files(demo_client_dir: Path):
    client_id = "acme-demo"
    for f in _iter_json_files(demo_client_dir):
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "client_id" in data:
            assert data["client_id"] == client_id, f"{f} has client_id={data['client_id']!r}, expected {client_id!r}"


def test_demo_client_evidence_ids_unique(demo_client_dir: Path):
    evidence = json.loads((demo_client_dir / "evidence.json").read_text(encoding="utf-8"))
    ids = [e["evidence_id"] for e in evidence["evidences"]]
    assert len(ids) == len(set(ids)), f"duplicate evidence_id in demo fixture: {ids}"


def test_demo_client_quarter_ids_match_pattern(demo_client_dir: Path):
    quarters_dir = demo_client_dir / "quarters"
    quarter_dirs = [p for p in quarters_dir.iterdir() if p.is_dir()]
    assert quarter_dirs, "expected at least one quarter directory"
    for qdir in quarter_dirs:
        assert QUARTER_ID_RE.match(qdir.name), f"invalid quarter_id directory name: {qdir.name}"
        plan = json.loads((qdir / "plan.json").read_text(encoding="utf-8"))
        assert plan["quarter_id"] == qdir.name


def test_demo_client_evidence_ids_referenced_by_tasks_resolve(demo_client_dir: Path):
    evidence = json.loads((demo_client_dir / "evidence.json").read_text(encoding="utf-8"))
    known_ids = {e["evidence_id"] for e in evidence["evidences"]}
    tasks = json.loads((demo_client_dir / "tasks.json").read_text(encoding="utf-8"))
    for task in tasks["tasks"]:
        for eid in task["evidence_ids"]:
            assert eid in known_ids, f"task {task['task_id']} references unknown evidence_id {eid}"
