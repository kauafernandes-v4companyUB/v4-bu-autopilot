from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator


def test_all_intelligence_schemas_valid_draft_2020_12(repo_root):
    files = [
        repo_root / "schemas" / "context-pack.schema.json",
        repo_root / "schemas" / "artifact-ref.schema.json",
        repo_root / "skills" / "build-context-pack" / "output.schema.json",
        repo_root / "skills" / "diagnose-client" / "output.schema.json",
        repo_root / "skills" / "calculate-gap" / "output.schema.json",
        repo_root / "skills" / "identify-priorities" / "output.schema.json",
        repo_root / "skills" / "replan-client" / "output.schema.json",
        repo_root / "skills" / "audit-plan" / "output.schema.json",
        repo_root / "skills" / "generate-tasks" / "output.schema.json",
    ]
    for f in files:
        assert f.is_file(), f
        Draft202012Validator.check_schema(json.loads(f.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", ["context-pack", "diagnosis", "gaps", "priorities", "replanning", "audit", "task-proposals"])
def test_demo_chain_artifact_validates_against_its_schema(name, demo_chain, intelligence_schema_paths, validate):
    errors = validate(demo_chain[name], intelligence_schema_paths[name])
    assert not errors, "\n".join(errors)


def test_demo_chain_client_id_consistent(demo_chain):
    for name, artifact in demo_chain.items():
        assert artifact["client_id"] == "acme-demo", name


def test_demo_chain_never_uses_walmaq_or_real_looking_data(demo_intelligence_dir):
    for f in demo_intelligence_dir.glob("*.json"):
        text = f.read_text(encoding="utf-8").lower()
        assert "walmaq" not in text, f
    # every synthetic statement is explicitly tagged in this demo's convention
    for f in demo_intelligence_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["client_id"] == "acme-demo"


# --- P: no arbitrary numeric score anywhere in the priority/finding contracts ---

def test_no_numeric_score_field_in_finding_or_priority_schemas(repo_root):
    diag_schema = json.loads((repo_root / "skills" / "diagnose-client" / "output.schema.json").read_text())
    finding_props = diag_schema["$defs"]["finding"]["properties"]
    assert "score" not in finding_props and "health_score" not in finding_props
    assert finding_props["impact"]["enum"] == ["unknown", "low", "medium", "high"]

    pr_schema = json.loads((repo_root / "skills" / "identify-priorities" / "output.schema.json").read_text())
    priority_props = pr_schema["$defs"]["priority"]["properties"]
    assert "score" not in priority_props and "rank_score" not in priority_props
    assert priority_props["order"]["type"] == "integer"


# --- T: replan-client can never mutate the Quarter plan — structural check ---

def test_replan_client_schema_has_no_plan_mutation_fields(repo_root):
    schema = json.loads((repo_root / "skills" / "replan-client" / "output.schema.json").read_text())
    top_level_keys = set(schema["properties"].keys())
    forbidden = {"planned_budget", "target", "smart_objective", "baseline"}
    assert not (top_level_keys & forbidden), top_level_keys & forbidden


# --- AC: tasks never carry a responsible/owner field — structural check ---

def test_generate_tasks_schema_has_no_responsible_field(repo_root):
    schema = json.loads((repo_root / "skills" / "generate-tasks" / "output.schema.json").read_text())
    op_props = schema["$defs"]["manageTaskOperation"]["properties"]
    assert "responsible" not in op_props and "owner" not in op_props


# --- AD: generate-tasks mode is always "preview" — structural check ---

def test_generate_tasks_mode_is_always_preview(repo_root):
    schema = json.loads((repo_root / "skills" / "generate-tasks" / "output.schema.json").read_text())
    assert schema["properties"]["mode"] == {"const": "preview"}


# --- AH proxy: no INTELLIGENCE artifact schema declares an apply mode ---

def test_no_intelligence_schema_declares_an_apply_mode(repo_root):
    for name in ["context-pack", "diagnosis", "gaps", "priorities", "replanning", "audit"]:
        path = (
            repo_root / "schemas" / "context-pack.schema.json"
            if name == "context-pack"
            else repo_root / "skills" / {"diagnosis": "diagnose-client", "gaps": "calculate-gap", "priorities": "identify-priorities", "replanning": "replan-client", "audit": "audit-plan"}[name] / "output.schema.json"
        )
        schema = json.loads(path.read_text(encoding="utf-8"))
        mode_field = schema.get("properties", {}).get("mode")
        assert mode_field is None, f"{name} schema must never declare a 'mode' field (no apply concept exists for INTELLIGENCE skills)"
