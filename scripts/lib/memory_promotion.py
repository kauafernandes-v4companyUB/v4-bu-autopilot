"""Hash binding, approval gate and reference apply for
skills/promote-client-memory/SKILL.md (sections 17, 17.1, 17.1.1, 17.2, 18).

Every target the skill declares is applied here, through one generic
operation model (`value` of a writing candidate):

  evidence.json       value = canonical evidence item (17.1.1 direct promotion)
  knowledge.json      {"op": "append" | "replace_item", "path": "/categories/<category>", "key": "knowledge_id", "item": {...}[, "match": "<id>"]}
  current-state.json  {"op": "set", "path": "/<field>[/<key>]", "value": ...} | append | replace_item
  decisions.json      {"op": "append" | "replace_item", "path": "/decisions", "key": "decision_id", "item": {...}}
  client.json         {"op": "set", "path": "/<field>", "value": ...}
  sources.json        {"op": "append" | "replace_item", "path": "/sources", "key": "source_id", "item": {...}}
  strategy.md         {"op": "replace_text", "text": "..."}
  history             {"op": "create_file", "name": "<record>.json", "content": {...}}

Replacing existing content always requires action "supersede" and snapshots
the previous value into history/ (section 18.1) in the same atomic write.
Evidence used by any writing candidate is synced into evidence.json from
the preview's `evidence` block (section 17.1). Apply = gate -> simulate ->
validate every target -> one atomic multi-file write + receipt.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable, Optional

from scripts.lib import canonical_action as ca
from scripts.lib import storage_contract as storage
from scripts.lib.artifact_hash import content_sha256
from scripts.lib.evidence_projection import project_to_canonical
from scripts.lib.exec_clock import utc_now_rfc3339

ACTION = "promote-client-memory"
OUTPUT_SCHEMA_VERSION = "1.1.0"
APPROVAL_ITEM_TYPE = "memory_promotion"
APPROVAL_SOURCE_TYPE = "memory_promotion_preview"
ALWAYS_BOUND_FILES = ("evidence.json", "knowledge.json", "current-state.json", "decisions.json")
WRITING_ACTIONS = {"promote", "supersede", "historize"}
TARGET_OPS = {
    "knowledge.json": {"append", "replace_item"},
    "current-state.json": {"set", "append", "replace_item"},
    "decisions.json": {"append", "replace_item"},
    "client.json": {"set"},
    "sources.json": {"append", "replace_item"},
    "strategy.md": {"replace_text"},
    "history": {"create_file"},
}
EVIDENCE_MATERIAL_FIELDS = (
    "statement", "type", "value", "unit", "confidence", "source_date", "period",
    "source_kind", "source_reference", "source_skill", "external_provenance",
)
HISTORY_REQUIRED = ("candidate_id", "knowledge_type", "statement", "confidence", "evidence_ids", "provenance")
TEMPLATES = ca.REPO_ROOT / "templates" / "client"
semantic = ca.semantic


class _Conflict(Exception):
    pass


# ---------------------------------------------------------------------------
# hashing / binding
# ---------------------------------------------------------------------------


def bound_files(promotion_plan: list[dict]) -> list[str]:
    files = set(ALWAYS_BOUND_FILES)
    for cand in promotion_plan:
        t = cand.get("target_file")
        if t == "history":
            files.add("history/")
        elif t in TARGET_OPS or t == "evidence.json":
            files.add(t)
        if cand.get("action") == "supersede":
            files.add("history/")
    return sorted(files)


def compute_preview_hash(preview: dict) -> str:
    return content_sha256(semantic({
        "client_id": preview["client_id"], "base_state_hash": preview["base_state_hash"],
        "promotion_plan": preview["promotion_plan"], "evidence": preview["evidence"],
        "mutation_plan": preview["mutation_plan"],
    }))


def _mutation_plan(plan: list[dict], files: list[str], base_hash: str) -> dict:
    return {"canonical_targets": files, "base_state_hash": base_hash, "will_write": False,
            "changes": [{"candidate_id": c["candidate_id"], "target_file": c["target_file"],
                         "target_path": c.get("target_path"), "action": c["action"],
                         "material": c["action"] in WRITING_ACTIONS} for c in plan]}


def bind_preview(preview: dict, client_dir: Path) -> dict:
    if preview.get("mode") != "preview":
        raise ValueError("only a preview can be hash-bound")
    files = bound_files(preview["promotion_plan"])
    base_hash = ca.state_hash(client_dir, files)
    bound = {**preview, "schema_version": OUTPUT_SCHEMA_VERSION, "base_state_hash": base_hash, "approval_id": None,
             "mutation_plan": _mutation_plan(preview["promotion_plan"], files, base_hash)}
    bound["preview_hash"] = compute_preview_hash(bound)
    return bound


# ---------------------------------------------------------------------------
# document helpers
# ---------------------------------------------------------------------------


def _segments(path: str) -> list[str]:
    if not path or not path.startswith("/"):
        raise _Conflict(f"invalid JSON pointer {path!r}")
    return [s.replace("~1", "/").replace("~0", "~") for s in path[1:].split("/")]


def _get(doc, segs):
    cur = doc
    for s in segs:
        if not isinstance(cur, dict) or s not in cur:
            return None
        cur = cur[s]
    return cur


def _parent(doc, segs, create_list: bool):
    cur = doc
    for s in segs[:-1]:
        if not isinstance(cur, dict):
            raise _Conflict(f"path segment {s!r} is not inside an object")
        cur = cur.setdefault(s, {})
    if create_list and isinstance(cur, dict):
        cur.setdefault(segs[-1], [])
    return cur


def _same_material(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in EVIDENCE_MATERIAL_FIELDS)


def _template_keys(target: str) -> set[str]:
    path = TEMPLATES / target
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else set()


def _contract_errors(target: str, doc, client_id: str) -> list[str]:
    """Every canonical target is validated against its JSON Schema
    (scripts/lib/storage_contract.py CANONICAL_SCHEMAS) before apply."""
    if target == "strategy.md":
        return [] if isinstance(doc, str) and doc.strip() else ["strategy.md must be non-empty text"]
    if not isinstance(doc, dict):
        return [f"{target} must be a JSON object"]
    errs = [f"{target}: {e}" for e in ca.schema_errors(doc, storage.CANONICAL_SCHEMAS[target])]
    if doc.get("client_id") != client_id:
        errs.append(f"{target}: client_id must stay {client_id!r}")
    if target in ("decisions.json", "sources.json"):
        key, items = ("decision_id", doc.get("decisions", [])) if target == "decisions.json" else ("source_id", doc.get("sources", []))
        ids = [i.get(key) for i in items if isinstance(i, dict)]
        if len(ids) != len(set(ids)):
            errs.append(f"{target}: duplicate {key}")
    return errs


def _history_errors(content: dict) -> list[str]:
    if not isinstance(content, dict):
        return ["history record must be a JSON object"]
    errs = [f"history record missing {k!r}" for k in HISTORY_REQUIRED if k not in content]
    if not isinstance(content.get("provenance"), dict) or not content["provenance"].get("source_skill"):
        errs.append("history record provenance.source_skill is required")
    return errs


# ---------------------------------------------------------------------------
# simulation (shared by preview and apply)
# ---------------------------------------------------------------------------


def _simulate(client_dir: Path, client_id: str, plan: list[dict], evidence_block: list[dict], now: str) -> dict:
    """Returns {writes, effects, applied, noop, conflicts, errors} without
    touching disk. `applied`/`noop`/`conflicts` are candidate_id lists."""
    docs: dict[str, object] = {}
    originals: dict[str, Optional[bytes]] = {}
    history_new: dict[str, dict] = {}
    applied, noop, conflicts, errors = [], [], [], []

    def load(target: str):
        if target not in docs:
            path = client_dir / target
            originals[target] = path.read_bytes() if path.is_file() else None
            if target.endswith(".json"):
                docs[target] = json.loads(originals[target]) if originals[target] else {
                    **json.loads((TEMPLATES / target).read_text(encoding="utf-8").replace("__CLIENT_ID__", client_id)),
                    **({"updated_at": None} if "updated_at" in _template_keys(target) else {})}
            else:
                docs[target] = originals[target].decode("utf-8") if originals[target] else ""
        return docs[target]

    def snapshot(cand: dict, target: str, path: Optional[str], old) -> None:
        name = f"{target.replace('.', '-')}-superseded-by-{cand['candidate_id']}.json"
        history_new[name] = {
            "candidate_id": cand["candidate_id"], "knowledge_type": "superseded_snapshot",
            "statement": f"Previous value of {target}{path or ''} superseded by {cand['candidate_id']}.",
            "confidence": cand["confidence"], "evidence_ids": cand["evidence_ids"], "superseded_value": old,
            "provenance": {"source_skill": ACTION, "historized_at": now, "historized_by": ACTION},
        }

    ledger = load("evidence.json")
    ledger.setdefault("evidences", [])
    by_id = {e["evidence_id"]: e for e in ledger["evidences"]}
    evidence_pool = {e["evidence_id"]: e for e in evidence_block}

    for cand in plan:
        if cand["action"] not in WRITING_ACTIONS:
            continue
        target, cid = cand["target_file"], cand["candidate_id"]
        try:
            if target == "evidence.json":
                item = {**cand["value"], "added_at": now, "added_by": ACTION}
                cur = by_id.get(item["evidence_id"])
                if cur is None:
                    ledger["evidences"].append(item)
                    by_id[item["evidence_id"]] = item
                    applied.append(cid)
                elif _same_material(cur, item):
                    noop.append(cid)
                else:
                    raise _Conflict(f"{item['evidence_id']} exists in the ledger with different content")
                continue
            spec = cand.get("value")
            if not isinstance(spec, dict) or spec.get("op") not in TARGET_OPS.get(target, set()):
                raise _Conflict(f"target {target!r} does not accept op {None if not isinstance(spec, dict) else spec.get('op')!r}")
            op = spec["op"]
            if target == "history":
                if op != "create_file" or not str(spec.get("name", "")).endswith(".json") or "/" in spec["name"] or "\\" in spec["name"]:
                    raise _Conflict("history create_file needs a plain '<name>.json'")
                content = copy.deepcopy(spec["content"])
                if isinstance(content.get("provenance"), dict):
                    content["provenance"].update(historized_at=now, historized_by=ACTION)
                path = client_dir / "history" / spec["name"]
                if path.is_file():
                    if semantic(json.loads(path.read_text(encoding="utf-8"))) == semantic(content):
                        noop.append(cid)
                        continue
                    raise _Conflict(f"history/{spec['name']} exists with different content")
                errs = _history_errors(content)
                if errs:
                    raise _Conflict("; ".join(errs))
                history_new[spec["name"]] = content
                applied.append(cid)
                continue
            doc = load(target)
            if op == "replace_text":
                if doc == spec["text"]:
                    noop.append(cid)
                    continue
                if doc.strip() and cand["action"] != "supersede":
                    raise _Conflict("replacing existing strategy.md text requires action 'supersede'")
                if doc.strip():
                    snapshot(cand, target, None, doc)
                docs[target] = spec["text"]
                applied.append(cid)
                continue
            segs = _segments(spec["path"])
            if op == "set":
                old = _get(doc, segs)
                if old is not None and semantic(old) == semantic(spec["value"]):
                    noop.append(cid)
                    continue
                if old not in (None, {}, [], "unknown") and cand["action"] != "supersede":
                    raise _Conflict(f"{target}{spec['path']} already holds a value; replacing it requires action 'supersede'")
                if old not in (None, {}, [], "unknown"):
                    snapshot(cand, target, spec["path"], old)
                _parent(doc, segs, create_list=False)[segs[-1]] = copy.deepcopy(spec["value"])
                applied.append(cid)
                continue
            key, item = spec.get("key"), copy.deepcopy(spec.get("item"))
            if not key or not isinstance(item, dict) or not item.get(key):
                raise _Conflict(f"{op} needs 'key' and an 'item' carrying it")
            if target == "knowledge.json" and isinstance(item.get("provenance"), dict):
                item["provenance"].update(promoted_at=now, promoted_by=ACTION)
            lst = _parent(doc, segs, create_list=True)[segs[-1]]
            if not isinstance(lst, list):
                raise _Conflict(f"{target}{spec['path']} is not a list")
            if op == "append":
                same = [x for x in lst if isinstance(x, dict) and x.get(key) == item[key]]
                if same:
                    if semantic(same[0]) == semantic(item):
                        noop.append(cid)
                        continue
                    raise _Conflict(f"{key}={item[key]!r} already exists with different content; use replace_item + supersede")
                lst.append(item)
            else:  # replace_item
                if cand["action"] != "supersede":
                    raise _Conflict("replace_item requires action 'supersede'")
                match = spec.get("match", item[key])
                idx = [i for i, x in enumerate(lst) if isinstance(x, dict) and x.get(key) == match]
                if len(idx) != 1:
                    raise _Conflict(f"replace_item needs exactly one {key}={match!r} (found {len(idx)})")
                if semantic(lst[idx[0]]) == semantic(item):
                    noop.append(cid)
                    continue
                snapshot(cand, target, f"{spec['path']}[{key}={match}]", lst[idx[0]])
                lst[idx[0]] = item
            applied.append(cid)
        except _Conflict as exc:
            conflicts.append({"candidate_id": cid, "target_file": target, "target_path": cand.get("target_path"),
                              "description": str(exc), "resolution": "needs_user_decision"})

    # evidence ledger sync (17.1) for every candidate that actually writes
    for cand in plan:
        if cand["candidate_id"] not in applied or cand["target_file"] == "evidence.json":
            continue
        for eid in cand["evidence_ids"]:
            if eid in by_id:
                continue
            if eid not in evidence_pool:
                conflicts.append({"candidate_id": cand["candidate_id"], "target_file": "evidence.json", "target_path": None,
                                  "description": f"unresolved_evidence: {eid} is neither in the ledger nor in the preview evidence",
                                  "resolution": "needs_user_decision"})
                continue
            item = project_to_canonical(evidence_pool[eid], added_at=now, added_by=ACTION)
            ledger["evidences"].append(item)
            by_id[eid] = item

    writes: dict[str, bytes] = {}
    effects: list[dict] = []
    for target, doc in docs.items():
        if isinstance(doc, dict):
            before = originals[target]
            if before is not None and json.loads(before) == doc:
                continue
            if "updated_at" in doc:
                doc["updated_at"] = now
            errs = _contract_errors(target, doc, client_id)
            if errs:
                errors.extend(errs)
            data = ca.serialize_json(doc)
        else:
            if originals[target] is not None and originals[target].decode("utf-8") == doc:
                continue
            errs = _contract_errors(target, doc, client_id)
            errors.extend(errs)
            data = doc.encode("utf-8")
        writes[target] = data
        effects.append(ca.effect(f"clients/{client_id}/{target}", "update" if originals[target] else "create", originals[target], data))
    for name, content in sorted(history_new.items()):
        rel = f"history/{name}"
        data = ca.serialize_json(content)
        writes[rel] = data
        effects.append(ca.effect(f"clients/{client_id}/{rel}", "create", None, data))
    return {"writes": writes, "effects": effects, "applied": applied, "noop": noop,
            "conflicts": conflicts, "errors": errors}


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def plan_promotion(*, client_id: str, client_dir: Path, candidates: list[dict], evidence_items: list[dict],
                   source_outputs: list[dict], clock: Callable[[], str] = utc_now_rfc3339,
                   warnings: Optional[list[str]] = None, missing_data: Optional[list[dict]] = None) -> dict:
    """Preview (never writes): classifies each writing candidate against the
    current canonical state (no-op -> skip, incompatible -> conflict) and
    returns a hash-bound output."""
    generated_at = clock()
    for ev in evidence_items:
        if ev.get("client_id") != client_id:
            raise ValueError(f"evidence {ev.get('evidence_id')!r} belongs to another client")
        errs = ca.schema_errors(ev, "schemas/evidence.schema.json")
        if errs:
            raise ValueError(f"evidence {ev.get('evidence_id')!r} is invalid: {errs}")
    for cand in candidates:
        if cand["target_file"] not in TARGET_OPS and cand["target_file"] != "evidence.json":
            raise ValueError(f"unknown target_file {cand['target_file']!r}")
    sim = _simulate(client_dir, client_id, candidates, evidence_items, generated_at)
    conflict_ids = {c["candidate_id"] for c in sim["conflicts"]}
    plan, skipped = [], []
    for cand in candidates:
        cand = copy.deepcopy(cand)
        if cand["candidate_id"] in conflict_ids:
            cand["action"] = "conflict"
        elif cand["candidate_id"] in sim["noop"]:
            cand["action"] = "skip"
            cand["reason"] = "NO_CHANGE: identical content already in canonical memory. " + cand.get("reason", "")
            cand.pop("value", None)
            skipped.append({"candidate_id": cand["candidate_id"], "reason": "NO_CHANGE: identical content already in canonical memory."})
        plan.append(cand)
    status = "partial" if sim["conflicts"] or sim["errors"] else "success"
    preview = {
        "schema_version": OUTPUT_SCHEMA_VERSION, "skill": ACTION, "client_id": client_id, "generated_at": generated_at,
        "mode": "preview", "status": status, "source_outputs": source_outputs, "promotion_plan": plan,
        "applied_changes": [], "conflicts": sim["conflicts"], "skipped": skipped, "evidence": evidence_items,
        "missing_data": list(missing_data or []),
        "warnings": list(warnings or []) + [f"contract: {e}" for e in sim["errors"]],
    }
    return bind_preview(preview, client_dir)


def plan_evidence_promotion(*, client_id: str, client_dir: Path, evidence_items: list[dict], source_outputs: list[dict],
                            candidate_prefix: str, clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Convenience preview for direct promotion of normalized external
    observations to the evidence ledger (SKILL.md 17.1.1)."""
    now = clock()
    candidates = []
    for i, ev in enumerate(evidence_items, start=1):
        projected = project_to_canonical(ev, added_at=now, added_by=ACTION)
        errs = ca.schema_errors(projected, _canonical_item_ref())
        if errs:
            raise ValueError(f"evidence {ev.get('evidence_id')!r} does not project to a canonical item: {errs}")
        candidates.append({"candidate_id": f"{candidate_prefix}-{i:03d}", "target_file": "evidence.json", "target_path": None,
                           "category": None, "action": "promote", "value": projected,
                           "summary": f"Promote evidence {ev['evidence_id']} to the canonical ledger.",
                           "reason": "Normalized external observation (SKILL 17.1.1).",
                           "evidence_ids": [ev["evidence_id"]], "confidence": ev["confidence"]})
    return plan_promotion(client_id=client_id, client_dir=client_dir, candidates=candidates, evidence_items=evidence_items,
                          source_outputs=source_outputs, clock=lambda: now)


