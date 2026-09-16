# Quarter rules

Consolidated from CLAUDE.md section 27 and
`skills/monitor-quarter/SKILL.md`. Read the SKILL.md for the full
contract (hashing, preview/apply, flags) — this is the summary that
keeps other docs/skills from re-stating it.

## Quarter is the planning unit

`YYYY-QN` (e.g. `2026-Q3`). Every Quarter requires a fresh replanning;
the SMART objective is versioned per Quarter and never silently carried
over from a previous one.

## `plan.json` vs `monitoring.json` — never the same file, never mixed

- `clients/<client_id>/quarters/<quarter_id>/plan.json` — what was
  **planned**. SMART objective, target, baseline, `media_plan`
  (`planned_budget` per month/channel), strategic priorities,
  assumptions. Immutable/read-only to `monitor-quarter` — it never
  writes here.
- `clients/<client_id>/quarters/<quarter_id>/monitoring.json` — what was
  **observed**. `objective_progress`, `media_monitoring` (actuals),
  `flags`. Never redefines the plan.

An observation that contradicts the plan produces an observation or a
sustained flag — never a silent correction of the plan.

## `upsert_media_actual` — key uniqueness, never sum, never guess

Key = `(month, channel)`. Zero existing records for the key -> create.
Exactly one -> update in place. More than one existing (an already
-corrupt state) -> conflict, nothing is chosen or summed. The identical
operation replayed is a no-op (idempotent), never a duplicate.

Formulas (`scripts/lib/media_monitoring.py` is the pinned reference
implementation, tested against the real Walmaq September 2026 numbers):

```
attainment_percent = actual_spend / planned_budget * 100   (null if planned_budget is 0 or null)
variance_value     = actual_spend - planned_budget          (null only if planned_budget is null)
```

An actual for a `(month, channel)` not present in `plan.json` is kept
(never dropped), with `planned_budget`/`attainment_percent`/
`variance_value` as `null`, plus an `unplanned_media_actual` warning —
never promoted into the plan.

## Evidence resolution — canonical by default, overlay only in preview

Every material operation requires non-empty `evidence_ids` that resolve
in `clients/<client_id>/evidence.json`. In `mode: apply`, that's the
*only* source — always, no exception.

In `mode: preview` only, an optional `evidence_overlay` (evidence
proposed by an upstream ACTION's own preview, not yet written to the
canonical ledger) may resolve an otherwise-unresolved `evidence_id` —
see `monitor-quarter/SKILL.md` section 5.1 for the full rule set
(exact-ID match, `client_id` match, schema + canonical-shape validation,
canonical always wins on conflict, never silent). This exists to close
the `ATOMIC_PREVIEW_GAP` between an ACTION preview and a downstream
preview that depends on it — it never grants `apply` authority.

## Never invented here

`pacing_percent` (only when explicitly sustained), `on_track` /
`at_risk` / `off_track` / `achieved` classification (needs explicit
sustaining evidence), and `target_value` (always exactly the plan's
SMART target — never redefined by a monitoring operation).

## Preview -> apply safety

Every apply requires the matching, previously-approved `preview_hash`.
Apply rereads plan/monitoring/evidence and recomputes the base state
hash; any drift since the preview is `conflict`/`stale_preview`, zero
writes. A batch with any invalid operation aborts entirely — no partial
canonical mutation. Only `updated_at` is replaced by the real clock at
apply time; every other field matches the approved plan exactly.
