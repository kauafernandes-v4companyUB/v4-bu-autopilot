"""Regression: every file bootstrap_client.py writes must validate against
its canonical schema (tasks.json used to ship updated_at: null, which
schemas/task-ledger.schema.json rejects)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.bootstrap_client import LEGACY_RENDERS, bootstrap, render
from scripts.lib.workspace import Workspace

CLIENT_ID = "synthtest-bootstrap"
SCHEMAS = {
    "tasks.json": "task-ledger.schema.json",
    "evidence.json": "client-evidence.schema.json",
    "knowledge.json": "client-knowledge.schema.json",
}


def _client_dir(ws_root):
    return Workspace(root=ws_root).client_dir(CLIENT_ID)


def test_bootstrapped_files_validate_against_canonical_schemas(temp_workspace, validate, repo_root):
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=False) == 0
    client_dir = _client_dir(temp_workspace)
    for name, schema in SCHEMAS.items():
        data = json.loads((client_dir / name).read_text(encoding="utf-8"))
        assert not validate(data, repo_root / "schemas" / schema), name


def test_tasks_updated_at_is_real_execution_clock(temp_workspace):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=False) == 0
    tasks = json.loads((_client_dir(temp_workspace) / "tasks.json").read_text(encoding="utf-8"))
    ts = datetime.strptime(tasks["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= ts <= datetime.now(timezone.utc) + timedelta(seconds=1)
    assert tasks["client_id"] == CLIENT_ID and tasks["tasks"] == []


def test_force_rerun_treats_timestamped_render_as_untouched(temp_workspace, capsys):
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=False) == 0
    original = (_client_dir(temp_workspace) / "tasks.json").read_text(encoding="utf-8")
    capsys.readouterr()
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=True) == 0
    out = capsys.readouterr().out
    assert "PROTECTED" not in out
    assert (_client_dir(temp_workspace) / "tasks.json").read_text(encoding="utf-8") == original


def test_force_upgrades_untouched_legacy_null_ledger_only(temp_workspace, validate, repo_root):
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=False) == 0
    tasks_path = _client_dir(temp_workspace) / "tasks.json"
    tasks_path.write_text(render(LEGACY_RENDERS["tasks.json"][0], CLIENT_ID, CLIENT_ID), encoding="utf-8")
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=True) == 0
    upgraded = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert isinstance(upgraded["updated_at"], str)
    assert not validate(upgraded, repo_root / "schemas" / "task-ledger.schema.json")


def test_force_never_touches_customized_ledger(temp_workspace, capsys):
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=False) == 0
    tasks_path = _client_dir(temp_workspace) / "tasks.json"
    custom = '{"schema_version": "1.0.0", "client_id": "synthtest-bootstrap", "updated_at": null, "tasks": [], "x": 1}\n'
    tasks_path.write_text(custom, encoding="utf-8")
    assert bootstrap(CLIENT_ID, str(temp_workspace), None, force=True) == 0
    assert tasks_path.read_text(encoding="utf-8") == custom
    assert "! tasks.json" in capsys.readouterr().out
