"""Executable storage contract (operation/storage-contract.md).

RAW        private/clients/<client_id>/            never canonical by existing; never in the public engine
CANONICAL  clients/<client_id>/                    durable memory; only .json/.md (+ .gitkeep markers)
TRANSIENT  context/generated/<client_id>/          deletable at any time without durable-state loss
RECEIPT    clients/<client_id>/receipts/           audit records written by canonical ACTION applies

Used by scripts/doctor.py, scripts/lib/memory_promotion.py and the tests.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

REQUIRED_AT_BOOTSTRAP = (
    "client.json", "sources.json", "knowledge.json", "evidence.json", "current-state.json",
    "decisions.json", "tasks.json", "strategy.md", "history/", "quarters/",
)
# file -> the ACTION (or skill) that creates it the first time it is needed
CREATED_LAZILY = {
    "operations.json": "manage-operations-ledger",
    "source-manifest.json": "manage-source-manifest",
    "receipts/": "any canonical ACTION apply",
    "quarters/<quarter_id>/plan.json": "manage-quarter create_quarter",
    "quarters/<quarter_id>/monitoring.json": "monitor-quarter",
    "quarters/<quarter_id>/check-ins/current.json": "close-ropre",
    "quarters/<quarter_id>/closure.json": "manage-quarter close_quarter",
}
CANONICAL_SCHEMAS = {
    "client.json": "schemas/client.schema.json",
    "sources.json": "schemas/client-sources.schema.json",
    "knowledge.json": "schemas/client-knowledge.schema.json",
    "evidence.json": "schemas/client-evidence.schema.json",
    "current-state.json": "schemas/current-state.schema.json",
    "decisions.json": "schemas/client-decisions.schema.json",
    "tasks.json": "schemas/task-ledger.schema.json",
    "operations.json": "schemas/operations-ledger.schema.json",
    "source-manifest.json": "schemas/source-manifest.schema.json",
}
CANONICAL_SUFFIXES = {".json", ".md"}
MARKER_NAMES = {".gitkeep", ".workspace-placeholder"}
PLACEHOLDER_MARKER = ".workspace-placeholder"


def classify(rel_path: str) -> str:
    """Classify a workspace-relative path (either separator) into RAW,
    CANONICAL, TRANSIENT, RECEIPT or UNKNOWN."""
    parts = PurePosixPath(rel_path.replace("\\", "/")).parts
    if len(parts) >= 3 and parts[0] == "private" and parts[1] == "clients":
        return "RAW"
    if len(parts) >= 3 and parts[0] == "context" and parts[1] == "generated":
        return "TRANSIENT"
    if len(parts) >= 3 and parts[0] == "clients":
        return "RECEIPT" if parts[2] == "receipts" else "CANONICAL"
    return "UNKNOWN"


def is_placeholder(client_dir: Path) -> bool:
    """A reserved directory with only the placeholder marker is not a client yet."""
    files = [p for p in client_dir.rglob("*") if p.is_file()]
    return bool(files) and all(p.name == PLACEHOLDER_MARKER for p in files)


def missing_required(client_dir: Path) -> list[str]:
    return [rel for rel in REQUIRED_AT_BOOTSTRAP
            if not ((client_dir / rel.rstrip("/")).is_dir() if rel.endswith("/") else (client_dir / rel).is_file())]


def raw_in_canonical(client_dir: Path) -> list[str]:
    """Files under clients/<id>/ that are not canonical memory formats."""
    return sorted(p.relative_to(client_dir).as_posix() for p in client_dir.rglob("*")
                  if p.is_file() and p.name not in MARKER_NAMES and p.suffix.lower() not in CANONICAL_SUFFIXES)
