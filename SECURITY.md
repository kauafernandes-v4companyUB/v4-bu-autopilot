# Security

## Scope

This is a public **engine** repository: skills (Claude/Codex-executed
contracts), JSON schemas, tooling, tests, docs and synthetic examples.
It never contains real client data — see `docs/security-model.md` for
the full public/private boundary model.

## Reporting a vulnerability or an exposure

If you find real client data (names, CNPJ/company identifiers, phone
numbers, WhatsApp content, BI/campaign figures, or any other data that
identifies a real person or business) anywhere in this repository —
including in git history, not just the current tree — **do not open a
public issue**. Instead:

1. Stop, and do not clone/fork/mirror further than necessary.
2. Contact the repository owner directly and privately.
3. If it's in git history (not just the current tree), see
   `docs/security/public-history-remediation.md` for the remediation
   process already documented for a known prior case.

## What must never be in this repository

- `clients/` — real canonical client memory (belongs in the private
  workspace, `$V4_BU_WORKSPACE_ROOT`).
- `private/` — raw sources (WhatsApp exports, PDFs, audio, transcripts).
- `context/generated/` — transient skill output.
- `.env`, `*.key`, `*.pem`, or any credential/secret.
- Anything derived from a real client that isn't in `examples/` as
  explicitly, obviously synthetic data.

`scripts/doctor.py` and `tests/security/` check the current tree for all
of the above on every run and in CI. They cannot check git history —
that requires a manual audit (see the remediation doc above for the
methodology used the one time this happened).

## Known prior incident

`clients/walmaq/**` (real client data, including CNPJ/e-mail/legal
representative name) was committed to this repository while it was
public, across 8 commits. The current tree has been cleaned up and the
data migrated to a private workspace, but the git history on
`origin/main` still contains it as of this writing. See
`docs/security/public-history-remediation.md` for full details and the
remediation plan (`REMOTE_HISTORY_PURGE_REQUIRED` — pending human
authorization to force-push a rewritten history).
