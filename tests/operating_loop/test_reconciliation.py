from __future__ import annotations

from scripts.lib.ekyte_transport import FakeEkyteTransport
from scripts.lib.reconciliation import classify_task, reconcile_tasks, summarize

LOCAL_UNBOUND = {"task_id": "t-1", "status": "pending", "due_at": "2026-04-15", "external": None}


def _bound_task(external_id, status="pending", due_at="2026-04-15"):
    return {"task_id": "t-2", "status": status, "due_at": due_at, "external": {"system": "ekyte", "external_id": external_id, "url": "u", "published_at": "t", "last_verified_at": "t"}}


# Y. local only

def test_y_unbound_task_is_local_only():
    c = classify_task(LOCAL_UNBOUND, transport=None)
    assert c.classification == "LOCAL_ONLY"


def test_unbound_task_local_only_even_with_transport():
    transport = FakeEkyteTransport()
    c = classify_task(LOCAL_UNBOUND, transport=transport)
    assert c.classification == "LOCAL_ONLY"


def test_bound_task_without_transport_is_unknown():
    task = _bound_task("fake-1")
    c = classify_task(task, transport=None)
    assert c.classification == "UNKNOWN"


def test_bound_task_transport_finds_nothing_is_unknown():
    transport = FakeEkyteTransport()
    task = _bound_task("fake-does-not-exist")
    c = classify_task(task, transport=transport)
    assert c.classification == "UNKNOWN"


# X. matched

def test_x_matched_when_status_and_due_date_agree():
    transport = FakeEkyteTransport()
    remote = transport.create_task({"title": "t", "description": "d", "due_at": "2026-04-15"})
    task = _bound_task(remote["external_id"], status="pending", due_at="2026-04-15")
    c = classify_task(task, transport=transport)
    assert c.classification == "MATCHED"


# Z. status mismatch

def test_z_status_mismatch_when_remote_marked_done():
    transport = FakeEkyteTransport()
    remote = transport.create_task({"title": "t", "description": "d", "due_at": "2026-04-15"})
    transport.update_task(remote["external_id"], {"status": "done"})
    task = _bound_task(remote["external_id"], status="pending", due_at="2026-04-15")
    c = classify_task(task, transport=transport)
    assert c.classification == "STATUS_MISMATCH"


def test_due_date_mismatch_when_dates_disagree():
    transport = FakeEkyteTransport()
    remote = transport.create_task({"title": "t", "description": "d", "due_at": "2026-04-15"})
    transport.update_task(remote["external_id"], {"due_at": "2026-04-20"})
    task = _bound_task(remote["external_id"], status="pending", due_at="2026-04-15")
    c = classify_task(task, transport=transport)
    assert c.classification == "DUE_DATE_MISMATCH"


def test_reconcile_tasks_and_summarize():
    transport = FakeEkyteTransport()
    matched_remote = transport.create_task({"title": "a", "description": "d", "due_at": "2026-04-15"})
    tasks = [LOCAL_UNBOUND, _bound_task(matched_remote["external_id"])]
    comparisons = reconcile_tasks(tasks, transport)
    summary = summarize(comparisons)
    assert summary["local_only"] == 1
    assert summary["matched"] == 1
    assert summary["remote_only"] == 0  # documented limitation — never detected by this minimal transport
