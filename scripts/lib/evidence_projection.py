"""Project a universal evidence object (schemas/evidence.schema.json) into
the shape required by the canonical ledger item
(schemas/client-evidence.schema.json#/$defs/canonical_evidence_item).

Both promote-client-memory (writing clients/<client_id>/evidence.json) and
monitor-quarter's evidence_overlay preview projection (SKILL.md section
5.1, step 3) perform this same mapping. Centralizing it here is also what
powers tests/contracts/test_evidence_drift.py (CLAUDE.md/mission section
22): if the two schemas drift apart such that a valid universal evidence
can no longer be projected into a valid canonical item, that test fails
loudly instead of silently at promotion time.
"""

from __future__ import annotations

from typing import Optional


def project_to_canonical(
    universal_evidence: dict,
    *,
    added_at: str,
    added_by: str = "promote-client-memory",
    source_id: Optional[str] = None,
) -> dict:
    """Build a canonical_evidence_item dict from a universal evidence dict.

    Only performs the field mapping — callers are responsible for JSON
    Schema validation of both the input and the output (see
    tests/contracts/test_evidence_drift.py).
    """
    reference = universal_evidence.get("reference") or {}
    source_reference = {
        "label": reference.get("label"),
        "source_location": reference.get("path") or reference.get("uri"),
        "page": reference.get("page"),
        "row": reference.get("row"),
        "column": reference.get("column"),
        "section": None,
        "uri": reference.get("uri"),
    }

    canonical = {
        "evidence_id": universal_evidence["evidence_id"],
        "client_id": universal_evidence["client_id"],
        "type": universal_evidence["type"],
        "statement": universal_evidence["statement"],
        "value": universal_evidence.get("value"),
        "unit": universal_evidence.get("unit"),
        "confidence": universal_evidence["confidence"],
        "observed_at": universal_evidence["observed_at"],
        "source_date": universal_evidence.get("source_date"),
        "period": universal_evidence.get("period"),
        "source_id": source_id,
        "source_kind": universal_evidence.get("source_type", "unknown"),
        "source_skill": universal_evidence.get("source_skill"),
        "source_reference": source_reference,
        "external_provenance": universal_evidence.get("external_provenance"),
        "tags": universal_evidence.get("tags", []),
        "added_at": added_at,
        "added_by": added_by,
    }
    return canonical