def _canonical_item_ref() -> str:
    schema = json.loads((ca.REPO_ROOT / "schemas/client-evidence.schema.json").read_text(encoding="utf-8"))
    return schema["$id"] + "#/$defs/canonical_evidence_item"


# ---------------------------------------------------------------------------
# approval + apply
# ---------------------------------------------------------------------------


def approval_item_id(preview: dict) -> str:
    return f"memory-promotion:{preview['client_id']}"


def approval_item_payload(preview: dict) -> dict:
    return ca.approval_payload(preview)


def build_promotion_approval_candidate(preview: dict, *, approval_id: str, created_at: str, preview_path: str) -> dict:
    return ca.build_approval_candidate(preview, item_id=approval_item_id(preview), item_type=APPROVAL_ITEM_TYPE,
                                       source_type=APPROVAL_SOURCE_TYPE, approval_id=approval_id,
                                       created_at=created_at, preview_path=preview_path)


def check_apply_gate(preview: Optional[dict], approval: Optional[dict], client_dir: Path) -> list[dict]:
    if preview is not None and preview.get("mode") == "preview" and preview.get("preview_hash") and not preview.get("mutation_plan"):
        return [ca.notice("PREVIEW_NOT_HASH_BOUND", "preview has no mutation_plan; re-run preview")]
    files = (preview or {}).get("mutation_plan", {}).get("canonical_targets") or list(ALWAYS_BOUND_FILES)
    return ca.check_gate(preview, approval, client_dir, item_id=approval_item_id(preview) if preview else "",
                         item_type=APPROVAL_ITEM_TYPE, bound_files=files, recompute_preview_hash=compute_preview_hash)


