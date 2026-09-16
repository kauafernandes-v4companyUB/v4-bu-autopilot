"""Structural invariant checks across the Intelligence artifact chain
(operation/replanning-rules.md) that a single-file JSON Schema can't
express — mainly cross-artifact evidence traceability (an evidence_id
cited in diagnosis.json must actually exist in context-pack.json's
evidence_index) and a few explicit business invariants the mission
called out (audit_status derivation, task classification/readiness
pairing, priority ordering).

This is deterministic linting, not reasoning — it never decides *what*
a finding/gap/priority/action should say, only whether the artifacts
are internally consistent with each other and with the rules already
written down in SKILL.md/operation/replanning-rules.md.
"""

from __future__ import annotations


def _index_ids(evidence_index: list[dict]) -> set[str]:
    return {e["id"] for e in evidence_index}


def lint_context_pack(cp: dict) -> list[str]:
    issues = []
    ids = [e["id"] for e in cp["evidence_index"]]
    if len(ids) != len(set(ids)):
        issues.append("context_pack.evidence_index has duplicate ids")
    known = set(ids)

    def check_group(items, label):
        for item in items:
            for eid in item.get("evidence_ids", []):
                if eid not in known:
                    issues.append(f"{label} references unknown evidence_id {eid!r} (not in evidence_index)")

    check_group(cp["observed_results"]["metrics"], "observed_results.metrics")
    check_group(cp["observed_results"]["commercial_results"], "observed_results.commercial_results")
    for group_name in ("decisions", "requests", "feedback", "ideas", "dependencies"):
        check_group(cp["client_voice"][group_name], f"client_voice.{group_name}")
    check_group(cp["operational_state"]["pending"], "operational_state.pending")
    check_group(cp["operational_state"]["blockers"], "operational_state.blockers")
    for c in cp["conflicts"]:
        for eid in c["evidence_ids"]:
            if eid not in known:
                issues.append(f"conflicts[{c['conflict_id']}] references unknown evidence_id {eid!r}")
    return issues


def lint_diagnosis(diagnosis: dict, context_pack: dict) -> list[str]:
    issues = []
    known = _index_ids(context_pack["evidence_index"])
    seen_ids = set()
    for f in diagnosis["findings"]:
        if f["finding_id"] in seen_ids:
            issues.append(f"duplicate finding_id {f['finding_id']!r}")
        seen_ids.add(f["finding_id"])
        for eid in f["evidence_ids"]:
            if eid not in known:
                issues.append(f"finding {f['finding_id']} references unknown evidence_id {eid!r}")
        for eid in f.get("opposing_evidence", []):
            if eid not in known:
                issues.append(f"finding {f['finding_id']} opposing_evidence references unknown evidence_id {eid!r}")
    return issues


def lint_gaps(gaps: dict, context_pack: dict) -> list[str]:
    issues = []
    known = _index_ids(context_pack["evidence_index"])
    seen_ids = set()
    for g in gaps["gaps"]:
        if g["gap_id"] in seen_ids:
            issues.append(f"duplicate gap_id {g['gap_id']!r}")
        seen_ids.add(g["gap_id"])
        for eid in g["evidence_ids"]:
            if eid not in known:
                issues.append(f"gap {g['gap_id']} references unknown evidence_id {eid!r}")
        if g["calculable"] and (g["current"] is None or g["delta"] is None):
            issues.append(f"gap {g['gap_id']} is calculable=true but current/delta is null")
        if not g["calculable"] and (g["current"] is not None or g["delta"] is not None):
            issues.append(f"gap {g['gap_id']} is calculable=false but current/delta is not null (never invent a value)")
    return issues


