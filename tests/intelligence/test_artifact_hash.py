from __future__ import annotations

import copy

from scripts.lib.artifact_hash import content_sha256, make_artifact_ref, verify_artifact_ref


# --- AG: same inputs produce stable content hashes ---

def test_content_hash_is_deterministic():
    obj = {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}}
    assert content_sha256(obj) == content_sha256(copy.deepcopy(obj))


def test_content_hash_ignores_key_order():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert content_sha256(a) == content_sha256(b)


def test_content_hash_changes_with_content():
    a = {"x": 1}
    b = {"x": 2}
    assert content_sha256(a) != content_sha256(b)


# --- AE: a chain of real artifact_refs verifies clean end to end ---

def test_demo_chain_hashes_verify_end_to_end(demo_chain):
    checks = [
        verify_artifact_ref(demo_chain["diagnosis"]["context_pack_ref"], demo_chain["context-pack"]),
        verify_artifact_ref(demo_chain["gaps"]["context_pack_ref"], demo_chain["context-pack"]),
        verify_artifact_ref(demo_chain["gaps"]["diagnosis_ref"], demo_chain["diagnosis"]),
        verify_artifact_ref(demo_chain["priorities"]["context_pack_ref"], demo_chain["context-pack"]),
        verify_artifact_ref(demo_chain["priorities"]["diagnosis_ref"], demo_chain["diagnosis"]),
        verify_artifact_ref(demo_chain["priorities"]["gaps_ref"], demo_chain["gaps"]),
        verify_artifact_ref(demo_chain["replanning"]["priorities_ref"], demo_chain["priorities"]),
        verify_artifact_ref(demo_chain["audit"]["replanning_ref"], demo_chain["replanning"]),
        verify_artifact_ref(demo_chain["task-proposals"]["replanning_ref"], demo_chain["replanning"]),
        verify_artifact_ref(demo_chain["task-proposals"]["audit_ref"], demo_chain["audit"]),
    ]
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


# --- AF: a stale/mismatched upstream artifact is detected, never silently accepted ---

def test_stale_upstream_context_pack_is_detected(demo_chain):
    mutated_context_pack = copy.deepcopy(demo_chain["context-pack"])
    mutated_context_pack["warnings"].append("this file changed after diagnosis.json was computed")

    chk = verify_artifact_ref(demo_chain["diagnosis"]["context_pack_ref"], mutated_context_pack)
    assert chk.ok is False
    assert "stale" in chk.reason


def test_missing_upstream_artifact_is_detected():
    ref = {"artifact_id": "x", "artifact_type": "context_pack", "content_sha256": "a" * 64, "path": "nowhere.json"}
    chk = verify_artifact_ref(ref, None)
    assert chk.ok is False
    assert "no longer exists" in chk.reason


def test_make_artifact_ref_round_trips():
    obj = {"my_id": "abc", "x": 1}
    ref = make_artifact_ref(obj, artifact_id_field="my_id", artifact_type="context_pack", path="p.json")
    assert ref["artifact_id"] == "abc"
    assert ref["content_sha256"] == content_sha256(obj)
    chk = verify_artifact_ref(ref, obj)
    assert chk.ok is True
