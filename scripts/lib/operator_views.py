"""Read-only operational views and preview builders.

No function here writes canonical state.  The optional persistence of an
intake manifest belongs to an explicit ACTION after its preview is approved.
"""
from __future__ import annotations

import hashlib, json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from scripts.lib.operations_ledger import external_execution_status, human_external_state

def utcnow() -> str: return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _task_ref(t): return {k: t.get(k) for k in ("task_id", "title", "due_at", "status")}
def _op_ref(o, state): return {"operation_id": o.get("operation_id"), "statement": o.get("statement"), "status": o.get("status"), "scheduled_for": o.get("scheduled_for"), "derived_state": state}
def _load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default

def resolve_deferred_operations(operations: Iterable[dict], tasks: Iterable[dict] = ()) -> list[dict]:
    """Return a transient state projection. Deferred records remain canonical
    ``deferred`` until a separate explicit operator decision changes them."""
    completed_ops = {x.get("operation_id") for x in operations if x.get("status") in {"completed", "executed", "materialized"}}
    completed_tasks = {x.get("task_id") for x in tasks if x.get("status") == "completed"}
    answer = []
    for op in operations:
        item = dict(op)
        gate = op.get("deferred_until") or {}
        ready = op.get("status") == "deferred" and ((gate.get("type") == "after_operation" and gate.get("reference_id") in completed_ops) or (gate.get("type") == "after_task" and gate.get("reference_id") in completed_tasks))
        item["resolved_state"] = "READY_FOR_DECISION" if ready else op.get("status")
        answer.append(item)
    return answer

def daily_view(tasks: dict, operations: dict, today: date | None = None, capabilities: dict | None = None) -> dict:
    today = today or date.today(); capabilities = capabilities or {}
    result = {k: [] for k in ("TODAY", "OVERDUE", "NEXT_7_DAYS", "BLOCKED", "WAITING_DECISION", "DEFERRED", "EXTERNAL_APPROVED", "EXTERNAL_EXECUTION_READY", "EXTERNAL_NOT_EXECUTABLE", "OPERATIONS_OVERDUE", "OPERATIONS_SCHEDULED", "EXTERNAL_REVIEW")}
    for task in tasks.get("tasks", []):
        if task.get("status") != "pending": continue
        due = date.fromisoformat(task["due_at"])
        if due < today: result["OVERDUE"].append(_task_ref(task))
        elif due == today: result["TODAY"].append(_task_ref(task))
        elif due <= today + timedelta(days=7): result["NEXT_7_DAYS"].append(_task_ref(task))
    projected = resolve_deferred_operations(operations.get("operations", []), tasks.get("tasks", []))
    for op in projected:
        state, typ = op["resolved_state"], op.get("type")
        # Scheduled operations: overdue is derived from `today` for the view only;
        # the canonical status stays "scheduled" until an explicit ACTION changes it.
        if op.get("status") == "scheduled" and op.get("scheduled_for"):
            when = date.fromisoformat(op["scheduled_for"])
            if when < today: result["OPERATIONS_OVERDUE"].append(_op_ref(op, "OVERDUE"))
            else: result["OPERATIONS_SCHEDULED"].append(_op_ref(op, "TODAY" if when == today else "SCHEDULED"))
        if typ in ("external_approved", "external_rejected") or op.get("external"):
            ref = _op_ref(op, None); ref["external_state"] = human_external_state(op, capability=capabilities.get(op["operation_id"]))
            ref["system"] = (op.get("external") or {}).get("system")
            result["EXTERNAL_REVIEW"].append(ref)
        if state == "READY_FOR_DECISION" or typ == "decision_pending" and op.get("status") in {"pending", "active"}: result["WAITING_DECISION"].append(op)
        elif state == "deferred": result["DEFERRED"].append(op)
        elif typ == "external_approved":
            status = external_execution_status(op, capability=capabilities.get(op["operation_id"]))
            op["execution_status"] = status
            result["EXTERNAL_APPROVED"].append(op)
            result["EXTERNAL_EXECUTION_READY" if status == "execution_ready" else "EXTERNAL_NOT_EXECUTABLE"].append(op)
    return result

