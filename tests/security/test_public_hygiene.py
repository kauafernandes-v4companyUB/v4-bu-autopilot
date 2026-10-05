"""Public-repository hygiene checks (mission sections 6-8).

These run against `git ls-files` — the actual tracked set — not just
.gitignore contents, since .gitignore only prevents *future* accidents;
this test catches anything already staged/committed.
"""

from __future__ import annotations

import fnmatch
import json
import re
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


def test_no_google_credentials_or_tokens_tracked(tracked):
    """OAuth client secrets, tokens and service-account keys must live
    outside the engine (scripts/lib/google_sheets_auth.py refuses in-repo
    paths) — never tracked."""
    offenders = [
        f for f in tracked
        if fnmatch.fnmatch(Path(f).name, "client_secret*.json")
        or fnmatch.fnmatch(Path(f).name, "*google-sheets-token*.json")
        or fnmatch.fnmatch(Path(f).name, "*service-account*.json")
        or Path(f).name.endswith(".credentials.json")
    ]
    assert not offenders, f"Google credential/token files tracked in public engine: {offenders}"


def test_public_google_sheet_fixtures_use_synthetic_ids(repo_root: Path, tracked):
    """Every google_sheet spreadsheet_id in tracked examples must be
    visibly synthetic (fake-*) — real ids live only in the private workspace."""
    for f in tracked:
        if not (f.startswith("examples/") and f.endswith(".json")):
            continue
        data = json.loads((repo_root / f).read_text(encoding="utf-8"))
        for entry in data.get("sources", []) if isinstance(data, dict) else []:
            if entry.get("type") == "google_sheet":
                assert entry["google_sheet"]["spreadsheet_id"].startswith("fake-"), f
        if isinstance(data, dict) and "spreadsheet_id" in data:
            assert str(data["spreadsheet_id"]).startswith("fake-"), f


def test_examples_demo_client_is_the_only_clients_shaped_tree(tracked):
    demo_files = [f for f in tracked if f.startswith("examples/demo-client/")]
    assert demo_files, "expected examples/demo-client/ to be tracked (the synthetic fixture)"


def test_gitignore_covers_required_patterns(repo_root: Path):
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ["private/", "context/generated/", "clients/", ".env", "*.key", "*.pem", "client_secret*.json", "*google-sheets-token*.json"]:
        assert pattern in gitignore, f".gitignore missing pattern: {pattern}"


# --- Content guards (structural patterns only; no real PII lives here) ---

# The pilot client id is already public (CLAUDE.md). It may appear in prose
# docs, but never in code, tests or fixtures, where it would mean real data
# was pasted in. Files listed here only mention it to assert its absence.
PILOT_CLIENT_ID = "walmaq"
CODE_AND_FIXTURE_PREFIXES = ("tests/", "examples/", "scripts/")
CODE_AND_FIXTURE_SUFFIXES = (".py", ".json", ".csv", ".txt", ".jsonl")
PILOT_ID_GUARD_FILES = {
    "tests/security/test_public_hygiene.py",
    "tests/intelligence/test_schemas.py",
    "tests/operating_loop/test_demo_artifacts.py",
    "scripts/doctor.py",
}
TEXT_SUFFIXES = {".py", ".json", ".md", ".csv", ".txt", ".jsonl", ".yml", ".yaml", ".toml", ".cfg", ".ini", ""}

CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
BR_PHONE_RE = re.compile(r"\+55\s?\(?\d{2}\)?\s?9?\d{4}-?\d{4}|\(\d{2}\)\s?9\d{4}-\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "anthropic.com")


def _tracked_text(repo_root: Path, tracked: list[str]):
    for f in tracked:
        if Path(f).suffix.lower() not in TEXT_SUFFIXES:
            continue
        path = repo_root / f
        if not path.is_file():
            continue
        try:
            yield f, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def _is_code_or_fixture(f: str) -> bool:
    if f.startswith(CODE_AND_FIXTURE_PREFIXES) or (f.startswith("skills/") and "/scripts/" in f):
        return f.endswith(CODE_AND_FIXTURE_SUFFIXES)
    return False


def test_pilot_client_id_never_in_code_or_fixtures(repo_root: Path, tracked):
    """Fixtures must be synthetic from the origin (CLAUDE.md 27.1); the
    pilot id inside code/tests/examples is a strong signal of copied data."""
    offenders = [
        f for f, text in _tracked_text(repo_root, tracked)
        if _is_code_or_fixture(f) and f not in PILOT_ID_GUARD_FILES and PILOT_CLIENT_ID in text.lower()
    ]
    assert not offenders, f"pilot client id found in code/fixtures (use a synthetic client): {offenders}"


def test_no_personal_identifier_shaped_values_tracked(repo_root: Path, tracked):
    """CNPJ/CPF/BR phone/e-mail shaped values never belong in the public
    engine. Reports file and kind only — never the matched value."""
    offenders = []
    for f, text in _tracked_text(repo_root, tracked):
        for kind, rx in (("cnpj", CNPJ_RE), ("cpf", CPF_RE), ("br_phone", BR_PHONE_RE)):
            if rx.search(text):
                offenders.append((f, kind))
        for m in EMAIL_RE.finditer(text):
            if not m.group(0).lower().split("@", 1)[1].endswith(ALLOWED_EMAIL_DOMAINS):
                offenders.append((f, "email"))
                break
    assert not offenders, f"personal-identifier-shaped values tracked: {offenders}"
