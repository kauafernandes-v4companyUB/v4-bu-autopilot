"""No blind automatic retry on mutations (Sheets and Drive).

googleapiclient's `execute(num_retries=N)` / `next_chunk(num_retries=N)`
repeats the request — POSTs included — on 5xx/429/socket errors. A failed
write response may hide an applied mutation (or a created file), so every
call passes LIBRARY_NUM_RETRIES (0); idempotent reads retry quota errors via
ReadRetryPolicy only. Offline: injected fake services, mocked sleep/clock.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from scripts.lib.google_drive_transport import MIME_GOOGLE_SHEET, MIME_XLSX, GoogleApiDriveTransport
from scripts.lib.google_sheets_transport import (
    LIBRARY_NUM_RETRIES,
    GoogleApiSheetsTransport,
    GoogleSheetsAPIError,
    ReadRetryPolicy,
)

from .test_read_retry import QUOTA, SID, FakeHttpError, _Svc

ROOT = Path(__file__).resolve().parents[2]


def _policy():
    slept, now = [], [0.0]

    def sleep(s):
        slept.append(s)
        now[0] += s
    return ReadRetryPolicy(sleep=sleep, clock=lambda: now[0], rng=lambda: 0.0), slept


def test_library_retry_constant_is_zero():
    assert LIBRARY_NUM_RETRIES == 0


def test_googleapiclient_default_num_retries_is_zero():
    http = pytest.importorskip("googleapiclient.http")
    for fn in (http.HttpRequest.execute, http.HttpRequest.next_chunk, http.MediaIoBaseDownload.next_chunk):
        assert inspect.signature(fn).parameters["num_retries"].default == 0, fn


def test_every_library_call_pins_num_retries_to_the_constant():
    """Static audit: each execute()/next_chunk() in the transports passes
    num_retries=LIBRARY_NUM_RETRIES — never a literal, never a parameter."""
    for rel in ("scripts/lib/google_sheets_transport.py", "scripts/lib/google_drive_transport.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        calls = re.findall(r"\.(?:execute|next_chunk)\(([^)]*)\)", src)
        assert calls, rel
        for args in calls:
            assert args == "num_retries=LIBRARY_NUM_RETRIES", (rel, args)
        assert "_num_retries" not in src, rel


def test_transports_no_longer_accept_a_library_retry_count():
    with pytest.raises(TypeError):
        GoogleApiSheetsTransport(service=_Svc(), num_retries=2)
    with pytest.raises(TypeError):
        GoogleApiDriveTransport(service=object(), num_retries=2)


# -- Sheets: every mutation is sent once, whatever the error -----------------------


@pytest.mark.parametrize("error", [FakeHttpError(500, "backendError"), FakeHttpError(503, "unavailable"), QUOTA(), ConnectionResetError("reset")])
def test_sheets_mutations_are_attempted_exactly_once(error):
    calls = {
        "values.batchUpdate": lambda t: t.write_values(SID, [{"range": "'T'!A1", "values": [[1]]}], "RAW"),
        "batchClear": lambda t: t.clear_values(SID, ["'T'!A1"]),
        "batchUpdate": lambda t: t.batch_update(SID, [{"addSheet": {}}]),
    }
    for kind, call in calls.items():
        svc = _Svc(**{kind: [error]})
        policy, slept = _policy()
        t = GoogleApiSheetsTransport(service=svc, read_retry=policy)
        with pytest.raises(Exception):
            call(t)
        assert svc.executions == [(kind, 0)] and slept == [] and t.retry_events == [], kind


@pytest.mark.parametrize("method,args", [
    ("set_number_formats", (SID, [{"sheet_id": 1, "range": "'T'!A1", "number_format": {"type": "NUMBER"}}])),
    ("duplicate_sheet", (SID, 1, "NOVA", 1)),
    ("add_sheets", (SID, [{"title": "NOVA", "row_count": 10, "column_count": 3}])),
])
def test_sheets_structural_mutations_are_attempted_exactly_once(method, args):
    svc = _Svc(batchUpdate=[FakeHttpError(500, "backendError")])
    t = GoogleApiSheetsTransport(service=svc, read_retry=_policy()[0])
    with pytest.raises(GoogleSheetsAPIError):
        getattr(t, method)(*args)
    assert svc.executions == [("batchUpdate", 0)]


# -- Drive -------------------------------------------------------------------------


class _DriveReq:
    def __init__(self, svc, kind, kw):
        self.svc, self.kind, self.kw = svc, kind, kw

    def execute(self, num_retries=0):
        self.svc.executions.append((self.kind, num_retries))
        script = self.svc.scripts.get(self.kind, [])
        outcome = script.pop(0) if script else self.svc.ok(self.kind, self.kw)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _DriveSvc:
    def __init__(self, **scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.executions = []
        svc = self

        class Files:
            def get(self, **kw):
                return _DriveReq(svc, "get", kw)

            def list(self, **kw):
                return _DriveReq(svc, "list", kw)

            def copy(self, **kw):
                return _DriveReq(svc, "copy", kw)

            def create(self, **kw):
                return _DriveReq(svc, "create", kw)

        self._files = Files()

    @staticmethod
    def ok(kind, kw):
        if kind == "list":
            return {"files": []}
        name = (kw.get("body") or {}).get("name", "x")
        return {"id": "fake-file", "name": name, "mimeType": MIME_GOOGLE_SHEET if kind in ("copy", "create") else MIME_XLSX}

    def files(self):
        return self._files


@pytest.mark.parametrize("error", [FakeHttpError(500, "backendError"), QUOTA(), ConnectionResetError("reset")])
def test_drive_copy_is_attempted_exactly_once(error):
    svc = _DriveSvc(copy=[error])
    policy, slept = _policy()
    t = GoogleApiDriveTransport(service=svc, read_retry=policy)
    with pytest.raises(Exception):
        t.copy_file("fake-src", name="N", parent_id=None, app_properties={})
    assert svc.executions == [("copy", 0)] and slept == [] and t.retry_events == []


@pytest.mark.parametrize("error", [FakeHttpError(500, "backendError"), QUOTA()])
def test_drive_create_import_is_attempted_exactly_once(error):
    pytest.importorskip("googleapiclient.http")
    svc = _DriveSvc(create=[error])
    policy, slept = _policy()
    t = GoogleApiDriveTransport(service=svc, read_retry=policy)
    with pytest.raises(Exception):
        t.import_as_google_sheet(b"PK", name="N", parent_id=None, app_properties={})
    assert svc.executions == [("create", 0)] and slept == []


@pytest.mark.parametrize("kind,call", [
    ("get", lambda t: t.get_file_metadata("fake-file")),
    ("list", lambda t: t.find_created_copies(source_file_id="fake-src", operation="copy_sheet", name="N")),
])
def test_drive_reads_retry_quota_via_the_policy_only(kind, call):
    svc = _DriveSvc(**{kind: [QUOTA(), QUOTA()]})
    policy, slept = _policy()
    t = GoogleApiDriveTransport(service=svc, read_retry=policy)
    call(t)
    assert svc.executions == [(kind, 0)] * 3 and slept == [15.0, 30.0]
    assert [e.outcome for e in t.retry_events] == ["retrying", "retrying", "succeeded_after_retry"]


def test_drive_read_does_not_retry_non_quota_errors():
    svc = _DriveSvc(get=[FakeHttpError(500, "backendError")])
    policy, slept = _policy()
    with pytest.raises(GoogleSheetsAPIError):
        GoogleApiDriveTransport(service=svc, read_retry=policy).get_file_metadata("fake-file")
    assert svc.executions == [("get", 0)] and slept == []


def test_drive_download_chunks_retry_quota_via_the_policy_with_library_retry_off(monkeypatch):
    http = pytest.importorskip("googleapiclient.http")
    seen, script = [], [QUOTA(), (None, False), (None, True)]

    class Downloader:
        def __init__(self, buf, request):
            pass

        def next_chunk(self, num_retries=0):
            seen.append(num_retries)
            outcome = script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class Files:
        def get_media(self, **kw):
            return object()

    class Svc:
        def files(self):
            return Files()

    monkeypatch.setattr(http, "MediaIoBaseDownload", Downloader)
    policy, slept = _policy()
    GoogleApiDriveTransport(service=Svc(), read_retry=policy).download_file("fake-file")
    assert seen == [0, 0, 0] and slept == [15.0]
