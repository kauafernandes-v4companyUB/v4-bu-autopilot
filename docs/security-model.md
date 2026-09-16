# Security model — public engine, private workspace

## The split

```
v4-bu-autopilot            (this repo — PUBLIC)
  skills/, schemas/, scripts/, tests/, docs/, operation/,
  examples/, templates/, .github/

v4-bu-workspace-private     (separate repo — PRIVATE, local, no remote)
  clients/     — canonical client memory, versioned
  private/     — raw sources (WhatsApp, PDFs, audio, transcripts), ignored
  context/generated/ — transient skill output, ignored
  outputs/     — operational outputs, ignored by default
```

The engine is generic: contracts, prompts, schemas and tooling that work
the same way for any client. It's safe to be public because it contains
no client-identifying information by construction — every path that
could is either absent from the repo or gitignored (see below), and
`examples/demo-client/acme-demo/` demonstrates the exact same shapes
with 100% synthetic data instead.

The workspace is where real operational memory lives: `clients/<id>/`
canonical memory (versioned — we want history/diff of a client's memory
over time), `private/` raw sources (never versioned — see below), and
`context/generated/` transient skill output (never versioned).

## How the engine finds the workspace

`scripts/lib/workspace.py` resolves `$V4_BU_WORKSPACE_ROOT`. There is no
silent fallback to a directory inside the engine repo — if the variable
is unset and a workspace is required, resolution raises loudly. See
`.env.example`.

## Data classification

| Data | Where | Versioned? | Why |
|---|---|---|---|
| Skills, schemas, scripts, tests, docs | engine (public) | yes | generic, safe |
| Synthetic demo client | engine, `examples/demo-client/` | yes | 100% fictional, safe |
| Canonical client memory (`clients/<id>/`) | workspace (private) | yes | real, but we want history |
| Raw sources (`private/`) | workspace (private) | **no** | real, high-sensitivity, no need for git history of binary/raw exports |
| Transient skill output (`context/generated/`) | workspace (private) | **no** | derived, reproducible, not memory |
| Secrets (`.env`, keys) | neither | **no** | never belongs in git at all |

## Provenance and evidence (why this matters for security too)

Every piece of canonical memory that matters is traceable to an
`evidence_id` resolvable in `clients/<client_id>/evidence.json`
(`schemas/client-evidence.schema.json`). This isn't just an audit
feature — it also means a security review of a client's workspace can
answer "where did this fact come from" without needing the original raw
file (which may be large, binary, and doesn't need to be re-read to
verify what was promoted from it).

## What CI checks (and what it cannot check)

`scripts/doctor.py`, `tests/security/`, and `.github/workflows/ci.yml`
check the **current tree** on every push/PR: no `clients/`, `private/`,
`context/generated/`, `.env`, `*.key`/`*.pem` tracked; a `gitleaks` scan
for secret-shaped strings. A secondary CI job runs `gitleaks` in
history-scan mode against the full commit range of the PR (not the
entire repository history — that's a one-time manual audit, see below)
to catch a newly-introduced secret before merge.

What CI **cannot** catch: data that was committed to `main` before this
hardening pass existed. That's a manual, one-time audit — see
`docs/security/public-history-remediation.md` for the methodology and
the one known case found by it.

## Incident response (if real client data ends up in the public repo again)

1. Do not panic-force-push. Confirm exactly what's exposed and since
   when (`git log --diff-filter=A --name-only -- <path>`,
   `git merge-base --is-ancestor <sha> origin/main`).
2. Make sure the canonical copy is safe in the private workspace before
   touching the public repo at all.
3. Remove from the current tree and commit that removal — stops new
   clones from getting it.
4. Follow `docs/security/public-history-remediation.md`'s pattern:
   backup mirror, `git-filter-repo --path <path> --invert-paths` on a
   fresh clone, verify, then — only with explicit human authorization —
   `git push --force`.
5. Consider GitHub Support for cache/index purge on sensitive data
   (CNPJ, PII, credentials).

## Explicitly out of scope for this model

CRM integration is not required for v1 — BI is sufficient for external
performance data (CLAUDE.md/this doc). This has no bearing on the
security boundary above; CRM, if added later, would be just another
SOURCE skill reading from `private/`/external APIs into evidence, same
rules apply.
