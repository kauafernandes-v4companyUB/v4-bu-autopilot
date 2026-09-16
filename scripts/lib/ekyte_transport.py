"""eKyte transport abstraction (skills/publish-ekyte).

No real, documented eKyte API/connector/webhook was found anywhere in
the engine or the private workspace (audited 2026-09-16 — see
docs/workflows/ekyte-publication.md). This module therefore defines the
interface any real transport would need to satisfy, a FakeEkyteTransport
for tests and dry runs, and a small capability-discovery helper that
never pretends a real transport exists when it doesn't.

Never invent an endpoint, a credential, or a request shape for a real
API here — RealEkyteTransport is intentionally absent until a real,
documented capability is found.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

CAPABILITY_API = "API"
CAPABILITY_CONNECTOR = "CONNECTOR"
CAPABILITY_BROWSER_AUTOMATION = "BROWSER_AUTOMATION"
CAPABILITY_MANUAL_EXPORT = "MANUAL_EXPORT"
CAPABILITY_NONE = "NONE"

KNOWN_CAPABILITIES = (
    CAPABILITY_API,
    CAPABILITY_CONNECTOR,
    CAPABILITY_BROWSER_AUTOMATION,
    CAPABILITY_MANUAL_EXPORT,
    CAPABILITY_NONE,
)


def discover_ekyte_capability() -> str:
    """Never invents a capability. Only reports API if a real, explicit
    transport configuration is present in the environment (the one
    honest way a future real integration could announce itself without
    this module hardcoding a URL/credential shape it has never seen
    documented). Absent that, the best REAL capability available today
    is MANUAL_EXPORT: an operator can paste a task into eKyte's web UI
    and record the resulting URL via manage-task-ledger's link_ekyte —
    that path already exists and needs no new transport at all.
    """
    if os.environ.get("V4_BU_EKYTE_API_URL") and os.environ.get("V4_BU_EKYTE_API_TOKEN"):
        return CAPABILITY_API
    return CAPABILITY_MANUAL_EXPORT


class EkyteTransportError(Exception):
    pass


class EkyteTaskConflict(EkyteTransportError):
    pass


class EkyteTransport(ABC):
    """Interface any real transport must implement. Payload/response
    shapes are intentionally minimal — extend only when a real,
    documented eKyte interface requires more, never speculatively."""

    @abstractmethod
    def create_task(self, payload: dict) -> dict:
        """payload: {title, description, due_at (optional)}.
        Returns {external_id, url, status}."""

    @abstractmethod
    def fetch_task(self, external_id: str) -> Optional[dict]:
        """Returns {external_id, url, title, description, due_at, status}
        or None if not found."""

    @abstractmethod
    def update_task(self, external_id: str, payload: dict) -> dict:
        """Returns the updated remote record, same shape as fetch_task."""


@dataclass
class FakeEkyteTransport(EkyteTransport):
    """In-memory transport for tests and dry runs. Never touches a real
    network. Deterministic external_id sequence so tests are stable."""

    _store: dict = field(default_factory=dict)
    _next_id: int = field(default=1)

    def create_task(self, payload: dict) -> dict:
        for existing in self._store.values():
            if existing["title"] == payload.get("title") and existing["due_at"] == payload.get("due_at"):
                raise EkyteTaskConflict(f"a task with the same title/due_at already exists: {existing['external_id']}")
        external_id = f"fake-{self._next_id}"
        self._next_id += 1
        record = {
            "external_id": external_id,
            "url": f"https://fake-ekyte.local/tasks/{external_id}",
            "title": payload.get("title"),
            "description": payload.get("description"),
            "due_at": payload.get("due_at"),
            "status": "open",
        }
        self._store[external_id] = record
        return dict(record)

    def fetch_task(self, external_id: str) -> Optional[dict]:
        record = self._store.get(external_id)
        return dict(record) if record else None

    def update_task(self, external_id: str, payload: dict) -> dict:
        if external_id not in self._store:
            raise EkyteTransportError(f"no such task: {external_id}")
        self._store[external_id].update({k: v for k, v in payload.items() if v is not None})
        return dict(self._store[external_id])
