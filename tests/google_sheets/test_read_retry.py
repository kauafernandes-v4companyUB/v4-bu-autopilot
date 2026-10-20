"""Quota resilience of the real Sheets transport: idempotent READS retry on
429 / 403 rate-limit reasons (Retry-After or exponential backoff with
jitter, bounded); WRITES never retry. sleep/clock/jitter are mocked — no
test waits for real, no Google library or network is needed."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.lib.google_sheets_patch import preview_patch
from scripts.lib.google_sheets_transport import (
    FakeGoogleSheetsTransport,
    GoogleApiSheetsTransport,
    GoogleSheetsAPIError,
    GoogleSheetsPermissionDenied,
    ReadRetryPolicy,
    is_retryable_read_error,
    run_read_with_retry,
)

from .conftest import CLIENT_ID, Q, base_patch  # noqa: F401

SID = "fake-sheet-000000001"


class _Resp(dict):
    def __init__(self, status, headers=None):
        super().__init__(headers or {})
        self.status = status


class FakeHttpError(Exception):
    """Shape of googleapiclient.errors.HttpError, duck-typed."""

    def __init__(self, status, reason="", headers=None, error_details=None, content=None):
        super().__init__(f"HTTP {status} {reason}")
        self.resp = _Resp(status, headers)
        self.reason = reason
        self.error_details = error_details
        self.content = content


def QUOTA(**kw):
    return FakeHttpError(429, "Quota exceeded for quota metric 'Read requests'", **kw)


class _Req:
    def __init__(self, svc, kind, kw):
        self.svc, self.kind, self.kw = svc, kind, kw

    def execute(self, num_retries=0):
        self.svc.executions.append((self.kind, num_retries))
        script = self.svc.scripts.get(self.kind, [])
        outcome = script.pop(0) if script else self.svc.ok[self.kind](self.kw)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Svc:
    """spreadsheets() service whose calls follow a per-kind script of
    exceptions before falling back to a normal response."""

    def __init__(self, **scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.executions = []
        self.ok = {
            "batchGet": lambda kw: {"valueRanges": [{"range": r, "values": [["v"]]} for r in kw["ranges"]]},
            "get": lambda kw: {"spreadsheetId": SID, "properties": {"title": "T", "locale": "pt_BR", "timeZone": "Etc/GMT"},
                               "sheets": [{"properties": {"sheetId": 1, "title": "T", "index": 0, "gridProperties": {"rowCount": 10, "columnCount": 3}}}]},
            "batchUpdate": lambda kw: {"replies": [{}]}, "values.batchUpdate": lambda kw: {"totalUpdatedCells": 1, "responses": []},
            "batchClear": lambda kw: {"clearedRanges": kw["body"]["ranges"]},
        }
        svc = self

        class Values:
            def batchGet(self, **kw):
                return _Req(svc, "batchGet", kw)

            def batchUpdate(self, **kw):
                return _Req(svc, "values.batchUpdate", kw)

            def batchClear(self, **kw):
                return _Req(svc, "batchClear", kw)

        class Sheets:
            def values(self):
                return Values()

            def get(self, **kw):
                return _Req(svc, "get", kw)

            def batchUpdate(self, **kw):
                return _Req(svc, "batchUpdate", kw)

        self._sheets = Sheets()

    def spreadsheets(self):
        return self._sheets


def _policy(rng=0.0, **kw):
    slept, now = [], [0.0]

    def sleep(s):
        slept.append(s)
        now[0] += s
    return ReadRetryPolicy(sleep=sleep, clock=lambda: now[0], rng=lambda: rng, **kw), slept


def _transport(svc, **kw):
    policy, slept = _policy(**kw)
    return GoogleApiSheetsTransport(service=svc, read_retry=policy), slept


# 1, 11 ----------------------------------------------------------------------------------------------


def test_normal_read_has_no_retry_and_same_result_as_after_retry():
    plain, slept = _transport(_Svc())
    expected = plain.read_values(SID, ["'T'!A1"])
    assert slept == [] and plain.retry_events == []
    retried, slept2 = _transport(_Svc(batchGet=[QUOTA()]))
    assert retried.read_values(SID, ["'T'!A1"]) == expected  # 11: identical result after a retry
    assert slept2 == [15.0]


# 2, 3, 6 --------------------------------------------------------------------------------------------


def test_429_then_success_and_multiple_429s_use_exponential_backoff():
    t, slept = _transport(_Svc(get=[QUOTA()]))
    assert t.get_spreadsheet_metadata(SID)["title"] == "T" and slept == [15.0]
    assert [e.outcome for e in t.retry_events] == ["retrying", "succeeded_after_retry"]
    assert t.retry_events[0].status == 429 and t.retry_events[0].wait_s == 15.0 and t.retry_events[0].operation == "spreadsheets.get:metadata"
    t, slept = _transport(_Svc(batchGet=[QUOTA(), QUOTA(), QUOTA()]))
    t.read_values(SID, ["'T'!A1"])
    assert slept == [15.0, 30.0, 60.0]  # base 15s doubling, capped at 60s
    t, slept = _transport(_Svc(get=[QUOTA()]), rng=0.5)
    t.get_spreadsheet_metadata(SID)
    assert slept == [15.0 + 0.5 * 5.0]  # jitter up to 5s


# 4 --------------------------------------------------------------------------------------------------


def test_exhausted_retries_surface_api_error():
    t, slept = _transport(_Svc(batchGet=[QUOTA()] * 4))
    with pytest.raises(GoogleSheetsAPIError) as e:
        t.read_values(SID, ["'T'!A1"])
    assert e.value.code == "API_ERROR" and "HTTP 429" in str(e.value)
    assert slept == [15.0, 30.0, 60.0] and t.retry_events[-1].outcome == "gave_up"
    budget, slept = _policy(max_elapsed_s=20.0)
    calls = []
    with pytest.raises(FakeHttpError):
        run_read_with_retry(lambda: calls.append(1) or (_ for _ in ()).throw(QUOTA()), policy=budget, operation="x")
    assert slept == [15.0] and len(calls) == 2  # the 30s wait would pass the 20s elapsed budget


# 5 --------------------------------------------------------------------------------------------------


def test_valid_retry_after_is_honored_otherwise_backoff():
    t, slept = _transport(_Svc(batchGet=[QUOTA(headers={"retry-after": "7"})]))
    t.read_values(SID, ["'T'!A1"])
    assert slept == [7.0] and t.retry_events[0].retry_after == "7"
    for bad in ("soon", "-3", "100000"):
        t, slept = _transport(_Svc(batchGet=[QUOTA(headers={"retry-after": bad})]))
        t.read_values(SID, ["'T'!A1"])
        assert slept == [15.0], bad  # invalid / negative / absurd Retry-After -> exponential backoff


# 8, 9 -----------------------------------------------------------------------------------------------


def test_403_only_for_rate_limit_reasons():
    via_details = FakeHttpError(403, "User rate limit exceeded", error_details=[{"reason": "userRateLimitExceeded"}])
    via_body = FakeHttpError(403, "Rate limit", content=json.dumps({"error": {"errors": [{"reason": "rateLimitExceeded"}]}}).encode())
    denied = FakeHttpError(403, "The caller does not have permission", error_details=[{"reason": "permissionDenied"}])
    plain_403 = FakeHttpError(403, "Forbidden")
    assert is_retryable_read_error(via_details) and is_retryable_read_error(via_body)
    assert not is_retryable_read_error(denied) and not is_retryable_read_error(plain_403)
    assert not is_retryable_read_error(FakeHttpError(500, "backend")) and not is_retryable_read_error(ValueError("x"))
    t, slept = _transport(_Svc(get=[via_details]))
    assert t.get_spreadsheet_metadata(SID)["title"] == "T" and slept == [15.0]
    t, slept = _transport(_Svc(get=[denied]))
    with pytest.raises(GoogleSheetsPermissionDenied):
        t.get_spreadsheet_metadata(SID)
    assert slept == [] and len(t._service.executions) == 1


# 10 -------------------------------------------------------------------------------------------------


def test_writes_are_never_retried_automatically():
    cases = [
        ("values.batchUpdate", lambda t: t.write_values(SID, [{"range": "'T'!A1", "values": [["x"]]}], "RAW")),
        ("batchClear", lambda t: t.clear_values(SID, ["'T'!A1"])),
        ("batchUpdate", lambda t: t.add_sheets(SID, [{"title": "N", "row_count": 5, "column_count": 2, "frozen_row_count": 0, "insert_index": None}])),
        ("batchUpdate", lambda t: t.duplicate_sheet(SID, 1, "COPIA", 1)),
        ("batchUpdate", lambda t: t.batch_update(SID, [{"x": {}}])),
        ("batchUpdate", lambda t: t.set_number_formats(SID, [{"sheet_id": 1, "range": "'T'!A1", "number_format": {"type": "NUMBER"}}])),
    ]
    for kind, call in cases:
        svc = _Svc(**{kind: [QUOTA(), QUOTA()]})
        t, slept = _transport(svc)
        with pytest.raises(GoogleSheetsAPIError):
            call(t)
        assert slept == [] and t.retry_events == [] and svc.executions == [(kind, 0)], kind  # one attempt, library retry off
    svc = _Svc()
    t, _ = _transport(svc)
    t.read_values(SID, ["'T'!A1"])
    assert svc.executions == [("batchGet", 0)]  # the library's own retry is disabled on reads too: one central policy


# 12 -------------------------------------------------------------------------------------------------


class _QuotaFlakyFake(FakeGoogleSheetsTransport):
    """Fake whose reads go through run_read_with_retry and fail once with 429."""

    def __init__(self):
        super().__init__()
        self.policy, self.slept = _policy()
        self.events = []
        self._failed = set()

    def _flaky(self, name, fn):
        def call():
            if name not in self._failed:
                self._failed.add(name)
                raise QUOTA()
            return fn()
        return run_read_with_retry(call, policy=self.policy, operation=name, events=self.events)

    def get_spreadsheet_metadata(self, spreadsheet_id):
        return self._flaky("meta", lambda: super(_QuotaFlakyFake, self).get_spreadsheet_metadata(spreadsheet_id))

    def get_values(self, spreadsheet_id, ranges, value_render):
        return self._flaky(f"values:{value_render}", lambda: super(_QuotaFlakyFake, self).get_values(spreadsheet_id, ranges, value_render))

    def get_structure(self, spreadsheet_id, ranges):
        return self._flaky("structure", lambda: super(_QuotaFlakyFake, self).get_structure(spreadsheet_id, ranges))

    def get_cell_formats(self, spreadsheet_id, ranges):
        return self._flaky("formats", lambda: super(_QuotaFlakyFake, self).get_cell_formats(spreadsheet_id, ranges))


def test_retry_does_not_change_base_state_or_preview_hash(transport, sources_doc, patch):
    plain = preview_patch(transport, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc, clock=lambda: "2026-01-01T00:00:00Z")
    flaky = _QuotaFlakyFake()
    flaky._books = copy.deepcopy(transport._books)
    retried = preview_patch(flaky, client_id=CLIENT_ID, patch=patch, sources_doc=sources_doc, clock=lambda: "2026-01-01T00:00:00Z")
    assert flaky.slept and any(e.outcome == "succeeded_after_retry" for e in flaky.events)
    assert (retried["base_state_hash"], retried["preview_hash"]) == (plain["base_state_hash"], plain["preview_hash"])
    assert retried == plain and "retry" not in json.dumps(retried).lower()
