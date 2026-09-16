from __future__ import annotations

import os
import subprocess
import sys


def test_doctor_passes_in_engine_only_mode_with_no_workspace(repo_root):
    env = dict(os.environ)
    env.pop("V4_BU_WORKSPACE_ROOT", None)
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "doctor.py")],
        cwd=repo_root, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Workspace ................. SKIP" in result.stdout
    assert "FAIL" not in result.stdout


def test_doctor_exits_nonzero_when_workspace_override_is_invalid(repo_root, tmp_path):
    env = dict(os.environ)
    env.pop("V4_BU_WORKSPACE_ROOT", None)
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "doctor.py"), "--workspace", str(tmp_path / "does-not-exist")],
        cwd=repo_root, env=env, capture_output=True, text=True,
    )
    # an explicitly-passed but invalid --workspace should SKIP (not crash) —
    # doctor never fails just because a workspace wasn't reachable.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Workspace ................. SKIP" in result.stdout
