# Evidence & authority policy

Consolidated from CLAUDE.md sections 5-9 and 26, and
`skills/promote-client-memory/SKILL.md`. This file doesn't introduce new
rules — it's the one place to read them without opening ten SKILL.md
files. If this doc and a SKILL.md ever disagree, the SKILL.md wins for
that skill's own behavior; update this doc to match.

## Semantic types (never auto-converted)

`FACT`, `METRIC`, `DECISION`, `HYPOTHESIS`, `REQUEST`, `COMMITMENT`,
`PENDING`, `RISK`, `IDEA`, `DEPENDENCY`.

Promotion to canonical memory never elevates the type: a `risk` stays a
`risk`, a `hypothesis` never becomes a `fact`, a `request` never becomes
a `commitment`. The destination category (e.g. `operation_context` in
`knowledge.json`) describes *where* a fact fits, not how certain it is —
`confidence` and the semantic type are the only sources of truth for
certainty.

## Confidence

`low` / `medium` / `high`. A promotion never raises confidence. `low`
normally isn't promoted as canonical fact. `medium` needs real, concrete
future utility plus absence of a cheaper/better upcoming confirmation
before being promoted as stable — prefer `skip` when a better source is
about to confirm the same thing anyway.

## Non-invention (CLAUDE.md section 6)

Never invent metrics, targets, dates, deadlines, owners, decisions,
campaigns, budgets, results, scope, client requests, completed tasks, or
commercial information. Use `unknown`/`null`/`not_found`/`not_available`,
or say explicitly that the information is missing. Never fill a gap
silently.

## Evidence object (`schemas/evidence.schema.json`)

Required: `evidence_id`, `client_id`, `source_type`, `observed_at`,
`type`, `statement`, `confidence`, `reference.label`. `source_date` is a
*different concept* from `observed_at` — see below.

## `observed_at` vs `source_date` (CLAUDE.md section 26.3)

- `observed_at` = when the system read/observed the evidence — an
  execution timestamp, from the real system clock, never inferred from
  the source's content.
- `source_date` = a date the source itself explicitly states (e.g. a
  document's issue date). `null` when the source doesn't declare one —
  never filled with the execution date.

## Execution timestamps (CLAUDE.md section 26)

Every timestamp a skill generates during its own execution
(`generated_at`, `observed_at`, `promoted_at`, `historized_at`,
`applied_at`, `updated_at`, a freshly-created `created_at`) comes from
the real system clock at the moment of execution — never estimated,
rounded, copied from an example, or inferred from the conversation. A
timestamp materially in the future relative to the real clock is a
validation failure, reflected in `warnings`/`status`, never accepted
silently.

## Deterministic `evidence_id` for promoted external observations

Reference implementation: `scripts/lib/evidence_id.py`
(`compute_evidence_id`). Identity = SHA-256 of canonical JSON
(`client_id`, `source_skill`, `source_type`, `source_observation_id`,
`source_file_sha256`), first 16 hex chars, prefixed `evobs-`. Never a
timestamp, a computed value, or discovery order. Same inputs → same ID,
always — this is what makes re-running a SOURCE skill and re-promoting
idempotent instead of duplicating evidence.

## Canonical ledger (`clients/<client_id>/evidence.json`)

The durable proof of everything in `knowledge.json`, `strategy.md`,
`current-state.json`, `decisions.json`, `history/`. `context/generated/`
is never a substitute — it's ignored by git and may not exist in a clean
clone. See `scripts/lib/evidence_projection.py` for the universal ->
canonical mapping, and `tests/contracts/test_evidence_drift.py` for the
guard that keeps `schemas/evidence.schema.json` and
`schemas/client-evidence.schema.json` from silently drifting apart
(mission "schema drift" hardening item).

## Conflict, never silent

Two sources disagreeing is never resolved by picking one silently.
Record the conflict; weigh type + authority + recency + context
(CLAUDE.md section 9) before any human or skill decides.

## Authority hierarchy by domain (CLAUDE.md section 9)

- **Metrics:** BI / CRM / media platforms / analytics / structured
  sources first.
- **Execution:** eKyte / current operational systems / recent internal
  decisions first.
- **Strategy:** current strategy / technical direction / later explicit
  decisions first.
- **Client's voice:** explicit decisions / check-ins / approvals /
  disapprovals / recent relevant messages first.

Recency alone never overrides authority; a later, explicit decision can
override a previously documented strategy — the reverse is never assumed
automatically.
