"""Deterministic support for skills/plan-seasonal-calendar/SKILL.md.

This module never decides *what* a client should do in a season — that
reasoning is Claude/Codex following the SKILL.md. It only:

- resolves the requested period into a real calendar (weeks Monday–Sunday,
  months, year crossing) and the generic calendar occurrences inside it
  (skills/plan-seasonal-calendar/calendar-catalog.json — rules only, no
  relevance);
- lazily loads ONE client's context from the private workspace (canonical
  memory files + a fixed list of generated-artifact kinds), recording which
  sources exist, which were used and which are empty/missing;
- validates a plan against the output schema plus the no-invention
  invariants a JSON Schema can't express (evidence-backed classes, preserved
  operational decisions, no invented segments/offers/money, calendar
  consistency, client isolation);
- renders the Markdown view FROM the JSON (never the other way around) and
  writes both, only under <workspace>/context/generated/<client_id>/.

It performs no network I/O and never writes canonical memory, Sheets,
Playbook, tasks or metrics.
"""

from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem

SKILL = "plan-seasonal-calendar"
SCHEMA_VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / SKILL
CATALOG_PATH = SKILL_DIR / "calendar-catalog.json"
OUTPUT_SCHEMA_PATH = SKILL_DIR / "output.schema.json"

CLASSES = ("FACT", "METRIC", "CONFIRMED_OPERATIONAL_DECISION", "PLANNING_RECOMMENDATION", "CLIENT_CONFIRMATION_REQUIRED", "UNKNOWN")
EVIDENCED = {"FACT", "METRIC", "CONFIRMED_OPERATIONAL_DECISION"}
RELEVANCE = ("HIGH_RELEVANCE", "MEDIUM_RELEVANCE", "LOW_RELEVANCE", "NOT_RECOMMENDED")
FUNNEL_ROLES = ("AWARENESS", "CONSIDERATION", "DEMAND_CAPTURE", "CONVERSION", "REMARKETING", "RETENTION_REACTIVATION", "ENABLER")
PRIORITIES = ("P0", "P1", "P2", "P3")
REVENUE_METRICS = {"revenue", "faturamento", "receita"}
MIN_DAYS, MAX_DAYS = 7, 400

CANONICAL_FILES = ("client.json", "current-state.json", "strategy.md", "knowledge.json",
                   "decisions.json", "evidence.json", "tasks.json", "sources.json")
# Generated-artifact kinds the planner may use (glob relative to context/generated/<client_id>/).
# Anything else under the client's generated dir — and everything under private/ — is never read.
ARTIFACT_KINDS = (
    ("replanning/*.json", "replanning"),
    ("bi-imports/*/bi-import-*.json", "bi_import"),
    ("bi-imports/*/read-bi/*.json", "read_bi_output"),
    ("*contract*.json", "sheet_contract"),
    ("seasonal-planning/*/seasonal-plan*.json", "previous_seasonal_plan"),
    ("account-plan/*.json", "account_plan"),
    ("creative-learnings/*.json", "creative_learnings"),
    ("product-context/*.json", "product_context"),
    ("campaigns/*.json", "campaign_history"),
)
# Unknowns every plan must treat as CLIENT_CONFIRMATION_REQUIRED unless a source proves them.
GUARDED_TOPICS = ("product", "stock", "price", "discount", "offer", "budget", "team", "capacity", "channel", "calendar")
_MONEY = re.compile(r"R\$\s*\d|\b\d+(?:[.,]\d+)?\s*%\s*(?:off|de desconto|desconto)\b|\b\d+(?:[.,]\d+)?\s*reais\b", re.IGNORECASE)


