"""End-to-end integration test of the real pipeline shape:

    read-like observation -> evidence promotion -> quarter monitoring
    (preview via evidence_overlay, then apply against canonical evidence)
    -> idempotent replay

...entirely on a synthetic client in a temp workspace. NEVER uses Walmaq
or any real client data — see CLAUDE.md/mission section 10.

This exercises the same reference logic (scripts/lib/*) that pins the
contracts described in skills/promote-client-memory/SKILL.md and
skills/monitor-quarter/SKILL.md, wired together the way the real skills
are wired together conceptually.
"""

from __future__ import annotations

import json

from scripts.bootstrap_client import bootstrap
from scripts.lib.evidence_id import compute_evidence_id
from scripts.lib.evidence_projection import project_to_canonical
from scripts.lib.evidence_resolution import resolve_evidence_id
from scripts.lib.media_monitoring import upsert_media_actual
from scripts.lib.workspace import Workspace

CLIENT_ID = "synthtest-integration"
QUARTER_ID = "2026-Q2"


def _synthetic_read_bi_observation():
    return {
        "observation_id": "biobs-synth-integration-0001",
        "canonical_metric": "spend",
        "value": 350.0,
        "channel": "meta_ads",
        "period": {"start_date": "2026-04-01", "end_date": "2026-04-10"},
        "source": {
            "type": "pdf",
            "file_sha256": "b" * 64,
            "observed_at": "2026-04-10T10:00:00Z",
        },
    }


def _universal_evidence_from_observation(obs, client_id, evidence_id):
    return {
        "evidence_id": evidence_id,
        "client_id": client_id,
        "source_type": obs["source"]["type"],
        "source_skill": "read-bi",
        "observed_at": obs["source"]["observed_at"],
        "type": "metric",
        "statement": f"[synthetic] Meta Ads spend of {obs['value']} observed for the period.",
        "confidence": "medium",
        "reference": {"label": "synthetic BI reference", "path": f"private/clients/{client_id}/bi/fake.pdf", "page": 1},
        "value": obs["value"],
        "unit": "brl",
        "period": {"from": obs["period"]["start_date"], "to": obs["period"]["end_date"]},
        "external_provenance": {
            "source_observation_id": obs["observation_id"],
            "source_file_sha256": obs["source"]["file_sha256"],
            "source_output": f"context/generated/{client_id}/bi/read-bi.json",
        },
        "tags": ["spend", "meta_ads"],
    }


def _bootstrap(temp_workspace):
    rc = bootstrap(CLIENT_ID, str(temp_workspace), "Synth Test Integration", force=False)
    assert rc == 0
    return Workspace(root=temp_workspace)


def _write_quarter_plan(ws: Workspace):
    plan_path = ws.client_file(CLIENT_ID, f"quarters/{QUARTER_ID}/plan.json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": "1.0.0",
        "client_id": CLIENT_ID,
        "quarter_id": QUARTER_ID,
        "period": {"start": "2026-04-01", "end": "2026-06-30"},
        "status": "active",
        "planned_at": "2026-04-01T00:00:00Z",
        "smart_objective": {
            "statement": "[synthetic] Generate 5 sales.",
            "metric": "sales",
            "baseline": None,
            "target": {"value": 5, "unit": "count"},
            "deadline": "2026-06-30",
        },
        "planning": {"strategic_priorities": [], "assumptions": [], "evidence_ids": []},
        "media_plan": {
            "currency": "BRL",
            "monthly": [{"month": "2026-04", "channel": "meta_ads", "planned_budget": 1000.0}],
        },
    }
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan


