"""source-intake discovery + manage-source-manifest ACTION. Synthetic only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bootstrap_client import bootstrap_client
from scripts.lib import approval as ap
from scripts.lib import source_manifest as sm

CLIENT = "acme-demo"


@pytest.fixture
def ws(temp_workspace):
    assert bootstrap_client(CLIENT, workspace_root=str(temp_workspace))["status"] == "CREATED"
    return temp_workspace


def _dirs(ws: Path):
    return ws / "clients" / CLIENT, ws / "private" / "clients" / CLIENT


def _put(private: Path, rel: str, text: str):
    p = private / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _approve(pv):
    c = sm.build_approval_candidate(pv, approval_id=f"appr-{pv['preview_hash'][:6]}", created_at="2026-10-02T09:00:00Z", preview_path="x")
    return ap.apply_operator_decision(c, approved_at="2026-10-02T09:01:00Z", approved_by="operator-synthetic",
                                      approve_item_ids=[sm.approval_item_id(pv)])


def _run(ws, **kw):
    client, private = _dirs(ws)
    pv = sm.preview(client, private, client_id=CLIENT, **kw)
    out = sm.apply(pv, _approve(pv), client) if pv["status"] == "success" else sm.apply(pv, None, client)
    return pv, out


@pytest.mark.parametrize(("rel", "expected"), [
    ("client-context/handoff.md", "client_context"), ("account-gt/2026-09-30.txt", "account_gt_transcript"),
    ("whatsapp/chat.zip", "whatsapp_export"), ("bi/2026-09/dashboard.pdf", "bi_pdf"), ("bi/export.csv", "bi_csv"),
    ("google-sheets/metrics.gsheet.json", "google_sheet"), ("manual/approved-note.md", "manual_authorized_input"),
    ("misc/photo.jpg", "unknown"),
])
def test_classification_covers_every_supported_type(rel, expected):
    assert sm.classify(rel) == expected and sm.classify(rel.replace("/", "\\")) == expected


def test_new_no_change_revision_and_missing(ws, repo_root, validate):
    client, private = _dirs(ws)
    _put(private, "whatsapp/chat.txt", "[synthetic] v1")
    _put(private, "bi/export.csv", "a,b\n1,2\n")
    pv, out = _run(ws)
    assert {f["status"] for f in pv["findings"]} == {"NEW_SOURCE"} and out["status"] == "success"
    assert validate(pv, repo_root / "skills/manage-source-manifest/output.schema.json") == []
    manifest = json.loads((client / "source-manifest.json").read_text(encoding="utf-8"))
    assert validate(manifest, repo_root / "schemas/source-manifest.schema.json") == []
    assert (client / "receipts" / f"{out['receipt']['receipt_id']}.json").is_file()
    sid = {e["path"]: e["source_id"] for e in manifest["sources"]}

    pv2, out2 = _run(ws)
    assert {f["status"] for f in pv2["findings"]} == {"NO_CHANGE"} and out2["status"] == "no_change"

    _put(private, "whatsapp/chat.txt", "[synthetic] v2")
    (private / "bi" / "export.csv").unlink()
    pv3, out3 = _run(ws)
    statuses = {f["path"]: f["status"] for f in pv3["findings"]}
    assert statuses == {"whatsapp/chat.txt": "NEW_REVISION", "bi/export.csv": "MISSING"}
    manifest = json.loads((client / "source-manifest.json").read_text(encoding="utf-8"))
    chats = [e for e in manifest["sources"] if e["path"] == "whatsapp/chat.txt"]
    assert [e["revision"] for e in chats] == [1, 2] and {e["source_id"] for e in chats} == {sid["whatsapp/chat.txt"]}
    assert any(e["path"] == "bi/export.csv" for e in manifest["sources"])  # missing is never deleted


def test_mark_processed_and_raw_never_becomes_canonical(ws):
    client, private = _dirs(ws)
    _put(private, "account-gt/call.txt", "[synthetic] transcript")
    _run(ws)
    entry = json.loads((client / "source-manifest.json").read_text(encoding="utf-8"))["sources"][0]
    pv, out = _run(ws, mark_processed=[{"source_id": entry["source_id"], "revision": 1, "processor": "read-account-gt",
                                        "processor_version": "1.0.0", "output_ref": f"context/generated/{CLIENT}/account-gt.json"}])
    assert out["status"] == "success"
    done = json.loads((client / "source-manifest.json").read_text(encoding="utf-8"))["sources"][0]
    assert done["status"] == "processed" and done["processed_at"] and done["output_ref"].startswith("context/generated/")
    assert json.loads((client / "evidence.json").read_text(encoding="utf-8"))["evidences"] == []
    assert not any("[synthetic] transcript" in p.read_text(encoding="utf-8") for p in client.rglob("*.json"))


def test_stale_manifest_preview_is_blocked(ws):
    client, private = _dirs(ws)
    _put(private, "manual/note.md", "[synthetic] note")
    pv = sm.preview(client, private, client_id=CLIENT)
    approval = _approve(pv)
    _put(private, "client-context/ctx.md", "[synthetic]")
    _run(ws)  # another approved intake lands first
    before = (client / "source-manifest.json").read_bytes()
    out = sm.apply(pv, approval, client)
    assert out["status"] == "conflict" and out["errors"][0].startswith("STALE_APPROVAL")
    assert (client / "source-manifest.json").read_bytes() == before
