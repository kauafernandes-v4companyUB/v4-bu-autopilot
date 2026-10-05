from __future__ import annotations

import pytest

from scripts.lib.evidence_id import compute_evidence_id


def test_deterministic_id_is_stable_across_calls():
    args = dict(
        client_id="synthtest",
        source_skill="read-bi",
        source_type="pdf",
        source_observation_id="biobs-synth-0001",
        source_file_sha256="a" * 64,
    )
    assert compute_evidence_id(**args) == compute_evidence_id(**args)


def test_deterministic_id_matches_known_reference_value():
    # Synthetic fixture. The expected value was computed independently with
    # hashlib over the canonical JSON documented in
    # skills/promote-client-memory/SKILL.md section 17.1.1 (not via this
    # module) — pinned here so the algorithm can never silently drift.
    # source_file_sha256 = sha256(b"synthetic-bi-fixture-file").
    eid = compute_evidence_id(
        client_id="acme-demo",
        source_skill="read-bi",
        source_type="pdf",
        source_observation_id="biobs-0000000000000001",
        source_file_sha256="afa29227c799a1330637e0b616fb069d1f70f2580074074e90850ad5cc2964c4",
    )
    assert eid == "evobs-8d6060a2d8162d19"


def test_deterministic_id_ignores_argument_object_identity_not_values():
    a = compute_evidence_id("c", "s", "t", "o1", "f1")
    b = compute_evidence_id("c", "s", "t", "o1", "f1")
    c = compute_evidence_id("c", "s", "t", "o2", "f1")
    assert a == b
    assert a != c


def test_deterministic_id_changes_when_any_identity_field_changes():
    base = dict(client_id="c", source_skill="s", source_type="t", source_observation_id="o", source_file_sha256="f")
    base_id = compute_evidence_id(**base)
    for field in base:
        variant = dict(base)
        variant[field] = (variant[field] or "") + "-changed"
        assert compute_evidence_id(**variant) != base_id, f"changing {field} should change the evidence_id"


def test_deterministic_id_never_uses_a_timestamp_as_input():
    # The function signature itself has no timestamp parameter — this test
    # documents/pins that contract so a future refactor can't quietly add
    # one (CLAUDE.md section 26 / SKILL.md section 17.1.1).
    import inspect

    params = list(inspect.signature(compute_evidence_id).parameters)
    assert params == [
        "client_id",
        "source_skill",
        "source_type",
        "source_observation_id",
        "source_file_sha256",
    ], params


def test_missing_required_identity_field_raises():
    with pytest.raises(ValueError):
        compute_evidence_id(client_id="", source_skill=None, source_type="pdf", source_observation_id="o", source_file_sha256=None)
