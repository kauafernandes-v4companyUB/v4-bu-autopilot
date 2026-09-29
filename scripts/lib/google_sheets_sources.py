"""Resolve a Google Sheet binding from a client's canonical sources.json
(clients/<client_id>/sources.json, private workspace).

A spreadsheet is only ever reached through an entry of
``type: "google_sheet"`` declared by the requesting client
(schemas/google-sheet-source.schema.json). This is the client-isolation
boundary: a spreadsheet id that the client has not declared is never
read or written on that client's behalf, and nothing is ever looked up
by spreadsheet name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SOURCE_TYPE = "google_sheet"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_URL_RE = re.compile(r"^https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{10,})(?:[/?#].*)?$")


class SheetSourceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class SheetBinding:
    client_id: str
    source_id: str
    spreadsheet_id: str
    expected_title: Optional[str]
    allowed_tabs: Optional[tuple[str, ...]]
    writable: bool
    contains_multiple_clients: bool

    def tab_allowed(self, title: str) -> bool:
        return self.allowed_tabs is None or title in self.allowed_tabs


def parse_spreadsheet_locator(locator: str) -> str:
    """Accepts a bare spreadsheet id or a docs.google.com/spreadsheets/d/<id>
    URL. Never a spreadsheet name."""
    if not isinstance(locator, str):
        raise SheetSourceError("INVALID_LOCATOR", "spreadsheet locator must be a string")
    locator = locator.strip()
    m = _URL_RE.match(locator)
    if m:
        return m.group(1)
    if _ID_RE.match(locator):
        return locator
    raise SheetSourceError("INVALID_LOCATOR", "spreadsheet locator must be a spreadsheet id or a docs.google.com/spreadsheets/d/<id> URL (names are never searched)")


def load_client_sources(client_dir: Path) -> Optional[dict]:
    path = client_dir / "sources.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_sheet_binding(
    sources_doc: Optional[dict],
    client_id: str,
    *,
    source_id: Optional[str] = None,
    spreadsheet_locator: Optional[str] = None,
) -> SheetBinding:
    if sources_doc is None:
        raise SheetSourceError("SOURCE_REGISTRY_MISSING", f"no sources.json available for client {client_id!r}")
    if sources_doc.get("client_id") != client_id:
        raise SheetSourceError("CLIENT_ISOLATION", f"sources.json belongs to {sources_doc.get('client_id')!r}, not {client_id!r}")
    if source_id is None and spreadsheet_locator is None:
        raise SheetSourceError("INVALID_LOCATOR", "either source_id or spreadsheet id/URL is required")

    spreadsheet_id = parse_spreadsheet_locator(spreadsheet_locator) if spreadsheet_locator is not None else None
    entries = [s for s in sources_doc.get("sources", []) if s.get("type") == SOURCE_TYPE]
    matches = [
        s for s in entries
        if (source_id is None or s.get("source_id") == source_id)
        and (spreadsheet_id is None or (s.get("google_sheet") or {}).get("spreadsheet_id") == spreadsheet_id)
    ]
    if not matches:
        if source_id is not None and spreadsheet_id is not None and any(s.get("source_id") == source_id for s in entries):
            raise SheetSourceError("WRONG_SPREADSHEET", f"source {source_id!r} does not point at the requested spreadsheet id")
        raise SheetSourceError("SOURCE_NOT_REGISTERED", f"no google_sheet source matching the request is declared in {client_id}'s sources.json")
    if len(matches) > 1:
        raise SheetSourceError("AMBIGUOUS_SOURCE", f"{len(matches)} google_sheet sources match — pass source_id explicitly")

    entry = matches[0]
    gs = entry.get("google_sheet") or {}
    if not gs.get("spreadsheet_id"):
        raise SheetSourceError("INVALID_SOURCE", f"source {entry.get('source_id')!r} has no google_sheet.spreadsheet_id")
    allowed = gs.get("allowed_tabs")
    return SheetBinding(
        client_id=client_id,
        source_id=entry["source_id"],
        spreadsheet_id=gs["spreadsheet_id"],
        expected_title=gs.get("expected_title"),
        allowed_tabs=tuple(allowed) if allowed is not None else None,
        writable=bool(gs.get("writable", False)),
        contains_multiple_clients=bool(entry.get("contains_multiple_clients", False)),
    )
