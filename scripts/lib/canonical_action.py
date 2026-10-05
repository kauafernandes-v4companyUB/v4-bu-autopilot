"""Shared V1 contract for canonical-mutating ACTIONs:

    PREVIEW -> base_state_hash + preview_hash -> approval bound to both
            -> APPLY (gate re-derives everything; STALE_APPROVAL on drift)
            -> atomic multi-file write -> receipt

Used by scripts/lib/memory_promotion.py and scripts/lib/quarter_lifecycle.py.
Nothing here decides content; it only hashes, gates and writes exactly what
an approved preview already declared.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from scripts.lib import approval as ap
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.receipt import build_receipt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTION_TIMESTAMP_KEYS = frozenset({
    "generated_at", "added_at", "promoted_at", "historized_at", "applied_at", "updated_at", "created_at",
    "planned_at", "closed_at",
})


def notice(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def semantic(value):
    """Drop execution-timestamp keys recursively (CLAUDE.md section 26):
    they record when the system acted, not what was proposed."""
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in EXECUTION_TIMESTAMP_KEYS}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# canonical state
# ---------------------------------------------------------------------------


def _file_sha(path: Path) -> Optional[str]:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_state(client_dir: Path, files: list[str]) -> dict:
    """Canonical content of `files` (relative to client_dir). Missing -> None.
    A name ending in "/" is a directory -> {relative file: sha256}."""
    state: dict = {}
    for name in files:
        path = client_dir / name.rstrip("/")
        if name.endswith("/"):
            state[name] = ({str(p.relative_to(path)).replace("\\", "/"): _file_sha(p)
                            for p in sorted(path.rglob("*")) if p.is_file()} if path.is_dir() else None)
        elif not path.is_file():
            state[name] = None
        elif name.endswith(".json"):
            state[name] = json.loads(path.read_text(encoding="utf-8"))
        else:
            state[name] = path.read_text(encoding="utf-8")
    return state


def state_hash(client_dir: Path, files: list[str]) -> str:
    return content_sha256(read_state(client_dir, files))


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

_REGISTRY: Optional[Registry] = None


def registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        resources = []
        for f in sorted((REPO_ROOT / "schemas").glob("*.json")) + sorted((REPO_ROOT / "skills").glob("*/output.schema.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            if "$id" in data:
                resources.append((data["$id"], Resource.from_contents(data)))
        _REGISTRY = Registry().with_resources(resources)
    return _REGISTRY


def schema_errors(instance, schema: str) -> list[str]:
    """`schema` is a repo-relative path or an absolute $id/$ref URI."""
    if schema.startswith("https://"):
        doc = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": schema}
    else:
        doc = json.loads((REPO_ROOT / schema).read_text(encoding="utf-8"))
    return [f"{list(e.path)}: {e.message}" for e in Draft202012Validator(doc, registry=registry()).iter_errors(instance)]


# ---------------------------------------------------------------------------
# approval binding
# ---------------------------------------------------------------------------


def approval_payload(preview: dict) -> dict:
    return {"client_id": preview["client_id"], "base_state_hash": preview["base_state_hash"],
            "preview_hash": preview["preview_hash"]}


def build_approval_candidate(preview: dict, *, item_id: str, item_type: str, source_type: str,
                             approval_id: str, created_at: str, preview_path: str,
                             quarter_id: Optional[str] = None) -> dict:
    """status=draft only — becomes real exclusively through
    approval.apply_operator_decision on an explicit operator request."""
    if preview.get("mode") != "preview" or preview.get("status") != "success" or not preview.get("preview_hash"):
        raise ap.ApprovalError("only a successful, hash-bound preview can be proposed for approval")
    return ap.build_approval_candidate(
        approval_id=approval_id, client_id=preview["client_id"], quarter_id=quarter_id, created_at=created_at,
        source_artifact_type=source_type, source_artifact_id=f"{preview['client_id']}:{preview['preview_hash'][:16]}",
        source_artifact=preview, source_artifact_path=preview_path,
        candidate_items=[{"item_id": item_id, "item_type": item_type, "payload": approval_payload(preview)}],
    )


def check_gate(preview: Optional[dict], approval: Optional[dict], client_dir: Path, *,
               item_id: str, item_type: str, bound_files: list[str],
               recompute_preview_hash: Callable[[dict], str]) -> list[dict]:
    """Any notice returned means the apply must perform zero writes."""
    if preview is None or preview.get("mode") != "preview":
        return [notice("NO_PREVIEW", "apply requires the approved preview output (mode=preview)")]
    if not preview.get("preview_hash") or not preview.get("base_state_hash"):
        return [notice("PREVIEW_NOT_HASH_BOUND", "preview has no preview_hash/base_state_hash (legacy output); re-run preview")]
    if preview.get("status") != "success":
        return [notice("NO_PREVIEW", f"preview status is {preview.get('status')!r}; only a success preview is applicable")]
    if recompute_preview_hash(preview) != preview["preview_hash"]:
        return [notice("STALE_APPROVAL", "preview payload was changed after preview_hash was computed")]
    if approval is None:
        return [notice("NO_APPROVAL", "apply requires an explicit operator approval record (schemas/approval.schema.json)")]
    if approval.get("client_id") != preview["client_id"]:
        return [notice("CLIENT_ISOLATION", "approval belongs to a different client")]
    covered = [i for i in approval.get("scope", {}).get("approved_items", [])
               if i.get("item_id") == item_id and i.get("item_type") == item_type]
    if not covered:
        return [notice("NO_APPROVAL", f"approval does not cover {item_id!r}")]
    bad = [c for c in ap.validate_approval(approval, preview, {item_id: approval_payload(preview)}) if not c.ok]
    if bad:
        return [notice("STALE_APPROVAL", bad[0].reason)]
    if state_hash(client_dir, bound_files) != preview["base_state_hash"]:
        return [notice("STALE_APPROVAL", "canonical state changed since the preview (base_state_hash mismatch); re-run preview and re-approve")]
    return []


# ---------------------------------------------------------------------------
# atomic multi-file write + receipt
# ---------------------------------------------------------------------------


def serialize_json(data) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_multi_write(client_dir: Path, writes: dict[str, bytes]) -> None:
    """Write every file or none: stage temp files next to each target
    (fsync), then rename in order; on any failure restore the originals
    and remove the files this call created."""
    staged: list[tuple[Path, str]] = []
    backups: dict[Path, Optional[bytes]] = {}
    try:
        for rel, data in writes.items():
            target = client_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            backups[target] = target.read_bytes() if target.is_file() else None
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            staged.append((target, tmp))
        done: list[Path] = []
        try:
            for target, tmp in staged:
                os.replace(tmp, target)
                done.append(target)
        except BaseException:
            for target in done:
                if backups[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(backups[target])
            raise
    finally:
        for _, tmp in staged:
            if os.path.exists(tmp):
                os.remove(tmp)


def build_action_receipt(*, action: str, client_id: str, preview: dict, approval: Optional[dict],
                         executed_at: str, status: str, effects: list[dict]) -> dict:
    return build_receipt(
        receipt_id=f"{action}-{client_id}-{preview['preview_hash'][:12]}", action=action, client_id=client_id,
        executed_at=executed_at, input_payload={"preview_hash": preview["preview_hash"],
                                                "base_state_hash": preview["base_state_hash"]},
        approval_id=(approval or {}).get("approval_id"), status=status, effects=effects,
    )


def effect(rel_target: str, operation: str, before: Optional[bytes], after: Optional[bytes]) -> dict:
    sha = lambda b: hashlib.sha256(b).hexdigest() if b is not None else None  # noqa: E731
    return {"target": rel_target, "operation": operation, "before_hash": sha(before), "after_hash": sha(after),
            "external_id": None, "external_url": None}
