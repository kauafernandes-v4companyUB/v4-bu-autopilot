"""plan-seasonal-calendar — deterministic support (calendar, lazy context,
validation, render, write). Synthetic fixtures only: no real client data."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.lib import seasonal_planning as sp
from scripts.lib.exec_clock import utc_now_rfc3339

SCHEMA = sp.OUTPUT_SCHEMA_PATH
RICH, EMPTY, OTHER = "synth-rich", "synth-empty", "synth-other"
EMPTY_FILES = {
    "client.json": {"schema_version": "1.0.0", "client_id": None, "display_name": None, "status": "unknown"},
    "current-state.json": {"schema_version": "1.0.0", "client_id": None, "updated_at": None, "status": "unknown", "goals": {}, "metrics": {}, "flags": [], "pending": [], "dependencies": []},
    "decisions.json": {"schema_version": "1.0.0", "client_id": None, "decisions": []},
    "evidence.json": {"schema_version": "1.0.0", "client_id": None, "updated_at": None, "evidences": []},
    "knowledge.json": {"schema_version": "1.0.0", "client_id": None, "updated_at": None, "categories": {}},
    "tasks.json": {"schema_version": "1.0.0", "client_id": None, "updated_at": None, "tasks": []},
    "sources.json": {"schema_version": "1.0.0", "client_id": None, "sources": []},
}


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _client(root: Path, cid: str, **overrides) -> None:
    for name, body in EMPTY_FILES.items():
        body = copy.deepcopy(overrides.get(name, body))
        body["client_id"] = cid
        _write(root / "clients" / cid / name, body)
    _write(root / "clients" / cid / "strategy.md", overrides.get("strategy.md", "# Estratégia\n\n## Posicionamento\n\nunknown — sem fonte ainda.\n"))


@pytest.fixture
def ws(temp_workspace: Path) -> Path:
    root = temp_workspace
    _client(root, RICH, **{
        "client.json": {"schema_version": "1.0.0", "display_name": "Synth Rich", "status": "active"},
        "decisions.json": {"schema_version": "1.0.0", "decisions": [{"decision_id": "dec-001", "statement": "Campanha de verão confirmada para dezembro."}]},
        "knowledge.json": {"schema_version": "1.0.0", "updated_at": "2026-11-01T00:00:00Z", "categories": {"segments": ["varejo", "atacado"]}},
        "strategy.md": "# Estratégia\n\n## Posicionamento\n\nFornecedor regional para varejo e atacado.\n",
    })
    gen = root / "context" / "generated" / RICH
    _write(gen / "replanning" / "plan-2026-12.json", {"client_id": RICH, "status": "applied_to_playbook",
            "decisions": [{"decision_id": "rp-d1", "type": "DECISION", "statement": "Briefing semanal às segundas."}],
            "actions": [{"action_id": "A1", "action": "Briefing de verão", "due_date": "2026-12-07", "due_date_basis": "INFERRED_OPERATIONALLY", "responsible": {"role": None, "basis": "PENDING"}}]})
    _write(gen / "bi-imports" / "2026-11" / "read-bi" / "read-bi-x.json", {"client_id": RICH, "report_period": {"start_date": "2026-11-02", "end_date": "2026-11-08"},
            "metric_observations": [{"label": "Investido", "canonical_metric": "spend", "value": 100.0, "unit": "brl", "channel": "meta_ads"},
                                    {"label": "Mensagens", "canonical_metric": None, "value": 12, "unit": "count", "channel": "meta_ads"}]})
    _write(gen / "replanning" / "poisoned.json", {"client_id": OTHER, "decisions": [{"decision_id": "leak", "type": "DECISION", "statement": "de outro cliente"}]})
    _write(gen / "google-sheets" / "preview.json", {"client_id": RICH, "decisions": [{"decision_id": "never-read", "type": "DECISION", "statement": "x"}]})
    _write(root / "private" / "clients" / RICH / "raw.json", {"decisions": [{"decision_id": "raw", "type": "DECISION", "statement": "x"}]})
    _client(root, EMPTY)
    _client(root, OTHER, **{"decisions.json": {"schema_version": "1.0.0", "decisions": [{"decision_id": "other-d1", "statement": "decisão do outro cliente"}]}})
    return root


def _ctx(ws, cid=RICH, start="2026-12-01", end="2027-01-31", **kw):
    return sp.load_client_context(ws, cid, date.fromisoformat(start), date.fromisoformat(end), **kw)


def _plan(ctx: dict, *, granularity: str = "week") -> dict:
    """A minimal valid plan as an agent would produce it from `ctx`."""
    loaded = {s["kind"] + ":" + s["path"].rsplit("/", 1)[-1]: s for s in ctx["sources"] if s["status"] in ("loaded", "empty")}
    sources_used = [{"source_id": s["source_id"], "path": s["path"], "kind": s["kind"], "used_for": "contexto"} for s in loaded.values()]
    sid = lambda name: next((s["source_id"] for s in ctx["sources"] if s["path"].endswith(name) and s["status"] == "loaded"), None)  # noqa: E731
    knowledge, bi = sid("knowledge.json"), sid("read-bi-x.json")
    per = ctx["period"]
    start, end = per["start_date"], per["end_date"]
    mid = per["weeks"][len(per["weeks"]) // 2]["in_horizon"]["start"]
    segments = [{"segment_id": "varejo", "name": "Varejo", "description": "Frente de varejo", "classification": "FACT", "source_refs": [knowledge]}] if knowledge else []
    seg_ids = [s["segment_id"] for s in segments]
    rec = lambda **k: dict(k, classification="PLANNING_RECOMMENDATION", source_refs=[])  # noqa: E731
    channel = ({"channel": "Meta Ads", "classification": "FACT", "source_refs": [bi]} if bi
               else {"channel": "Meta Ads", "classification": "CLIENT_CONFIRMATION_REQUIRED", "source_refs": []})

    def campaign(cid_, s, e, prev, nxt, prio):
        return {"campaign_id": cid_, "name": f"Campanha {cid_}", "start_date": s, "end_date": e, "objective": "Gerar intenção e conversas.",
                "audience": {"description": "Público do contexto.", "classification": "PLANNING_RECOMMENDATION", "source_refs": []},
                "segment_ids": seg_ids, "funnel_roles": ["CONSIDERATION"], "commercial_opportunity": "Janela sazonal do período.",
                "central_messages": [{"segment_id": seg_ids[0] if seg_ids else None, "message": "Prepare-se para a temporada."}],
                "offer": {"description": "Oferta a definir pelo cliente.", "classification": "CLIENT_CONFIRMATION_REQUIRED", "source_refs": []},
                "cta": "Fale conosco", "channels": [channel], "media_role": "Alcance e conversa.", "materials": ["estático"],
                "dependencies": ["oferta do cliente"], "client_decision": "Oferta e estoque.", "previous_campaign_id": prev, "next_campaign_id": nxt,
                "priority": prio, "classification": "PLANNING_RECOMMENDATION", "source_refs": []}

    units = per["weeks"] if granularity == "week" else per["months"]
    plan = {
        "schema_version": "1.0.0", "skill": "plan-seasonal-calendar", "client_id": ctx["client_id"], "generated_at": utc_now_rfc3339(),
        "status": "draft_for_operator_review",
        "period": {"start_date": start, "end_date": end, "period_id": per["period_id"], "granularity": granularity},
        "operator_instructions": list(ctx["operator_instructions"]), "sources_used": sources_used,
        "strategic_summary": rec(statement="Preparar, capturar e continuar."),
        "facts": [{"id": "F-01", "statement": "Atua em varejo e atacado.", "classification": "FACT", "source_refs": [knowledge]}] if knowledge else [],
        "confirmed_decisions": [{"id": f"CD-{i + 1}", "statement": d["statement"], "classification": "CONFIRMED_OPERATIONAL_DECISION", "source_refs": [d["decision_id"]]}
                                for i, d in enumerate(ctx["confirmed_decisions"])],
        "context_decisions_not_applicable": [], "segments": segments,
        "period_architecture": [rec(phase="Preparar", start_date=start, end_date=end, role="preparação", description="Fase única.")],
        "seasonal_opportunities": [
            dict(rec(occurrence_id=o["occurrence_id"], name=o["name"], start_date=o["start"], end_date=o["end"], relevance="NOT_RECOMMENDED",
                     segment_ids=[], rationale="Sem aderência ao negócio.", role=None))
            for o in per["calendar_occurrences"][:1]],
        "campaigns": [campaign("C1", start, mid, None, "C2", "P0"), campaign("C2", mid, end, "C1", None, "P1")],
        "timeline": [rec(period_start=u["start"], period_end=u["end"], fronts=["C1"], objective="o", main_action="a", material_ready="m",
                         client_decision="d", dependency="dep", next_action="n") for u in units],
        "priorities": {"P0": ["C1"], "P1": ["C2"], "P2": [], "P3": []},
        "dependencies": [rec(id="DEP-1", statement="Oferta definida pelo cliente.")],
        "client_decisions_required": [dict(decision="Estoque disponível", topic="stock", deadline=start, deadline_classification="PLANNING_RECOMMENDATION",
                                           classification="CLIENT_CONFIRMATION_REQUIRED", source_refs=[])],
        "risks": [rec(risk="Oferta indefinida", impact="Campanha sem oferta", mitigation="Prazo de decisão")],
        "anti_priorities": [rec(statement="Não abrir frentes demais ao mesmo tempo.")],
        "suggested_metrics": [
            {"campaign_id": None, "metric": "investimento", "available_in_sources": bool(bi), "required": False,
             "classification": "METRIC" if bi else "UNKNOWN", "source_refs": [bi] if bi else []},
            {"campaign_id": None, "metric": "faturamento", "available_in_sources": False, "required": False, "classification": "UNKNOWN", "source_refs": []}],
        "semantic_summary": {}, "warnings": [],
    }
    plan["semantic_summary"] = sp.semantic_counts(plan)
    return plan


def _issues(plan, ctx):
    plan = copy.deepcopy(plan)
    plan["semantic_summary"] = sp.semantic_counts(plan)
    return sp.validate_plan(plan, ctx, schema_validator=Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))))


# 1 --------------------------------------------------------------------------------------------------


def test_rich_context_is_lazily_loaded_and_a_plan_validates(ws):
    ctx = _ctx(ws)
    status = {s["path"]: s["status"] for s in ctx["sources"]}
    assert status[f"clients/{RICH}/knowledge.json"] == "loaded" and status[f"clients/{RICH}/evidence.json"] == "empty"
    assert status[f"context/generated/{RICH}/replanning/poisoned.json"] == "rejected_other_client"
    assert not any("google-sheets" in p or p.startswith("private/") for p in status)
    ids = {d["decision_id"] for d in ctx["confirmed_decisions"]}
    assert ids == {"dec-001", "rp-d1"}  # canonical + replanning; never the poisoned/preview/private ones
    assert ctx["scheduled_actions"][0]["due_date_basis"] == "INFERRED_OPERATIONALLY"
    assert ctx["metrics"][0]["observations"][0]["canonical_metric"] == "spend" and ctx["observed_channels"] == ["meta_ads"]
    assert _issues(_plan(ctx), ctx) == []


# 2, 9 -----------------------------------------------------------------------------------------------


def test_almost_empty_client_still_plans_without_metrics(ws):
    ctx = _ctx(ws, EMPTY, "2026-10-01", "2026-10-31")
    assert {s["status"] for s in ctx["sources"]} == {"empty"} and ctx["metrics"] == [] and ctx["confirmed_decisions"] == []
    assert {"product", "stock", "price", "discount", "offer", "budget", "team", "capacity", "channel", "calendar"} <= set(ctx["unknown_topics"])
    plan = _plan(ctx)
    assert plan["segments"] == [] and plan["period"]["period_id"] == "2026-10"
    assert _issues(plan, ctx) == []
    bad = copy.deepcopy(plan)
    bad["suggested_metrics"][0]["required"] = True
    assert any(i.startswith("METRIC:") for i in _issues(bad, ctx))


# 3 --------------------------------------------------------------------------------------------------


def test_segments_are_never_invented(ws):
    ctx = _ctx(ws, EMPTY, "2026-10-01", "2026-10-31")
    plan = _plan(ctx)
    plan["campaigns"][0]["segment_ids"] = ["b2b"]
    assert any(i.startswith("INVENTED_SEGMENT") for i in _issues(plan, ctx))
    plan = _plan(ctx)
    plan["segments"] = [{"segment_id": "b2b", "name": "B2B", "description": "d", "classification": "PLANNING_RECOMMENDATION", "source_refs": []}]
    assert any(i.startswith("INVENTED_SEGMENT") for i in _issues(plan, ctx))


# 4 --------------------------------------------------------------------------------------------------


def test_period_crossing_the_year_uses_the_real_calendar(ws):
    ctx = _ctx(ws)
    per = ctx["period"]
    assert per["crosses_year"] and per["period_id"] == "20261201-20270131"
    assert per["weeks"][0]["start"] == "2026-11-30" and per["weeks"][-1]["end"] == "2027-01-31"
    assert [m["month"] for m in per["months"]] == ["2026-12", "2027-01"]
    occ = {o["catalog_id"]: o["start"] for o in per["calendar_occurrences"]}
    assert occ["br-natal"] == "2026-12-25" and occ["br-confraternizacao"] == "2027-01-01" and occ["br-13o-2a-parcela"] == "2026-12-20"
    plan = _plan(ctx)
    plan["timeline"] = plan["timeline"][:-1]
    assert any(i.startswith("TIMELINE_CALENDAR") for i in _issues(plan, ctx))
    assert _issues(_plan(ctx, granularity="month"), ctx) == []


def test_calendar_rules_and_period_ids():
    occ = {o["catalog_id"]: o["start"] for o in sp.resolve_period(date(2026, 11, 1), date(2026, 11, 30))["calendar_occurrences"]}
    assert occ["black-friday"] == "2026-11-27" and occ["cyber-monday"] == "2026-11-30"
    assert sp.easter(2026) == date(2026, 4, 5) and sp.easter(2027) == date(2027, 3, 28)
    assert sp.resolve_period(date(2026, 10, 1), date(2026, 12, 31))["period_id"] == "2026-q4"
    assert sp.resolve_period(date(2026, 7, 1), date(2026, 12, 31))["period_id"] == "2026-h2"
    for bad in ((date(2026, 10, 1), date(2026, 10, 3)), (date(2026, 1, 1), date(2027, 6, 1)), (date(2026, 10, 2), date(2026, 10, 1))):
        with pytest.raises(sp.SeasonalPlanningError):
            sp.resolve_period(*bad)


# 5 --------------------------------------------------------------------------------------------------


def test_catalog_has_no_relevance_and_discards_need_a_reason(ws):
    assert all(set(e) == {"id", "name", "country", "kind", "rule"} for e in sp.load_catalog())
    ctx = _ctx(ws)
    assert all("relevance" not in o for o in ctx["period"]["calendar_occurrences"])
    plan = _plan(ctx)
    plan["seasonal_opportunities"][0]["rationale"] = " "
    assert any("needs a rationale" in i for i in _issues(plan, ctx))
    plan = _plan(ctx)
    plan["seasonal_opportunities"][0]["occurrence_id"] = "br-dia-das-maes@2026"  # not inside the horizon
    assert any(i.startswith("SEASONALITY") for i in _issues(plan, ctx))
    plan = _plan(ctx)
    real = plan["seasonal_opportunities"][0]["start_date"]
    plan["seasonal_opportunities"][0]["start_date"] = plan["seasonal_opportunities"][0]["end_date"] = "2027-01-30"  # window misses the real date
    assert any("does not contain the real date" in i for i in _issues(plan, ctx)) and real != "2027-01-30"


# 6 --------------------------------------------------------------------------------------------------


def test_unknown_offer_price_or_stock_must_stay_client_confirmation(ws):
    ctx = _ctx(ws)
    plan = _plan(ctx)
    plan["campaigns"][0]["offer"]["classification"] = "PLANNING_RECOMMENDATION"
    assert any(i.startswith("INVENTED_OFFER") for i in _issues(plan, ctx))
    for field, text in (("objective", "Vender com 20% de desconto"), ("cta", "Compre por R$ 999")):
        plan = _plan(ctx)
        plan["campaigns"][0][field] = text
        assert any(i.startswith("INVENTED_MONEY") for i in _issues(plan, ctx))
    plan = _plan(ctx)
    plan["campaigns"][0]["channels"] = [{"channel": "Google Ads", "classification": "FACT", "source_refs": []}]
    assert _issues(plan, ctx)


# 7, 8 -----------------------------------------------------------------------------------------------


def test_recommendation_never_becomes_fact_and_decisions_are_preserved(ws):
    ctx = _ctx(ws)
    plan = _plan(ctx)
    plan["risks"][0]["classification"] = "FACT"
    assert any(i.startswith("UNSUPPORTED_FACT") for i in _issues(plan, ctx))
    plan = _plan(ctx)
    plan["confirmed_decisions"][0]["source_refs"] = [plan["sources_used"][0]["source_id"]]
    assert any(i.startswith("UNSUPPORTED_CONFIRMED_OPERATIONAL_DECISION") for i in _issues(plan, ctx))
    plan = _plan(ctx)
    plan["confirmed_decisions"] = plan["confirmed_decisions"][1:]
    assert any(i.startswith("DECISION_DROPPED") for i in _issues(plan, ctx))
    plan["context_decisions_not_applicable"] = [{"decision_id": "dec-001", "reason": "fora do horizonte"}]
    assert _issues(plan, ctx) == []
    plan = _plan(ctx)
    plan["confirmed_decisions"][0]["classification"] = "PLANNING_RECOMMENDATION"
    assert any("DECISION_DOWNGRADED" in i for i in _issues(plan, ctx))


def test_operator_instruction_can_confirm_a_decision(ws):
    ctx = _ctx(ws, operator_instructions=["Promoção de dezembro já decidida."])
    plan = _plan(ctx)
    plan["confirmed_decisions"].append({"id": "CD-OP", "statement": "Promoção de dezembro.", "classification": "CONFIRMED_OPERATIONAL_DECISION", "source_refs": ["OP-01"]})
    assert _issues(plan, ctx) == []


# 10 -------------------------------------------------------------------------------------------------


def test_revenue_is_never_required(ws):
    ctx = _ctx(ws)
    plan = _plan(ctx)
    plan["suggested_metrics"][1].update(required=True, available_in_sources=True, source_refs=[plan["sources_used"][0]["source_id"]])
    assert any(i.startswith("REVENUE_REQUIRED") for i in _issues(plan, ctx))


# 11 -------------------------------------------------------------------------------------------------


def test_client_isolation(ws):
    ctx = _ctx(ws)
    assert not any("other-d1" == d["decision_id"] or OTHER in d["source_id"] for d in ctx["confirmed_decisions"])
    assert not any(s["path"].startswith(f"clients/{OTHER}") for s in ctx["sources"])
    plan = _plan(ctx)
    plan["sources_used"].append({"source_id": "S-99", "path": f"clients/{OTHER}/decisions.json", "kind": "canonical_memory", "used_for": "x"})
    assert any(i.startswith("UNKNOWN_SOURCE") for i in _issues(plan, ctx))
    other = _plan(ctx)
    other["client_id"] = OTHER
    assert _issues(other, ctx)[0].startswith("CLIENT_ISOLATION")
    for bad in ("../x", "a/b", ""):
        with pytest.raises(sp.SeasonalPlanningError):
            _ctx(ws, bad)


# 12, 13, 14 -----------------------------------------------------------------------------------------


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def test_write_is_local_derived_and_never_overwrites(ws):
    ctx = _ctx(ws)
    plan = _plan(ctx)
    before = _tree(ws)
    out = sp.write_plan(ws, plan, ctx)
    after = _tree(ws)
    expected_dir = ws / "context" / "generated" / RICH / "seasonal-planning" / "20261201-20270131"
    assert out["json"] == (expected_dir / "seasonal-plan.json").resolve() and out["markdown"] == (expected_dir / "seasonal-plan.md").resolve()
    assert set(after) - set(before) == {f"context/generated/{RICH}/seasonal-planning/20261201-20270131/seasonal-plan.json",
                                        f"context/generated/{RICH}/seasonal-planning/20261201-20270131/seasonal-plan.md"}
    assert {k: v for k, v in after.items() if k in before} == before  # canonical memory and everything else untouched
    md = out["markdown"].read_text(encoding="utf-8")
    written = json.loads(out["json"].read_text(encoding="utf-8"))
    assert written == plan and sp.markdown_matches(written, md) and f"plan_sha256={out['plan_sha256']}" in md
    changed = copy.deepcopy(written)
    changed["campaigns"][0]["name"] = "Outra"
    assert not sp.markdown_matches(changed, md)
    with pytest.raises(sp.SeasonalPlanningError, match="refusing to overwrite"):
        sp.write_plan(ws, plan, ctx)
    dry = sp.write_plan(ws, plan, ctx, out_subdir="dry-run")
    assert dry["json"].parent.name == "dry-run"
    for bad in ("../escape", "a/b", ".."):
        with pytest.raises(sp.SeasonalPlanningError):
            sp.write_plan(ws, plan, ctx, out_subdir=bad)
    with pytest.raises(sp.SeasonalPlanningError, match="invalid"):
        broken = copy.deepcopy(plan)
        broken["priorities"]["P0"] = []
        sp.write_plan(ws, broken, ctx, out_subdir="broken")


def test_engine_has_no_external_io():
    src = Path(sp.__file__).read_text(encoding="utf-8")
    for token in ("googleapiclient", "requests", "urllib", "socket", "http.client", "google_sheets", "subprocess"):
        assert token not in src


def test_registry_and_contract(repo_root, validate):
    reg = json.loads((repo_root / "skills" / "registry.json").read_text(encoding="utf-8"))
    entry = next(s for s in reg["skills"] if s["id"] == "plan-seasonal-calendar")
    assert entry["category"] == "INTELLIGENCE" and entry["implemented"] and entry["canonical_side_effects"] == "NONE"
    assert (repo_root / entry["skill_path"]).is_file() and (repo_root / entry["output_schema_path"]).is_file()


def test_cli_context_and_validate(ws, tmp_path, capsys):
    from scripts import seasonal_planning as cli
    out = tmp_path / "ctx.json"
    assert cli.main(["context", "--client", RICH, "--start", "2026-12-01", "--end", "2027-01-31", "--workspace", str(ws), "--out", str(out)]) == 0
    ctx = json.loads(out.read_text(encoding="utf-8"))
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(ctx)), encoding="utf-8")
    assert cli.main(["validate", "--client", RICH, "--start", "2026-12-01", "--end", "2027-01-31", "--workspace", str(ws), "--plan", str(plan_path)]) == 0
