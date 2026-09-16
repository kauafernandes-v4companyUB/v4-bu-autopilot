# V4 BU Autopilot

A versioned operational brain for managing V4's BU clients — not a
traditional web app. It's a set of contracts (JSON schemas), prompts
(skills, executed by Claude/Codex), and tooling (Python scripts +
pytest) that turn evidence, context, strategy and results into
higher-quality operational decisions.

## Status

- **Implemented and tested:** the full SOURCE → Intelligence →
  operating-loop chain — `read-bu`, `read-client-context`,
  `read-account-gt`, `read-whatsapp`, `read-bi`, `read-quarter`,
  `promote-client-memory`, `monitor-quarter`, `manage-task-ledger`,
  `prepare-ropre`, `close-ropre`; the Intelligence MVP
  (`build-context-pack` → `diagnose-client` → `calculate-gap` →
  `identify-priorities` → `replan-client` → `audit-plan` →
  `generate-tasks`, `docs/workflows/replan-client.md`); and the
  operating loop that closes the cycle (`docs/workflows/operating-loop.md`)
  — an explicit, hash-locked approval model (`schemas/approval.schema.json`),
  a deterministic task-identity bridge into `manage-task-ledger`
  (never duplicates a task across repeated replans), `publish-ekyte`,
  `reconcile-ekyte`, `midweek` and `week-close`. See `skills/registry.json`
  and `workflows/registry.json` — the single sources of truth for
  `implemented`/`partial`/`planned`, not this file.
- **Honest external-capability status:** `publish-ekyte` is
  `IMPLEMENTED_DRY_RUN` — no real eKyte API/connector is documented or
  available anywhere in this setup (full audit:
  `docs/workflows/ekyte-publication.md`), so real publication today is
  a manual-export packet, not a programmatic call. The contract,
  payload mapping, approval gating and idempotency are real and tested
  against `FakeEkyteTransport`.
- Verified end to end: 196 automated tests (schemas, drift guards,
  cross-artifact lint, hash-chain integrity, approval staleness,
  idempotent task/publish replay, security hygiene, synthetic
  integration) all pass; a real BI → evidence → Quarter monitoring flow
  and a real "replaneje walmaq" Intelligence dry run were both
  validated against a real client's workspace (never copied into this
  repo — see `docs/security-model.md`) with
  `scripts/doctor.py --workspace` passing every check and zero
  canonical files changed.

## Architecture

```
Private Sources (private/)
      ↓
SOURCE Skills   — observe, never decide
      ↓
Evidence (evidence.json — deterministic IDs, provenance)
      ↓
Canonical Memory (knowledge.json, strategy.md, current-state.json, decisions.json)
      ↓
INTELLIGENCE Skills   — reason, never write canonical state or call external systems
      ↓
ACTION Skills   — materialize already-validated decisions, preview before apply
      ↓
Quarter Monitoring / Tasks / ROPRE / (eventually) eKyte
```

## Public engine / private workspace

This repository is the **engine**: skills, schemas, scripts, tests,
docs, synthetic examples. It contains **no real client data**, by
construction — see `docs/security-model.md` and `SECURITY.md`.

Real canonical client memory, raw sources, and transient generated
context live in a **separate, private workspace** repository, pointed to
by `V4_BU_WORKSPACE_ROOT`:

```
v4-bu-autopilot              (this repo — public)
  skills/  schemas/  scripts/  tests/  docs/  operation/  examples/

v4-bu-workspace-private        (separate repo — private, local only)
  clients/     — canonical memory, versioned
  private/     — raw sources, gitignored
  context/generated/ — transient skill output, gitignored
```

## Quick start

```bash
git clone <this-repo>
cd v4-bu-autopilot
make venv                 # creates .venv, installs requirements-dev.txt
make doctor                # health check — Workspace: SKIP is expected/fine here
make test                  # full pytest suite, entirely on examples/demo-client (synthetic)
```

### Working with a real client

```bash
cp .env.example .env
# edit .env: V4_BU_WORKSPACE_ROOT=/path/to/your/private/workspace

python scripts/bootstrap_client.py acme --workspace "$V4_BU_WORKSPACE_ROOT"
python scripts/doctor.py --workspace "$V4_BU_WORKSPACE_ROOT"   # now validates real client data too
```

Then invoke skills (via Claude Code / Codex, following each
`skills/<id>/SKILL.md`) against that workspace.

## Skill model

Three categories (CLAUDE.md section 2/11):

- **SOURCE** — observe and normalize a source. Never decide.
- **INTELLIGENCE** — reason (diagnose, calculate gap, prioritize,
  replan, audit). Never write canonical state, never call external
  systems.
- **ACTION** — materialize an already-validated decision. `preview`
  before `apply`, always; `apply` only on explicit request.

`skills/registry.json` is the authority on what's actually implemented.
`skills/_template/` is the contract new skills must follow.

## Evidence model

Every evidence has a semantic type (`fact` / `metric` / `decision` /
`hypothesis` / `request` / `commitment` / `pending` / `risk` / `idea` /
`dependency`) that promotion never elevates, a `confidence`
(`low`/`medium`/`high`), and provenance resolvable in
`clients/<id>/evidence.json`. Promoted observations get a **deterministic
`evidence_id`** (`scripts/lib/evidence_id.py`) — same source data always
produces the same ID, which is what makes re-running a SOURCE skill and
re-promoting idempotent instead of duplicating evidence. Full policy:
`operation/evidence-authority.md`.

