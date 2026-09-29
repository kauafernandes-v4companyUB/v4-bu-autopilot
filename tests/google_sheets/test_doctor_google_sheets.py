from __future__ import annotations

import json
import os
import subprocess
import sys


def _entry(source_id: str, spreadsheet_id: str, **gs) -> dict:
    return {
        "source_id": source_id, "type": "google_sheet", "scope": "client", "location": None,
        "contains_multiple_clients": False,
        "google_sheet": {"spreadsheet_id": spreadsheet_id, "writable": True, **gs},
    }


def _client(workspace, client_id: str, sources: list[dict]) -> None:
    d = workspace / "clients" / client_id
    d.mkdir(parents=True)
    (d / "sources.json").write_text(json.dumps({"schema_version": "1.0.0", "client_id": client_id, "sources": sources}), encoding="utf-8")


def _doctor(repo_root, workspace):
    env = dict(os.environ)
    env.pop("V4_BU_WORKSPACE_ROOT", None)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "doctor.py"), "--workspace", str(workspace)],
        cwd=repo_root, env=env, capture_output=True, text=True,
    ).stdout


def test_doctor_accepts_valid_google_sheet_sources(repo_root, temp_workspace):
    _client(temp_workspace, "synthtest-a", [_entry("synthtest-a-sheet", "fake-synthtest-a-000001")])
    out = _doctor(repo_root, temp_workspace)
    assert "Client isolation .......... PASS" in out
    assert "Source references ......... PASS" in out


def test_doctor_flags_same_spreadsheet_declared_by_two_clients(repo_root, temp_workspace):
    _client(temp_workspace, "synthtest-a", [_entry("synthtest-a-sheet", "fake-shared-sheet-000001")])
    _client(temp_workspace, "synthtest-b", [_entry("synthtest-b-sheet", "fake-shared-sheet-000001")])
    out = _doctor(repo_root, temp_workspace)
    assert "Client isolation .......... FAIL" in out
    assert "also declared by client 'synthtest-a'" in out


def test_doctor_flags_invalid_google_sheet_entry(repo_root, temp_workspace):
    bad = _entry("synthtest-a-sheet", "short")
    _client(temp_workspace, "synthtest-a", [bad])
    out = _doctor(repo_root, temp_workspace)
    assert "Source references ......... FAIL" in out
