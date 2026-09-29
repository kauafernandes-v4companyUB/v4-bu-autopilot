"""Google credentials for the Sheets and Drive transports — one local
authentication for both.

Configuration comes only from environment variables (see .env.example).
Nothing here ever reads a credential from, or writes one into, the
engine repository: every credential path is resolved and refused if it
falls inside this repo. Tokens and secrets are never printed or logged.

Modes (V4_BU_GOOGLE_AUTH_MODE):
- ``oauth`` (default): the local operator's own Google account, so the
  engine sees exactly the spreadsheets the operator can see. The OAuth
  client secret (Desktop app) and the token it produces live outside the
  repo. Login is an explicit, interactive step
  (``python scripts/google_sheets.py auth``); skills never open a
  browser on their own — a missing/expired token is an AUTH_ERROR.
- ``service_account``: optional alternative; the spreadsheet must be
  shared with the service account's e-mail.

Scopes (docs/workflows/google-sheets.md, "Scopes"):
- ``spreadsheets``: read/write cell content (Sheets API).
- ``drive.readonly``: metadata + download of existing files addressed by
  an explicit file id (MIME detection, .xlsx download for conversion).
  ``drive.file`` alone is not enough: without a Google Picker it only
  reaches files this app created.
- ``drive.file``: create files (converted/copied operational sheets) and
  manage only the files this app created. Never full ``drive``.

Each transport requires only its own scopes, so a token created before
the Drive scopes existed keeps working for Sheets and fails with a clear
INSUFFICIENT_SCOPE + re-authentication instruction for Drive.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from scripts.lib.google_sheets_transport import (
    GoogleApiSheetsTransport,
    GoogleInsufficientScope,
    GoogleSheetsAuthError,
    GoogleSheetsDependencyMissing,
)

ENV_AUTH_MODE = "V4_BU_GOOGLE_AUTH_MODE"
ENV_CLIENT_SECRETS = "V4_BU_GOOGLE_OAUTH_CLIENT_SECRETS"
ENV_TOKEN_PATH = "V4_BU_GOOGLE_OAUTH_TOKEN_PATH"
ENV_SERVICE_ACCOUNT_FILE = "V4_BU_GOOGLE_SERVICE_ACCOUNT_FILE"

AUTH_MODES = ("oauth", "service_account")
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
SHEETS_REQUIRED_SCOPES = [SHEETS_SCOPE]
DRIVE_REQUIRED_SCOPES = [DRIVE_READONLY_SCOPE, DRIVE_FILE_SCOPE]
SCOPES = [SHEETS_SCOPE, DRIVE_READONLY_SCOPE, DRIVE_FILE_SCOPE]  # requested at login
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "v4-bu-autopilot" / "google-sheets-token.json"
ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent

_INSTALL_HINT = "pip install -r requirements-google.txt"


@dataclass(frozen=True)
class GoogleAuthConfig:
    mode: str
    client_secrets_path: Optional[Path]
    token_path: Optional[Path]
    service_account_path: Optional[Path]


def _outside_engine(raw: str, env_name: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if path == ENGINE_ROOT or ENGINE_ROOT in path.parents:
        raise GoogleSheetsAuthError(
            f"{env_name} points inside the engine repository — refusing. Credentials and tokens must live outside the repo (see docs/workflows/google-sheets.md)."
        )
    return path


def load_auth_config(env: Optional[Mapping[str, str]] = None) -> GoogleAuthConfig:
    env = os.environ if env is None else env
    mode = (env.get(ENV_AUTH_MODE) or "oauth").strip().lower()
    if mode not in AUTH_MODES:
        raise GoogleSheetsAuthError(f"{ENV_AUTH_MODE} must be one of {AUTH_MODES}, got {mode!r}")
    if mode == "service_account":
        raw = env.get(ENV_SERVICE_ACCOUNT_FILE)
        if not raw:
            raise GoogleSheetsAuthError(f"{ENV_AUTH_MODE}=service_account requires {ENV_SERVICE_ACCOUNT_FILE}")
        return GoogleAuthConfig(mode, None, None, _outside_engine(raw, ENV_SERVICE_ACCOUNT_FILE))
    secrets = env.get(ENV_CLIENT_SECRETS)
    token = env.get(ENV_TOKEN_PATH)
    return GoogleAuthConfig(
        mode,
        _outside_engine(secrets, ENV_CLIENT_SECRETS) if secrets else None,
        _outside_engine(token, ENV_TOKEN_PATH) if token else _outside_engine(str(DEFAULT_TOKEN_PATH), "default token path"),
        None,
    )


def _save_token(creds, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # best effort on filesystems without POSIX modes
        pass
    os.replace(tmp, path)


def _granted_scopes(info: dict) -> list[str]:
    raw = info.get("scopes") or info.get("scope") or []
    return raw.split() if isinstance(raw, str) else list(raw)


def load_credentials(config: GoogleAuthConfig, required_scopes: Optional[list[str]] = None):
    """Non-interactive: returns valid credentials or raises
    GoogleSheetsAuthError. Refreshes an expired OAuth token when a
    refresh_token exists, and persists the refreshed token. A token that
    was not granted every scope in `required_scopes` (default: Sheets)
    raises GoogleInsufficientScope with a re-authentication instruction."""
    required_scopes = list(required_scopes or SHEETS_REQUIRED_SCOPES)
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2 import service_account  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
    except ImportError as e:
        raise GoogleSheetsDependencyMissing(f"Google auth libraries are not installed: {_INSTALL_HINT}") from e

    if config.mode == "service_account":
        if not config.service_account_path or not config.service_account_path.is_file():
            raise GoogleSheetsAuthError(f"service account file not found at the path configured in {ENV_SERVICE_ACCOUNT_FILE}")
        return service_account.Credentials.from_service_account_file(str(config.service_account_path), scopes=SCOPES)

    if not config.token_path or not config.token_path.is_file():
        raise GoogleSheetsAuthError("no OAuth token found — run `python scripts/google_sheets.py auth` once (interactive login)")
    try:
        info = json.loads(config.token_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise GoogleSheetsAuthError(f"stored OAuth token is unreadable ({type(e).__name__}) — run `python scripts/google_sheets.py auth` again") from e
    granted = _granted_scopes(info)
    missing = [s for s in required_scopes if s not in granted]
    if missing:
        raise GoogleInsufficientScope(
            "stored OAuth token was not granted the scope(s) this operation needs "
            f"({', '.join(missing)}) — it was probably created before they were added. "
            "Re-run `python scripts/google_sheets.py auth` to re-consent with the current scopes."
        )
    try:
        # keep the scopes actually granted, so a refresh never asks for more than consented
        creds = Credentials.from_authorized_user_info(info, granted)
    except (ValueError, OSError) as e:
        raise GoogleSheetsAuthError(f"stored OAuth token is unreadable ({type(e).__name__}) — run `python scripts/google_sheets.py auth` again") from e
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001 - mapped to a clean auth error, no secret in message
            raise GoogleSheetsAuthError(f"OAuth token refresh failed ({type(e).__name__}) — run `python scripts/google_sheets.py auth` again") from e
        _save_token(creds, config.token_path)
        return creds
    raise GoogleSheetsAuthError("OAuth token is invalid — run `python scripts/google_sheets.py auth` again")


def run_oauth_login(config: GoogleAuthConfig) -> Path:
    """Interactive, explicit operator step: opens the browser for consent
    and stores the token at config.token_path. Returns the token path."""
    if config.mode != "oauth":
        raise GoogleSheetsAuthError("interactive login only applies to oauth mode")
    if not config.client_secrets_path or not config.client_secrets_path.is_file():
        raise GoogleSheetsAuthError(f"OAuth client secrets file not found — set {ENV_CLIENT_SECRETS} to the Desktop-app client JSON downloaded from Google Cloud Console")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError as e:
        raise GoogleSheetsDependencyMissing(f"google-auth-oauthlib is not installed: {_INSTALL_HINT}") from e
    flow = InstalledAppFlow.from_client_secrets_file(str(config.client_secrets_path), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save_token(creds, config.token_path)
    return config.token_path


def build_real_transport(env: Optional[Mapping[str, str]] = None) -> GoogleApiSheetsTransport:
    return GoogleApiSheetsTransport(credentials=load_credentials(load_auth_config(env), SHEETS_REQUIRED_SCOPES))


def build_real_drive_transport(env: Optional[Mapping[str, str]] = None):
    from scripts.lib.google_drive_transport import GoogleApiDriveTransport

    return GoogleApiDriveTransport(credentials=load_credentials(load_auth_config(env), DRIVE_REQUIRED_SCOPES))


def token_scope_status(config: GoogleAuthConfig) -> dict:
    """For auth-status: which required scope sets the stored token covers.
    Never returns token contents."""
    if config.mode != "oauth" or not config.token_path or not config.token_path.is_file():
        return {"sheets_scopes_granted": None, "drive_scopes_granted": None}
    try:
        granted = _granted_scopes(json.loads(config.token_path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return {"sheets_scopes_granted": False, "drive_scopes_granted": False}
    return {
        "sheets_scopes_granted": all(s in granted for s in SHEETS_REQUIRED_SCOPES),
        "drive_scopes_granted": all(s in granted for s in DRIVE_REQUIRED_SCOPES),
    }
