"""document-winning-creative — deterministic support (lazy context, isolation,
metric normalization/derivation, validation, render, write). Synthetic
fixtures only: no real client or creative data."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.lib import creative_performance as cp
from scripts.lib.exec_clock import utc_now_rfc3339

ALPHA, BETA = "synth-alpha", "synth-beta"
OUT_SCHEMA = Draft202012Validator(json.loads(cp.OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")))
IN_SCHEMA = Draft202012Validator(json.loads(cp.INPUT_SCHEMA_PATH.read_text(encoding="utf-8")))
WINNER = "private/clients/synth-alpha/creatives/winner-a.png"
FULL_METRICS = [
    {"metric": "Investimento", "value": 500.0, "unit": "brl", "source": "operator"},
    {"metric": "Impressões", "value": 25000, "unit": "count", "source": "operator"},
    {"metric": "Alcance", "value": 10000, "unit": "count", "source": "operator"},
    {"metric": "Cliques", "value": 450, "unit": "count", "source": "operator"},
    {"metric": "Mensagens", "value": 40, "unit": "count", "source": "operator"},
    {"metric": "Leads", "value": 20, "unit": "count", "source": "operator"},
    {"metric": "SQL", "value": 5, "unit": "count", "source": "operator"},
    {"metric": "Vendas", "value": 2, "unit": "count", "source": "operator"},
]


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def ws(temp_workspace: Path) -> Path:
    root = temp_workspace
    for cid in (ALPHA, BETA):
        _write(root / "clients" / cid / "client.json", {"schema_version": "1.0.0", "client_id": cid, "display_name": cid, "status": "active"})
        _write(root / "clients" / cid / "strategy.md", "# Estratégia\n\nunknown\n")
    _write(root / WINNER, _png(1080, 1350))
    _write(root / "private/clients/synth-alpha/creatives/other-b.png", _png(1080, 1080))  # another creative: must never be read
    _write(root / "private/clients/synth-alpha/creatives/copy.txt", "Headline sintética\nCTA: Fale no WhatsApp\n")
    _write(root / "private/clients/synth-alpha/bi/export.json", {"client_id": ALPHA, "rows": [{"ad": "winner-a", "ctr": 1.8}]})
    _write(root / "private/clients/synth-alpha/bi/foreign.json", {"client_id": BETA, "rows": []})
    _write(root / "private/clients/synth-alpha/tests/ab-test.json", {"client_id": ALPHA, "variants": ["a", "b"]})
    _write(root / "private/clients/synth-beta/creatives/beta.png", _png(100, 100))
    return root


def _brief(**over) -> dict:
    b = {"schema_version": "1.0.0", "client_id": ALPHA, "creative_id": "winner-a",
         "winner_declaration": {"statement": "Esse foi o criativo campeão de setembro.", "declared_by": "operator"},
         "period": {"start_date": "2026-09-01", "end_date": "2026-09-30", "label": "setembro"},
         "campaign_context": {"campaign_name": "Campanha sintética", "objective": "mensagens", "channel": "meta_ads", "placement": None, "notes": None},
         "assets": [{"path": WINNER, "kind": "image"}], "metrics": copy.deepcopy(FULL_METRICS),
         "operator_instructions": ["Documentar para replicar no próximo briefing."]}
    b.update(over)
    return b


def _ctx(ws, brief=None):
    return cp.load_context(ws, brief or _brief(), input_validator=IN_SCHEMA)


def _report(ctx: dict) -> dict:
    """A minimal valid report as an agent would write it from `ctx`."""
    loaded_asset = next((a["asset_id"] for a in ctx["assets"] if a["status"] == "loaded"), None)
    elements = []
    for i, dim in enumerate(cp.DIMENSIONS):
        observed = loaded_asset is not None and dim in ("format", "cta", "headline", "orientation")
        elements.append({"element_id": f"E-{i + 1:02d}", "dimension": dim, "status": "OBSERVED" if observed else "NOT_OBSERVABLE",
                         "description": f"{dim} visível no bloco superior" if observed else None,
                         "asset_id": loaded_asset if observed else None, "location": "bloco superior" if observed else None,
                         "learning_class": "OBSERVED_PATTERN"})
    cta = next((e["element_id"] for e in elements if e["dimension"] == "cta" and e["status"] == "OBSERVED"), None)
    metrics = {m["metric_key"]: m for m in ctx["provided_metrics"] + ctx["derived_metrics"] if m["value"] is not None}
    perf = []
    if "ctr" in metrics:
        v = metrics["ctr"]["value"]
        perf.append({"id": "PF-01", "statement": f"CTR de {v:.2f}% no período.".replace(".", ",", 1), "learning_class": "PERFORMANCE_FACT",
                     "metric_refs": [metrics["ctr"]["metric_id"]]})
    hyps = ([{"id": "H-01", "statement": "A exposição antecipada do CTA pode ter contribuído para os cliques.", "learning_class": "REPLICATION_HYPOTHESIS",
              "based_on_elements": [cta], "related_metric_refs": [metrics["ctr"]["metric_id"]] if "ctr" in metrics else [],
              "test_suggestion": "Repetir CTA visível no topo em peça semelhante, mantendo o resto constante.", "confidence": "medium"}] if cta else [])
    report = {
        "schema_version": "1.0.0", "skill": cp.SKILL, "client_id": ctx["client_id"], "creative_id": ctx["creative_id"],
        "generated_at": utc_now_rfc3339(), "status": "draft_for_operator_review",
        "winner_status": copy.deepcopy(ctx["winner_status"]), "period": copy.deepcopy(ctx["period"]),
        "campaign_context": copy.deepcopy(ctx["campaign_context"]),
        "sources_used": [{"source_id": s["source_id"], "path": s["path"], "kind": s["kind"], "used_for": "análise"}
                         for s in ctx["sources"] if s["status"] == "loaded"],
        "asset_metadata": copy.deepcopy(ctx["assets"]), "observed_elements": elements,
        "provided_metrics": copy.deepcopy(ctx["provided_metrics"]), "derived_metrics": copy.deepcopy(ctx["derived_metrics"]),
        "performance_summary": perf, "replication_hypotheses": hyps,
        "do_not_generalize": [{"id": "NG-01", "statement": "Não afirmar que a cor do CTA causou mais cliques sem comparação.",
                               "learning_class": "DO_NOT_GENERALIZE", "related_elements": [cta] if cta else []}],
        "comparisons": [],
        "unknowns": [{"topic": t, "status": "NOT_AVAILABLE" if t.startswith("metric:") else "UNKNOWN", "reason": "não fornecido"}
                     for t in ctx["required_unknowns"]] + [{"topic": "destino do clique", "status": "UNKNOWN", "reason": "não observável na imagem"}],
        "operator_notes": copy.deepcopy(ctx["operator_notes"]),
        "memory_promotion_candidates": ([{"kind": "PERFORMANCE_FACT", "ref": "PF-01", "note": "CTR do vencedor"}] if perf else [])
                                       + ([{"kind": "OBSERVED_PATTERN", "ref": cta, "note": "CTA visível"}] if cta else []),
        "learning_summary": {}, "warnings": list(ctx["warnings"]),
    }
    report["learning_summary"] = cp.learning_counts(report)
    return report


def _issues(report, ctx):
    report = copy.deepcopy(report)
    report["learning_summary"] = cp.learning_counts(report)
    return cp.validate_report(report, ctx, schema_validator=OUT_SCHEMA)


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


# 1 --------------------------------------------------------------------------------------------------


def test_full_metrics_report_validates(ws):
    ctx = _ctx(ws)
    a = ctx["assets"][0]
    assert (a["status"], a["width"], a["height"], a["orientation"], a["aspect_ratio"], a["dimensions_basis"]) == \
           ("loaded", 1080, 1350, "portrait", "4:5", "file_header")
    derived = {d["metric_key"]: d["value"] for d in ctx["derived_metrics"]}
    assert derived == {"ctr": 1.8, "cpc": 1.1111, "cpm": 20.0, "frequency": 2.5, "cost_per_message": 12.5, "cpl": 25.0}
    assert {m["metric_key"] for m in ctx["metrics_not_available"]} == {"revenue"}
    assert _issues(_report(ctx), ctx) == []


# 2, 14 ----------------------------------------------------------------------------------------------


def test_few_metrics_and_no_history_of_other_creatives(ws):
    ctx = _ctx(ws, _brief(metrics=[{"metric": "CTR", "value": 2.1, "unit": "percent", "source": "operator"}], period=None, campaign_context=None))
    assert ctx["derived_metrics"] == [] and "period" in ctx["required_unknowns"]
    assert [s["path"] for s in ctx["sources"]] == [WINNER]  # nothing but the brief's file — no other creative, no identity
    assert "other creatives of the client" in ctx["not_read"] and not ctx["loaded"]["client_identity"]
    report = _report(ctx)
    assert _issues(report, ctx) == []
    report["unknowns"] = [u for u in report["unknowns"] if u["topic"] != "period"]
    assert any("UNKNOWN_NOT_DECLARED: 'period'" in i for i in _issues(report, ctx))


def test_client_identity_is_loaded_only_on_request(ws):
    assert not any(s["kind"] == "client_identity" for s in _ctx(ws)["sources"])
    ctx = _ctx(ws, _brief(load_client_identity=True))
    assert [s["path"] for s in ctx["sources"] if s["kind"] == "client_identity"] == [f"clients/{ALPHA}/client.json", f"clients/{ALPHA}/strategy.md"]
    assert _issues(_report(ctx), ctx) == []


# 3 --------------------------------------------------------------------------------------------------


def test_missing_metric_is_never_zero(ws):
    metrics = [m for m in FULL_METRICS if m["metric"] != "Cliques"] + [{"metric": "Cliques", "value": None, "unit": "count", "source": "operator"}]
    ctx = _ctx(ws, _brief(metrics=metrics))
    clicks = next(m for m in ctx["provided_metrics"] if m["metric_key"] == "clicks")
    assert clicks["value"] is None and clicks["status"] == "NOT_AVAILABLE"
    assert not {"ctr", "cpc"} & {d["metric_key"] for d in ctx["derived_metrics"]}  # nothing derived from an absent value
    assert {"metric:clicks", "metric:ctr", "metric:cpc"} <= set(ctx["required_unknowns"])
    report = _report(ctx)
    assert _issues(report, ctx) == []
    zeroed = copy.deepcopy(report)
    next(m for m in zeroed["provided_metrics"] if m["metric_key"] == "clicks").update(value=0, status="PROVIDED")
    assert any(i.startswith("METRICS_ALTERED") for i in _issues(zeroed, ctx))
    dropped = copy.deepcopy(report)
    dropped["unknowns"] = [u for u in dropped["unknowns"] if u["topic"] != "metric:clicks"]
    assert any("metric:clicks" in i for i in _issues(dropped, ctx))
    zero_den = _ctx(ws, _brief(metrics=[{"metric": "investimento", "value": 10, "unit": "brl", "source": "operator"},
                                        {"metric": "leads", "value": 0, "unit": "count", "source": "operator"}]))
    assert zero_den["derived_metrics"] == [] and zero_den["provided_metrics"][1]["value"] == 0  # a real zero stays zero


# 4 --------------------------------------------------------------------------------------------------


def test_operator_declared_winner_is_preserved(ws):
    ctx = _ctx(ws)
    assert ctx["winner_status"] == {"source": "OPERATOR_DECLARED", "declared_by": "operator",
                                    "statement": "Esse foi o criativo campeão de setembro.", "statistically_compared": False}
    report = _report(ctx)
    changed = copy.deepcopy(report)
    changed["winner_status"]["statement"] = "Venceu com significância estatística."
    assert any(i.startswith("INPUT_ALTERED: winner_status") for i in _issues(changed, ctx))
    for field, value in (("source", "STATISTICALLY_PROVEN"), ("statistically_compared", True)):
        bad = copy.deepcopy(report)
        bad["winner_status"][field] = value
        assert any(i.startswith("schema") for i in _issues(bad, ctx))
    ranked = copy.deepcopy(report)
    ranked["ranking"] = [{"creative_id": "winner-a", "position": 1}]
    assert any(i.startswith("schema") for i in _issues(ranked, ctx))  # no ranking exists in this contract


# 5 --------------------------------------------------------------------------------------------------


def test_no_comparison_without_comparative_source(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    report["comparisons"] = [{"id": "CMP-01", "statement": "Teve CTR maior que o criativo B.", "source_refs": ["S-01"]}]
    assert any(i.startswith("NO_COMPARATIVE_EVIDENCE") for i in _issues(report, ctx))
    ctx2 = _ctx(ws, _brief(comparative_evidence=[{"path": "private/clients/synth-alpha/tests/ab-test.json", "description": "teste A/B"}]))
    cmp_id = ctx2["comparative_evidence_ids"][0]
    ok = _report(ctx2)
    ok["comparisons"] = [{"id": "CMP-01", "statement": "No teste A/B fornecido, a variante A performou melhor devido ao CTA no topo.", "source_refs": [cmp_id]}]
    assert _issues(ok, ctx2) == []
    ok["comparisons"][0]["source_refs"] = ["S-01"]
    assert any(i.startswith("NO_COMPARATIVE_EVIDENCE") for i in _issues(ok, ctx2))


# 6 --------------------------------------------------------------------------------------------------


def test_hypothesis_never_becomes_fact(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    for mutate in (lambda r: r["replication_hypotheses"][0].update(learning_class="PERFORMANCE_FACT"),
                   lambda r: r["replication_hypotheses"][0].update(confidence="high"),
                   lambda r: r["performance_summary"].append({"id": "PF-02", "statement": "CTA no topo gera cliques.", "learning_class": "PERFORMANCE_FACT", "metric_refs": []})):
        bad = copy.deepcopy(report)
        mutate(bad)
        assert any(i.startswith("schema") for i in _issues(bad, ctx))
    promoted = copy.deepcopy(report)
    promoted["memory_promotion_candidates"].append({"kind": "OBSERVED_PATTERN", "ref": "H-01", "note": "x"})
    assert any(i.startswith("HYPOTHESIS_PROMOTED") for i in _issues(promoted, ctx))
    ungrounded = copy.deepcopy(report)
    ungrounded["replication_hypotheses"][0]["based_on_elements"] = ["E-23"]  # destination: NOT_OBSERVABLE
    assert any(i.startswith("UNGROUNDED_HYPOTHESIS") for i in _issues(ungrounded, ctx))


# 7 --------------------------------------------------------------------------------------------------


def test_missing_revenue_does_not_block(ws):
    ctx = _ctx(ws)
    assert "metric:revenue" in ctx["required_unknowns"]
    assert _issues(_report(ctx), ctx) == []
    none = _ctx(ws, _brief(metrics=[]))
    assert none["provided_metrics"] == [] and len(none["metrics_not_available"]) == len(cp.STANDARD_METRICS)
    assert _issues(_report(none), none) == []


# 8 --------------------------------------------------------------------------------------------------


def test_derived_metric_is_distinct_from_provided(ws):
    ctx = _ctx(ws)
    ctr = next(d for d in ctx["derived_metrics"] if d["metric_key"] == "ctr")
    assert ctr["classification"] == "DERIVED_METRIC" and ctr["formula"] == "clicks / impressions * 100" and len(ctr["inputs"]) == 2
    assert all(m["classification"] == "METRIC" for m in ctx["provided_metrics"])
    with_ctr = _ctx(ws, _brief(metrics=FULL_METRICS + [{"metric": "CTR", "value": 1.8, "unit": "percent", "source": "operator"}]))
    assert "ctr" not in {d["metric_key"] for d in with_ctr["derived_metrics"]} and not with_ctr["warnings"]
    off = _ctx(ws, _brief(metrics=FULL_METRICS + [{"metric": "CTR", "value": 3.0, "unit": "percent", "source": "operator"}]))
    assert any(w.startswith("METRIC_INCONSISTENT") for w in off["warnings"])
    assert next(m for m in off["provided_metrics"] if m["metric_key"] == "ctr")["value"] == 3.0  # never corrected
    report = _report(ctx)
    moved = copy.deepcopy(report)
    moved["derived_metrics"] = []
    assert any(i.startswith("DERIVED_METRICS_ALTERED") for i in _issues(moved, ctx))


def test_performance_fact_numbers_must_come_from_metrics(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    imp = next(m["metric_id"] for m in ctx["provided_metrics"] if m["metric_key"] == "impressions")
    report["performance_summary"].append({"id": "PF-02", "statement": "25.000 impressões em 2026-09-30.", "learning_class": "PERFORMANCE_FACT", "metric_refs": [imp]})
    assert _issues(report, ctx) == []
    report["performance_summary"][1]["statement"] = "27.000 impressões."
    assert any(i.startswith("INVENTED_NUMBER") for i in _issues(report, ctx))


# 9 --------------------------------------------------------------------------------------------------


def test_client_isolation(ws):
    ctx = _ctx(ws)
    other = _report(ctx)
    other["client_id"] = BETA
    assert _issues(other, ctx)[0].startswith("CLIENT_ISOLATION")
    report = _report(ctx)
    report["sources_used"].append({"source_id": "S-09", "path": "private/clients/synth-beta/creatives/beta.png", "kind": "creative_asset", "used_for": "x"})
    assert any(i.startswith("UNKNOWN_SOURCE") for i in _issues(report, ctx))
    for bad in ("../x", "a/b", "", "Synth"):
        with pytest.raises(cp.CreativePerformanceError):
            cp.load_context(ws, _brief(client_id=bad))
    for path in ("../outside.png", "/etc/passwd", "outputs/x.png", "private/shared/x.png", "C:/x.png"):
        with pytest.raises(cp.CreativePerformanceError):
            _ctx(ws, _brief(assets=[{"path": path, "kind": "image"}]))
    with pytest.raises(cp.CreativePerformanceError):
        _ctx(ws, _brief(client_id="synth-missing"))


# 13 -------------------------------------------------------------------------------------------------


def test_other_client_asset_or_source_is_rejected(ws):
    ctx = _ctx(ws, _brief(assets=[{"path": WINNER, "kind": "image"},
                                  {"path": "private/clients/synth-beta/creatives/beta.png", "kind": "image"},
                                  {"path": "private/clients/synth-alpha/creatives/copy.txt", "kind": "text", "client_id": BETA}],
                          metric_sources=[{"path": "private/clients/synth-alpha/bi/foreign.json"}],
                          metrics=[{"metric": "CTR", "value": 9.9, "unit": "percent", "source": "private/clients/synth-alpha/bi/foreign.json"}]))
    status = {s["path"]: s["status"] for s in ctx["sources"]}
    assert status["private/clients/synth-beta/creatives/beta.png"] == "rejected_other_client"
    assert status["private/clients/synth-alpha/creatives/copy.txt"] == "rejected_other_client"  # declared owner differs
    assert status["private/clients/synth-alpha/bi/foreign.json"] == "rejected_other_client"  # client_id inside the file differs
    ctr = ctx["provided_metrics"][0]
    assert ctr["value"] is None and ctr["status"] == "NOT_AVAILABLE" and "rejected_other_client" in ctr["note"]
    assert all(a["sha256"] is None for a in ctx["assets"] if a["status"] != "loaded")
    report = _report(ctx)
    assert _issues(report, ctx) == []
    rejected = next(s for s in ctx["sources"] if s["status"] == "rejected_other_client")
    report["sources_used"].append({"source_id": rejected["source_id"], "path": rejected["path"], "kind": rejected["kind"], "used_for": "x"})
    assert any(i.startswith("UNUSABLE_SOURCE") for i in _issues(report, ctx))
    report = _report(ctx)
    report["observed_elements"][5].update(status="OBSERVED", description="texto", asset_id="A-02")
    assert any(i.startswith("UNOBSERVABLE_ELEMENT") for i in _issues(report, ctx))


def test_no_loaded_asset_keeps_every_element_unobservable(ws):
    ctx = _ctx(ws, _brief(assets=[{"path": "private/clients/synth-alpha/creatives/gone.png", "kind": "image"}]))
    assert ctx["assets"][0]["status"] == "missing" and any(w.startswith("NO_LOADED_ASSET") for w in ctx["warnings"])
    report = _report(ctx)
    assert all(e["status"] == "NOT_OBSERVABLE" for e in report["observed_elements"]) and _issues(report, ctx) == []
    report["observed_elements"][0].update(status="OBSERVED", description="carrossel", asset_id="A-01")
    assert any(i.startswith("UNOBSERVABLE_ELEMENT") for i in _issues(report, ctx))
    omitted = _report(ctx)
    omitted["observed_elements"] = omitted["observed_elements"][:-1]
    assert any(i.startswith("DIMENSIONS_NOT_ADDRESSED") for i in _issues(omitted, ctx))


# 15 -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("claim", [
    "O criativo venceu porque apresentou a oferta logo no início.",
    "Performou melhor devido ao CTA verde.",
    "Esse elemento causou o aumento de cliques.",
    "Esse padrão é comprovadamente superior.",
    "O CTR ficou acima da média do mercado.",
    "Foi melhor que os outros criativos.",
    "Graças à oferta, o CPL caiu.",
    "It won because of the hook.",
])
def test_causal_language_is_rejected_without_comparative_evidence(ws, claim):
    ctx = _ctx(ws)
    for where in ("hypothesis", "element", "fact"):
        report = _report(ctx)
        if where == "hypothesis":
            report["replication_hypotheses"][0]["statement"] = claim
        elif where == "element":
            report["observed_elements"][0]["description"] = claim
        else:
            report["performance_summary"][0]["statement"] = claim.replace("1", "")
        assert any(i.startswith("CAUSAL_CLAIM_WITHOUT_EVIDENCE") for i in _issues(report, ctx)), (where, claim)
    exempt = _report(ctx)
    exempt["do_not_generalize"][0]["statement"] = f"Não generalizar: “{claim}” não tem comparação."
    assert _issues(exempt, ctx) == []


def test_observation_and_hedged_hypothesis_are_allowed(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    report["observed_elements"][0]["description"] = "O criativo apresenta oferta no primeiro bloco visual."
    report["replication_hypotheses"][0]["statement"] = "A exposição antecipada da oferta pode ter contribuído para reduzir fricção."
    assert _issues(report, ctx) == []


# 10, 11, 12 -----------------------------------------------------------------------------------------


def test_write_is_local_derived_and_never_overwrites(ws):
    ctx = _ctx(ws)
    report = _report(ctx)
    before = _tree(ws)
    out = cp.write_report(ws, report, ctx, schema_validator=OUT_SCHEMA)
    after = _tree(ws)
    rel = f"context/generated/{ALPHA}/creative-performance/winner-a"
    assert set(after) - set(before) == {f"{rel}/creative-performance.json", f"{rel}/creative-performance.md"}
    assert {k: v for k, v in after.items() if k in before} == before  # canonical memory, assets, other clients untouched
    written = json.loads(out["json"].read_text(encoding="utf-8"))
    md = out["markdown"].read_text(encoding="utf-8")
    assert written == report and cp.markdown_matches(written, md) and f"report_sha256={out['report_sha256']}" in md
    for text in (report["winner_status"]["statement"], report["replication_hypotheses"][0]["statement"], "DERIVED_METRIC", "OPERATOR_DECLARED"):
        assert text in md
    changed = copy.deepcopy(written)
    changed["replication_hypotheses"][0]["test_suggestion"] = "outra"
    assert not cp.markdown_matches(changed, md)
    with pytest.raises(cp.CreativePerformanceError, match="refusing to overwrite"):
        cp.write_report(ws, report, ctx, schema_validator=OUT_SCHEMA)
    assert cp.write_report(ws, report, ctx, out_subdir="dry-run")["json"].parent.name == "dry-run"
    for bad in ("../escape", "a/b", ".."):
        with pytest.raises(cp.CreativePerformanceError):
            cp.write_report(ws, report, ctx, out_subdir=bad)
    beta_ctx = _ctx(ws, _brief(client_id=BETA, assets=[{"path": "private/clients/synth-beta/creatives/beta.png", "kind": "image"}]))
    with pytest.raises(cp.CreativePerformanceError, match="CLIENT_ISOLATION"):
        cp.write_report(ws, report, beta_ctx)
    assert not (ws / "context" / "generated" / BETA).exists()


def test_engine_has_no_external_io():
    for src in (Path(cp.__file__), cp.REPO_ROOT / "scripts" / "creative_performance.py"):
        text = src.read_text(encoding="utf-8")
        for token in ("googleapiclient", "requests", "urllib", "socket", "http.client", "google_sheets", "ekyte", "promote_client_memory", "shell=True", "os.system"):
            assert token not in text, (src.name, token)
    # the only subprocess use is the optional local ffprobe, with list arguments
    lib = Path(cp.__file__).read_text(encoding="utf-8")
    calls = [ln.strip() for ln in lib.splitlines() if "subprocess.run(" in ln]
    assert len(calls) == 2 and all(c.split("subprocess.run(", 1)[1].startswith(("cmd,", "[exe,")) for c in calls)
    assert "subprocess" not in (cp.REPO_ROOT / "scripts" / "creative_performance.py").read_text(encoding="utf-8")


def test_image_header_parsing():
    assert cp.image_dimensions(_png(1080, 1920)) == (1080, 1920)
    assert cp.image_dimensions(b"GIF89a" + struct.pack("<HH", 300, 250)) == (300, 250)
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00" + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 628, 1200) + b"\x00" * 12
    assert cp.image_dimensions(jpeg) == (1200, 628)
    assert cp.image_dimensions(b"not an image") is None


def test_registry_and_contract(repo_root):
    reg = json.loads((repo_root / "skills" / "registry.json").read_text(encoding="utf-8"))
    entry = next(s for s in reg["skills"] if s["id"] == cp.SKILL)
    assert entry["category"] == "INTELLIGENCE" and entry["implemented"] and entry["canonical_side_effects"] == "NONE"
    assert (repo_root / entry["skill_path"]).is_file() and (repo_root / entry["output_schema_path"]).is_file()
    assert not IN_SCHEMA.is_valid(_brief(assets=[]))  # a creative is the one mandatory input


def test_cli_context_validate_write(ws, tmp_path):
    from scripts import creative_performance as cli
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps(_brief()), encoding="utf-8")
    out = tmp_path / "ctx.json"
    assert cli.main(["context", "--brief", str(brief), "--workspace", str(ws), "--out", str(out)]) == 0
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report(json.loads(out.read_text(encoding="utf-8")))), encoding="utf-8")
    assert cli.main(["validate", "--brief", str(brief), "--workspace", str(ws), "--report", str(report)]) == 0
    assert cli.main(["write", "--brief", str(brief), "--workspace", str(ws), "--report", str(report), "--out-subdir", "cli"]) == 0
    assert (ws / "context" / "generated" / ALPHA / "creative-performance" / "cli" / "creative-performance.md").is_file()
