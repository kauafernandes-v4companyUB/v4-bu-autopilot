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
    # Recomputed independently from a real read-bi.json observation during
    # the Walmaq BI apply (see project history) — pinned here so the
    # algorithm can never silently drift.
    eid = compute_evidence_id(
        client_id="walmaq",
        source_skill="read-bi",
        source_type="pdf",
        source_observation_id="biobs-4ddc33077f4a1ad3",
        source_file_sha256="e278f84acbcfe44d19405cf567eecc23551a0e816c66dbc8af682a07c6b79f75",
    )
    assert eid == "evobs-c26aed008bb65da0"


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