def lint_priorities(priorities: dict, diagnosis: dict, gaps: dict) -> list[str]:
    issues = []
    finding_ids = {f["finding_id"] for f in diagnosis["findings"]}
    gap_ids = {g["gap_id"] for g in gaps["gaps"]}
    orders = [p["order"] for p in priorities["priorities"]]
    if sorted(orders) != list(range(1, len(orders) + 1)):
        issues.append(f"priority order values are not a contiguous 1..N sequence: {orders}")
    for p in priorities["priorities"]:
        for fid in p["related_findings"]:
            if fid not in finding_ids:
                issues.append(f"priority {p['priority_id']} references unknown finding_id {fid!r}")
        for gid in p["related_gaps"]:
            if gid not in gap_ids:
                issues.append(f"priority {p['priority_id']} references unknown gap_id {gid!r}")
        dims = p["rationale_dimensions"]
        if not any(v is not None for v in dims.values()):
            issues.append(f"priority {p['priority_id']} has no rationale_dimensions populated — unjustified rank")
    return issues


def lint_replanning(replanning: dict, priorities: dict, context_pack: dict) -> list[str]:
    issues = []
    known_priority_ids = {p["priority_id"] for p in priorities["priorities"]}
    known_evidence = _index_ids(context_pack["evidence_index"])
    action_ids = set()
    for ws in replanning["workstreams"]:
        if ws["priority_id"] not in known_priority_ids:
            issues.append(f"workstream {ws['workstream_id']} references unknown priority_id {ws['priority_id']!r}")
        for eid in ws["evidence_ids"]:
            if eid not in known_evidence:
                issues.append(f"workstream {ws['workstream_id']} references unknown evidence_id {eid!r}")
        for a in ws["actions"]:
            if a["action_id"] in action_ids:
                issues.append(f"duplicate action_id {a['action_id']!r} across workstreams")
            action_ids.add(a["action_id"])
            for eid in a["evidence_ids"]:
                if eid not in known_evidence:
                    issues.append(f"action {a['action_id']} references unknown evidence_id {eid!r}")
    return issues


def derive_audit_status(issues: list[dict]) -> str:
    if any(i["severity"] == "high" for i in issues):
        return "fail"
    if issues:
        return "pass_with_warnings"
    return "pass"


def lint_audit(audit: dict) -> list[str]:
    issues = []
    expected = derive_audit_status(audit["issues"])
    if audit["audit_status"] != expected:
        issues.append(
            f"audit_status={audit['audit_status']!r} does not match severity-derived status {expected!r} "
            f"(operation/replanning-rules.md: any 'high' -> fail; only low/medium -> pass_with_warnings; none -> pass)"
        )
    return issues


_CLASSIFICATION_READINESS = {
    "task_candidate": {"ready", "needs_scheduling"},
    "decision_required": {"needs_decision"},
    "external_action": {"external"},
    "information_request": {"dependency"},
    "monitoring_item": {"ready", "needs_scheduling"},
    "not_task": {"not_task"},
}


def lint_task_proposals(task_proposals: dict, replanning: dict) -> list[str]:
    issues = []
    known_action_ids = {a["action_id"] for ws in replanning["workstreams"] for a in ws["actions"]}
    for tp in task_proposals["task_proposals"]:
        if tp["action_id"] not in known_action_ids:
            issues.append(f"task proposal {tp['proposal_id']} references unknown action_id {tp['action_id']!r}")
        allowed = _CLASSIFICATION_READINESS.get(tp["classification"], set())
        if tp["readiness"] not in allowed:
            issues.append(
                f"task proposal {tp['proposal_id']}: classification={tp['classification']!r} does not allow "
                f"readiness={tp['readiness']!r} (allowed: {sorted(allowed)})"
            )
        if tp["readiness"] == "ready" and tp["manage_task_operation"] is None:
            issues.append(f"task proposal {tp['proposal_id']} is readiness=ready but has no manage_task_operation")
        if "responsible" in (tp.get("manage_task_operation") or {}):
            issues.append(f"task proposal {tp['proposal_id']} manage_task_operation must never carry a 'responsible' field")
    return issues
