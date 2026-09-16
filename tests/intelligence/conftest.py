from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def demo_intelligence_dir(repo_root: Path) -> Path:
    return repo_root / "examples" / "demo-client" / "acme-demo" / "intelligence"


@pytest.fixture
def demo_chain(demo_intelligence_dir: Path) -> dict:
    names = ["context-pack", "diagnosis", "gaps", "priorities", "replanning", "audit", "task-proposals"]
    return {name: json.loads((demo_intelligence_dir / f"{name}.json").read_text(encoding="utf-8")) for name in names}


@pytest.fixture
def intelligence_schema_paths(repo_root: Path) -> dict:
    return {
        "context-pack": repo_root / "schemas" / "context-pack.schema.json",
        "diagnosis": repo_root / "skills" / "diagnose-client" / "output.schema.json",
        "gaps": repo_root / "skills" / "calculate-gap" / "output.schema.json",
        "priorities": repo_root / "skills" / "identify-priorities" / "output.schema.json",
        "replanning": repo_root / "skills" / "replan-client" / "output.schema.json",
        "audit": repo_root / "skills" / "audit-plan" / "output.schema.json",
        "task-proposals": repo_root / "skills" / "generate-tasks" / "output.schema.json",
    }
