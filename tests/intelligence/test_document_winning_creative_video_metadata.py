"""document-winning-creative — technical video metadata via ffprobe (optional
capability) with per-field provenance and operator-vs-ffprobe precedence.
ffprobe is always mocked: the real binary is never required."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts.lib import creative_performance as cp
from tests.intelligence.test_document_winning_creative import IN_SCHEMA, WINNER, _brief, _issues, _report, _write, ws  # noqa: F401

VIDEO = "private/clients/synth-alpha/creatives/winner.mp4"
MEASURED = {"width": 720, "height": 1280, "video_codec": "hevc", "frame_rate": 25.0, "duration_seconds": 21.333,
            "audio_codec": "opus", "audio_channels": 1, "audio_sample_rate": 48000}


def _probe(values=None, status="OK"):
    calls = []

    def probe(path):
        calls.append(Path(path))
        ok = status == "OK"
        return {"status": status, "tool_version": "ffprobe version 9.9-synthetic" if ok else None, "values": dict(values if values is not None else MEASURED) if ok else {}}
    probe.calls = calls
    return probe


def _vctx(ws, probe, **asset_over):
    _write(ws / VIDEO, b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64)
    asset = {"path": VIDEO, "kind": "video", **asset_over}
    return cp.load_context(ws, _brief(assets=[asset]), input_validator=IN_SCHEMA, probe=probe)


def _fields(ctx):
    return ctx["assets"][0]["technical_metadata"]["fields"]


# 1 --------------------------------------------------------------------------------------------------


def test_video_with_ffprobe_available(ws):
    probe = _probe()
    ctx = _vctx(ws, probe)
    a = ctx["assets"][0]
    tm = a["technical_metadata"]
    assert tm["probe"]["status"] == "OK" and tm["probe"]["probed_sha256"] == a["sha256"] and tm["probe"]["values"] == MEASURED
    assert probe.calls == [(ws / VIDEO)]  # only the brief's video, never other files
    assert (a["width"], a["height"], a["dimensions_basis"], a["orientation"], a["aspect_ratio"]) == (720, 1280, "ffprobe", "portrait", "9:16")
    assert (a["duration_seconds"], a["duration_basis"]) == (21.333, "ffprobe")
    assert _fields(ctx)["orientation"] == {"value": "portrait", "source": "DERIVED", "derived_from": ["width", "height", "rotation"]}
    report = _report(ctx)
    assert _issues(report, ctx) == []
    md = cp.render_markdown(report)
    assert "### Metadados técnicos — A-01 (ffprobe: OK, ffprobe version 9.9-synthetic)" in md and "| video_codec | hevc | FFPROBE |" in md


# 3, 4, 5, 6 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [("duration_seconds", 21.333), ("width", 720), ("height", 1280), ("frame_rate", 25.0),
                                         ("video_codec", "hevc"), ("audio_codec", "opus"), ("audio_channels", 1), ("audio_sample_rate", 48000)])
def test_each_field_is_filled_by_ffprobe_with_provenance(ws, field, value):
    f = _fields(_vctx(ws, _probe()))[field]
    assert f == {"value": value, "source": "FFPROBE", "operator_value": None, "ffprobe_value": value, "status": "SINGLE_SOURCE"}


def test_partial_ffprobe_answer_never_invents_fields(ws):
    ctx = _vctx(ws, _probe({"width": 640, "height": 640, "video_codec": "vp9"}))  # silent video, no duration reported
    f = _fields(ctx)
    assert f["audio_codec"]["source"] == "NOT_AVAILABLE" and f["audio_codec"]["value"] is None
    assert f["duration_seconds"]["source"] == "NOT_AVAILABLE" and ctx["assets"][0]["duration_basis"] == "not_available"
    assert ctx["assets"][0]["orientation"] == "square"


# 2 --------------------------------------------------------------------------------------------------


def test_ffprobe_unavailable_does_not_block(ws):
    ctx = _vctx(ws, _probe(status="FFPROBE_UNAVAILABLE"))
    a = ctx["assets"][0]
    assert a["technical_metadata"]["probe"] == {"tool": "ffprobe", "status": "FFPROBE_UNAVAILABLE", "tool_version": None, "probed_sha256": None, "values": {}}
    assert all(f["source"] == "NOT_AVAILABLE" for k, f in _fields(ctx).items())
    assert (a["width"], a["duration_seconds"], a["dimensions_basis"], a["duration_basis"]) == (None, None, "not_available", "not_available")
    assert any(w.startswith("FFPROBE_UNAVAILABLE: A-01") for w in ctx["warnings"])
    assert _issues(_report(ctx), ctx) == []


def test_real_probe_function_is_safe_and_optional(ws, monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    assert cp.ffprobe_probe(ws / WINNER) == {"status": "FFPROBE_UNAVAILABLE", "tool_version": None, "values": {}}
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/opt/synthetic/ffprobe")
    seen = []
    answer = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001",
                           "r_frame_rate": "30000/1001", "duration": "12.345678", "side_data_list": [{"rotation": -90}]},
                          {"codec_type": "audio", "codec_name": "aac", "channels": 1, "sample_rate": "48000"}],
              "format": {"duration": "12.4"}}

    def fake_run(args, **kwargs):
        seen.append((args, kwargs))
        out = json.dumps(answer) if args[1] != "-version" else "ffprobe version 1.2.3 synthetic\nmore"
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    result = cp.ffprobe_probe(ws / WINNER)
    assert result["status"] == "OK" and result["tool_version"] == "ffprobe version 1.2.3"
    assert result["values"] == {"width": 1920, "height": 1080, "video_codec": "h264", "frame_rate": 29.97, "rotation": -90,
                                "duration_seconds": 12.346, "audio_codec": "aac", "audio_channels": 1, "audio_sample_rate": 48000}
    for args, kwargs in seen:
        assert isinstance(args, list) and args[0] == "/opt/synthetic/ffprobe" and "shell" not in kwargs and kwargs["timeout"] == cp.FFPROBE_TIMEOUT_S
    assert seen[0][0][-1] == str((ws / WINNER).resolve())
    meta, _ = cp.build_technical_metadata({"asset_id": "A-01", "sha256": "x", "width": None, "height": None, "orientation": None, "aspect_ratio": None,
                                           "dimensions_basis": "not_available", "duration_seconds": None, "duration_basis": "not_available"}, {}, result)
    assert meta["orientation"] == "portrait"  # coded 1920×1080 rotated 90° displays as portrait
    monkeypatch.setattr(cp.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr="boom"))
    assert cp.ffprobe_probe(ws / WINNER)["status"] == "FFPROBE_FAILED"

    def timeout(args, **kw):
        raise subprocess.TimeoutExpired(args, kw["timeout"])
    monkeypatch.setattr(cp.subprocess, "run", timeout)
    assert cp.ffprobe_probe(ws / WINNER)["status"] == "FFPROBE_FAILED"


# 7 --------------------------------------------------------------------------------------------------


def test_operator_value_equal_within_tolerance_is_confirmed(ws):
    ctx = _vctx(ws, _probe(), duration_seconds=21, frame_rate=25.04, video_codec="HEVC", audio_channels=1)
    f = _fields(ctx)
    assert f["duration_seconds"] == {"value": 21, "source": "OPERATOR_PROVIDED", "operator_value": 21, "ffprobe_value": 21.333, "status": "CONFIRMED"}
    assert f["frame_rate"]["status"] == f["video_codec"]["status"] == f["audio_channels"]["status"] == "CONFIRMED"
    assert (ctx["assets"][0]["duration_seconds"], ctx["assets"][0]["duration_basis"]) == (21, "operator_provided")  # never overwritten
    assert not any(w.startswith("METADATA_INCONSISTENT") for w in ctx["warnings"])
    assert _issues(_report(ctx), ctx) == []


# 8 --------------------------------------------------------------------------------------------------


def test_material_divergence_is_metadata_inconsistent(ws):
    ctx = _vctx(ws, _probe(), duration_seconds=60, audio_channels=2, width=1080, height=1920)
    f = _fields(ctx)
    assert f["duration_seconds"] == {"value": 60, "source": "OPERATOR_PROVIDED", "operator_value": 60, "ffprobe_value": 21.333, "status": "METADATA_INCONSISTENT"}
    assert f["audio_channels"]["status"] == f["width"]["status"] == "METADATA_INCONSISTENT"
    a = ctx["assets"][0]
    assert (a["width"], a["dimensions_basis"], a["duration_seconds"]) == (1080, "operator_provided", 60)  # both kept, operator not overwritten
    inconsistent = [w for w in ctx["warnings"] if w.startswith("METADATA_INCONSISTENT")]
    assert len(inconsistent) == 4  # duration, width, height, audio_channels
    report = _report(ctx)
    assert _issues(report, ctx) == []
    report["warnings"] = [w for w in report["warnings"] if not w.startswith("METADATA_INCONSISTENT")]
    assert any(i.startswith("WARNING_DROPPED") for i in _issues(report, ctx))


# 9 --------------------------------------------------------------------------------------------------


def test_image_never_calls_ffprobe(ws):
    def never(path):
        raise AssertionError("ffprobe must not run for images")
    ctx = cp.load_context(ws, _brief(), input_validator=IN_SCHEMA, probe=never)
    a = ctx["assets"][0]
    assert a["dimensions_basis"] == "file_header" and "technical_metadata" not in a and ctx["asset_probe_inputs"] == []
    assert _issues(_report(ctx), ctx) == []


# 10 -------------------------------------------------------------------------------------------------


def test_old_and_cross_replica_reports_stay_valid(ws):
    ctx_ok = _vctx(ws, _probe())
    legacy = _report(ctx_ok)
    legacy["asset_metadata"] = [copy.deepcopy(ctx_ok["asset_probe_inputs"][0]["base"])]  # pre-1.2.0 video report: no technical metadata
    assert _issues(legacy, ctx_ok) == []
    made_with_ffprobe = _report(ctx_ok)
    ctx_without = _vctx(ws, _probe(status="FFPROBE_UNAVAILABLE"))
    assert _issues(made_with_ffprobe, ctx_without) == []  # a replica without ffprobe re-derives from the recorded answer
    made_without = _report(ctx_without)
    assert _issues(made_without, ctx_ok) == []  # a report made where ffprobe was absent stays valid where it exists


def test_tampered_technical_metadata_is_rejected(ws):
    ctx_ok = _vctx(ws, _probe())
    ctx_without = _vctx(ws, _probe(status="FFPROBE_UNAVAILABLE"))
    report = _report(ctx_ok)
    report["asset_metadata"][0]["technical_metadata"]["fields"]["duration_seconds"]["value"] = 30.0  # field no longer matches the recorded answer
    for ctx in (ctx_ok, ctx_without):
        assert any(i.startswith("ASSET_METADATA_ALTERED") for i in _issues(report, ctx))
    rebound = _report(ctx_ok)
    rebound["asset_metadata"][0]["technical_metadata"]["probe"]["probed_sha256"] = "0" * 64  # answer not bound to this file
    assert any(i.startswith("ASSET_METADATA_ALTERED") for i in _issues(rebound, ctx_without))
    other = _vctx(ws, _probe({**MEASURED, "duration_seconds": 12.0}))
    assert any(i.startswith("ASSET_METADATA_ALTERED") for i in _issues(_report(other), ctx_ok))  # fresh measurement disagrees
