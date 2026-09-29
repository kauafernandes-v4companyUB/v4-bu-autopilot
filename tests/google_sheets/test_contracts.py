from __future__ import annotations

import json

from scripts.lib.google_sheets_patch import APPROVAL_ITEM_TYPE, APPROVAL_SOURCE_TYPE, build_patch_approval_candidate
from scripts.lib.google_sheets_sources import resolve_sheet_binding

from .conftest import CLIENT_ID, Q, SOURCE_ID, base_patch


def _load(repo_root, rel):
    return json.loads((repo_root / rel).read_text(encoding="utf-8"))


def test_demo_google_sheet_sources_validate_and_resolve(repo_root, validate, demo_client_dir):
    sources = json.loads((demo_client_dir / "sources.json").read_text(encoding="utf-8"))
    sheets = [s for s in sources["sources"] if s["type"] == "google_sheet"]
    assert sheets, "demo client should demonstrate a synthetic google_sheet source"
    for entry in sheets:
        assert not validate(entry, repo_root / "schemas" / "google-sheet-source.schema.json")
        assert entry["google_sheet"]["spreadsheet_id"].startswith("fake-")
    binding = resolve_sheet_binding(sources, "acme-demo", source_id="acme-demo-metrics-sheet")
    assert binding.writable


def test_example_patch_validates(repo_root, validate):
    patch = _load(repo_root, "examples/google-sheets/acme-demo-metrics-patch.json")
    assert not validate(patch, repo_root / "schemas" / "google-sheet-patch.schema.json")


def test_patch_schema_rejects_structural_and_formula_as_value(repo_root, validate):
    schema = repo_root / "schemas" / "google-sheet-patch.schema.json"
    structural = base_patch(operations=[{"op_id": "x", "type": "insert_rows", "range": f"{Q}!A1"}])
    assert validate(structural, schema)
    bad_formula = base_patch(operations=[{"op_id": "x", "type": "write_formula", "range": f"{Q}!A1", "formulas": [["A1+1"]]}])
    assert validate(bad_formula, schema)
    extra_key = base_patch(operations=[{"op_id": "x", "type": "clear_value", "range": f"{Q}!A1", "values": [[1]]}])
    assert validate(extra_key, schema)
    no_locator = base_patch()
    no_locator.pop("source_id")
    assert validate(no_locator, schema)


def test_approval_candidate_validates_against_approval_schema(transport, sources_doc, repo_root, validate):
    from scripts.lib.google_sheets_patch import preview_patch

    preview = preview_patch(transport, client_id=CLIENT_ID, patch=base_patch(), sources_doc=sources_doc)
    cand = build_patch_approval_candidate(preview, approval_id="appr-x", created_at="2026-01-01T00:00:00Z", preview_path="p.json")
    assert cand["status"] == "draft" and cand["approved_by"] is None
    assert cand["source_artifact"]["type"] == APPROVAL_SOURCE_TYPE
    assert cand["scope"]["approved_items"][0]["item_type"] == APPROVAL_ITEM_TYPE
    assert not validate(cand, repo_root / "schemas" / "approval.schema.json")


def test_registry_declares_honest_categories(repo_root):
    reg = {e["id"]: e for e in _load(repo_root, "skills/registry.json")["skills"]}
    assert reg["read-google-sheet"]["category"] == "SOURCE"
    assert reg["read-google-sheet"]["canonical_side_effects"] == "NONE"
    assert reg["update-google-sheet"]["category"] == "ACTION"
    assert reg["update-google-sheet"]["canonical_side_effects"] == "EXTERNAL"


def test_source_id_constant_used(sources_doc):
    assert resolve_sheet_binding(sources_doc, CLIENT_ID, source_id=SOURCE_ID).source_id == SOURCE_ID
