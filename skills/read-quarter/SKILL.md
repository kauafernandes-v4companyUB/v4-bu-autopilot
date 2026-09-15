---
name: read-quarter
description: Resolve, validate, and load a client's tactical Quarter plan and optional monitoring without changing canonical memory.
---

# Read Quarter

## Identity

- **Class:** SOURCE
- **Canonical side effects:** NONE
- **Inputs:** required `client_id`; optional `quarter_id` (`YYYY-QN`)
- **Output contract:** `skills/read-quarter/output.schema.json`

## Purpose

Resolve one existing tactical Quarter and return its validated planned and observed
context. This skill reads `plan.json` and, when present, `monitoring.json`; it
does not create any client artifact in this version.

It may calculate only deterministic arithmetic from recorded media values and
the age in days of open flags. It does not diagnose performance, assign
severity, create risks, or infer missing values.

## Boundaries

This skill does **not**:

- diagnose, recommend, or replan;
- create, alter, close, or migrate a Quarter;
- change `plan.json`, `monitoring.json`, flags, tasks, evidence, or canonical
  memory;
- prepare a ROPRE check-in or create tasks;
- query or integrate with eKyte;
- treat absent monitoring or absent `actual_spend` as zero.

## Allowed sources

Read only the selected client's canonical tactical files:

```text
clients/<client_id>/quarters/<quarter_id>/plan.json
clients/<client_id>/quarters/<quarter_id>/monitoring.json  # optional
```

Validate them respectively against:

```text
schemas/quarter-plan.schema.json
schemas/quarter-monitoring.schema.json
```

`plan.json` is the source of planned values. `monitoring.json` is the source
of observed/realized values. A missing monitoring file means observation is
not yet available; it never means that realized spend is zero.

## Quarter resolution

1. When `quarter_id` is supplied, use that exact identifier. Do not substitute
   a newer or similarly named Quarter.
2. Otherwise inspect existing Quarter plans whose validated `status` is
   `active`.
3. If exactly one is active, resolve it by `active_status`.
4. If none is active, obtain the real system date, calculate its `YYYY-QN`, and
   use that exact Quarter only if it exists. Resolution method is `system_date`.
5. If more than one validated plan is active, return `error` with method
   `unresolved` and an ambiguity record. Never select one silently.
6. If the calculated current Quarter does not exist, return `error` with
   `missing_data`; never create it.

The system clock is the only clock allowed for step 4 and for flag age. Do not
use a conversation date, source date, or an example date as the current date.

An invalid selected plan is an `error`; do not repair or normalize it. During
automatic discovery, an invalid unrelated plan is reported in `warnings` and
cannot qualify as active. A selected monitoring file that is invalid produces
`partial`: the validated plan remains available, but monitoring is returned as
`null` and the validation error is reported.

## Validation and context returned

For a valid plan, return the complete, unchanged object validated against
`quarter-plan.schema.json`; do not project it into a weaker local contract.
For valid monitoring, return the complete, unchanged object validated against
`quarter-monitoring.schema.json`. Validate that its `client_id` and `quarter_id`
match the resolved plan; a mismatch is invalid monitoring.

The complete plan includes at least:

- `quarter_id`, `period`, `status`, `planned_at`;
- `smart_objective`, including a `baseline` of `null` when unknown;
- `planning` and `media_plan`.

The complete monitoring includes at least `updated_at`, `objective_progress`,
`media_monitoring`, and `flags`.

Missing monitoring returns `partial`, `monitoring: null`, and a
`missing_data` entry. It is not a plan-validation error.

## Deterministic media derivations

Match a plan row and monitoring row only by the same `month` and `channel`.
Before deriving, require each `(month, channel)` pair to occur at most once in
the plan and at most once in monitoring. Any duplicate in either source is a
material ambiguity: do not sum, select, or use the last row. Emit `null` for
all derived values for that pair, mark coverage `partial`, add an appropriate
`missing_data` or `warning` entry, and return `partial`.
For one unambiguous pair with an observed `actual_spend`:

```text
remaining_budget   = planned_budget - actual_spend
attainment_percent = actual_spend / planned_budget * 100
variance_value     = actual_spend - planned_budget
```

When `planned_budget` is zero, `attainment_percent` is `null`; no division is
performed. `remaining_budget` and `variance_value` remain arithmetic values if
`actual_spend` is recorded. When no matching actual exists, all actual-based
derivations for that plan row are `null`, not zero. Preserve a valid source
`pacing_percent` if monitoring supplies it; never infer pacing.

`planned_total_by_month`, `planned_total_by_channel`, and
`planned_total_quarter` sum plan rows only when their applicable pairs are
unambiguous. A total affected by a duplicate is `null`, never a silent sum.
Actual totals, remaining total, and Quarter attainment are emitted only when
every planned month/channel pair has one unambiguous observed actual. Otherwise
those totals are `null` with coverage `partial` (or `not_observed` when no
applicable actual is recorded). This avoids silently treating unknown actuals
as zero. Monitoring rows without a planned counterpart are returned separately
as `unplanned_actuals` and are not included in planned-versus-actual totals.

## Flags

Read flags without changing them, split them into open and resolved lists, and
preserve their provenance fields. For an open flag only, `age_days` may be
calculated as whole elapsed calendar days between `first_seen_at` and the real
system date. It is descriptive only and never a severity or risk assessment.

## Status contract

- `success`: the Quarter resolves, its plan is valid, monitoring is present and
  valid, there is no material ambiguity, and all expected derivations have
  complete coverage (or no planned values require an observed value).
- `partial`: the Quarter resolves and its plan is valid, but monitoring is
  absent or invalid; an expected planned pair has no `actual_spend`; a
  `(month, channel)` pair is duplicated; or another material derivative cannot
  be calculated without inventing data.
- `error`: the Quarter cannot be resolved, more than one plan is active, the
  explicit or current Quarter does not exist, or its selected plan is invalid
  or inaccessible.

Warnings alone do not downgrade `success`; only a material missing or ambiguous
part of the tactical context does. The `validation` tri-state is explicit:
`plan_valid` is `true` for a found valid plan, `false` for a found selected plan
that fails validation, and `null` when no plan was validated. `monitoring_valid`
is `true` when present and valid, `false` when present and invalid, and `null`
when absent or not evaluated because no valid Quarter resolved.

The output includes source-file validation, missing data, and warnings rather
than concealing gaps. A future caller may write a transient
`context/generated/<client_id>/quarter.json`, but this skill definition does
not create one and never changes canonical memory.