## Quarter

`YYYY-QN` is the tactical planning unit. `plan.json` (planned, immutable
to `monitor-quarter`) vs `monitoring.json` (observed, never redefines
the plan). Media actuals are keyed by `(month, channel)`, never
duplicated. `monitor-quarter` supports a preview-only `evidence_overlay`
to evaluate an operation against evidence an upstream ACTION preview
proposed but hasn't written to the canonical ledger yet — `apply` always
requires canonical evidence, no exception. Full policy:
`operation/quarter-rules.md`.

## ROPRE

Resultados, Objetivos, Premissas, Riscos, Próximos Passos, Visão de
Longo Prazo. State machine `absent -> draft -> ready -> completed`,
forward-only. The first check-in for a client/Quarter legitimately
doesn't exist until there's a real scheduled meeting — `scheduled_for`
is never invented. Full policy: `operation/ropre-rules.md`.

## Intelligence pipeline ("replaneje `<cliente>`")

`build-context-pack` → `diagnose-client` → `calculate-gap` →
`identify-priorities` → `replan-client` → `audit-plan` →
`generate-tasks` (ACTION, preview only). Every skill after the first is
read-only and cites `artifact-ref`s (content-hash chain,
`schemas/artifact-ref.schema.json` + `scripts/lib/artifact_hash.py`) to
the exact upstream artifacts it used, so a stale/mismatched chain is
detectable, not silently trusted. `diagnose-client` distinguishes
`observed_issue` / `observation` / `hypothesis` / `missing_data` /
`risk` explicitly — never a numeric health score.
`calculate-gap`/`identify-priorities` never invent an unknown current
value or an arbitrary priority score. `audit-plan`'s `audit_status` is
derived from issue severity, never asserted independently, and blocks
`generate-tasks` on any `fail`. `scripts/run_replanning_checks.py`
validates an on-disk chain's schemas and cross-artifact invariants
(`scripts/lib/replanning_lint.py`) without reasoning about content — the
reasoning is entirely Claude/Codex executing each `SKILL.md`. Full
policy: `operation/replanning-rules.md`; full example:
`examples/demo-client/acme-demo/intelligence/`.

## Preview / apply

Every ACTION skill defaults to `preview` (read, validate, compute a
`preview_hash`, write nothing) and only `apply`s on explicit request,
re-validating everything against the approved hash before writing
atomically. See any ACTION skill's `SKILL.md` section 5 for the exact
mechanics.

## Operating loop

`replanejamento → audit → approval → local task → external action →
reconciliation`. `INTELLIGENCE → EXTERNAL` directly never happens —
every canonical or external mutation passes through an explicit,
hash-locked `approval` first (`schemas/approval.schema.json`), and a
new replanning run stales the previous approval for any changed item.
`workflows/registry.json` is the authority on which natural-language
workflows exist for real. Full picture: `docs/workflows/operating-loop.md`,
`docs/workflows/task-approval.md`, `docs/workflows/ekyte-publication.md`,
`docs/workflows/midweek.md`.

## Security

See `SECURITY.md` and `docs/security-model.md`. In short: `clients/`,
`private/`, `context/generated/`, `.env`, keys/certs are never tracked
in this engine repo — `scripts/doctor.py` and `tests/security/` check
this on every run and in CI. A prior incident (real client data
committed to public git history) is documented and remediated at the
tree level in `docs/security/public-history-remediation.md`
(`REMOTE_HISTORY_PURGE_REQUIRED` pending human authorization for the
history rewrite itself).

## Repo structure

```
CLAUDE.md, AGENTS.md   — operating constitution / agent map
skills/                 — SKILL.md + output.schema.json per skill, registry.json
workflows/               — registry.json: natural-language workflow authority
schemas/                — shared JSON Schema contracts
operation/               — consolidated cross-skill policy (evidence, Quarter, ROPRE, tasks, replanning)
docs/                    — security model, workflows, project orchestration
scripts/                 — workspace resolver, bootstrap_client, doctor, reference logic (scripts/lib/)
tests/                   — contracts, skills, integration, security, intelligence, operating_loop
templates/client/        — schema-valid empty client skeleton
examples/demo-client/    — synthetic client fixture (acme-demo), full intelligence + operating-loop chain
.github/workflows/       — CI (tests + doctor + gitleaks)
```

## Roadmap

The Intelligence MVP and the operating loop (approval, task bridge,
`publish-ekyte`, `reconcile-ekyte`, `midweek`, `week-close`) are
implemented — see `operation/replanning-rules.md`,
`operation/task-rules.md` and `docs/workflows/operating-loop.md`.

Next: a real eKyte transport, if/when a real API, connector, or a
deliberate browser-automation build exists (`docs/workflows/ekyte-publication.md`
lists exactly what would unblock it — nothing is invented ahead of
that). Beyond that, deepening the Intelligence layer itself (CRM/
sales-evidence integration, a real pacing model) as those data sources
and decisions become available — never invented ahead of real evidence
(CLAUDE.md section 6).
