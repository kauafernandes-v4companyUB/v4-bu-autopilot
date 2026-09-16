from __future__ import annotations

import copy

from scripts.lib import replanning_lint


# --- clean demo chain: zero lint issues at every stage ---

def test_demo_context_pack_lints_clean(demo_chain):
    assert replanning_lint.lint_context_pack(demo_chain["context-pack"]) == []


def test_demo_diagnosis_lints_clean(demo_chain):
    assert replanning_lint.lint_diagnosis(demo_chain["diagnosis"], demo_chain["context-pack"]) == []


def test_demo_gaps_lint_clean(demo_chain):
    assert replanning_lint.lint_gaps(demo_chain["gaps"], demo_chain["context-pack"]) == []


def test_demo_priorities_lint_clean(demo_chain):
    assert replanning_lint.lint_priorities(demo_chain["priorities"], demo_chain["diagnosis"], demo_chain["gaps"]) == []


def test_demo_replanning_lints_clean(demo_chain):
    assert replanning_lint.lint_replanning(demo_chain["replanning"], demo_chain["priorities"], demo_chain["context-pack"]) == []


def test_demo_audit_lints_clean(demo_chain):
    assert replanning_lint.lint_audit(demo_chain["audit"]) == []


def test_demo_task_proposals_lint_clean(demo_chain):
    assert replanning_lint.lint_task_proposals(demo_chain["task-proposals"], demo_chain["replanning"]) == []


# --- F/G/H: finding_class distinctions actually present in the demo ---

def test_demo_has_an_observed_issue_finding(demo_chain):
    classes = {f["finding_class"] for f in demo_chain["diagnosis"]["findings"]}
    assert "observed_issue" in classes


def test_demo_has_a_hypothesis_finding_with_confirmation_criterion(demo_chain):
    hyps = [f for f in demo_chain["diagnosis"]["findings"] if f["finding_class"] == "hypothesis"]
    assert hyps
    for h in hyps:
        assert h["hypothesis_when_applicable"] is not None
        assert h["hypothesis_when_applicable"]["would_be_confirmed_by"]
        assert h["semantic_type"] == "hypothesis"


def test_demo_has_a_missing_data_finding(demo_chain):
    classes = {f["finding_class"] for f in demo_chain["diagnosis"]["findings"]}
    assert "missing_data" in classes


# --- J: a finding citing an evidence_id absent from the context pack is caught ---

def test_finding_with_unknown_evidence_id_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["diagnosis"])
    broken["findings"][0]["evidence_ids"] = ["acme-demo-ev-does-not-exist"]
    issues = replanning_lint.lint_diagnosis(broken, demo_chain["context-pack"])
    assert any("unknown evidence_id" in i for i in issues)


# --- K/L/N: gap invariants ---

def test_calculable_gap_has_numeric_current_and_delta(demo_chain):
    calculable = [g for g in demo_chain["gaps"]["gaps"] if g["calculable"]]
    assert calculable
    for g in calculable:
        assert g["current"] is not None
        assert g["delta"] is not None


def test_uncalculable_gap_never_has_a_value(demo_chain):
    uncalculable = [g for g in demo_chain["gaps"]["gaps"] if not g["calculable"]]
    assert uncalculable
    for g in uncalculable:
        assert g["current"] is None
        assert g["delta"] is None


def test_gap_marked_calculable_but_missing_value_is_caught_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["gaps"])
    broken["gaps"][1]["current"] = None  # was calculable=true with a real current
    issues = replanning_lint.lint_gaps(broken, demo_chain["context-pack"])
    assert any("calculable=true but current/delta is null" in i for i in issues)


def test_gap_marked_uncalculable_but_carrying_a_value_is_caught_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["gaps"])
    broken["gaps"][0]["current"] = 0  # calculable=false must never carry an invented value
    issues = replanning_lint.lint_gaps(broken, demo_chain["context-pack"])
    assert any("never invent a value" in i for i in issues)


# --- O/P/Q: priorities ---

def test_blocking_priority_is_ranked_first_when_justified(demo_chain):
    top = min(demo_chain["priorities"]["priorities"], key=lambda p: p["order"])
    assert top["blocking"] is True


def test_priority_order_is_contiguous(demo_chain):
    orders = [p["order"] for p in demo_chain["priorities"]["priorities"]]
    assert sorted(orders) == list(range(1, len(orders) + 1))


