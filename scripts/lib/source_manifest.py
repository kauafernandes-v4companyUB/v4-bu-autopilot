"""Source manifest (skills/source-intake + skills/manage-source-manifest).

Discovery (source-intake, read-only) scans private/clients/<client_id>/ and
compares each file with clients/<client_id>/source-manifest.json:

  path never seen                    -> NEW_SOURCE   (revision 1)
  same path, same sha256             -> NO_CHANGE
  same path, new sha256              -> NEW_REVISION (revision n+1, same source_id)
  path in manifest, file gone        -> MISSING      (reported only; nothing deleted,
                                                      evidence is never touched)

Persisting the manifest is the manage-source-manifest ACTION: hash-bound
preview, approval, atomic apply and receipt (scripts/lib/canonical_action.py).
Raw files never become canonical by existing: the manifest records only
identity (path, hash, revision) and processing pointers.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import utc_now_rfc3339

ACTION = "manage-source-manifest"
SCHEMA_VERSION = "1.1.0"
APPROVAL_ITEM_TYPE = "source_manifest_change"
APPROVAL_SOURCE_TYPE = "source_manifest_preview"
BOUND_FILES = ["source-manifest.json"]
SOURCE_TYPES = ("client_context", "account_gt_transcript", "whatsapp_export", "bi_pdf", "bi_csv",
                "google_sheet", "manual_authorized_input", "unknown")


def classify(rel_path: str) -> str:
    """Conservative classification by folder first, then name/extension."""
    rel = rel_path.replace("\\", "/").casefold()
    parts, name = rel.split("/"), rel.rsplit("/", 1)[-1]
    top = parts[0] if len(parts) > 1 else ""
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if top in ("manual", "manual-authorized") or "manual" in top:
        return "manual_authorized_input"
    if top in ("google-sheets", "google_sheets") or name.endswith(".gsheet.json"):
        return "google_sheet"
    if "whatsapp" in rel:
        return "whatsapp_export"
    if top in ("account-gt", "account_gt") or "transcri" in rel or "account-gt" in name:
        return "account_gt_transcript"
    if top in ("client-context", "context", "handoff") or "handoff" in name or "contexto" in name:
        return "client_context"
    if suffix == ".csv":
        return "bi_csv"
    if suffix == ".pdf":
        return "bi_pdf"
    return "unknown"


def stable_source_id(client_id: str, rel_path: str) -> str:
    key = f"{client_id}:{rel_path.replace(chr(92), '/')}"
    return "src-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _empty(client_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "client_id": client_id, "updated_at": None, "sources": []}


def _latest(manifest: dict) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in manifest.get("sources", []):
        cur = latest.get(entry["path"])
        if cur is None or entry.get("revision", 1) >= cur.get("revision", 1):
            latest[entry["path"]] = entry
    return latest


def scan(client_id: str, private_dir: Path, manifest: Optional[dict], now: str) -> dict:
    """Pure discovery. Returns {findings, new_entries}; never writes."""
    manifest = manifest or _empty(client_id)
    latest = _latest(manifest)
    findings, new_entries, seen = [], [], set()
    files = sorted(p for p in private_dir.rglob("*") if p.is_file()) if private_dir.is_dir() else []
    for path in files:
        rel = path.relative_to(private_dir).as_posix()
        seen.add(rel)
        fp = hashlib.sha256(path.read_bytes()).hexdigest()
        prev = latest.get(rel)
        if prev is not None and prev["fingerprint"] == fp:
            findings.append({"status": "NO_CHANGE", "source_id": prev["source_id"], "path": rel, "revision": prev.get("revision", 1)})
            continue
        revision = 1 if prev is None else prev.get("revision", 1) + 1
        entry = {"source_id": prev["source_id"] if prev else stable_source_id(client_id, rel), "source_type": classify(rel),
                 "path": rel, "fingerprint": fp, "revision": revision, "discovered_at": now, "observed_at": now,
                 "processed_at": None, "processor": None, "processor_version": None, "output_ref": None,
                 "status": "new" if prev is None else "new_revision", "warnings": []}
        new_entries.append(entry)
        findings.append({"status": "NEW_SOURCE" if prev is None else "NEW_REVISION", "source_id": entry["source_id"],
                         "path": rel, "revision": revision, "source_type": entry["source_type"]})
    for rel, entry in sorted(latest.items()):
        if rel not in seen:
            findings.append({"status": "MISSING", "source_id": entry["source_id"], "path": rel, "revision": entry.get("revision", 1)})
    return {"findings": findings, "new_entries": new_entries}


# ---------------------------------------------------------------------------
# manage-source-manifest ACTION
# ---------------------------------------------------------------------------


def _apply_changes(manifest: dict, changes: list[dict], now: str) -> tuple[dict, list[str]]:
    after, errors = copy.deepcopy(manifest), []
    by_key = {(e["source_id"], e.get("revision", 1)): e for e in after["sources"]}
    for i, ch in enumerate(changes):
        if ch.get("kind") == "record_revision":
            e = ch["entry"]
            key = (e["source_id"], e.get("revision", 1))
            if key in by_key:
                if by_key[key]["fingerprint"] != e["fingerprint"]:
                    errors.append(f"change {i}: {key} already recorded with a different fingerprint")
                continue
            entry = {**copy.deepcopy(e), "discovered_at": now, "observed_at": now}
            after["sources"].append(entry)
            by_key[key] = entry
        elif ch.get("kind") == "mark_processed":
            key = (ch.get("source_id"), ch.get("revision"))
            e = by_key.get(key)
            if e is None:
                errors.append(f"change {i}: unknown source revision {key}")
                continue
            if not ch.get("processor") or not ch.get("output_ref"):
                errors.append(f"change {i}: mark_processed needs processor and output_ref")
                continue
            if e.get("status") == "processed" and e.get("output_ref") == ch["output_ref"] and e.get("processor") == ch["processor"]:
                continue
            e.update(status="processed", processed_at=now, processor=ch["processor"],
                     processor_version=ch.get("processor_version"), output_ref=ch["output_ref"])
        else:
            errors.append(f"change {i}: kind must be record_revision or mark_processed")
    return after, errors


def compute_preview_hash(preview: dict) -> str:
    return content_sha256(ca.semantic({"client_id": preview["client_id"], "base_state_hash": preview["base_state_hash"],
                                       "changes": preview["changes"], "proposed": preview["proposed"]}))


def preview(client_dir: Path, private_dir: Path, *, client_id: str, mark_processed: Optional[list[dict]] = None,
            clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """source-intake discovery + the manifest mutation it implies, hash-bound."""
    now = clock()
    path = client_dir / "source-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else _empty(client_id)
    found = scan(client_id, private_dir, manifest, now)
    changes = [{"kind": "record_revision", "entry": e} for e in found["new_entries"]]
    changes += [{"kind": "mark_processed", **m} for m in (mark_processed or [])]
    after, errors = _apply_changes(manifest, changes, now)
    if not errors:
        after["schema_version"] = SCHEMA_VERSION
        errors += ca.schema_errors(after, "schemas/source-manifest.schema.json")
    material = bool(changes) and ca.semantic(after) != ca.semantic({**manifest, "schema_version": SCHEMA_VERSION})
    out = {"schema_version": "1.0.0", "skill": ACTION, "client_id": client_id, "generated_at": now, "mode": "preview",
           "status": "error" if errors else ("success" if material else "no_change"),
           "findings": found["findings"], "changes": changes, "proposed": after if not errors else None,
           "base_state_files": list(BOUND_FILES), "base_state_hash": ca.state_hash(client_dir, BOUND_FILES),
           "preview_hash": None, "approval_id": None, "receipt": None, "errors": errors}
    out["preview_hash"] = compute_preview_hash(out)
    return out


def approval_item_id(pv: dict) -> str:
    return f"source-manifest:{pv['client_id']}"


def build_approval_candidate(pv: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    return ca.build_approval_candidate(pv, item_id=approval_item_id(pv), item_type=APPROVAL_ITEM_TYPE,
                                       source_type=APPROVAL_SOURCE_TYPE, approval_id=approval_id,
                                       created_at=created_at, preview_path=preview_path)


def apply(pv: Optional[dict], approval: Optional[dict], client_dir: Path, *,
          clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    if pv is not None and pv.get("mode") == "preview" and pv.get("status") == "no_change":
        return {**pv, "mode": "apply"}
    gate = ca.check_gate(pv, approval, client_dir, item_id=approval_item_id(pv) if pv else "", item_type=APPROVAL_ITEM_TYPE,
                         bound_files=BOUND_FILES, recompute_preview_hash=compute_preview_hash)
    base = {**(pv or {}), "mode": "apply", "receipt": None}
    if gate:
        return {**base, "status": "error" if gate[0]["code"] in ("NO_PREVIEW", "NO_APPROVAL", "PREVIEW_NOT_HASH_BOUND") else "conflict",
                "errors": [f"{g['code']}: {g['message']}" for g in gate]}
    now = clock()
    path = client_dir / "source-manifest.json"
    before = path.read_bytes() if path.is_file() else None
    manifest = json.loads(before) if before else _empty(pv["client_id"])
    after, errors = _apply_changes(manifest, pv["changes"], now)
    after.update(schema_version=SCHEMA_VERSION, updated_at=now)
    errors += ca.schema_errors(after, "schemas/source-manifest.schema.json")
    if errors:
        return {**base, "status": "conflict", "errors": errors}
    data = ca.serialize_json(after)
    receipt = ca.build_action_receipt(action=ACTION, client_id=pv["client_id"], preview=pv, approval=approval, executed_at=now,
                                      status="success", effects=[ca.effect(f"clients/{pv['client_id']}/source-manifest.json",
                                                                           "update" if before else "create", before, data)])
    ca.atomic_multi_write(client_dir, {"source-manifest.json": data, f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)})
    return {**base, "status": "success", "proposed": after, "approval_id": approval["approval_id"], "receipt": receipt, "errors": []}
