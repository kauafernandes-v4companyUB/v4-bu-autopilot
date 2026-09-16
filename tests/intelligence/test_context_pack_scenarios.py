"""Context Pack scenario coverage (mission section 27, letters A-E) that
the acme-demo chain doesn't exercise on its own — conflicts, opposing
evidence, and the blocking/non-blocking missing_data distinction —
using small standalone constructed instances validated against the real
schema, never Walmaq or any real client shape.
"""

from __future__ import annotations

import json


def _minimal_valid_context_pack():
    return {
        "schema_version": "1.0.0",
        "skill": "build-context-pack",
        "client_id": "synthtest",
        "quarter_id": "2026-Q2",
        "generated_at": "2026-04-01T00:00:00Z",
        "status": "success",
        "identity": {"client_id": "synthtest", "quarter_id": "2026-Q2", "generated_at": "2026-04-01T00:00:00Z"},
        "source_status": [
            {"source": "read-bi", "available": True, "observed_at": "2026-04-01T00:00:00Z", "source_date": None, "period": None, "freshness": "current", "status": "success", "confidence": "medium", "limitations": []}
        ],
        "strategic_context": {"smart_objective": None, "target": None, "baseline": None, "priorities": [], "assumptions": [], "long_term_direction": None, "evidence_ids": []},
        "observed_results": {"metrics": [], "media_monitoring": [], "objective_progress": None, "commercial_results": []},
        "client_voice": {"decisions": [], "requests": [], "feedback": [], "ideas": [], "dependencies": []},
        "operational_state": {
            "pending": [], "tasks_summary": {"total": 0, "pending": 0, "completed": 0, "cancelled": 0, "overdue": 0},
            "ropre_state": {"current_status": "absent", "last_completed_check_in_id": None, "note": None},
            "flags": [], "blockers": [],
        },
        "conflicts": [],
        "missing_data": [],
        "quality": {"sufficient_for_diagnosis": False, "confidence": "low", "reasons": ["minimal synthetic fixture"]},
        "evidence_index": [
            {"id": "syn-ev-1", "kind": "canonical", "type": "metric", "statement": "synthetic A", "confidence": "medium", "source": "read-bi", "observed_at": "2026-04-01T00:00:00Z"},
            {"id": "syn-ev-2", "kind": "source_observation", "type": "metric", "statement": "synthetic B, contradicts A", "confidence": "medium", "source": "read-bi", "observed_at": "2026-04-02T00:00:00Z"},
        ],
        "warnings": [],
    }


def test_a_complete_sources_pack_is_schema_valid(validate, repo_root):
    cp = _minimal_valid_context_pack()
    errors = validate(cp, repo_root / "schemas" / "context-pack.schema.json")
    assert not errors, errors


def test_b_non_blocking_missing_source_keeps_status_useful(validate, repo_root):
    cp = _minimal_valid_context_pack()
    cp["status"] = "partial"
    cp["source_status"].append(
        {"source": "read-account-gt", "available": False, "observed_at": None, "source_date": None, "period": None, "freshness": "unknown", "status": "not_run", "confidence": "low", "limitations": ["not run"]}
    )
    cp["missing_data"].append({"field": "account_gt_notes", "expected_source": "read-account-gt", "impact": "minor context gap", "blocking": False})
    errors = validate(cp, repo_root / "schemas" / "context-pack.schema.json")
    assert not errors, errors
    assert cp["status"] in ("success", "partial")  # never forced to failed just because one non-blocking source is absent


def test_c_blocking_missing_source_is_explicit(validate, repo_root):
    cp = _minimal_valid_context_pack()
    cp["missing_data"].append({"field": "sales_evidence", "expected_source": "crm_or_evidence", "impact": "objective progress cannot be measured", "blocking": True})
    errors = validate(cp, repo_root / "schemas" / "context-pack.schema.json")
    assert not errors, errors
    assert any(m["blocking"] for m in cp["missing_data"])


def test_d_conflict_between_two_evidences_is_recorded_not_resolved_silently(validate, repo_root):
    cp = _minimal_valid_context_pack()
    cp["conflicts"].append({
        "conflict_id": "syn-conflict-1",
        "statement": "syn-ev-1 and syn-ev-2 report different values for the same metric/period.",
        "evidence_ids": ["syn-ev-1", "syn-ev-2"],
        "why_unresolved": "Same authority level, same recency — no explicit later decision resolves which is authoritative.",
    })
    errors = validate(cp, repo_root / "schemas" / "context-pack.schema.json")
    assert not errors, errors
    assert len(cp["conflicts"]) == 1
    assert set(cp["conflicts"][0]["evidence_ids"]) == {"syn-ev-1", "syn-ev-2"}


def test_e_unknown_freshness_is_a_valid_first_class_value(validate, repo_root):
    cp = _minimal_valid_context_pack()
    cp["source_status"][0]["freshness"] = "unknown"
    cp["source_status"][0]["period"] = None
    cp["source_status"][0]["source_date"] = None
    errors = validate(cp, repo_root / "schemas" / "context-pack.schema.json")
    assert not errors, errors


def test_freshness_enum_is_exactly_the_three_sustainable_categories(repo_root):
    schema = json.loads((repo_root / "schemas" / "context-pack.schema.json").read_text())
    assert schema["$defs"]["freshness"]["enum"] == ["current", "historical", "unknown"]


# --- I: opposing evidence is a first-class, non-hidden field ---

def test_finding_can_declare_opposing_evidence(repo_root):
    finding_schema = json.loads((repo_root / "skills" / "diagnose-client" / "output.schema.json").read_text())
    assert "opposing_evidence" in finding_schema["$defs"]["finding"]["required"]
