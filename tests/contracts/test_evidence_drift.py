"""test_evidence_contract_compatibility (mission section 22).

Every universal evidence (schemas/evidence.schema.json) that
promote-client-memory would legitimately promote must be projectable into
a valid canonical_evidence_item (schemas/client-evidence.schema.json)
without losing any required field. This is the explicit drift guard
between the two schemas — if someone adds a new required field to one
schema without a corresponding source in the other, this test fails.
"""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from scripts.lib.evidence_projection import project_to_canonical


def _canonical_item_errors(instance: dict, repo_root, registry) -> list[str]:
    """Validate against #/$defs/canonical_evidence_item directly, since
    the top level of client-evidence.schema.json is the ledger wrapper
    ({schema_version, client_id, updated_at, evidences: [...]}), not a
    single item."""
    schema_doc = json.loads((repo_root / "schemas" / "client-evidence.schema.json").read_text(encoding="utf-8"))
    item_schema = {**schema_doc["$defs"]["canonical_evidence_item"], "$id": schema_doc["$id"]}
    validator = Draft202012Validator(item_schema, registry=registry)
    return [f"{list(e.path)}: {e.message}" for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))]

MINIMAL_UNIVERSAL_EVIDENCE = {
    "evidence_id": "synthtest-ev-0001",
    "client_id": "synthtest",
    "source_type": "pdf",
    "observed_at": "2026-01-01T00:00:00Z",
    "type": "metric",
    "statement": "synthetic test evidence",
    "confidence": "medium",
    "reference": {"label": "synthetic reference"},
}

FULL_UNIVERSAL_EVIDENCE = {
    **MINIMAL_UNIVERSAL_EVIDENCE,
    "evidence_id": "synthtest-ev-0002",
    "source_skill": "read-bi",
    "source_name": "synthetic-source.pdf",
    "source_date": None,
    "value": 123.45,
    "unit": "brl",
    "period": {"from": "2026-01-01", "to": "2026-01-15"},
    "external_provenance": {
        "source_observation_id": "biobs-synth-0001",
        "source_file_sha256": "a" * 64,
        "source_output": "context/generated/synthtest/bi/read-bi.json",
    },
    "tags": ["spend", "meta_ads"],
    "reference": {
        "label": "synthetic reference",
        "uri": None,
        "path": "private/clients/synthtest/bi/fake.pdf",
        "location": "Investido R$ 123,45",
        "page": 1,
        "row": None,
        "column": None,
    },
}


def _validate(instance, schema_path, validate):
    errors = validate(instance, schema_path)
    assert not errors, "\n".join(errors)


def test_minimal_universal_evidence_is_schema_valid(validate, repo_root):
    _validate(MINIMAL_UNIVERSAL_EVIDENCE, repo_root / "schemas" / "evidence.schema.json", validate)


def test_full_universal_evidence_is_schema_valid(validate, repo_root):
    _validate(FULL_UNIVERSAL_EVIDENCE, repo_root / "schemas" / "evidence.schema.json", validate)


def test_minimal_universal_evidence_projects_to_valid_canonical_item(repo_root, schema_registry):
    canonical = project_to_canonical(MINIMAL_UNIVERSAL_EVIDENCE, added_at="2026-01-01T00:05:00Z")
    errors = _canonical_item_errors(canonical, repo_root, schema_registry)
    assert not errors, "\n".join(errors)


def test_full_universal_evidence_projects_to_valid_canonical_item(repo_root, schema_registry):
    canonical = project_to_canonical(
        FULL_UNIVERSAL_EVIDENCE, added_at="2026-01-01T00:05:00Z", source_id="synthetic-bi-export"
    )
    errors = _canonical_item_errors(canonical, repo_root, schema_registry)
    assert not errors, "\n".join(errors)


def test_projection_never_elevates_semantic_type():
    for semantic_type in ["fact", "metric", "decision", "hypothesis", "request", "commitment", "pending", "risk", "idea", "dependency"]:
        universal = {**MINIMAL_UNIVERSAL_EVIDENCE, "type": semantic_type}
        canonical = project_to_canonical(universal, added_at="2026-01-01T00:05:00Z")
        assert canonical["type"] == semantic_type, "promotion must never change the semantic type (CLAUDE.md section 5)"


def test_projection_preserves_confidence_without_rounding_up():
    for confidence in ["low", "medium", "high"]:
        universal = {**MINIMAL_UNIVERSAL_EVIDENCE, "confidence": confidence}
        canonical = project_to_canonical(universal, added_at="2026-01-01T00:05:00Z")
        assert canonical["confidence"] == confidence