def operator_brief(client_id: str, client_dir: Path, today: date | None = None) -> dict:
    tasks = _load(client_dir / "tasks.json", {"tasks": []}); ops = _load(client_dir / "operations.json", {"operations": []})
    view = daily_view(tasks, ops, today)
    return {"schema_version":"1.0.0", "skill":"operator-brief", "client_id":client_id, "generated_at":utcnow(),
      "summary": {"open_tasks": sum(t.get("status")=="pending" for t in tasks["tasks"]), "open_operations": len([o for o in ops["operations"] if o.get("status") not in {"completed","cancelled","executed","revoked","superseded","materialized"}])},
      "priorities": view["TODAY"] + view["OVERDUE"] + view["OPERATIONS_OVERDUE"], "pendencias": view["NEXT_7_DAYS"], "decisions": view["WAITING_DECISION"], "next_milestones": view["NEXT_7_DAYS"] + view["OPERATIONS_SCHEDULED"],
      "overdue_operations": view["OPERATIONS_OVERDUE"], "risks_flags": [], "approved_not_executed": view["EXTERNAL_APPROVED"],
      "external_action_review": view["EXTERNAL_REVIEW"], "missing_data": []}

def prepare_call(client_id: str, client_dir: Path, today: date | None = None) -> dict:
    brief = operator_brief(client_id, client_dir, today)
    return {"schema_version":"1.0.0", "skill":"prepare-client-call", "client_id":client_id, "generated_at":utcnow(),
      "abertura_sugerida": "Revisar os combinados e os pontos abertos sustentados no registro.", "numeros_importantes": [],
      "status_dos_combinados": brief["pendencias"], "pontos_para_cobrar": brief["priorities"], "decisoes_abertas":brief["decisions"],
      "perguntas_objetivas": [], "riscos":brief["risks_flags"], "o_que_nao_prometer": ["Não prometer prazo, resultado, orçamento ou execução sem evidência e aprovação."]}

