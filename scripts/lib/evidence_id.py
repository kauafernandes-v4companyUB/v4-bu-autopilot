"""Deterministic evidence_id computation for promoted external observations.

Reference implementation of the algorithm documented in
skills/promote-client-memory/SKILL.md section 17.1.1: an evidence_id for an
observation promoted directly to the evidence ledger (target_file =
"evidence.json") is derived only from stable identity fields — never from a
timestamp, a computed value, or discovery order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

PREFIX = "evobs-"
HEX_LENGTH = 16


def compute_evidence_id(
    client_id: str,
    source_skill: Optional[str],
    source_type: str,
    source_observation_id: str,
    source_file_sha256: Optional[str],
) -> str:
    """Compute the deterministic evidence_id for a promoted observation.

    Identity = SHA-256 of the canonical JSON (sorted keys, compact
    separators, UTF-8) of {client_id, source_skill, source_type,
    source_observation_id, source_file_sha256}, first 16 hex chars,
    prefixed with "evobs-".
    """
    if not client_id or not source_type or not source_observation_id:
        raise ValueError(
            "client_id, source_type and source_observation_id are required "
            "to compute a deterministic evidence_id"
        )
    identity = {
        "client_id": client_id,
        "source_skill": source_skill,
        "source_type": source_type,
        "source_observation_id": source_observation_id,
        "source_file_sha256": source_file_sha256,
    }
    canonical = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return PREFIX + digest[:HEX_LENGTH]
