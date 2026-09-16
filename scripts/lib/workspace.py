"""Resolve the V4 BU Autopilot workspace root.

The engine repository (this repo) never contains real client data. Real
operational data (canonical client memory, private raw sources, transient
generated context, operational outputs) lives in a separate workspace
directory, conventionally a private git repository, pointed to by the
``V4_BU_WORKSPACE_ROOT`` environment variable.

See ``docs/security-model.md`` and ``.env.example`` for the full picture.

This module is the single place that resolves that path. Skills, docs and
scripts should not hardcode ``clients/``, ``private/`` or
``context/generated/`` as repo-relative paths when operating on real
client data — they should go through :func:`resolve_workspace` /
:class:`Workspace` instead. Repo-relative paths remain fine for the
engine's own fixtures/tests under ``examples/`` and ``tests/fixtures/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ENV_VAR = "V4_BU_WORKSPACE_ROOT"

# Sub-directories every valid workspace must have.
REQUIRED_SUBDIRS = ("clients", "private", "context/generated", "outputs")


class WorkspaceError(Exception):
    """Base class for workspace resolution/validation failures."""


class WorkspaceNotConfigured(WorkspaceError):
    """Raised when a workspace is required but V4_BU_WORKSPACE_ROOT is unset."""


class WorkspaceInvalid(WorkspaceError):
    """Raised when V4_BU_WORKSPACE_ROOT points at something that is not a
    valid workspace (missing required sub-directories)."""


@dataclass(frozen=True)
class Workspace:
    """A validated workspace root and its canonical sub-paths."""

    root: Path

    @property
    def clients_dir(self) -> Path:
        return self.root / "clients"

    @property
    def private_dir(self) -> Path:
        return self.root / "private"

    @property
    def generated_dir(self) -> Path:
        return self.root / "context" / "generated"

    @property
    def outputs_dir(self) -> Path:
        return self.root / "outputs"

    def client_dir(self, client_id: str) -> Path:
        _validate_client_id(client_id)
        return self.clients_dir / client_id

    def client_file(self, client_id: str, relative_path: str) -> Path:
        """Path to a file inside a client's canonical memory tree.

        ``relative_path`` examples: ``"client.json"``,
        ``"quarters/2026-Q3/plan.json"``, ``"history/foo.json"``.
        """
        _validate_client_id(client_id)
        return self.client_dir(client_id) / relative_path

    def client_private_dir(self, client_id: str) -> Path:
        _validate_client_id(client_id)
        return self.private_dir / "clients" / client_id

    def client_generated_dir(self, client_id: str) -> Path:
        _validate_client_id(client_id)
        return self.generated_dir / client_id


def _validate_client_id(client_id: str) -> None:
    if not client_id or not isinstance(client_id, str):
        raise ValueError("client_id must be a non-empty string")
    if "/" in client_id or ".." in client_id:
        raise ValueError(f"unsafe client_id: {client_id!r}")


def _is_valid_workspace(root: Path) -> bool:
    if not root.is_dir():
        return False
    return all((root / sub).is_dir() for sub in REQUIRED_SUBDIRS)


def resolve_workspace(
    *,
    required: bool = True,
    override: Optional[str] = None,
    create_if_missing: bool = False,
) -> Optional[Workspace]:
    """Resolve the workspace root.

    Resolution order: ``override`` argument (mostly for tests/CLI
    ``--workspace``), then the ``V4_BU_WORKSPACE_ROOT`` environment
    variable. There is no silent fallback to a directory inside this
    repository, or to any other guessed location — that would risk
    treating engine-repo directories as if they held real client data.

    ``required=True`` (default): raise :class:`WorkspaceNotConfigured` if
    unset, or :class:`WorkspaceInvalid` if set but not a valid workspace
    (unless ``create_if_missing=True``, which scaffolds the required
    sub-directories — intended for ``bootstrap_client.py`` and tests, not
    for silently working around a broken production workspace).

    ``required=False``: return ``None`` when unset or invalid, instead of
    raising. This is how ``scripts/doctor.py`` reports "workspace: SKIP"
    on a public clone with no workspace configured, rather than failing.
    """
    raw = override if override is not None else os.environ.get(ENV_VAR)

    if not raw:
        if required:
            raise WorkspaceNotConfigured(
                f"{ENV_VAR} is not set and no workspace was required to be absent. "
                f"Set {ENV_VAR} to the path of your private workspace "
                f"(see .env.example)."
            )
        return None

    root = Path(raw).expanduser().resolve()

    if not _is_valid_workspace(root):
        if create_if_missing:
            for sub in REQUIRED_SUBDIRS:
                (root / sub).mkdir(parents=True, exist_ok=True)
        elif required:
            raise WorkspaceInvalid(
                f"{ENV_VAR}={raw!r} does not look like a valid workspace "
                f"(expected sub-directories: {', '.join(REQUIRED_SUBDIRS)}). "
                f"Refusing to guess — fix the path or scaffold it explicitly."
            )
        else:
            return None

    return Workspace(root=root)


def require_workspace(override: Optional[str] = None) -> Workspace:
    """Convenience: resolve_workspace(required=True), never returns None."""
    ws = resolve_workspace(required=True, override=override)
    assert ws is not None  # required=True never returns None
    return ws
