from __future__ import annotations

import json

import pytest

from scripts.lib.artifact_hash import content_sha256
from scripts.lib.task_identity import compute_task_id

CLIENT_ID = "synthtest-loop"
QUARTER_ID = "2026-Q2"
ACTION_ID = "synthtest-a-001"


@pytest.fixture
def sample_task_proposals() -> dict:
    task_id = compute_task_id(CLIENT_ID, QUARTER_ID, ACTION_ID)
    proposal = {
        "proposal_id": "synthtest-tp-001",
        "action_id": ACTION_ID,
        "classification": "task_candidate",
        "readiness": "ready",
        "title": "Synthetic test task",
        "description": "A synthetic task for operating-loop tests.",
        "raised_at": "2026-04-01",
        "due_at": "2026-04-15",
        "quarter_id": QUARTER_ID,
        "origin": {"type": "replanning", "evidence_ids": ["syn-ev-1"]},
        "evidence_ids": ["syn-ev-1"],
        "manage_task_operation": {
            "operation_id": "synthtest-op-001",
            "type": "create_task",
            "task_id": task_id,
            "title": "Synthetic test task",
            "description": "A synthetic task for operating-loop tests.",
            "raised_at": "2026-04-01",
            "due_at": "2026-04-15",
            "quarter_id": QUARTER_ID,
            "origin": {"type": "replanning", "evidence_ids": ["syn-ev-1"]},
            "evidence_ids": ["syn-ev-1"],
        },
        "reason_if_blocked": None,
    }
    blocked = {
        "proposal_id": "synthtest-tp-002",
        "action_id": "synthtest-a-002",
        "classification": "decision_required",
        "readiness": "needs_decision",
        "title": "Synthetic decision item",
        "description": "Needs an operator decision.",
        "raised_at": "2026-04-01",
        "due_at": None,
        "quarter_id": QUARTER_ID,
        "origin": {"type": "replanning", "evidence_ids": []},
        "evidence_ids": [],
        "manage_task_operation": None,
        "reason_if_blocked": "needs an operator decision first",
    }
    return {
        "schema_version": "1.0.0",
        "skill": "generate-tasks",
        "mode": "preview",
        "proposal_set_id": "synthtest-tp-set-001",
        "client_id": CLIENT_ID,
        "quarter_id": QUARTER_ID,
        "generated_at": "2026-04-01T00:00:00Z",
        "status": "success",
        "replanning_ref": {"artifact_id": "x", "artifact_type": "replanning", "content_sha256": "a" * 64, "path": "p.json"},
        "audit_ref": {"artifact_id": "y", "artifact_type": "audit", "content_sha256": "b" * 64, "path": "p2.json"},
        "task_proposals": [proposal, blocked],
        "summary": {"ready": 1, "needs_scheduling": 0, "needs_decision": 1, "dependency": 0, "external": 0, "not_task": 0},
        "missing_data": [],
        "warnings": [],
    }


@pytest.fixture
def sample_canonical_task() -> dict:
    task_id = compute_task_id(CLIENT_ID, QUARTER_ID, ACTION_ID)
    return {
        "task_id": task_id,
        "client_id": CLIENT_ID,
        "quarter_id": QUARTER_ID,
        "title": "Synthetic test task",
        "description": "A synthetic task for operating-loop tests.",
        "raised_at": "2026-04-01",
        "due_at": "2026-04-15",
        "status": "pending",
        "completed_at": None,
        "ekyte_url": None,
        "external": None,
        "evidence_ids": ["syn-ev-1"],
        "origin": {"type": "replanning", "evidence_ids": ["syn-ev-1"]},
    }
