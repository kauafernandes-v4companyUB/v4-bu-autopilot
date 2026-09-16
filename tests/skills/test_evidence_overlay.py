"""Tests for the monitor-quarter evidence_overlay extension (SKILL.md
section 5.1) — canonical-first resolution, overlay fallback, exact-id
match, client_id guard, and canonical-wins-on-conflict."""

from __future__ import annotations

from scripts.lib.evidence_resolution import resolve_evidence_id

CANONICAL = [
    {"evidence_id": "ev-canon-1", "client_id": "synthtest", "statement": "canonical statement", "type": "metric", "confidence": "medium", "value": 1, "unit": "brl", "period": None},
]


def test_a_canonical_present_resolves_from_canonical_even_with_overlay():
    overlay = [{"evidence_id": "ev-canon-1", "client_id": "synthtest", "statement": "canonical statement", "type": "metric", "confidence": "medium", "value": 1, "unit": "brl", "period": None}]
    r = resolve_evidence_id("ev-canon-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=overlay)
    assert r.resolved_from == "canonical"


def test_b_valid_overlay_resolves_when_absent_from_canonical():
    overlay = [{"evidence_id": "ev-overlay-1", "client_id": "synthtest", "statement": "overlay statement", "type": "metric", "confidence": "medium", "value": 2, "unit": "brl", "period": None}]
    r = resolve_evidence_id("ev-overlay-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=overlay)
    assert r.resolved_from == "overlay"
    assert r.item["statement"] == "overlay statement"


def test_c_overlay_id_mismatch_is_unresolved():
    overlay = [{"evidence_id": "ev-other-id", "client_id": "synthtest", "statement": "x", "type": "metric", "confidence": "medium"}]
    r = resolve_evidence_id("ev-overlay-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=overlay)
    assert r.resolved_from == "unresolved"


def test_e_overlay_wrong_client_id_is_unresolved():
    overlay = [{"evidence_id": "ev-overlay-1", "client_id": "someone-else", "statement": "x", "type": "metric", "confidence": "medium"}]
    r = resolve_evidence_id("ev-overlay-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=overlay)
    assert r.resolved_from == "unresolved"
    assert "client_id" in r.reason


def test_f_overlay_conflicting_with_canonical_is_unresolved_canonical_never_silently_overridden():
    overlay = [{"evidence_id": "ev-canon-1", "client_id": "synthtest", "statement": "DIFFERENT statement", "type": "metric", "confidence": "medium", "value": 999, "unit": "brl", "period": None}]
    r = resolve_evidence_id("ev-canon-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=overlay)
    assert r.resolved_from == "unresolved"
    assert "conflict" in r.reason


def test_no_orphan_when_neither_source_has_the_id():
    r = resolve_evidence_id("ev-nowhere", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=[])
    assert r.resolved_from == "unresolved"


def test_apply_never_calls_this_with_overlay_data_by_contract():
    # This module has no concept of "mode" — apply-mode callers (real
    # monitor-quarter execution) must never pass overlay_evidences at all
    # in apply. That contract lives in SKILL.md section 5.1 and is
    # enforced by callers, not by this pure function; this test documents
    # the expectation so it isn't silently forgotten.
    r = resolve_evidence_id("ev-overlay-1", client_id="synthtest", canonical_evidences=CANONICAL, overlay_evidences=[])
    assert r.resolved_from == "unresolved"  # without overlay data, overlay can never resolve anything
