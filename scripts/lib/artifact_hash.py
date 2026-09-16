"""Canonical JSON hashing + upstream artifact-chain integrity for the
Intelligence pipeline (operation/replanning-rules.md).

Each artifact after context-pack.json cites `artifact_ref`s (schema:
schemas/artifact-ref.schema.json) to the exact upstream artifacts it was
computed from. This module computes those hashes and verifies that a
downstream artifact's stored reference still matches what's actually on
disk — catching a stale chain (e.g. gaps.json computed against a
context-pack.json that has since been regenerated) before it silently
propagates into a replanning or a task proposal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def canonical_json_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_sha256(obj: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def make_artifact_ref(obj: dict, *, artifact_id_field: str, artifact_type: str, path: str) -> dict:
    """Build an artifact-ref dict (schemas/artifact-ref.schema.json) pointing at `obj`."""
    if artifact_id_field not in obj:
        raise KeyError(f"artifact is missing its own id field {artifact_id_field!r}")
    return {
        "artifact_id": obj[artifact_id_field],
        "artifact_type": artifact_type,
        "content_sha256": content_sha256(obj),
        "path": path,
    }


@dataclass(frozen=True)
class ChainCheck:
    artifact_type: str
    ok: bool
    reason: str


def verify_artifact_ref(ref: dict, current_obj: Optional[dict]) -> ChainCheck:
    """Verify a stored artifact_ref against the artifact it claims to point
    to, re-loaded fresh from disk. current_obj=None means the upstream
    artifact no longer exists at all."""
    artifact_type = ref.get("artifact_type", "unknown")
    if current_obj is None:
        return ChainCheck(artifact_type, False, f"upstream artifact at {ref.get('path')} no longer exists")
    actual_hash = content_sha256(current_obj)
    if actual_hash != ref.get("content_sha256"):
        return ChainCheck(
            artifact_type, False,
            f"stale upstream: ref content_sha256={ref.get('content_sha256')} but current file hashes to {actual_hash}",
        )
    return ChainCheck(artifact_type, True, "matches current upstream artifact")


def verify_artifact_ref_from_path(ref: dict, base_dir: Path) -> ChainCheck:
    """Same as verify_artifact_ref, but loads the upstream artifact from
    `base_dir / ref['path']` (or an absolute ref['path'])."""
    path = Path(ref["path"])
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        return ChainCheck(ref.get("artifact_type", "unknown"), False, f"upstream artifact file not found: {path}")
    current_obj = json.loads(path.read_text(encoding="utf-8"))
    return verify_artifact_ref(ref, current_obj)
