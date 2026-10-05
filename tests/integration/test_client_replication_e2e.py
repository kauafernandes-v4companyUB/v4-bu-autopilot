"""V1 replication kit, end to end, on synthetic clients only (acme-demo,
beta-demo) in a temporary workspace — no engine change per client.

Stages: BOOTSTRAP -> SOURCE INTAKE -> SOURCE (deterministic parsers where
they exist) -> MEMORY PROMOTION -> QUARTER CREATE -> MONITORING -> REPLAN
(contract artifacts) -> TASK APPLY + operations -> OPERATOR VIEWS ->
MIDWEEK / WEEK CLOSE -> ROPRE -> QUARTER CLOSE -> NEXT QUARTER CREATE ->
GENERATED DELETE/REBUILD.

What is agent reasoning (client-context / Account x GT normalization, the
diagnose -> audit-plan chain, prepare-ropre) enters as contract-shaped
artifacts validated by the same schemas and deterministic checks the real
run uses; every canonical write goes through a real hash-bound preview,
an operator approval, an atomic apply and a receipt.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts import doctor
from scripts import run_replanning_checks as rc
from scripts.bootstrap_client import bootstrap_client
from scripts.lib import approval as ap
from scripts.lib import memory_promotion as mp
from scripts.lib import operations_ledger as ol
from scripts.lib import quarter_lifecycle as ql
from scripts.lib import quarter_monitoring as qm
from scripts.lib import ropre_lifecycle as rl
from scripts.lib import source_manifest as sm
from scripts.lib import task_ledger as tl
from scripts.lib.evidence_id import compute_evidence_id
from scripts.lib.operator_views import build_midweek, operator_brief, post_call_preview, prepare_call, week_close_preview, what_changed
from scripts.lib.task_bridge import build_create_task_operations
from scripts.lib.task_identity import compute_task_id
from scripts.lib.workspace import resolve_workspace

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "skills" / "read-whatsapp" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "read-bi" / "scripts"))
from extract_bi import extract_csv  # noqa: E402
from parse_export import parse_export  # noqa: E402

APPROVER = "operator-synthetic"
STAGES: dict[str, str] = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def approve(module, pv, approval_id):
    """The operator's explicit decision on one exact preview."""
    builder = getattr(module, "build_approval_candidate", None) or getattr(module, "build_promotion_approval_candidate", None) \
        or getattr(module, "build_quarter_approval_candidate", None) or getattr(module, "build_changes_approval_candidate")
    item = (getattr(module, "approval_item_id", None) or getattr(module, "v1_approval_item_id"))(pv)
    cand = builder(pv, approval_id=approval_id, created_at="2026-10-05T09:00:00Z", preview_path=f"context/generated/{pv['client_id']}/{approval_id}.json")
    return ap.apply_operator_decision(cand, approved_at="2026-10-05T09:00:01Z", approved_by=APPROVER, approve_item_ids=[item])


def persist(ws: Path, client_id: str, name: str, payload: dict) -> None:
    """Transient outputs go to context/generated, as in a real run."""
    p = ws / "context" / "generated" / client_id / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_action(ws, client_id, module, pv, approval_id, apply_fn=None, **kw):
    assert pv["status"] == "success", (approval_id, pv.get("conflicts"), pv.get("errors"), pv.get("validation"))
    persist(ws, client_id, f"previews/{approval_id}.json", pv)
    out = (apply_fn or module.apply)(pv, approve(module, pv, approval_id), *kw.get("args", ()))
    assert out["status"] == "success", (approval_id, out)
    receipt = out.get("receipt")
    assert receipt and (ws / "clients" / client_id / "receipts" / f"{receipt['receipt_id']}.json").is_file(), approval_id
    return out


