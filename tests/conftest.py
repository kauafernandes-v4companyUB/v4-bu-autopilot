from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
SKILLS_DIR = REPO_ROOT / "skills"
EXAMPLES_DIR = REPO_ROOT / "examples"

sys.path.insert(0, str(REPO_ROOT))


def _all_schema_files() -> list[Path]:
    files = sorted(SCHEMAS_DIR.glob("*.json"))
    files += sorted(SKILLS_DIR.glob("*/output.schema.json"))
    return files


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def all_schema_files() -> list[Path]:
    return _all_schema_files()


@pytest.fixture(scope="session")
def schema_registry() -> Registry:
    """A referencing.Registry with every schemas/*.json loaded by $id, so
    cross-file $ref (e.g. client-evidence -> evidence, output schemas ->
    schemas/quarter-monitoring) resolves without network access."""
    resources = []
    for f in _all_schema_files():
        data = json.loads(f.read_text(encoding="utf-8"))
        if "$id" in data:
            resources.append((data["$id"], Resource.from_contents(data)))
    return Registry().with_resources(resources)


def validate_instance(instance: dict, schema_path: Path, registry: Registry) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [f"{list(e.path)}: {e.message}" for e in errors]


@pytest.fixture
def validate(schema_registry: Registry):
    def _validate(instance: dict, schema_path: Path) -> list[str]:
        return validate_instance(instance, schema_path, schema_registry)

    return _validate


@pytest.fixture
def demo_client_dir() -> Path:
    return EXAMPLES_DIR / "demo-client" / "acme-demo"


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """A scaffolded-but-empty workspace root under pytest's tmp_path —
    never touches $V4_BU_WORKSPACE_ROOT or any real data."""
    root = tmp_path / "workspace"
    for sub in ("clients", "private", "context/generated", "outputs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