class SeasonalPlanningError(ValueError):
    pass


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _rule_dates(rule: dict, year: int) -> tuple[date, date]:
    t = rule["type"]
    if t == "fixed":
        d = date(year, rule["month"], rule["day"])
        return d, d
    if t == "fixed_range":
        return date(year, rule["from_month"], rule["from_day"]), date(year, rule["to_month"], rule["to_day"])
    if t == "nth_weekday":
        d = _nth_weekday(year, rule["month"], rule["weekday"], rule["n"])
        return d, d
    if t == "day_after_nth_weekday":
        d = _nth_weekday(year, rule["month"], rule["weekday"], rule["n"]) + timedelta(days=rule.get("offset_days", 1))
        return d, d
    if t == "easter_offset":
        d = easter(year) + timedelta(days=rule["days"])
        return d, d
    if t == "easter_offset_range":
        e = easter(year)
        return e + timedelta(days=rule["from_days"]), e + timedelta(days=rule["to_days"])
    raise SeasonalPlanningError(f"unknown calendar rule type {t!r}")


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def _period_id(start: date, end: date) -> str:
    last = lambda y, m: monthrange(y, m)[1]  # noqa: E731
    if start.day == 1 and start.year == end.year:
        if end == date(end.year, end.month, last(end.year, end.month)):
            if start.month == end.month:
                return f"{start.year}-{start.month:02d}"
            if (start.month - 1) % 3 == 0 and end.month == start.month + 2:
                return f"{start.year}-q{(start.month - 1) // 3 + 1}"
            if start.month in (1, 7) and end.month == start.month + 5:
                return f"{start.year}-h{1 if start.month == 1 else 2}"
            if start.month == 1 and end.month == 12:
                return f"{start.year}"
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def resolve_period(start: date, end: date, *, catalog: Optional[list[dict]] = None, country: str = "BR") -> dict:
    """Real calendar of the requested horizon. Weeks are Monday–Sunday; the
    first/last week may extend outside the horizon (``in_horizon`` marks the
    clipped part)."""
    if end < start:
        raise SeasonalPlanningError("end_date is before start_date")
    days = (end - start).days + 1
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise SeasonalPlanningError(f"horizon must span {MIN_DAYS}–{MAX_DAYS} days (got {days})")
    weeks = []
    w = start - timedelta(days=start.weekday())
    while w <= end:
        we = w + timedelta(days=6)
        weeks.append({"week": len(weeks) + 1, "start": w.isoformat(), "end": we.isoformat(),
                      "in_horizon": {"start": max(w, start).isoformat(), "end": min(we, end).isoformat()}})
        w += timedelta(days=7)
    months, m = [], date(start.year, start.month, 1)
    while m <= end:
        me = date(m.year, m.month, monthrange(m.year, m.month)[1])
        months.append({"month": f"{m.year}-{m.month:02d}", "start": max(m, start).isoformat(), "end": min(me, end).isoformat()})
        m = me + timedelta(days=1)
    occ = []
    for entry in (catalog if catalog is not None else load_catalog()):
        if entry.get("country") != country:
            continue
        for year in range(start.year, end.year + 1):
            s, e = _rule_dates(entry["rule"], year)
            if e >= start and s <= end:
                occ.append({"occurrence_id": f"{entry['id']}@{year}", "catalog_id": entry["id"], "name": entry["name"], "kind": entry["kind"],
                            "start": s.isoformat(), "end": e.isoformat(), "weekday": s.strftime("%A")})
    occ.sort(key=lambda o: (o["start"], o["catalog_id"]))
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "period_id": _period_id(start, end), "days": days,
            "crosses_year": start.year != end.year, "weeks": weeks, "months": months, "calendar_occurrences": occ,
            "country": country}


# ---------------------------------------------------------------------------
# lazy context loading (one client only)
# ---------------------------------------------------------------------------


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _is_empty_canonical(name: str, text: str) -> bool:
    if name.endswith(".md"):
        body = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#") and not ln.startswith(">")]
        return all(ln.lower().startswith("unknown") for ln in body)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    payload = {k: v for k, v in data.items() if k not in ("schema_version", "client_id", "updated_at", "display_name", "memory", "pilot_client")}
    return all(v in (None, "", "unknown", [], {}) for v in payload.values())


