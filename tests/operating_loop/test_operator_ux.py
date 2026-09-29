from datetime import date

from scripts.lib.operator_router import route_command
from scripts.lib.operator_views import build_midweek, daily_view, meaningful_diff, post_call_preview, resolve_deferred_operations, source_intake_preview, week_close_preview, what_changed


def _task(task_id="t1", due="2026-09-17", status="pending"):
    return {"task_id": task_id, "title": task_id, "due_at": due, "status": status}


def _op(op_id="d1", status="deferred", kind="deferred", ref="t1"):
    return {"operation_id":op_id, "statement":"synthetic", "status":status, "type":kind,
            "deferred_until":{"type":"after_task", "reference_id":ref, "description":"after"} if kind=="deferred" else None,
            "approval":{"status":"approved","payload_hash":"a"*64} if kind=="external_approved" else None,
            "external":{"executed":False} if kind=="external_approved" else None}


def test_router_known_intents_are_read_only_or_preview():
    assert route_command("me prepara pra call da walmaq", "walmaq")["workflow"] == "prepare-client-call"
    post = route_command("acabei de sair da call da walmaq", "walmaq")
    assert post["intent"] == "post_call" and post["approval_required"]


def test_future_is_not_overdue_and_approved_without_transport_is_not_executable():
    view = daily_view({"tasks":[_task(due="2026-09-20")]}, {"operations":[_op("e1", "approved", "external_approved")]}, date(2026, 9, 16))
    assert not view["OVERDUE"] and view["NEXT_7_DAYS"]
    assert view["EXTERNAL_EXECUTION_READY"] == [] and view["EXTERNAL_NOT_EXECUTABLE"][0]["operation_id"] == "e1"


def test_deferred_only_reappears_after_its_trigger():
    operation = _op()
    assert resolve_deferred_operations([operation], [_task()])[0]["resolved_state"] == "deferred"
    assert resolve_deferred_operations([operation], [_task(status="completed")])[0]["resolved_state"] == "READY_FOR_DECISION"


def test_fictitious_post_call_is_quarantined_and_confirmation_is_not_new():
    assert post_call_preview("acme", "FACT: teste fictício")["status"] == "ignored_fictitious"
    result = post_call_preview("acme", "FACT: approved copy", {"evidences":[{"statement":"Approved copy"}]})
    assert result["evidence_proposals"][0]["comparison"] == "CONFIRMED"


def test_source_manifest_is_idempotent_and_changed_bytes_make_revision(tmp_path):
    raw = tmp_path / "bi.csv"; raw.write_text("a")
    first = source_intake_preview("acme", tmp_path, now="2026-09-16T00:00:00Z")
    replay = source_intake_preview("acme", tmp_path, first, now="2026-09-16T00:01:00Z")
    assert replay["sources"][0]["status"] == "no_change"
    raw.write_text("b")
    changed = source_intake_preview("acme", tmp_path, first, now="2026-09-16T00:02:00Z")
    assert changed["sources"][0]["status"] == "new" and changed["sources"][0]["source_id"] != first["sources"][0]["source_id"]


def test_generated_at_only_is_not_a_meaningful_change():
    assert not meaningful_diff({"generated_at":"a", "x":1}, {"generated_at":"b", "x":1})
    assert meaningful_diff({"x":1}, {"x":2})


def test_week_close_artifact_feeds_ropre_without_automatic_carry_forward():
    close = week_close_preview("acme", {"tasks":[_task(due="2026-10-01")]}, {"operations":[]}, date(2026, 9, 16))
    assert len(close["artifact_ref"]["content_sha256"]) == 64
    assert close["carry_forward_candidates"] == []
    assert build_midweek("acme", {"tasks":[_task()]}, {"operations":[]}, date(2026, 9, 16))["skill"] == "midweek"


def test_what_changed_is_semantic():
    assert what_changed({"tasks":[{"task_id":"a","generated_at":"a"}]}, {"tasks":[{"task_id":"a","generated_at":"b"}]})["ALTERADO"] == []