def canonical_snapshot(client_dir: Path) -> dict:
    return {p.relative_to(client_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(client_dir.rglob("*")) if p.is_file()}


def engine_snapshot() -> dict:
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    return {f: hashlib.sha256((REPO / f).read_bytes()).hexdigest() for f in files if (REPO / f).is_file()}


def evidence(client_id, skill, source_type, obs_id, file_sha, etype, statement, ref_path, **extra):
    return {"evidence_id": compute_evidence_id(client_id, skill, source_type, obs_id, file_sha), "client_id": client_id,
            "source_type": source_type, "source_skill": skill, "source_date": extra.pop("source_date", None),
            "observed_at": "2026-10-05T08:00:00Z", "type": etype, "statement": statement, "confidence": "high",
            "reference": {"label": f"[synthetic] {source_type}", "path": ref_path, "page": None},
            "external_provenance": {"source_observation_id": obs_id, "source_file_sha256": file_sha,
                                    "source_output": f"context/generated/{client_id}/sources/{skill}.json"},
            "tags": ["synthetic"], **extra}


def cand(cid, target, value, eid, action="promote", category=None):
    return {"candidate_id": cid, "target_file": target, "target_path": None, "category": category, "action": action,
            "summary": f"[synthetic] {target}", "reason": "synthetic replication test", "value": value,
            "evidence_ids": [eid], "confidence": "high"}


# ---------------------------------------------------------------------------
# one full client cycle (no client-specific branch anywhere)
# ---------------------------------------------------------------------------


def client_cycle(ws: Path, client_id: str, profile: dict) -> dict:
    cdir, raw = ws / "clients" / client_id, ws / "private" / "clients" / client_id
    ids: dict = {}

    # BOOTSTRAP
    out = bootstrap_client(client_id, display_name=profile["name"], workspace_root=str(ws), initial_context=profile["context"])
    assert out["status"] == "CREATED"
    assert bootstrap_client(client_id, display_name=profile["name"], workspace_root=str(ws), initial_context=profile["context"])["status"] == "NO_CHANGE"
    STAGES["BOOTSTRAP"] = "PASS"

    # RAW sources (synthetic)
    (raw / "whatsapp").mkdir(parents=True)
    (raw / "whatsapp" / "chat.txt").write_text(
        f"[01/10/2026, 10:00:00] Contato Exemplo: Bom dia\n[02/10/2026, 11:30:00] Contato Exemplo: {profile['wa_decision']}\n", encoding="utf-8")
    (raw / "account-gt").mkdir()
    (raw / "account-gt" / "2026-10-02.txt").write_text(f"[synthetic transcript] {profile['gt_pending']}\n", encoding="utf-8")
    (raw / "bi").mkdir()
    (raw / "bi" / "2026-10.csv").write_text(f"Mes,Canal,Investimento\n2026-10,meta_ads,{profile['spend']}\n", encoding="utf-8")

    # SOURCE INTAKE -> manifest (approved)
    pv = sm.preview(cdir, raw, client_id=client_id)
    assert sorted(f["status"] for f in pv["findings"]) == ["NEW_SOURCE"] * 4
    run_action(ws, client_id, sm, pv, f"appr-{client_id}-intake", args=(cdir,))
    manifest = {e["path"]: e for e in json.loads((cdir / "source-manifest.json").read_text(encoding="utf-8"))["sources"]}
    assert {e["source_type"] for e in manifest.values()} == {"whatsapp_export", "account_gt_transcript", "bi_csv", "client_context"}
    assert sm.preview(cdir, raw, client_id=client_id)["status"] == "no_change"
    STAGES["SOURCE INTAKE"] = "PASS"

    # SOURCE skills: deterministic parsers where they exist
    wa = parse_export(str(raw / "whatsapp" / "chat.txt"), source_id=manifest["whatsapp/chat.txt"]["source_id"])
    decision_msg = [m for m in wa["messages"] if profile["wa_decision"] in m["body_raw"]][0]
    bi = extract_csv(raw / "bi" / "2026-10.csv")
    spend_cell = [c for c in bi["rows"][0]["cells"] if c["column"] == "Investimento"][0]  # explicit header, no inference
    spend = float(spend_cell["raw_cell"])
    sha = {k: v["fingerprint"] for k, v in manifest.items()}
    ev_ctx = evidence(client_id, "read-client-context", "client_context", "ctx-1", sha["client-context/initial-context.md"], "fact",
                      profile["context_fact"], f"private/clients/{client_id}/client-context/initial-context.md")
    ev_wa = evidence(client_id, "read-whatsapp", "whatsapp_export", decision_msg["message_fingerprint"],
                     sha["whatsapp/chat.txt"], "decision", profile["wa_decision"], f"private/clients/{client_id}/whatsapp/chat.txt",
                     source_date=decision_msg["message_date"])
    ev_gt = evidence(client_id, "read-account-gt", "account_gt_transcript", "gt-1", sha["account-gt/2026-10-02.txt"], "pending",
                     profile["gt_pending"], f"private/clients/{client_id}/account-gt/2026-10-02.txt", source_date="2026-10-02")
    ev_bi = evidence(client_id, "read-bi", "bi_dashboard_export", "biobs-row-1", sha["bi/2026-10.csv"], "metric",
                     f"[synthetic] Meta Ads spend {spend} for 2026-10-01..2026-10-04", f"private/clients/{client_id}/bi/2026-10.csv",
                     value=spend, unit="brl", period={"from": "2026-10-01", "to": "2026-10-04"})
    ids.update(ev_ctx=ev_ctx["evidence_id"], ev_wa=ev_wa["evidence_id"], ev_gt=ev_gt["evidence_id"], ev_bi=ev_bi["evidence_id"])
    mark = [{"source_id": manifest[p]["source_id"], "revision": 1, "processor": s, "processor_version": "1.0.0",
             "output_ref": f"context/generated/{client_id}/sources/{s}.json"} for p, s in (
        ("whatsapp/chat.txt", "read-whatsapp"), ("bi/2026-10.csv", "read-bi"), ("account-gt/2026-10-02.txt", "read-account-gt"),
        ("client-context/initial-context.md", "read-client-context"))]
    for p, s in (("whatsapp/chat.txt", "read-whatsapp"), ("bi/2026-10.csv", "read-bi")):
        persist(ws, client_id, f"sources/{s}.json", {"parsed": wa if s == "read-whatsapp" else bi})
    run_action(ws, client_id, sm, sm.preview(cdir, raw, client_id=client_id, mark_processed=mark), f"appr-{client_id}-processed", args=(cdir,))

    # MEMORY PROMOTION (evidence, knowledge, current-state, decision)
    candidates = [
        cand("c-ev-bi", "evidence.json", mp.project_to_canonical(ev_bi, added_at="2026-10-05T08:00:00Z", added_by="promote-client-memory"), ev_bi["evidence_id"]),
        cand("c-knowledge", "knowledge.json", {"op": "append", "path": "/categories/business_identity", "key": "knowledge_id", "item": {
            "knowledge_id": f"{client_id}-k-001", "field": "segmento", "statement": profile["context_fact"], "knowledge_type": "fact",
            "confidence": "high", "status": "active", "provenance": {"source_skill": "read-client-context", "evidence_ids": [ev_ctx["evidence_id"]],
                                                                    "promoted_at": "2026-10-05T08:00:00Z", "promoted_by": "promote-client-memory"}}},
             ev_ctx["evidence_id"], category="business_identity"),
        cand("c-decision", "decisions.json", {"op": "append", "path": "/decisions", "key": "decision_id", "item": {
            "decision_id": f"{client_id}-d-001", "statement": profile["wa_decision"], "status": "active",
            "decided_at": decision_msg["message_date"], "evidence_ids": [ev_wa["evidence_id"]]}}, ev_wa["evidence_id"]),
        cand("c-pending", "current-state.json", {"op": "append", "path": "/pending", "key": "statement", "item": {
            "statement": profile["gt_pending"], "semantic_type": "pending", "status": "open", "confidence": "high",
            "source_date": "2026-10-02", "evidence_ids": [ev_gt["evidence_id"]]}}, ev_gt["evidence_id"]),
    ]
    pv = mp.plan_promotion(client_id=client_id, client_dir=cdir, candidates=candidates, evidence_items=[ev_ctx, ev_wa, ev_gt, ev_bi],
                           source_outputs=[{"path": f"context/generated/{client_id}/sources/read-whatsapp.json", "kind": "generated_context"}])
    run_action(ws, client_id, mp, pv, f"appr-{client_id}-promote", apply_fn=mp.apply_promotion, args=(cdir,))
    led = {e["evidence_id"] for e in json.loads((cdir / "evidence.json").read_text(encoding="utf-8"))["evidences"]}
    assert {ids["ev_ctx"], ids["ev_wa"], ids["ev_gt"], ids["ev_bi"]} <= led
    assert json.loads((cdir / "knowledge.json").read_text(encoding="utf-8"))["categories"]["business_identity"][0]["statement"] == profile["context_fact"]
    assert json.loads((cdir / "decisions.json").read_text(encoding="utf-8"))["decisions"][0]["decision_id"] == f"{client_id}-d-001"
    assert json.loads((cdir / "current-state.json").read_text(encoding="utf-8"))["pending"][0]["evidence_ids"] == [ids["ev_gt"]]
    STAGES["MEMORY PROMOTION"] = "PASS"

    # QUARTER CREATE (no seasonal plan; short synthetic period so it can close today)
    q_input = {"period": {"start": "2026-10-01", "end": "2026-10-04"},
               "smart_objective": {"statement": profile["smart"], "metric": "qualified sales", "baseline": None,
                                   "target": {"value": profile["target"], "unit": "count"}, "deadline": "2026-10-04"},
               "planning": {"strategic_priorities": [profile["priority"]], "assumptions": [], "evidence_ids": [ids["ev_ctx"]]},
               "media_plan": {"currency": "BRL", "monthly": [{"month": "2026-10", "channel": "meta_ads", "planned_budget": profile["budget"]}]}}
    run_action(ws, client_id, ql, ql.preview_create(cdir, client_id=client_id, quarter_id="2026-Q4", plan_input=q_input), f"appr-{client_id}-q4", args=(cdir,))
    STAGES["QUARTER CREATE"] = "PASS"

    # read-quarter resolution + monitor-quarter
    media = {"operation_id": "m1", "type": "upsert_media_actual", "month": "2026-10", "channel": "meta_ads", "actual_spend": spend, "evidence_ids": [ids["ev_bi"]]}
    pv = qm.preview(cdir, client_id=client_id, operations=[media])
    assert pv["quarter_id"] == "2026-Q4"
    run_action(ws, client_id, qm, pv, f"appr-{client_id}-monitor", args=(cdir,))

    # REPLAN: contract artifacts (agent reasoning) -> task proposals for this Quarter
    tp_doc = json.loads((REPO / "examples/demo-client/acme-demo/intelligence/task-proposals.json").read_text(encoding="utf-8"))
    tp_doc.update(client_id=client_id, quarter_id="2026-Q4", proposal_set_id=f"{client_id}-tp-2026-10")
    proposals = []
    for i, (readiness, cls) in enumerate((("ready", "task_candidate"), ("needs_decision", "decision_required"), ("external", "external_action")), start=1):
        base = copy.deepcopy(tp_doc["task_proposals"][0 if readiness == "ready" else 2])
        base.update(proposal_id=f"{client_id}-tp-{i}", action_id=f"{client_id}-a-{i}", readiness=readiness, classification=cls,
                    quarter_id="2026-Q4", raised_at="2026-10-02", due_at="2026-10-03" if readiness == "ready" else None,
                    title=f"[synthetic] {profile['actions'][i - 1]}", description=f"[synthetic] {profile['actions'][i - 1]}",
                    origin={"type": "replanning", "evidence_ids": [ids["ev_gt"]]}, evidence_ids=[ids["ev_gt"]])
        if readiness == "ready":
            base["manage_task_operation"] = {"operation_id": f"op-{client_id}-1", "type": "create_task",
                                             "task_id": compute_task_id(client_id, "2026-Q4", base["action_id"]), "title": base["title"],
                                             "description": base["description"], "raised_at": "2026-10-02", "due_at": "2026-10-03",
                                             "quarter_id": "2026-Q4", "origin": base["origin"], "evidence_ids": [ids["ev_gt"]]}
            base["reason_if_blocked"] = None
        else:
            base["manage_task_operation"] = None
            base["reason_if_blocked"] = "[synthetic] requires an operator decision" if readiness == "needs_decision" else "[synthetic] external system only"
        proposals.append(base)
    tp_doc["task_proposals"] = proposals
    # the agent-produced Intelligence chain is checked by the same deterministic tooling as a real run:
    # schema + structural lint + artifact hash chain over a complete synthetic chain in this client's workspace
    chain_dir = ws / "context" / "generated" / client_id / "replanning-chain"
    chain_dir.mkdir(parents=True)
    for name in rc.ARTIFACT_FILES:
        shutil.copy(REPO / "examples/demo-client/acme-demo/intelligence" / name, chain_dir / name)
    registry = rc._schema_registry()
    assert all(rc.validate_artifact(n, chain_dir / n, registry) == [] for n in rc.ARTIFACT_FILES)
    assert rc.lint_and_check_chain(chain_dir) == {}
    tp_errors = [f"{list(e.path)}: {e.message}" for e in rc.Draft202012Validator(
        json.loads((REPO / "skills/generate-tasks/output.schema.json").read_text(encoding="utf-8")), registry=registry).iter_errors(tp_doc)]
    assert tp_errors == [], tp_errors
    persist(ws, client_id, "replanning/task-proposals.json", tp_doc)
    STAGES["REPLAN"] = "PASS"

    # TASK APPLY: approve proposals -> bridge -> manage-task-ledger preview -> approval -> apply
    cand_tp = ap.build_approval_candidate(approval_id=f"appr-{client_id}-tp", client_id=client_id, quarter_id="2026-Q4", created_at="2026-10-05T09:00:00Z",
                                          source_artifact_type="task_proposals", source_artifact_id=tp_doc["proposal_set_id"], source_artifact=tp_doc,
                                          source_artifact_path=f"context/generated/{client_id}/replanning/task-proposals.json",
                                          candidate_items=[{"item_id": p["proposal_id"], "item_type": "task_proposal", "payload": p} for p in proposals])
    tp_approval = ap.apply_operator_decision(cand_tp, approved_at="2026-10-05T09:00:01Z", approved_by=APPROVER, approve_item_ids=[p["proposal_id"] for p in proposals])
    ap.require_fresh_approved_items(tp_approval, tp_doc, {p["proposal_id"]: p for p in proposals})
    bridge = build_create_task_operations(client_id, "2026-Q4", tp_doc, [p["proposal_id"] for p in proposals])
    assert len(bridge.operations) == 1 and len(bridge.skipped) == 2
    run_action(ws, client_id, tl, tl.preview(cdir, client_id=client_id, operations=bridge.operations), f"appr-{client_id}-tasks", args=(cdir,))
    ids["task"] = bridge.operations[0]["task_id"]
    ops = [{"kind": "add", "operation": {
        "operation_id": f"{client_id}-op-decision", "client_id": client_id, "quarter_id": "2026-Q4", "type": "decision_pending",
        "source": {"workflow": "replan-client", "source_item_id": proposals[1]["proposal_id"], "source_artifact_id": tp_doc["proposal_set_id"], "source_artifact_hash": "e" * 64},
        "statement": proposals[1]["title"], "status": "pending", "created_at": "2026-10-05T09:00:00Z", "updated_at": "2026-10-05T09:00:00Z",
        "scheduled_for": None, "deferred_until": None, "approval": None, "external": None, "evidence_ids": [ids["ev_gt"]], "receipt_refs": [],
        "materialized_ref": None, "superseded_by": None, "supersedes": [], "notes": None}},
           {"kind": "add", "operation": {
        "operation_id": f"{client_id}-op-external", "client_id": client_id, "quarter_id": "2026-Q4", "type": "external_approved",
        "source": {"workflow": "replan-client", "source_item_id": proposals[2]["proposal_id"], "source_artifact_id": tp_doc["proposal_set_id"], "source_artifact_hash": "e" * 64},
        "statement": proposals[2]["title"], "status": "approved", "created_at": "2026-10-05T09:00:00Z", "updated_at": "2026-10-05T09:00:00Z",
        "scheduled_for": None, "deferred_until": None,
        "approval": {"status": "approved", "approved_at": "2026-10-05T09:00:01Z", "approved_by": APPROVER, "payload_hash": "f" * 64, "conditions": []},
        "external": {"system": "meta_ads", "action_type": "synthetic_change", "executed": False, "executed_at": None, "external_id": None, "external_url": None},
        "evidence_ids": [ids["ev_gt"]], "receipt_refs": [], "materialized_ref": None, "superseded_by": None, "supersedes": [], "notes": None}}]
    run_action(ws, client_id, ol, ol.preview_changes(cdir, client_id=client_id, changes=ops), f"appr-{client_id}-ops",
               apply_fn=ol.apply_changes, args=(cdir,))
    STAGES["TASK APPLY"] = "PASS"

    # OPERATOR VIEWS (read-only)
    before = canonical_snapshot(cdir)
    today = date(2026, 10, 5)
    brief = operator_brief(client_id, cdir, today)
    assert {t["task_id"] for t in brief["priorities"] if "task_id" in t} == {ids["task"]}  # due 2026-10-03 -> overdue, derived
    assert {o["operation_id"] for o in brief["decisions"]} == {f"{client_id}-op-decision"}
    review = {o["operation_id"]: o["external_state"] for o in brief["external_action_review"]}
    assert review == {f"{client_id}-op-external": "APPROVED_WAITING_CAPABILITY"}
    call = prepare_call(client_id, cdir, today)
    ledger_now = json.loads((cdir / "evidence.json").read_text(encoding="utf-8"))
    assert post_call_preview(client_id, f"DECISION: {profile['wa_decision']}", ledger_now)["status"] == "ignored_fictitious"  # quarantine
    post = post_call_preview(client_id, "REQUEST: enviar proposta revisada", ledger_now, source_date="2026-10-05")
    assert post["status"] == "success" and post["evidence_proposals"][0] == {"type": "REQUEST", "statement": "enviar proposta revisada",
                                                                             "comparison": "NEW", "source_date": "2026-10-05"}
    persist(ws, client_id, "operator/daily-brief.json", brief)
    persist(ws, client_id, "operator/pre-call.json", call)
    assert canonical_snapshot(cdir) == before
    STAGES["OPERATOR BRIEF"] = "PASS"

    # MIDWEEK / WEEK CLOSE
    tasks_doc = json.loads((cdir / "tasks.json").read_text(encoding="utf-8"))
    ops_doc = json.loads((cdir / "operations.json").read_text(encoding="utf-8"))
    mw = build_midweek(client_id, tasks_doc, ops_doc, today, quarter_id="2026-Q4")
    assert [t["task_id"] for t in mw["overdue"]] == [ids["task"]]
    wc = week_close_preview(client_id, tasks_doc, ops_doc, today)
    persist(ws, client_id, "operating-loop/midweek.json", mw)
    persist(ws, client_id, "operating-loop/week-close.json", wc)
    STAGES["MIDWEEK"] = "PASS"
    STAGES["WEEK CLOSE"] = "PASS"

    # ROPRE: prepared draft (agent) -> close-ropre draft -> ready -> completed
    draft = json.loads((REPO / "examples/demo-client/acme-demo/quarters/2026-Q1/check-ins/demo-2026-01-20.json").read_text(encoding="utf-8"))
    draft.update(client_id=client_id, quarter_id="2026-Q4", check_in_id=f"{client_id}-ropre-2026-10-04", scheduled_for="2026-10-04T14:00:00Z",
                 status="draft", completed_at=None, task_ids=[ids["task"]], evidence_ids=[ids["ev_bi"], ids["ev_gt"]],
                 long_term_view=f"[synthetic] {profile['priority']}")
    draft["results"] = [{"statement": f"[synthetic] spend {spend}", "evidence_ids": [ids["ev_bi"]]}]
    draft["objectives"] = [{"smart_objective_reference": "quarter_plan.smart_objective", "statement": profile["smart"], "evidence_ids": []}]
    draft["next_steps"] = [{"statement": proposals[0]["title"], "task_id": ids["task"], "evidence_ids": [ids["ev_gt"]]}]
    persist(ws, client_id, "ropre-draft.json", draft)
    for i, op in enumerate(({"operation_id": "r1", "type": "save_draft", "ropre_draft": draft}, {"operation_id": "r2", "type": "mark_ready"},
                            {"operation_id": "r3", "type": "complete_check_in"})):
        run_action(ws, client_id, rl, rl.preview(cdir, client_id=client_id, quarter_id="2026-Q4", operation=op), f"appr-{client_id}-ropre-{i}", args=(cdir,))
    assert json.loads((cdir / "quarters/2026-Q4/check-ins/current.json").read_text(encoding="utf-8"))["status"] == "completed"
    STAGES["ROPRE"] = "PASS"

    # QUARTER CLOSE
    tasks_before, ops_before = (cdir / "tasks.json").read_bytes(), (cdir / "operations.json").read_bytes()
    pv = ql.preview_close(cdir, client_id=client_id, quarter_id="2026-Q4", as_of_date="2026-10-05")
    run_action(ws, client_id, ql, pv, f"appr-{client_id}-close", args=(cdir,))
    closure = json.loads((cdir / "quarters/2026-Q4/closure.json").read_text(encoding="utf-8"))
    assert json.loads((cdir / "quarters/2026-Q4/plan.json").read_text(encoding="utf-8"))["status"] == "closed"
    assert {c["id"] for c in closure["carry_over_candidates"]} == {ids["task"], f"{client_id}-op-decision", f"{client_id}-op-external"}
    assert (cdir / "tasks.json").read_bytes() == tasks_before and (cdir / "operations.json").read_bytes() == ops_before
    assert sorted(p.name for p in (cdir / "quarters").iterdir() if p.is_dir()) == ["2026-Q4"]
    STAGES["QUARTER CLOSE"] = "PASS"

    # NEXT QUARTER CREATE (new approval)
    nxt = {**q_input, "period": {"start": "2027-01-01", "end": "2027-03-31"},
           "smart_objective": {**q_input["smart_objective"], "deadline": "2027-03-31", "statement": profile["smart"] + " (next)"},
           "media_plan": {"currency": "BRL", "monthly": [{"month": "2027-01", "channel": "meta_ads", "planned_budget": profile["budget"]}]}}
    run_action(ws, client_id, ql, ql.preview_create(cdir, client_id=client_id, quarter_id="2027-Q1", plan_input=nxt), f"appr-{client_id}-q1", args=(cdir,))
    STAGES["NEXT QUARTER CREATE"] = "PASS"
    return ids


def rebuild_views(ws: Path, client_id: str) -> dict:
    """Everything an operator needs, recomputed from canonical only."""
    cdir = ws / "clients" / client_id
    today = date(2026, 10, 5)
    brief = operator_brief(client_id, cdir, today)
    tasks = json.loads((cdir / "tasks.json").read_text(encoding="utf-8"))
    ops = json.loads((cdir / "operations.json").read_text(encoding="utf-8"))
    return {
        "brief": {k: v for k, v in brief.items() if k != "generated_at"},
        "quarter": qm.preview(cdir, client_id=client_id, operations=[])["quarter_id"],
        "tasks": tasks, "operations": ops,
        "ropre": json.loads((cdir / "quarters/2026-Q4/check-ins/current.json").read_text(encoding="utf-8")),
        "closure": json.loads((cdir / "quarters/2026-Q4/closure.json").read_text(encoding="utf-8")),
        "what_changed": what_changed({"tasks": [], "operations": [], "evidences": []},
                                     {"tasks": tasks["tasks"], "operations": ops["operations"],
                                      "evidences": json.loads((cdir / "evidence.json").read_text(encoding="utf-8"))["evidences"]}),
    }


ACME = {"name": "Acme Demo (synthetic)", "context": "[synthetic] Acme sells industrial shelving to B2B buyers.",
        "context_fact": "[synthetic] Acme sells industrial shelving to B2B buyers.", "wa_decision": "[synthetic] Decisão: pausar a campanha de vitrines",
        "gt_pending": "[synthetic] Revisar a landing page de prateleiras", "spend": "512.34", "smart": "[synthetic] 12 qualified sales by 2026-10-04",
        "target": 12, "priority": "[synthetic] priorizar prateleiras", "budget": 2000.0,
        "actions": ["Ajustar landing page", "Decidir verba de novembro", "Trocar criativo no Meta Ads"]}
BETA = {"name": "Beta Demo (synthetic)", "context": "[synthetic] Beta runs a chain of pet clinics.",
        "context_fact": "[synthetic] Beta runs a chain of pet clinics.", "wa_decision": "[synthetic] Decisão: abrir agenda aos sábados",
        "gt_pending": "[synthetic] Enviar relatório de agendamentos", "spend": "88.10", "smart": "[synthetic] 40 bookings by 2026-10-04",
        "target": 40, "priority": "[synthetic] agendamentos", "budget": 300.0,
        "actions": ["Publicar horários", "Decidir promoção", "Atualizar perfil no Google"]}


def test_client_replication_e2e(temp_workspace):
    engine_before = engine_snapshot()
    acme_ids = client_cycle(temp_workspace, "acme-demo", ACME)

    # GENERATED DELETE / REBUILD
    acme_dir = temp_workspace / "clients" / "acme-demo"
    views_before = rebuild_views(temp_workspace, "acme-demo")
    canonical_before = canonical_snapshot(acme_dir)
    generated = temp_workspace / "context" / "generated" / "acme-demo"
    assert generated.is_dir() and any(generated.rglob("*.json"))
    shutil.rmtree(generated)
    assert rebuild_views(temp_workspace, "acme-demo") == views_before
    assert canonical_snapshot(acme_dir) == canonical_before
    assert views_before["quarter"] == "2027-Q1" and views_before["ropre"]["status"] == "completed"
    STAGES["GENERATED DELETE/REBUILD"] = "PASS (NO_DURABLE_STATE_LOSS)"

    # SECOND CLIENT, same workspace: isolation both ways
    beta_ids = client_cycle(temp_workspace, "beta-demo", BETA)
    assert canonical_snapshot(acme_dir) == canonical_before  # beta never touched acme
    beta_dir = temp_workspace / "clients" / "beta-demo"
    for cdir, own, other in ((acme_dir, acme_ids, beta_ids), (beta_dir, beta_ids, acme_ids)):
        text = "\n".join(p.read_text(encoding="utf-8") for p in cdir.rglob("*") if p.is_file() and p.suffix in (".json", ".md"))
        assert all(v not in text for k, v in other.items()), "cross-client identifier leaked"
        for name in ("evidence.json", "tasks.json", "operations.json", "source-manifest.json"):
            data = json.loads((cdir / name).read_text(encoding="utf-8"))
            assert data["client_id"] == cdir.name
    assert ACME["context_fact"] not in (beta_dir / "knowledge.json").read_text(encoding="utf-8")
    assert BETA["context_fact"] not in (acme_dir / "knowledge.json").read_text(encoding="utf-8")

    # doctor on the whole synthetic workspace
    results = doctor.check_client_workspace_integrity(resolve_workspace(required=True, override=str(temp_workspace)), doctor._schema_registry())
    assert {k: v for k, v in results.items() if v[0] == "FAIL"} == {}

    # ZERO ENGINE MODIFICATION PER CLIENT
    assert engine_snapshot() == engine_before
    STAGES["ZERO ENGINE MODIFICATION PER CLIENT"] = "PASS"
    STAGES["BETA ISOLATION"] = "PASS"
    print(json.dumps(STAGES, indent=2))