def source_fingerprint(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def classify_source(path: Path) -> str:
    from scripts.lib.source_manifest import classify
    return classify(path.as_posix())
def source_intake_preview(client_id: str, private_dir: Path, manifest: dict | None = None, now: str | None = None) -> dict:
    """Read-only discovery view; the single implementation lives in
    scripts/lib/source_manifest.py (manage-source-manifest persists it)."""
    from scripts.lib.source_manifest import scan
    now = now or utcnow(); manifest = manifest or {"sources": []}
    found = scan(client_id, private_dir, manifest, now)
    entries = {e["path"]: e for e in found["new_entries"]}
    latest = {e["path"]: e for e in sorted(manifest.get("sources", []), key=lambda e: e.get("revision", 1))}
    sources = []
    for f in found["findings"]:
        if f["status"] == "NO_CHANGE":
            sources.append({**latest[f["path"]], "status": "no_change", "observed_at": now})
        elif f["status"] in ("NEW_SOURCE", "NEW_REVISION"):
            sources.append(entries[f["path"]])
    return {"schema_version":"1.1.0", "client_id":client_id, "updated_at":now, "sources":sources, "findings": found["findings"]}

def meaningful_diff(before: dict, after: dict) -> bool:
    """Generated timestamps are not state changes."""
    def clean(value):
        if isinstance(value, dict): return {k: clean(v) for k,v in value.items() if k not in {"generated_at", "updated_at"}}
        if isinstance(value, list): return [clean(v) for v in value]
        return value
    return clean(before) != clean(after)

def post_call_preview(client_id: str, text: str, canonical_evidence: dict | None = None, source_date: str | None = None) -> dict:
    """Conservative normalization. No persistence; synthetic/test material is
    quarantined completely. Semantic classification deliberately requires an
    explicit leading type marker, avoiding invented extraction."""
    if any(x in text.casefold() for x in ("fictício", "ficticio", "synthetic", "teste", "test data")):
        return {"client_id":client_id,"mode":"preview","status":"ignored_fictitious","evidence_proposals":[],"task_proposals":[],"operation_proposals":[],"warnings":["fictitious_or_test_source_not_persistable"]}
    types={"fact":"FACT","metric":"METRIC","decision":"DECISION","request":"REQUEST","commitment":"COMMITMENT","pending":"PENDING","risk":"RISK","hypothesis":"HYPOTHESIS","idea":"IDEA","dependency":"DEPENDENCY"}
    existing={e.get("statement", "").casefold() for e in (canonical_evidence or {}).get("evidences", [])}; proposals=[]
    for raw in text.splitlines():
        line=raw.strip(); lower=line.casefold()
        for key,label in types.items():
            if lower.startswith(key + ":"):
                statement=line.split(":",1)[1].strip(); comparison="CONFIRMED" if statement.casefold() in existing else "NEW"
                proposals.append({"type":label,"statement":statement,"comparison":comparison,"source_date":source_date}); break
    return {"client_id":client_id,"mode":"preview","status":"success","evidence_proposals":proposals,"task_proposals":[],"operation_proposals":[],"warnings":["explicit operator approval is required before any ACTION"]}

def build_midweek(client_id: str, tasks: dict, operations: dict, today: date | None = None, evidence_since_week_start: list[dict] | None = None, monitoring: dict | None = None, quarter_id: str | None = None) -> dict:
    """Canonical-ledger midweek projection; never infers execution."""
    today = today or date.today(); start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    all_tasks = tasks.get("tasks", []); planned = [t for t in all_tasks if t.get("due_at") and start <= date.fromisoformat(t["due_at"]) <= end]
    completed = [t for t in all_tasks if t.get("status") == "completed"]; pending = [t for t in all_tasks if t.get("status") == "pending"]
    overdue = [t for t in pending if date.fromisoformat(t["due_at"]) < today]
    decisions = [o for o in resolve_deferred_operations(operations.get("operations", []), all_tasks) if o["resolved_state"] == "READY_FOR_DECISION" or (o.get("type") == "decision_pending" and o.get("status") in {"pending", "active"})]
    attention = [_op_ref(o, "OVERDUE") for o in operations.get("operations", []) if o.get("status") == "scheduled" and o.get("scheduled_for") and date.fromisoformat(o["scheduled_for"]) < today]
    return {"schema_version":"1.0.0","skill":"midweek","client_id":client_id,"quarter_id":quarter_id,"generated_at":utcnow(),"status":"success","operations_needing_attention":attention,"week_of":{"from":str(start),"to":str(end)}, "planned_this_week":[_task_ref(t) for t in planned],"completed":[_task_ref(t) for t in completed],"pending":[_task_ref(t) for t in pending],"overdue":[_task_ref(t) for t in overdue],"blocked":[], "changed_evidence_or_results": evidence_since_week_start or [],"risks":[f for f in (monitoring or {}).get("flags", []) if f.get("type") == "risk" and f.get("status") != "resolved"], "actions_needing_decision":[{"statement":o["statement"],"source":"operations"} for o in decisions],"missing_data":[],"warnings":[]}

def week_close_preview(client_id: str, tasks: dict, operations: dict, today: date | None = None, monitoring: dict | None = None) -> dict:
    """Read-only close artifact; carry-forward remains a candidate only."""
    today = today or date.today(); start=today-timedelta(days=today.weekday()); end=start+timedelta(days=6)
    promised=[t for t in tasks.get("tasks", []) if t.get("due_at") and start <= date.fromisoformat(t["due_at"]) <= end]
    executed=[t for t in promised if t.get("status")=="completed" and t.get("completed_at") and start <= date.fromisoformat(t["completed_at"]) <= end]; not_executed=[t for t in promised if t.get("status") in {"pending","cancelled"}]
    result={"schema_version":"1.0.0","skill":"week-close","client_id":client_id,"generated_at":utcnow(),"status":"success","week_of":{"from":str(start),"to":str(end)}, "promised":[_task_ref(t) for t in promised],"executed":[_task_ref(t) for t in executed],"not_executed":[_task_ref(t) for t in not_executed],"blockers":[],"bi_movement":None, "smart_evidence":(monitoring or {}).get("objective_progress"),"open_flags":[f for f in (monitoring or {}).get("flags",[]) if f.get("status")!="resolved"], "carry_forward_candidates":[{"task_id":t["task_id"],"title":t["title"],"reason":"not_executed; operator review required"} for t in not_executed], "ropre_preparation_inputs":{"results_candidates":[],"next_steps_candidates":[t["title"] for t in not_executed]},"missing_data":[],"warnings":[]}
    stable={k:v for k,v in result.items() if k != "generated_at"}; result["artifact_ref"]={"artifact_type":"week-close","content_sha256":hashlib.sha256(json.dumps(stable,sort_keys=True,separators=(",",":")).encode()).hexdigest()}
    return result

def what_changed(before: dict, after: dict) -> dict:
    """Canonical comparison ignoring generated/updated timestamps."""
    categories={"NOVO":[],"ALTERADO":[],"CONCLUÍDO":[],"ABERTO":[],"BLOQUEADO":[],"DECISÕES NOVAS":[],"IMPACTO NO PLANO":[]}
    for name,key in (("evidences","evidence_id"),("tasks","task_id"),("operations","operation_id")):
        old={x.get(key):x for x in before.get(name, [])}; new={x.get(key):x for x in after.get(name, [])}
        for ident,item in new.items():
            if ident not in old: categories["NOVO"].append({"kind":name,"id":ident})
            elif meaningful_diff(old[ident],item): categories["ALTERADO"].append({"kind":name,"id":ident})
            if item.get("status") in {"completed","executed"}: categories["CONCLUÍDO"].append({"kind":name,"id":ident})
            elif item.get("status") in {"pending","active","deferred"}: categories["ABERTO"].append({"kind":name,"id":ident})
            if item.get("type") == "decision_pending": categories["DECISÕES NOVAS"].append({"kind":name,"id":ident})
    return categories
