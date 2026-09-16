# V4 BU Autopilot

A versioned operational brain for managing V4's BU clients — not a
traditional web app. It's a set of contracts (JSON schemas), prompts
(skills, executed by Claude/Codex), and tooling (Python scripts +
pytest) that turn evidence, context, strategy and results into
higher-quality operational decisions.

## Status

- **Implemented and tested:** `read-bu`, `read-client-context`,
  `read-account-gt`, `read-whatsapp`, `read-bi`, `read-quarter`,
  `promote-client-memory`, `monitor-quarter`, `manage-task-ledger`,
  `prepare-ropre`, `close-ropre`. See `skills/registry.json` — it's the
  single source of truth for `implemented` vs `planned`, not this file.
- **Planned, not implemented:** `diagnose-client`, `calculate-gap`,
  `identify-priorities`, `replan-client`, `audit-plan`,
  `generate-tasks`, `publish-ekyte` — see `operation/replanning-rules.md`
  and `docs/workflows/replan-client.md`.
- One real end-to-end flow validated against a real client (Meta Ads
  spend → evidence → Quarter monitoring), now migrated out of this repo
  into a private workspace — see `docs/security-model.md`.

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

## Preview / apply

Every ACTION skill defaults to `preview` (read, validate, compute a
`preview_hash`, write nothing) and only `apply`s on explicit request,
re-validating everything against the approved hash before writing
atomically. See any ACTION skill's `SKILL.md` section 5 for the exact
mechanics.

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
schemas/                — shared JSON Schema contracts
operation/               — consolidated cross-skill policy (evidence, Quarter, ROPRE, tasks, replanning)
docs/                    — security model, workflows, project orchestration
scripts/                 — workspace resolver, bootstrap_client, doctor, reference logic (scripts/lib/)
tests/                   — contracts, skills, integration, security
templates/client/        — schema-valid empty client skeleton
examples/demo-client/    — synthetic client fixture (acme-demo)
.github/workflows/       — CI (tests + doctor + gitleaks)
```

## Roadmap

Next phase: `diagnose-client` → `calculate-gap` → `identify-priorities`
→ `replan-client` → `audit-plan` → `generate-tasks` — see
`operation/replanning-rules.md`. Not started in this hardening pass by
design (CLAUDE.md section 6 — these require real judgment calls, not a
diagram to fill in quickly).
