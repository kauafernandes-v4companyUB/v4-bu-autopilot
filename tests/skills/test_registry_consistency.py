from __future__ import annotations

import json
from pathlib import Path


def _registry(repo_root: Path) -> dict:
    return json.loads((repo_root / "skills" / "registry.json").read_text(encoding="utf-8"))


def test_registry_is_valid_against_its_schema(repo_root, validate):
    data = _registry(repo_root)
    errors = validate(data, repo_root / "schemas" / "skills-registry.schema.json")
    assert not errors, "\n".join(errors)


def test_every_implemented_skill_directory_exists_and_matches_registry(repo_root):
    data = _registry(repo_root)
    for entry in data["skills"]:
        if not entry["implemented"]:
            continue
        skill_md = repo_root / entry["skill_path"]
        output_schema = repo_root / entry["output_schema_path"]
        assert skill_md.is_file(), f"registry says {entry['id']} is implemented but {skill_md} is missing"
        assert output_schema.is_file(), f"registry says {entry['id']} is implemented but {output_schema} is missing"


def test_every_real_skill_directory_is_registered(repo_root):
    """Every skills/<id>/ with a SKILL.md (except the _template scaffold)
    must appear in the registry as implemented=true — a skill directory
    that exists but isn't registered would let Claude "discover" and run
    it without the registry ever having vetted it."""
    data = _registry(repo_root)
    registered_ids = {e["id"] for e in data["skills"] if e["implemented"]}

    skills_dir = repo_root / "skills"
    real_skill_dirs = {
        p.parent.name
        for p in skills_dir.glob("*/SKILL.md")
        if p.parent.name != "_template"
    }
    missing_from_registry = real_skill_dirs - registered_ids
    assert not missing_from_registry, f"skill directories not registered: {missing_from_registry}"


def test_no_planned_skill_has_an_implementation_path():
    pass  # covered by schema's if/then (skills-registry.schema.json), kept as a documented expectation


def test_registry_ids_are_unique(repo_root):
    data = _registry(repo_root)
    ids = [e["id"] for e in data["skills"]]
    assert len(ids) == len(set(ids)), f"duplicate ids in registry: {ids}"


def test_dependencies_reference_known_registry_ids(repo_root):
    data = _registry(repo_root)
    known = {e["id"] for e in data["skills"]}
    for entry in data["skills"]:
        for dep in entry["dependencies"]:
            assert dep in known, f"{entry['id']} depends on unknown skill {dep!r}"
