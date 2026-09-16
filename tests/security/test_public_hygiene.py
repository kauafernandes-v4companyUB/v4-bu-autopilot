"""Public-repository hygiene checks (mission sections 6-8).

These run against `git ls-files` — the actual tracked set — not just
.gitignore contents, since .gitignore only prevents *future* accidents;
this test catches anything already staged/committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

FORBIDDEN_EXTENSIONS = {".pem", ".key"}
FORBIDDEN_EXACT_NAMES = {".env"}


def _tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


@pytest.fixture(scope="module")
def tracked(repo_root: Path) -> list[str]:
    return _tracked_files(repo_root)


def test_no_real_client_tree_tracked(tracked):
    """clients/<id>/ must never be tracked in the public engine — real
    canonical memory lives in the private workspace
    ($V4_BU_WORKSPACE_ROOT). The only clients/-shaped tree that may exist
    in this repo is inside examples/, not at the repo root."""
    offenders = [f for f in tracked if f == "clients" or f.startswith("clients/")]
    assert not offenders, f"clients/ tracked in public engine: {offenders}"


def test_no_private_tree_tracked(tracked):
    offenders = [f for f in tracked if f == "private" or f.startswith("private/")]
    assert not offenders, f"private/ tracked in public engine: {offenders}"


def test_no_generated_context_tracked(tracked):
    offenders = [f for f in tracked if f.startswith("context/generated/")]
    assert not offenders, f"context/generated/ tracked in public engine: {offenders}"


def test_no_dotenv_tracked(tracked):
    offenders = [f for f in tracked if Path(f).name in FORBIDDEN_EXACT_NAMES]
    assert not offenders, f".env tracked in public engine: {offenders}"


def test_no_key_or_pem_files_tracked(tracked):
    offenders = [f for f in tracked if Path(f).suffix in FORBIDDEN_EXTENSIONS]
    assert not offenders, f"key/pem files tracked in public engine: {offenders}"


def test_no_walmaq_named_paths_tracked(tracked):
    """Extra guard: the pilot client's identifier must never appear in a
    tracked *path* (content is covered by history remediation docs /
    gitleaks in CI — this test is about the tree shape)."""
    offenders = [f for f in tracked if "walmaq" in f.lower()]
    assert not offenders, f"path containing 'walmaq' tracked in public engine: {offenders}"


def test_examples_demo_client_is_the_only_clients_shaped_tree(tracked):
    demo_files = [f for f in tracked if f.startswith("examples/demo-client/")]
    assert demo_files, "expected examples/demo-client/ to be tracked (the synthetic fixture)"


def test_gitignore_covers_required_patterns(repo_root: Path):
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ["private/", "context/generated/", "clients/", ".env", "*.key", "*.pem"]:
        assert pattern in gitignore, f".gitignore missing pattern: {pattern}"