def test_full_synthetic_pipeline_and_idempotent_replay(temp_workspace, validate, repo_root, schema_registry):
    ws = _bootstrap(temp_workspace)
    plan = _write_quarter_plan(ws)

    obs = _synthetic_read_bi_observation()
    evidence_id = compute_evidence_id(
        client_id=CLIENT_ID,
        source_skill="read-bi",
        source_type=obs["source"]["type"],
        source_observation_id=obs["observation_id"],
        source_file_sha256=obs["source"]["file_sha256"],
    )
    universal = _universal_evidence_from_observation(obs, CLIENT_ID, evidence_id)
    errors = validate(universal, repo_root / "schemas" / "evidence.schema.json")
    assert not errors, errors

    # --- monitor-quarter PREVIEW via evidence_overlay, before promotion ---
    evidence_ledger = json.loads(ws.client_file(CLIENT_ID, "evidence.json").read_text())
    resolution = resolve_evidence_id(
        evidence_id, client_id=CLIENT_ID, canonical_evidences=evidence_ledger["evidences"], overlay_evidences=[universal]
    )
    assert resolution.resolved_from == "overlay", "before promotion, evidence must resolve via overlay, not canonical"

    # --- promote-client-memory APPLY: write to canonical evidence ledger ---
    canonical_item = project_to_canonical(universal, added_at="2026-04-10T10:05:00Z", source_id=None)
    from tests.contracts.test_evidence_drift import _canonical_item_errors

    assert not _canonical_item_errors(canonical_item, repo_root, schema_registry)

    evidence_ledger["evidences"].append(canonical_item)
    evidence_ledger["updated_at"] = "2026-04-10T10:05:00Z"
    evidence_path = ws.client_file(CLIENT_ID, "evidence.json")
    evidence_path.write_text(json.dumps(evidence_ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    assert not validate(evidence_ledger, repo_root / "schemas" / "client-evidence.schema.json")

    # --- monitor-quarter PREVIEW again, now resolves from canonical ---
    resolution_after = resolve_evidence_id(
        evidence_id, client_id=CLIENT_ID, canonical_evidences=evidence_ledger["evidences"], overlay_evidences=[universal]
    )
    assert resolution_after.resolved_from == "canonical"

    # --- monitor-quarter APPLY: upsert_media_actual against plan ---
    media, status = upsert_media_actual(
        [],
        month="2026-04",
        channel="meta_ads",
        actual_spend=obs["value"],
        evidence_ids=[evidence_id],
        observed_at=obs["source"]["observed_at"],
        planned_budget=plan["media_plan"]["monthly"][0]["planned_budget"],
    )
    assert status == "created"
    assert media[0]["attainment_percent"] == 35.0
    assert media[0]["variance_value"] == -650.0

    monitoring = {
        "schema_version": "1.0.0",
        "client_id": CLIENT_ID,
        "quarter_id": QUARTER_ID,
        "updated_at": "2026-04-10T10:10:00Z",
        "objective_progress": {
            "status": "unknown", "current_value": None,
            "target_value": plan["smart_objective"]["target"]["value"],
            "progress_percent": None, "observed_at": None, "evidence_ids": [],
        },
        "media_monitoring": media,
        "flags": [],
    }
    monitoring_path = ws.client_file(CLIENT_ID, f"quarters/{QUARTER_ID}/monitoring.json")
    monitoring_path.write_text(json.dumps(monitoring, indent=2, ensure_ascii=False), encoding="utf-8")
    assert not validate(monitoring, repo_root / "schemas" / "quarter-monitoring.schema.json")

    # --- IDEMPOTENT REPLAY: same observation, same inputs ---
    evidence_id_2 = compute_evidence_id(
        client_id=CLIENT_ID, source_skill="read-bi", source_type=obs["source"]["type"],
        source_observation_id=obs["observation_id"], source_file_sha256=obs["source"]["file_sha256"],
    )
    assert evidence_id_2 == evidence_id, "replay must produce the same evidence_id"

    ledger_before_replay = json.loads(evidence_path.read_text())
    # simulate promote-client-memory re-running: identical content already present -> skip, no duplicate
    already_present = next((e for e in ledger_before_replay["evidences"] if e["evidence_id"] == evidence_id_2), None)
    assert already_present is not None
    assert already_present == canonical_item, "re-promoting identical content must not alter the existing entry"
    assert len(ledger_before_replay["evidences"]) == 1, "no duplicate evidence entry on replay"

    media_2, status_2 = upsert_media_actual(
        media, month="2026-04", channel="meta_ads", actual_spend=obs["value"],
        evidence_ids=[evidence_id], observed_at=obs["source"]["observed_at"],
        planned_budget=plan["media_plan"]["monthly"][0]["planned_budget"],
    )
    assert status_2 == "no_change", "replaying the identical media actual must be a no-op"
    assert media_2 == media
    assert len(media_2) == 1, "no second media_actual record for the same month/channel on replay"
