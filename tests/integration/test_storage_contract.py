"""Bootstrap, storage classes and doctor client checks
(operation/storage-contract.md). Synthetic clients in a temp workspace only."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from scripts import doctor
from scripts.bootstrap_client import bootstrap_client
from scripts.lib import storage_contract as storage
from scripts.lib.workspace import resolve_workspace


def _boot(ws: Path, client_id: str = "acme-demo", **kw) -> dict:
    return bootstrap_client(client_id, display_name=kw.pop("display_name", "Acme Demo (synthetic)"), workspace_root=str(ws), **kw)


def _doctor(ws: Path) -> dict:
    return doctor.check_client_workspace_integrity(resolve_workspace(required=True, override=str(ws)), doctor._schema_registry())


def _fails(results: dict) -> dict:
    return {k: v[1] for k, v in results.items() if v[0] == "FAIL"}


def test_bootstrap_creates_schema_valid_client_without_invented_state(temp_workspace, validate, repo_root):
    out = _boot(temp_workspace)
    assert out["status"] == "CREATED"
    client = temp_workspace / "clients" / "acme-demo"
    assert storage.missing_required(client) == []
    for rel, schema in storage.CANONICAL_SCHEMAS.items():
        if (client / rel).is_file():
            assert validate(json.loads((client / rel).read_text(encoding="utf-8")), repo_root / schema) == [], rel
    assert not list((client / "quarters").glob("*/plan.json"))
    for lazy in ("operations.json", "source-manifest.json", "receipts"):
        assert not (client / lazy).exists()
    assert json.loads((client / "tasks.json").read_text(encoding="utf-8"))["tasks"] == []
    assert json.loads((client / "decisions.json").read_text(encoding="utf-8"))["decisions"] == []
    assert json.loads((client / "evidence.json").read_text(encoding="utf-8"))["evidences"] == []
    assert _fails(_doctor(temp_workspace)) == {}  # a fresh client with no Quarter is valid


def test_bootstrap_is_idempotent_and_never_overwrites(temp_workspace):
    assert _boot(temp_workspace)["status"] == "CREATED"
    assert _boot(temp_workspace)["status"] == "NO_CHANGE"
    state = temp_workspace / "clients" / "acme-demo" / "current-state.json"
    data = json.loads(state.read_text(encoding="utf-8"))
    data["status"] = "active"
    state.write_text(json.dumps(data), encoding="utf-8")
    before = state.read_bytes()
    out = _boot(temp_workspace)
    assert out["status"] == "CONFLICT" and "current-state.json" in out["diverged"]
    assert state.read_bytes() == before


@pytest.mark.parametrize("bad", ["Acme", "acme_demo", "../acme", "a", "-acme", "acme/x", ""])
def test_bootstrap_rejects_invalid_slugs(temp_workspace, bad):
    assert _boot(temp_workspace, bad)["status"] == "ERROR"
    assert not any((temp_workspace / "clients").iterdir())


def test_initial_sources_and_context_land_in_the_right_class(temp_workspace):
    sources = [{"source_id": "acme-whatsapp", "type": "client_whatsapp_export", "location": "private/clients/acme-demo/whatsapp/", "canonical": False}]
    out = _boot(temp_workspace, initial_sources=sources, initial_context="[synthetic] context note")
    assert out["status"] == "CREATED"
    assert json.loads((temp_workspace / "clients/acme-demo/sources.json").read_text(encoding="utf-8"))["sources"] == sources
    raw = [w for w in out["written"] if w.startswith("private/")]
    assert raw and all(storage.classify(w) == "RAW" for w in raw)
    assert _boot(temp_workspace, initial_sources=[{"source_id": "x"}])["status"] in ("ERROR", "NO_CHANGE", "CONFLICT")


@pytest.mark.parametrize(("rel", "expected"), [
    ("private/clients/acme-demo/whatsapp/chat.txt", "RAW"),
    ("clients/acme-demo/knowledge.json", "CANONICAL"),
    ("clients/acme-demo/receipts/r.json", "RECEIPT"),
    ("context/generated/acme-demo/brief.json", "TRANSIENT"),
    ("context\\generated\\acme-demo\\brief.json", "TRANSIENT"),
    ("private\\clients\\acme-demo\\bi\\x.pdf", "RAW"),
    ("README.md", "UNKNOWN"),
])
def test_storage_classes_are_separator_independent(rel, expected):
    assert storage.classify(rel) == expected


@pytest.mark.parametrize("case", ["incomplete", "invalid_json", "raw_inside", "schema", "two_active", "quarter_mismatch", "manifest", "orphan_receipt", "closed_no_closure"])
def test_doctor_detects_client_problems(temp_workspace, case, repo_root):
    _boot(temp_workspace)
    c = temp_workspace / "clients" / "acme-demo"
    plan = json.loads((repo_root / "examples/demo-client/acme-demo/quarters/2026-Q1/plan.json").read_text(encoding="utf-8"))
    plan["client_id"] = "acme-demo"
    if case == "incomplete":
        (c / "decisions.json").unlink()
        label = "Canonical memory"
    elif case == "invalid_json":
        (c / "knowledge.json").write_text("{not json", encoding="utf-8")
        label = "Canonical memory"
    elif case == "raw_inside":
        (c / "bi").mkdir()
        (c / "bi" / "export.pdf").write_bytes(b"%PDF-synthetic")
        label = "Raw isolation"
    elif case == "schema":
        data = json.loads((c / "client.json").read_text(encoding="utf-8"))
        del data["display_name"]
        (c / "client.json").write_text(json.dumps(data), encoding="utf-8")
        label = "Canonical memory"
    elif case == "two_active":
        for q in ("2026-Q1", "2026-Q2"):
            (c / "quarters" / q).mkdir()
            (c / "quarters" / q / "plan.json").write_text(json.dumps({**plan, "quarter_id": q, "status": "active"}), encoding="utf-8")
        label = "Quarter integrity"
    elif case == "quarter_mismatch":
        (c / "quarters" / "2026-Q3").mkdir()
        (c / "quarters" / "2026-Q3" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        label = "Quarter integrity"
    elif case == "manifest":
        (c / "source-manifest.json").write_text(json.dumps({"schema_version": "1.0.0", "client_id": "acme-demo", "updated_at": None, "sources": [{"source_id": "x"}]}), encoding="utf-8")
        label = "Source manifest"
    elif case == "orphan_receipt":
        (c / "receipts").mkdir()
        (c / "receipts" / "r1.json").write_text(json.dumps({
            "schema_version": "1.0.0", "receipt_id": "r1", "action": "promote-client-memory", "client_id": "acme-demo",
            "executed_at": "2026-10-01T10:00:00Z", "input_hash": "a" * 64, "approval_id": "appr", "status": "success",
            "effects": [{"target": "clients/acme-demo/history/missing.json", "operation": "create", "before_hash": None,
                         "after_hash": "b" * 64, "external_id": None, "external_url": None}], "warnings": [], "errors": []}), encoding="utf-8")
        label = "Receipts"
    else:
        (c / "quarters" / "2026-Q1").mkdir()
        (c / "quarters" / "2026-Q1" / "plan.json").write_text(json.dumps({**plan, "status": "closed"}), encoding="utf-8")
        label = "Quarter integrity"
    fails = _fails(_doctor(temp_workspace))
    assert label in fails, fails


def test_placeholder_directory_is_not_a_client(temp_workspace):
    _boot(temp_workspace)
    reserved = temp_workspace / "clients" / "reserved-name"
    reserved.mkdir()
    (reserved / ".workspace-placeholder").write_text("{}", encoding="utf-8")
    assert storage.is_placeholder(reserved)
    assert _fails(_doctor(temp_workspace)) == {}


def test_workspace_root_comes_from_env_or_argument_with_either_path_style(monkeypatch, temp_workspace):
    monkeypatch.setenv("V4_BU_WORKSPACE_ROOT", str(temp_workspace))
    assert resolve_workspace(required=True).root == temp_workspace.resolve()
    assert PureWindowsPath(r"C:\ws\clients\acme-demo\tasks.json").parts[-3:] == PurePosixPath("/ws/clients/acme-demo/tasks.json").parts[-3:]


def test_core_code_has_no_personal_or_absolute_paths(repo_root):
    import re
    pattern = re.compile(r"(?i)([A-Z]:[\\/](Users|Trabalho)|~/Documentos|/home/[a-z]|/Users/[A-Za-z])")
    offenders = []
    for p in list((repo_root / "scripts").rglob("*.py")) + list((repo_root / "skills").rglob("scripts/*.py")):
        if pattern.search(p.read_text(encoding="utf-8")):
            offenders.append(p.relative_to(repo_root).as_posix())
    assert not offenders, offenders