def apply_promotion(preview: Optional[dict], approval: Optional[dict], client_dir: Path, *,
                    clock: Callable[[], str] = utc_now_rfc3339) -> dict:
    """Returns {status, applied_changes, errors, receipt}. status is
    success, no_change or failed; failed always means zero writes."""
    errors = check_apply_gate(preview, approval, client_dir)
    if errors:
        return {"status": "failed", "applied_changes": [], "errors": errors, "receipt": None}
    now = clock()
    sim = _simulate(client_dir, preview["client_id"], preview["promotion_plan"], preview["evidence"], now)
    if sim["conflicts"] or sim["errors"]:
        msgs = [c["description"] for c in sim["conflicts"]] + sim["errors"]
        return {"status": "failed", "applied_changes": [], "errors": [ca.notice("CONFLICT", m) for m in msgs], "receipt": None}
    if not sim["writes"]:
        receipt = ca.build_action_receipt(action=ACTION, client_id=preview["client_id"], preview=preview, approval=approval,
                                          executed_at=now, status="no_change", effects=[])
        return {"status": "no_change", "applied_changes": [], "errors": [], "receipt": receipt}
    receipt = ca.build_action_receipt(action=ACTION, client_id=preview["client_id"], preview=preview, approval=approval,
                                      executed_at=now, status="success", effects=sim["effects"])
    writes = {**sim["writes"], f"receipts/{receipt['receipt_id']}.json": ca.serialize_json(receipt)}
    ca.atomic_multi_write(client_dir, writes)
    by_id = {c["candidate_id"]: c for c in preview["promotion_plan"]}
    applied = [{"candidate_id": cid, "target_file": by_id[cid]["target_file"], "action": by_id[cid]["action"], "applied_at": now}
               for cid in sim["applied"]]
    return {"status": "success", "applied_changes": applied, "errors": [], "receipt": receipt}
