"""Hash binding, approval gate and reference apply for
skills/promote-client-memory/SKILL.md (sections 17, 17.1.1 and 17.2).

Same pattern as the rest of the operating loop (scripts/lib/approval.py,
scripts/lib/google_sheets_patch.py):

    PREVIEW -> mutation_plan -> preview_hash -> approval bound to it
            -> APPLY (re-reads canonical state; any drift = STALE_APPROVAL)

- `base_state_hash` covers every canonical file the promotion depends on or
  may modify: always evidence.json, knowledge.json, current-state.json and
  decisions.json, plus any other target_file named by the plan
  (client.json, sources.json, strategy.md, history/).
- `preview_hash` covers client_id, base_state_hash, the promotion plan, the
  proposed evidence and the mutation plan — with execution timestamps
  (generated_at, added_at, promoted_at, ...) stripped, so regenerating an
  identical preview at another time yields the same hash.
- Apply never trusts a hash written by hand next to the preview: it
  recomputes both hashes from the preview content and from canonical state
  on disk, and validates the approval record against the exact preview.

The reference apply writes only the evidence ledger (direct promotion of
normalized external observations, SKILL.md 17.1.1). A plan that also
targets other canonical files must still pass `check_apply_gate` before
any of those writes; this module refuses to apply them itself.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from scripts.lib import approval as ap
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.evidence_projection import project_to_canonical
from scripts.lib.exec_clock import utc_now_rfc3339

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_SCHEMA_VERSION = "1.1.0"
APPROVAL_ITEM_TYPE = "memory_promotion"
APPROVAL_SOURCE_TYPE = "memory_promotion_preview"
ALWAYS_BOUND_FILES = ("evidence.json", "knowledge.json", "current-state.json", "decisions.json")
OPTIONAL_TARGET_FILES = ("client.json", "sources.json", "strategy.md")
WRITING_ACTIONS = {"promote", "supersede", "historize"}
EXECUTION_TIMESTAMP_KEYS = {
    "generated_at", "added_at", "promoted_at", "historized_at", "applied_at", "updated_at", "created_at",
}
EVIDENCE_MATERIAL_FIELDS = (
    "statement", "type", "value", "unit", "confidence", "source_date", "period",
    "source_kind", "source_reference", "source_skill", "external_provenance",
)


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------


def semantic(value):
    """Drop execution-timestamp keys recursively (CLAUDE.md section 26):
    they record when the system acted, not what it proposes."""
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in EXECUTION_TIMESTAMP_KEYS}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def bound_files(promotion_plan: list[dict]) -> list[str]:
    targets = set(ALWAYS_BOUND_FILES)
    for cand in promotion_plan:
        target = cand.get("target_file")
        if target in OPTIONAL_TARGET_FILES or target == "history":
            targets.add("history/" if target == "history" else target)
    return sorted(targets)


def read_base_state(client_dir: Path, files: list[str]) -> dict:
    """Current canonical state for `files` (missing file -> None; history/
    -> {filename: sha256} so any added/changed record is detected)."""
    import hashlib

    state: dict = {}
    for name in files:
        path = client_dir / name.rstrip("/")
        if name == "history/":
            state[name] = (
                {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.iterdir()) if p.is_file()}
                if path.is_dir() else None
            )
        elif not path.is_file():
            state[name] = None
        elif name.endswith(".json"):
            state[name] = json.loads(path.read_text(encoding="utf-8"))
        else:
            state[name] = path.read_text(encoding="utf-8")
    return state


def compute_base_state_hash(client_dir: Path, files: list[str]) -> str:
    return content_sha256(read_base_state(client_dir, files))


def build_mutation_plan(promotion_plan: list[dict], files: list[str], base_state_hash: str) -> dict:
    return {
        "canonical_targets": files,
        "base_state_hash": base_state_hash,
        "changes": [
            {
                "candidate_id": c["candidate_id"], "target_file": c["target_file"], "target_path": c.get("target_path"),
                "action": c["action"], "material": c["action"] in WRITING_ACTIONS,
            }
            for c in promotion_plan
        ],
        "will_write": False,
    }


def compute_preview_hash(preview: dict) -> str:
    return content_sha256(semantic({
        "client_id": preview["client_id"],
        "base_state_hash": preview["base_state_hash"],
        "promotion_plan": preview["promotion_plan"],
        "evidence": preview["evidence"],
        "mutation_plan": preview["mutation_plan"],
    }))


def bind_preview(preview: dict, client_dir: Path) -> dict:
    """Attach base_state_hash, mutation_plan and preview_hash to a preview
    output (built by the agent or by plan_evidence_promotion)."""
    if preview.get("mode") != "preview":
        raise ValueError("only a preview can be hash-bound")
    files = bound_files(preview["promotion_plan"])
    base_hash = compute_base_state_hash(client_dir, files)
    bound = {**preview, "schema_version": OUTPUT_SCHEMA_VERSION, "base_state_hash": base_hash, "approval_id": None,
             "mutation_plan": build_mutation_plan(preview["promotion_plan"], files, base_hash)}
    bound["preview_hash"] = compute_preview_hash(bound)
    return bound


# ---------------------------------------------------------------------------
# preview for direct evidence promotion (SKILL.md 17.1.1)
# ---------------------------------------------------------------------------


def _registry() -> Registry:
    resources = []
    for f in sorted((REPO_ROOT / "schemas").glob("*.json")) + sorted((REPO_ROOT / "skills").glob("*/output.schema.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if "$id" in data:
            resources.append((data["$id"], Resource.from_contents(data)))
    return Registry().with_resources(resources)


def schema_errors(instance, schema_path_or_ref: str, registry: Optional[Registry] = None) -> list[str]:
    registry = registry or _registry()
    if schema_path_or_ref.startswith("https://"):
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": schema_path_or_ref}
    else:
        schema = json.loads((REPO_ROOT / schema_path_or_ref).read_text(encoding="utf-8"))
    return [f"{list(e.path)}: {e.message}" for e in Draft202012Validator(schema, registry=registry).iter_errors(instance)]


def _canonical_item_ref() -> str:
    schema = json.loads((REPO_ROOT / "schemas/client-evidence.schema.json").read_text(encoding="utf-8"))
    return schema["$id"] + "#/$defs/canonical_evidence_item"


def _same_material(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in EVIDENCE_MATERIAL_FIELDS)


def plan_evidence_promotion(
    *,
    client_id: str,
    client_dir: Path,
    evidence_items: list[dict],
    source_outputs: list[dict],
    candidate_prefix: str,
    clock: Callable[[], str] = utc_now_rfc3339,
) -> dict:
    """Preview (never writes) of promoting normalized external observations
    (schemas/evidence.schema.json) straight to the evidence ledger:
    promote when new, skip (NO_CHANGE) when identical, conflict when the
    same evidence_id holds different material content."""
    registry = _registry()
    generated_at = clock()
    ledger_path = client_dir / "evidence.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {"evidences": []}
    existing = {e["evidence_id"]: e for e in ledger.get("evidences", [])}
    plan, skipped, conflicts, warnings, missing = [], [], [], [], []
    if not ledger_path.is_file():
        missing.append({"field": "clients/<client_id>/evidence.json", "expected_source": None,
                        "impact": "ledger will be created by the first apply", "blocking": False})
    for i, ev in enumerate(evidence_items, start=1):
        if ev.get("client_id") != client_id:
            raise ValueError(f"evidence {ev.get('evidence_id')!r} belongs to another client")
        errs = schema_errors(ev, "schemas/evidence.schema.json", registry)
        projected = project_to_canonical(ev, added_at=generated_at, added_by="promote-client-memory")
        errs += schema_errors(projected, _canonical_item_ref(), registry)
        if errs:
            raise ValueError(f"evidence {ev.get('evidence_id')!r} is invalid: {errs}")
        cid = f"{candidate_prefix}-{i:03d}"
        current = existing.get(ev["evidence_id"])
        cand = {"candidate_id": cid, "target_file": "evidence.json", "target_path": None, "category": None,
                "summary": f"Promote evidence {ev['evidence_id']} to the canonical ledger.",
                "evidence_ids": [ev["evidence_id"]], "confidence": ev["confidence"]}
        if current is None:
            cand.update(action="promote", value=projected,
                        reason="Normalized external observation (SKILL 17.1.1); evidence_id not in the ledger.")
        elif _same_material(current, projected):
            cand.update(action="skip", reason="NO_CHANGE: identical evidence already in the ledger.")
            skipped.append({"candidate_id": cid, "reason": cand["reason"]})
        else:
            cand.update(action="conflict", value=projected, existing_value=current,
                        existing_evidence_ids=[current["evidence_id"]],
                        reason="Same evidence_id already in the ledger with different material content.")
            conflicts.append({"candidate_id": cid, "target_file": "evidence.json", "target_path": None,
                              "description": f"{ev['evidence_id']}: ledger content differs; nothing overwritten.",
                              "resolution": "needs_user_decision"})
            warnings.append(f"evidence ledger conflict for {ev['evidence_id']}; canonical value preserved")
        plan.append(cand)
    preview = {
        "schema_version": OUTPUT_SCHEMA_VERSION, "skill": "promote-client-memory", "client_id": client_id,
        "generated_at": generated_at, "mode": "preview", "status": "partial" if conflicts else "success",
        "source_outputs": source_outputs, "promotion_plan": plan, "applied_changes": [], "conflicts": conflicts,
        "skipped": skipped, "evidence": evidence_items, "missing_data": missing, "warnings": warnings,
    }
    return bind_preview(preview, client_dir)


# ---------------------------------------------------------------------------
# approval + apply gate
# ---------------------------------------------------------------------------


def _notice(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def approval_item_id(preview: dict) -> str:
    return f"memory-promotion:{preview['client_id']}"


def approval_item_payload(preview: dict) -> dict:
    return {"client_id": preview["client_id"], "base_state_hash": preview["base_state_hash"],
            "preview_hash": preview["preview_hash"]}


def build_promotion_approval_candidate(preview: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    """status=draft only — becomes real exclusively through
    approval.apply_operator_decision on an explicit operator request."""
    if preview.get("mode") != "preview" or preview.get("status") != "success" or not preview.get("preview_hash"):
        raise ap.ApprovalError("only a successful, hash-bound preview can be proposed for approval")
    return ap.build_approval_candidate(
        approval_id=approval_id, client_id=preview["client_id"], quarter_id=None, created_at=created_at,
        source_artifact_type=APPROVAL_SOURCE_TYPE, source_artifact_id=f"{preview['client_id']}:{preview['preview_hash'][:16]}",
        source_artifact=preview, source_artifact_path=preview_path,
        candidate_items=[{"item_id": approval_item_id(preview), "item_type": APPROVAL_ITEM_TYPE,
                          "payload": approval_item_payload(preview)}],
    )


def check_apply_gate(preview: Optional[dict], approval: Optional[dict], client_dir: Path) -> list[dict]:
    """Every promote-client-memory apply runs this first; any notice
    returned means zero canonical writes."""
    if preview is None or preview.get("mode") != "preview":
        return [_notice("NO_PREVIEW", "apply requires the approved preview output (mode=preview)")]
    if not preview.get("preview_hash") or not preview.get("base_state_hash") or not preview.get("mutation_plan"):
        return [_notice("PREVIEW_NOT_HASH_BOUND", "preview has no preview_hash/base_state_hash/mutation_plan (legacy output); re-run preview")]
    if preview.get("status") != "success":
        return [_notice("NO_PREVIEW", f"preview status is {preview.get('status')!r}; only a success preview is applicable")]
    if compute_preview_hash(preview) != preview["preview_hash"]:
        return [_notice("STALE_APPROVAL", "preview payload was changed after preview_hash was computed")]
    if approval is None:
        return [_notice("NO_APPROVAL", "apply requires an explicit operator approval record (schemas/approval.schema.json)")]
    if approval.get("client_id") != preview["client_id"]:
        return [_notice("CLIENT_ISOLATION", "approval belongs to a different client")]
    item_id = approval_item_id(preview)
    covered = [i for i in approval.get("scope", {}).get("approved_items", [])
               if i.get("item_id") == item_id and i.get("item_type") == APPROVAL_ITEM_TYPE]
    if not covered:
        return [_notice("NO_APPROVAL", f"approval does not cover {item_id!r}")]
    bad = [c for c in ap.validate_approval(approval, preview, {item_id: approval_item_payload(preview)}) if not c.ok]
    if bad:
        return [_notice("STALE_APPROVAL", bad[0].reason)]
    files = preview["mutation_plan"]["canonical_targets"]
    if compute_base_state_hash(client_dir, files) != preview["base_state_hash"]:
        return [_notice("STALE_APPROVAL", "canonical state changed since the preview (base_state_hash mismatch); re-run preview and re-approve")]
    return []


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def apply_promotion(
    preview: Optional[dict],
    approval: Optional[dict],
    client_dir: Path,
    *,
    clock: Callable[[], str] = utc_now_rfc3339,
) -> dict:
    """Apply an approved, hash-bound preview to the evidence ledger.
    Returns {status, applied_changes, errors}; status is success,
    no_change or failed. Any gate failure -> failed with zero writes."""
    errors = check_apply_gate(preview, approval, client_dir)
    if errors:
        return {"status": "failed", "applied_changes": [], "errors": errors}
    writing = [c for c in preview["promotion_plan"] if c["action"] in WRITING_ACTIONS]
    unsupported = [c["candidate_id"] for c in writing if c["target_file"] != "evidence.json"]
    if unsupported:
        return {"status": "failed", "applied_changes": [], "errors": [_notice(
            "UNSUPPORTED_TARGET", f"reference apply only writes evidence.json; candidates {unsupported} need the SKILL.md apply path after this same gate")]}
    if not writing:
        return {"status": "no_change", "applied_changes": [], "errors": []}

    now = clock()
    ledger_path = client_dir / "evidence.json"
    ledger = (json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file()
              else {"schema_version": "1.0.0", "client_id": preview["client_id"], "updated_at": None, "evidences": []})
    existing = {e["evidence_id"]: e for e in ledger["evidences"]}
    additions, applied = [], []
    for cand in writing:
        item = {**cand["value"], "added_at": now, "added_by": "promote-client-memory"}
        current = existing.get(item["evidence_id"])
        if current is not None:
            if _same_material(current, item):
                continue
            return {"status": "failed", "applied_changes": [], "errors": [_notice(
                "STALE_APPROVAL", f"{item['evidence_id']} appeared in the ledger with different content")]}
        additions.append(item)
        applied.append({"candidate_id": cand["candidate_id"], "target_file": "evidence.json",
                        "action": cand["action"], "applied_at": now})
    if not additions:
        return {"status": "no_change", "applied_changes": [], "errors": []}
    new_ledger = {**ledger, "updated_at": now, "evidences": ledger["evidences"] + additions}
    errs = schema_errors(new_ledger, "schemas/client-evidence.schema.json")
    if errs:
        return {"status": "failed", "applied_changes": [], "errors": [_notice("INVALID_RESULT", "; ".join(errs[:5]))]}
    _atomic_write_json(ledger_path, new_ledger)
    return {"status": "success", "applied_changes": applied, "errors": []}