def test_priority_with_no_rationale_dimensions_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["priorities"])
    broken["priorities"][0]["rationale_dimensions"] = {k: None for k in broken["priorities"][0]["rationale_dimensions"]}
    issues = replanning_lint.lint_priorities(broken, demo_chain["diagnosis"], demo_chain["gaps"])
    assert any("unjustified rank" in i for i in issues)


def test_priority_order_gap_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["priorities"])
    broken["priorities"][1]["order"] = 5  # not contiguous with order=1
    issues = replanning_lint.lint_priorities(broken, demo_chain["diagnosis"], demo_chain["gaps"])
    assert any("not a contiguous" in i for i in issues)


# --- R/U: replanning traceability and dependency respect ---

def test_every_action_has_evidence_ids(demo_chain):
    for ws in demo_chain["replanning"]["workstreams"]:
        for a in ws["actions"]:
            assert a["evidence_ids"], a["action_id"]


def test_dependent_workstream_declares_its_dependency(demo_chain):
    ws2 = next(w for w in demo_chain["replanning"]["workstreams"] if w["workstream_id"] == "acme-demo-ws-002")
    assert "acme-demo-a-001" in ws2["dependencies"]


def test_workstream_with_unknown_priority_id_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["replanning"])
    broken["workstreams"][0]["priority_id"] = "does-not-exist"
    issues = replanning_lint.lint_replanning(broken, demo_chain["priorities"], demo_chain["context-pack"])
    assert any("unknown priority_id" in i for i in issues)


# --- V/W/X/Y: audit ---

def test_audit_status_codes_include_deadline_and_semantic_elevation(repo_root):
    import json
    schema = json.loads((repo_root / "skills" / "audit-plan" / "output.schema.json").read_text())
    codes = schema["$defs"]["issue"]["properties"]["code"]["enum"]
    assert "invented_deadline" in codes
    assert "invented_responsible" in codes
    assert "semantic_elevation" in codes
    assert "unsupported_claim" in codes


def test_audit_status_pass_with_warnings_matches_low_severity_only(demo_chain):
    assert demo_chain["audit"]["audit_status"] == "pass_with_warnings"
    assert all(i["severity"] != "high" for i in demo_chain["audit"]["issues"])


def test_audit_status_mismatch_with_high_severity_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["audit"])
    broken["audit_status"] = "pass"
    broken["issues"][0]["severity"] = "high"
    issues = replanning_lint.lint_audit(broken)
    assert any("fail" in i for i in issues)


def test_clean_audit_with_zero_issues_derives_to_pass():
    clean = {"audit_status": "pass", "issues": []}
    assert replanning_lint.derive_audit_status(clean["issues"]) == "pass"
    assert replanning_lint.lint_audit(clean) == []


# --- Z/AA/AB: task readiness ---

def test_ready_task_has_due_date(demo_chain):
    ready = [tp for tp in demo_chain["task-proposals"]["task_proposals"] if tp["readiness"] == "ready"]
    assert ready
    for tp in ready:
        assert tp["manage_task_operation"]["due_at"]


def test_needs_scheduling_task_has_no_manage_task_operation(demo_chain):
    blocked = [tp for tp in demo_chain["task-proposals"]["task_proposals"] if tp["readiness"] == "needs_scheduling"]
    assert blocked
    for tp in blocked:
        assert tp["manage_task_operation"] is None
        assert tp["reason_if_blocked"]


def test_decision_required_action_is_never_auto_taskified(demo_chain):
    decisions = [tp for tp in demo_chain["task-proposals"]["task_proposals"] if tp["classification"] == "decision_required"]
    assert decisions
    for tp in decisions:
        assert tp["readiness"] == "needs_decision"
        assert tp["manage_task_operation"] is None


def test_information_request_classification_never_allows_ready_readiness():
    allowed = replanning_lint._CLASSIFICATION_READINESS["information_request"]
    assert "ready" not in allowed
    assert allowed == {"dependency"}


def test_task_proposal_with_mismatched_classification_readiness_is_rejected_by_lint(demo_chain):
    broken = copy.deepcopy(demo_chain["task-proposals"])
    broken["task_proposals"][2]["readiness"] = "ready"  # decision_required can never be ready
    issues = replanning_lint.lint_task_proposals(broken, demo_chain["replanning"])
    assert any("does not allow readiness" in i for i in issues)
