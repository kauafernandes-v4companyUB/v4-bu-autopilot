"""Reference evidence resolution logic for monitor-quarter's preview-only
evidence_overlay extension (skills/monitor-quarter/SKILL.md section 5.1).

Pure functions, no I/O, no schema validation (that's jsonschema's job,
against schemas/evidence.schema.json and schemas/client-evidence.schema.json
— see tests/contracts). This module only encodes the *resolution order and
conflict rule*: canonical ledger first, overlay second, exact-ID match
only, canonical always wins on conflict (never silently).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Fields compared to decide whether a canonical entry and an overlay entry
# that share an evidence_id are "the same evidence" or a genuine conflict.
_COMPARABLE_FIELDS = ("statement", "type", "confidence", "value", "unit")


@dataclass(frozen=True)
class Resolution:
    evidence_id: str
    resolved_from: str  # "canonical" | "overlay" | "unresolved"
    reason: str
    item: Optional[dict] = None


def _period_equal(a: Optional[dict], b: Optional[dict]) -> bool:
    return (a or None) == (b or None)


def _same_content(canonical_item: dict, overlay_item: dict) -> bool:
    for field in _COMPARABLE_FIELDS:
        if canonical_item.get(field) != overlay_item.get(field):
            return False
    return _period_equal(canonical_item.get("period"), overlay_item.get("period"))


def resolve_evidence_id(
    evidence_id: str,
    *,
    client_id: str,
    canonical_evidences: list[dict],
    overlay_evidences: list[dict],
) -> Resolution:
    """Resolve a single evidence_id per SKILL.md section 5.1 step 1-3.

    Does not perform JSON Schema validation of overlay items — callers
    that need "universal_schema_valid" / "canonical_shape_valid" should
    run jsonschema separately and treat a failure there as equivalent to
    "not found in overlay" before calling this function.
    """
    canonical_matches = [e for e in canonical_evidences if e.get("evidence_id") == evidence_id]
    overlay_matches = [e for e in overlay_evidences if e.get("evidence_id") == evidence_id]

    if canonical_matches:
        canonical_item = canonical_matches[0]
        if overlay_matches and not _same_content(canonical_item, overlay_matches[0]):
            return Resolution(
                evidence_id=evidence_id,
                resolved_from="unresolved",
                reason="overlay_conflict: same evidence_id present in canonical ledger and overlay with different content",
            )
        return Resolution(evidence_id=evidence_id, resolved_from="canonical", reason="found in canonical ledger", item=canonical_item)

    if not overlay_matches:
        return Resolution(evidence_id=evidence_id, resolved_from="unresolved", reason="not found in canonical ledger or overlay")

    overlay_item = overlay_matches[0]
    if overlay_item.get("client_id") != client_id:
        return Resolution(
            evidence_id=evidence_id,
            resolved_from="unresolved",
            reason=f"overlay item client_id {overlay_item.get('client_id')!r} does not match execution client_id {client_id!r}",
        )

    return Resolution(evidence_id=evidence_id, resolved_from="overlay", reason="found in overlay, client_id matches, no canonical conflict", item=overlay_item)


def resolve_all(
    evidence_ids: list[str],
    *,
    client_id: str,
    canonical_evidences: list[dict],
    overlay_evidences: list[dict],
) -> list[Resolution]:
    return [
        resolve_evidence_id(
            eid, client_id=client_id, canonical_evidences=canonical_evidences, overlay_evidences=overlay_evidences
        )
        for eid in evidence_ids
    ]