def _walk_decisions(obj: Any, path: str, out: list[dict]) -> None:
    """Every dict with type == DECISION (operator-confirmed) anywhere in an artifact."""
    if isinstance(obj, dict):
        if obj.get("type") == "DECISION" and (obj.get("statement") or obj.get("decision")):
            out.append(obj)
        for k, v in obj.items():
            _walk_decisions(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_decisions(v, f"{path}[{i}]", out)


def load_client_context(workspace_root: Path, client_id: str, start: date, end: date, *,
                        operator_instructions: Optional[list[str]] = None, catalog: Optional[list[dict]] = None) -> dict:
    """Seasonal Context: sources discovered for THIS client only, plus the
    evidenced material a planner may cite (decisions, scheduled actions,
    metrics) and the calendar. Missing sources never block."""
    if not client_id or "/" in client_id or "\\" in client_id or ".." in client_id:
        raise SeasonalPlanningError(f"unsafe client_id {client_id!r}")
    root = Path(workspace_root)
    client_dir = root / "clients" / client_id
    gen_dir = root / "context" / "generated" / client_id
    if not client_dir.is_dir():
        raise SeasonalPlanningError(f"client {client_id!r} has no canonical memory directory in this workspace")
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    sources, decisions, actions, metrics, texts = [], [], [], [], {}

    def add_source(path: Path, kind: str, status: str, note: str = "") -> str:
        sid = f"S-{len(sources) + 1:02d}"
        sources.append({"source_id": sid, "path": rel(path), "kind": kind, "status": status,
                        "sha256": _sha256_file(path) if path.is_file() else None, "note": note})
        return sid

    for name in CANONICAL_FILES:
        p = client_dir / name
        if not p.is_file():
            sources.append({"source_id": f"S-{len(sources) + 1:02d}", "path": f"clients/{client_id}/{name}", "kind": "canonical_memory",
                            "status": "missing", "sha256": None, "note": ""})
            continue
        text = p.read_text(encoding="utf-8")
        empty = _is_empty_canonical(name, text)
        sid = add_source(p, "canonical_memory", "empty" if empty else "loaded")
        if empty:
            continue
        if name == "decisions.json":
            for d in json.loads(text).get("decisions", []):
                decisions.append({"decision_id": d.get("decision_id") or d.get("id"), "statement": d.get("statement") or d.get("decision"),
                                  "source_id": sid, "origin": "canonical_memory"})
        elif name == "strategy.md":
            texts[sid] = text
        elif name in ("knowledge.json", "current-state.json", "client.json"):
            texts[sid] = json.loads(text)

    if gen_dir.is_dir():
        seen = set()
        for pattern, kind in ARTIFACT_KINDS:
            for p in sorted(gen_dir.glob(pattern)):
                if p in seen or not p.is_file():
                    continue
                seen.add(p)
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    add_source(p, kind, "unreadable")
                    continue
                if data.get("client_id") not in (None, client_id):
                    add_source(p, kind, "rejected_other_client")  # isolation: never used
                    continue
                sid = add_source(p, kind, "loaded")
                found: list[dict] = []
                _walk_decisions(data, "$", found)
                for d in found:
                    decisions.append({"decision_id": d.get("decision_id") or d.get("rule_id") or d.get("id"),
                                      "statement": d.get("statement") or d.get("decision"), "source_id": sid, "origin": kind})
                for a in data.get("actions", []) if kind == "replanning" else []:
                    actions.append({"action_id": a.get("action_id"), "action": a.get("action"), "due_date": a.get("due_date"),
                                    "due_date_basis": a.get("due_date_basis"), "responsible": a.get("responsible"),
                                    "artifact_status": data.get("status"), "source_id": sid})
                if kind == "read_bi_output":
                    rp = data.get("report_period", {})
                    metrics.append({"source_id": sid, "period": f"{rp.get('start_date')}..{rp.get('end_date')}",
                                    "observations": [{"label": o["label"], "canonical_metric": o.get("canonical_metric"), "value": o.get("value"),
                                                      "unit": o.get("unit"), "channel": o.get("channel")} for o in data.get("metric_observations", [])]})

    loaded_kinds = {s["kind"] for s in sources if s["status"] == "loaded"}
    unknowns = [t for t in GUARDED_TOPICS if t not in {"channel"} or not metrics]
    if "product_context" in loaded_kinds:
        unknowns = [t for t in unknowns if t not in ("product",)]
    period = resolve_period(start, end, catalog=catalog)
    context = {
        "schema_version": SCHEMA_VERSION, "artifact": "seasonal-context", "client_id": client_id, "period": period,
        "operator_instructions": list(operator_instructions or []),
        "sources": sources, "confirmed_decisions": decisions, "scheduled_actions": actions, "metrics": metrics,
        "context_texts": texts,
        "observed_channels": sorted({o["channel"] for m in metrics for o in m["observations"] if o.get("channel")}),
        "unknown_topics": unknowns,
        "not_read": ["private/ (raw sources)", "other clients", "context/generated/<client>/google-sheets/*", "any artifact kind not listed in ARTIFACT_KINDS"],
    }
    context["context_sha256"] = content_sha256(context)
    return context


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def _iter_classified(plan: dict):
    """(json_path, item) for every classified element of the plan."""
    singles = {"strategic_summary": plan.get("strategic_summary")}
    for k, v in singles.items():
        if isinstance(v, dict) and "classification" in v:
            yield k, v
    for section in ("facts", "confirmed_decisions", "segments", "period_architecture", "seasonal_opportunities", "campaigns", "timeline",
                    "dependencies", "client_decisions_required", "risks", "anti_priorities", "suggested_metrics"):
        for i, item in enumerate(plan.get(section) or []):
            if isinstance(item, dict) and "classification" in item:
                yield f"{section}[{i}]", item
    for i, c in enumerate(plan.get("campaigns") or []):
        for sub in ("audience", "offer"):
            if isinstance(c.get(sub), dict):
                yield f"campaigns[{i}].{sub}", c[sub]
        for j, ch in enumerate(c.get("channels") or []):
            yield f"campaigns[{i}].channels[{j}]", ch


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def validate_plan(plan: dict, context: dict, *, schema_validator=None) -> list[str]:
    """Schema (when a validator is given) + no-invention invariants. Empty list = valid."""
    issues: list[str] = []
    if schema_validator is not None:
        issues += [f"schema {list(e.path)}: {e.message}" for e in sorted(schema_validator.iter_errors(plan), key=lambda e: list(e.path))]
        if issues:
            return issues
    cid = context["client_id"]
    if plan.get("client_id") != cid:
        return [f"CLIENT_ISOLATION: plan client_id {plan.get('client_id')!r} != context client_id {cid!r}"]
    per = context["period"]
    if (plan["period"]["start_date"], plan["period"]["end_date"]) != (per["start_date"], per["end_date"]):
        issues.append("PERIOD_MISMATCH: plan period differs from the requested horizon")
    if plan["period"].get("period_id") != per["period_id"]:
        issues.append(f"PERIOD_MISMATCH: period_id must be {per['period_id']!r}")
    problem = future_timestamp_problem(plan["generated_at"])
    if problem:
        issues.append(f"EXECUTION_TIMESTAMP_IN_FUTURE: {problem}")

    # sources: only this client's discovered sources, cited ids must exist
    ctx_sources = {s["source_id"]: s for s in context["sources"]}
    used = {}
    for s in plan["sources_used"]:
        cs = ctx_sources.get(s["source_id"])
        if cs is None or cs["path"] != s["path"]:
            issues.append(f"UNKNOWN_SOURCE: {s['source_id']} {s['path']!r} is not a source discovered for this client")
            continue
        if cs["status"] not in ("loaded", "empty"):
            issues.append(f"UNUSABLE_SOURCE: {s['source_id']} has status {cs['status']!r}")
        if not (s["path"].startswith(f"clients/{cid}/") or s["path"].startswith(f"context/generated/{cid}/")):
            issues.append(f"CLIENT_ISOLATION: source path {s['path']!r} is outside this client's tree")
        used[s["source_id"]] = s
    ctx_decisions = {d["decision_id"]: d for d in context["confirmed_decisions"] if d.get("decision_id")}
    instructions = {f"OP-{i + 1:02d}" for i in range(len(plan.get("operator_instructions") or []))}
    valid_refs = set(used) | set(ctx_decisions) | instructions

    for path, item in _iter_classified(plan):
        cls = item.get("classification")
        if cls not in CLASSES:
            issues.append(f"{path}: invalid classification {cls!r}")
            continue
        refs = item.get("source_refs") or []
        bad = [r for r in refs if r not in valid_refs]
        if bad:
            issues.append(f"{path}: source_refs {bad} are not cited sources, context decisions or operator instructions")
        if cls in EVIDENCED and not [r for r in refs if r in valid_refs]:
            issues.append(f"UNSUPPORTED_{cls}: {path} is classified {cls} without evidence (a recommendation can never be a fact)")
        if cls == "CONFIRMED_OPERATIONAL_DECISION" and not any(r in ctx_decisions or r in instructions for r in refs):
            issues.append(f"UNSUPPORTED_CONFIRMED_OPERATIONAL_DECISION: {path} must cite a context decision or an operator instruction")

    # confirmed decisions: every context decision is either carried as CONFIRMED or explicitly set aside
    carried = {r for d in plan.get("confirmed_decisions", []) for r in d.get("source_refs", []) if r in ctx_decisions}
    set_aside = {x["decision_id"] for x in plan.get("context_decisions_not_applicable", [])}
    for did in ctx_decisions:
        if did not in carried and did not in set_aside:
            issues.append(f"DECISION_DROPPED: context decision {did!r} is neither carried in confirmed_decisions nor listed in context_decisions_not_applicable")
    for d in plan.get("confirmed_decisions", []):
        if d.get("classification") != "CONFIRMED_OPERATIONAL_DECISION":
            issues.append(f"DECISION_DOWNGRADED_OR_MISCLASSIFIED: confirmed_decisions item {d.get('id')!r} must stay CONFIRMED_OPERATIONAL_DECISION")

    # segments: only from context
    seg_ids = {s["segment_id"] for s in plan.get("segments", [])}
    for s in plan.get("segments", []):
        if s.get("classification") not in EVIDENCED:
            issues.append(f"INVENTED_SEGMENT: segment {s['segment_id']!r} must be evidenced by the client's context (FACT/CONFIRMED_OPERATIONAL_DECISION with sources)")

    # campaigns
    camp_ids = [c["campaign_id"] for c in plan.get("campaigns", [])]
    if len(camp_ids) != len(set(camp_ids)):
        issues.append("DUPLICATE_CAMPAIGN_ID")
    start, end = date.fromisoformat(per["start_date"]), date.fromisoformat(per["end_date"])
    for c in plan.get("campaigns", []):
        cs, ce = date.fromisoformat(c["start_date"]), date.fromisoformat(c["end_date"])
        if ce < cs or cs < start or ce > end:
            issues.append(f"{c['campaign_id']}: dates {c['start_date']}..{c['end_date']} outside the horizon or inverted")
        for seg in c.get("segment_ids", []):
            if seg not in seg_ids:
                issues.append(f"INVENTED_SEGMENT: {c['campaign_id']} uses segment {seg!r} not declared in segments")
        for key in ("previous_campaign_id", "next_campaign_id"):
            if c.get(key) and c[key] not in camp_ids:
                issues.append(f"{c['campaign_id']}: {key} {c[key]!r} does not exist")
        if c["offer"]["classification"] == "PLANNING_RECOMMENDATION":
            issues.append(f"INVENTED_OFFER: {c['campaign_id']}.offer cannot be a recommendation — it is CLIENT_CONFIRMATION_REQUIRED/UNKNOWN unless evidenced")
        for ch in c.get("channels", []):
            if ch["classification"] == "FACT" and not ch.get("source_refs"):
                issues.append(f"{c['campaign_id']}: channel {ch['channel']!r} claimed active without evidence")
        text = [c.get("objective", ""), c.get("offer", {}).get("description", ""), c.get("cta", ""), *[m.get("message", "") for m in c.get("central_messages", [])]]
        if any(_MONEY.search(t or "") for t in text):
            issues.append(f"INVENTED_MONEY: {c['campaign_id']} states a price/discount/amount — only evidenced sources may carry values")
    for i, t in enumerate(plan.get("timeline", [])):
        if t["classification"] in ("PLANNING_RECOMMENDATION", "UNKNOWN") and any(_MONEY.search(s or "") for s in (t.get("main_action", ""), t.get("material_ready", ""))):
            issues.append(f"INVENTED_MONEY: timeline[{i}] states a monetary value in a recommendation")

    # priorities: every campaign exactly once
    listed = [cid_ for p in PRIORITIES for cid_ in plan["priorities"].get(p, [])]
    for cid_ in camp_ids:
        if listed.count(cid_) != 1:
            issues.append(f"PRIORITY: campaign {cid_!r} must appear exactly once in P0..P3")
    for cid_ in listed:
        if cid_ not in camp_ids:
            issues.append(f"PRIORITY: unknown campaign {cid_!r}")
    for c in plan.get("campaigns", []):
        if c["campaign_id"] not in plan["priorities"].get(c["priority"], []):
            issues.append(f"PRIORITY: {c['campaign_id']} priority {c['priority']} disagrees with the priorities matrix")

    # timeline follows the real calendar
    gran = plan["period"]["granularity"]
    expected = [(w["start"], w["end"]) for w in per["weeks"]] if gran == "week" else [(m["start"], m["end"]) for m in per["months"]]
    got = [(t["period_start"], t["period_end"]) for t in plan.get("timeline", [])]
    if got != expected:
        issues.append(f"TIMELINE_CALENDAR: timeline must have one entry per {gran} of the horizon, in order ({len(expected)} expected, {len(got)} given)")

    # seasonal opportunities
    occ_by_id = {o["occurrence_id"]: o for o in per["calendar_occurrences"]}
    for s in plan.get("seasonal_opportunities", []):
        if s.get("occurrence_id") and s["occurrence_id"] not in occ_by_id:
            issues.append(f"SEASONALITY: {s['occurrence_id']!r} is not a calendar occurrence inside the horizon")
        elif s.get("occurrence_id"):
            o = occ_by_id[s["occurrence_id"]]
            if not (s["start_date"] <= o["start"] and o["end"] <= s["end_date"]):
                issues.append(f"SEASONALITY: {s['name']!r} window {s['start_date']}..{s['end_date']} does not contain the real date {o['start']}..{o['end']}")
        if s["relevance"] == "NOT_RECOMMENDED" and not (s.get("rationale") or "").strip():
            issues.append(f"SEASONALITY: discarded {s.get('name')!r} needs a rationale")

    # client decisions & metrics
    for d in plan.get("client_decisions_required", []):
        dl = date.fromisoformat(d["deadline"])
        if not (start - timedelta(days=31) <= dl <= end):
            issues.append(f"DEADLINE: {d['decision']!r} deadline {d['deadline']} is outside the planning window")
        if d["deadline_classification"] == "CONFIRMED_OPERATIONAL_DECISION" and not any(r in ctx_decisions or r in used or r in instructions for r in d.get("source_refs", [])):
            issues.append(f"DEADLINE: {d['decision']!r} deadline claimed as confirmed without evidence")
    for m in plan.get("suggested_metrics", []):
        if m["metric"].lower() in REVENUE_METRICS and m.get("required"):
            issues.append("REVENUE_REQUIRED: revenue/faturamento can be suggested but never required")
        if m.get("required") and not m.get("available_in_sources"):
            issues.append(f"METRIC: {m['metric']!r} cannot be required when no source provides it")
        if m.get("available_in_sources") and not m.get("source_refs"):
            issues.append(f"METRIC: {m['metric']!r} marked available without source_refs")

    counts = {k: 0 for k in CLASSES}
    for _, item in _iter_classified(plan):
        if item.get("classification") in counts:
            counts[item["classification"]] += 1
    if plan.get("semantic_summary") and plan["semantic_summary"] != counts:
        issues.append(f"SEMANTIC_SUMMARY: counts must be {counts}")
    return issues


def semantic_counts(plan: dict) -> dict:
    counts = {k: 0 for k in CLASSES}
    for _, item in _iter_classified(plan):
        if item.get("classification") in counts:
            counts[item["classification"]] += 1
    return counts


# ---------------------------------------------------------------------------
# markdown (derived from JSON) and output
# ---------------------------------------------------------------------------


def _cls(item: dict) -> str:
    refs = item.get("source_refs") or []
    return f"`{item['classification']}`" + (f" ({', '.join(refs)})" if refs else "")


def render_markdown(plan: dict) -> str:
    p = plan["period"]
    L = [f"<!-- generated from seasonal-plan.json · plan_sha256={content_sha256(plan)} · do not edit by hand -->",
         f"# Planejamento sazonal — {plan['client_id']} — {p['start_date']} a {p['end_date']} ({p['period_id']})", "",
         f"- generated_at: {plan['generated_at']} · status: {plan['status']} · canônico: não",
         "- classes: " + " · ".join(f"`{k}`={v}" for k, v in plan["semantic_summary"].items()), ""]
    if plan.get("operator_instructions"):
        L += ["## Instruções do operador", ""] + [f"- OP-{i + 1:02d}: {x}" for i, x in enumerate(plan["operator_instructions"])] + [""]
    L += ["## Fontes utilizadas", ""] + [f"- {s['source_id']} `{s['path']}` — {s['used_for']}" for s in plan["sources_used"]] + [""]
    L += ["## Síntese estratégica", "", f"{plan['strategic_summary']['statement']} — {_cls(plan['strategic_summary'])}", ""]
    for title, key, field in (("Fatos", "facts", "statement"), ("Decisões operacionais confirmadas", "confirmed_decisions", "statement")):
        L += [f"## {title}", ""] + [f"- **{x['id']}** {x[field]} — {_cls(x)}" for x in plan.get(key, [])] + [""]
    if plan.get("context_decisions_not_applicable"):
        L += ["## Decisões do contexto fora deste plano", ""] + [f"- `{x['decision_id']}` — {x['reason']}" for x in plan["context_decisions_not_applicable"]] + [""]
    if plan.get("segments"):
        L += ["## Segmentos (do contexto)", ""] + [f"- **{s['segment_id']}** {s['name']} — {s['description']} — {_cls(s)}" for s in plan["segments"]] + [""]
    L += ["## Arquitetura do período", ""] + [f"- **{a['phase']}** ({a['start_date']}→{a['end_date']}, {a['role']}): {a['description']} — {_cls(a)}" for a in plan["period_architecture"]] + [""]
    L += ["## Oportunidades sazonais", "", "| Data | Oportunidade | Relevância | Segmentos | Justificativa | Papel | Classe |", "|---|---|---|---|---|---|---|"]
    L += [f"| {s['start_date']}→{s['end_date']} | {s['name']} | {s['relevance']} | {', '.join(s.get('segment_ids', [])) or '—'} | {s['rationale']} | {s.get('role') or '—'} | {_cls(s)} |" for s in plan["seasonal_opportunities"]] + [""]
    L += ["## Campanhas", ""]
    for c in plan["campaigns"]:
        L += [f"### {c['campaign_id']} · {c['name']} — {c['priority']}", "",
              f"- **Período:** {c['start_date']} → {c['end_date']} · **Funil:** {', '.join(c['funnel_roles'])} · **Segmentos:** {', '.join(c.get('segment_ids', [])) or '—'} · {_cls(c)}",
              f"- **Objetivo:** {c['objective']}",
              f"- **Público:** {c['audience']['description']} — {_cls(c['audience'])}",
              f"- **Oportunidade comercial:** {c['commercial_opportunity']}",
              "- **Mensagens centrais:** " + " · ".join(f"{m.get('segment_id') or 'geral'}: “{m['message']}”" for m in c["central_messages"]),
              f"- **Oferta:** {c['offer']['description']} — {_cls(c['offer'])}",
              f"- **CTA:** {c['cta']} · **Canais:** " + "; ".join(f"{ch['channel']} ({ch['classification']})" for ch in c["channels"]),
              f"- **Função da mídia:** {c['media_role']}",
              f"- **Materiais:** {', '.join(c['materials'])}",
              f"- **Dependências:** {'; '.join(c['dependencies']) or '—'}",
              f"- **Decisão do cliente:** {c['client_decision']}",
              f"- **Anterior:** {c.get('previous_campaign_id') or '—'} → **seguinte:** {c.get('next_campaign_id') or '—'}", ""]
    L += ["## Cronograma", "", "| Período | Frentes | Objetivo | Ação principal | Material | Decisão do cliente | Dependência | Próxima ação | Classe |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {t['period_start']}→{t['period_end']} | {', '.join(t['fronts'])} | {t['objective']} | {t['main_action']} | {t['material_ready']} | {t['client_decision']} | {t['dependency']} | {t['next_action']} | {_cls(t)} |" for t in plan["timeline"]] + [""]
    L += ["## Prioridades", ""] + [f"- **{k}:** {', '.join(plan['priorities'].get(k, [])) or '—'}" for k in PRIORITIES] + [""]
    L += ["## Decisões necessárias do cliente", "", "| Decisão | Tema | Até | Base do prazo | Classe |", "|---|---|---|---|---|"]
    L += [f"| {d['decision']} | {d['topic']} | {d['deadline']} | {d['deadline_classification']} | {_cls(d)} |" for d in plan["client_decisions_required"]] + [""]
    L += ["## Dependências", ""] + [f"- **{d['id']}** {d['statement']} — {_cls(d)}" for d in plan["dependencies"]] + [""]
    L += ["## Riscos", "", "| Risco | Impacto | Mitigação | Classe |", "|---|---|---|---|"]
    L += [f"| {r['risk']} | {r['impact']} | {r['mitigation']} | {_cls(r)} |" for r in plan["risks"]] + [""]
    L += ["## O que não fazer", ""] + [f"- {a['statement']} — {_cls(a)}" for a in plan["anti_priorities"]] + [""]
    L += ["## Métricas sugeridas", "", "| Campanha | Métrica | Disponível nas fontes | Obrigatória | Classe |", "|---|---|---|---|---|"]
    L += [f"| {m.get('campaign_id') or 'todas'} | {m['metric']} | {'sim' if m['available_in_sources'] else 'não'} | {'sim' if m['required'] else 'não'} | {_cls(m)} |" for m in plan["suggested_metrics"]]
    if plan.get("warnings"):
        L += ["", "## Avisos", ""] + [f"- {w}" for w in plan["warnings"]]
    return "\n".join(L) + "\n"


def markdown_matches(plan: dict, markdown: str) -> bool:
    return render_markdown(plan) == markdown


def write_plan(workspace_root: Path, plan: dict, context: dict, *, out_subdir: Optional[str] = None,
               overwrite: bool = False, schema_validator=None) -> dict:
    """Validate, then write seasonal-plan.json + seasonal-plan.md under
    <workspace>/context/generated/<client_id>/seasonal-planning/<period_id|out_subdir>/."""
    issues = validate_plan(plan, context, schema_validator=schema_validator)
    if issues:
        raise SeasonalPlanningError("plan is invalid:\n- " + "\n- ".join(issues))
    root = Path(workspace_root).resolve()
    base = (root / "context" / "generated" / plan["client_id"] / "seasonal-planning").resolve()
    sub = out_subdir or plan["period"]["period_id"]
    if not sub or "/" in sub or "\\" in sub or ".." in sub:
        raise SeasonalPlanningError(f"unsafe out_subdir {sub!r}")
    target = (base / sub).resolve()
    if base not in target.parents:
        raise SeasonalPlanningError("output must stay inside this client's seasonal-planning directory")
    json_path, md_path = target / "seasonal-plan.json", target / "seasonal-plan.md"
    if not overwrite and (json_path.exists() or md_path.exists()):
        raise SeasonalPlanningError(f"{target} already has a seasonal plan — refusing to overwrite (use another out_subdir)")
    target.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(plan), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "plan_sha256": content_sha256(plan)}
