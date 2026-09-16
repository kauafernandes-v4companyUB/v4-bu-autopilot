---
name: close-ropre
description: Safely preview and apply the canonical draft-to-ready-to-completed lifecycle for one approved ROPRE check-in.
---

# Close ROPRE

## 1. Identity and scope

- **Class:** ACTION
- **Canonical Side Effects:** `ROPRE_CHECK_IN`
- **Version:** 1.0.0
- **Output contract:** `skills/close-ropre/output.schema.json`
- **Only canonical targets:** `quarters/<quarter_id>/check-ins/current.json` and `history/<check_in_id>.json`

This skill persists and closes an already prepared ROPRE. It does not prepare or
correct its content, diagnose, change plan/monitoring/evidence/tasks/Quarter,
create flags or tasks, or call eKyte or other external systems.

## 2. Inputs and validation

Require `client_id`, `quarter_id`, `mode` (`preview` by default or `apply`) and
one strict operation: `save_draft`, `mark_ready`, or `complete_check_in`.
`save_draft` requires `ropre_draft`; prefer a valid prepare-ropre output with
`status: success`, `readiness: ready` and non-null draft, but a direct draft is
allowed after the same full canonical validation. The draft must be `draft` with
`completed_at: null`, correct client/Quarter identity, and is never repaired.

For a direct draft, additionally enforce prepare-ropre's relational invariants:
`task_ids` is exactly the unique non-null set of `next_steps[].task_id`; every
such ID resolves exactly once to the same client; every evidence ID used by a
result, objective, next step, premise or risk is present in draft-level
`evidence_ids`; and every draft-level ID resolves to the same client's ledger.
Failure is error/conflict with zero writes.

Before every operation, validate the explicit Quarter's `plan.json`, current
and relevant history check-ins against canonical schemas; then validate the
same-client evidence ledger and task ledger only for IDs referenced by the
check-in. Every referenced evidence ID must resolve in `evidence.json`; every
non-null task reference must have exactly one task of the same client. Missing,
duplicate or cross-client references return respectively
`unresolved_evidence`, `unresolved_task_reference`,
`ambiguous_task_reference`, or `client_isolation_violation`, with zero writes.
The skill reads, but never alters, any of these dependencies.

Every considered current/history check-in must match input client and Quarter.
A mismatch is `check_in_identity_conflict`, `conflict`, and zero writes.

## 3. State machine

For the same check-in, the only material transitions are `absent → draft`,
`draft → ready`, and `ready → completed`. Identical target state is idempotent:
same draft, ready, or completed produces `no_change`. All reverse/skipped
transitions (including draft → completed, ready → draft, or completed →
ready/draft) conflict or error and never write.

`save_draft` writes only current. With absent current it proposes the approved
draft. Existing same ID and semantically identical content is `no_change`; same
ID but different content is `current_check_in_diverged`; a distinct ID in open
draft/ready is `open_check_in_exists`.

There is one separate current-pointer rotation: completed A in current plus
semantically identical completed `history/A.json`, followed by save_draft for
different ID B, may replace current with draft B. This is
`rotate_closed_current_to_new_draft`, not completed→draft for A. If history A
is absent return `completed_not_historized`; if it diverges return
`history_collision`; if B reuses A's ID return `check_in_id_reuse`. Rotation
never removes or changes history A.

`mark_ready` requires current draft and changes only `status` to `ready`.
`check_in_id`, identity, schedule, results, objectives, premises, risks, next
steps, long-term view, task IDs and evidence IDs remain byte/semantic-content
identical. Ready is a no-op; completed conflicts.

`complete_check_in` requires current ready and changes only `status` to
`completed` and `completed_at`, obtained from the real UTC RFC3339 system clock
at apply time. Preview may show a logical proposal but its timestamp is not
final. Re-completing preserves the original completed_at and is a no-op.

## 4. History and recovery policy

On completion, write the completed object unchanged to deterministic
`history/<check_in_id>.json`; filename derives only from check_in_id. An absent
history entry may be created; an equivalent entry is idempotent; divergent
content is `history_collision` / `check_in_id_collision` and is never replaced.
Check the same ID across current and all relevant history objects: an ID may
represent only one semantic check-in.

`current.json` remains the newly completed object after closure, while history
is the immutable longitudinal copy. It is never deleted in this version.

Completion is a logical two-file transaction, not fictional multi-file ACID.
Validate all objects/collisions first; prepare same-directory temporary files,
fsync files, write immutable history first, then current completed, and fsync
directories when supported. If failure happens after history succeeds but
before current, a later run recognizes equivalent `history: completed` plus
corresponding `current: ready` and safely copies the exact history object,
including its completed_at, into current. It never generates a second completion
time. Any divergent pair conflicts. If current is already completed but matching
history is absent, an explicit complete_check_in may create history by copying
the exact current object without changing current/completed_at; it is recovery,
not no_change. Do not claim success until both logical effects are present.

## 5. Preview, hashes and apply

Preview reads and validates canonical state, calculates before/after, history
effect, mutation plan, `base_state_hash` and `preview_hash`, and writes nothing.
Semantic equality and all hashes use compact sorted-key UTF-8 canonical JSON;
formatting/whitespace alone never makes check-ins different. `base_state_hash`
is SHA-256 of current/null, relevant history identity state, validated Quarter
plan, only referenced evidence records, only referenced task records, and the
approved input draft for save_draft. Apply rereads all of them; any relevant
change is stale_preview.

For complete_check_in, the approval uses deterministic `completion_intent`:
`{check_in_id, target_status: completed, completion_time_policy: apply_clock,
business_content_hash: SHA-256(current ready without completed_at)}`. It does
not bind a preview timestamp. preview_hash contains client, Quarter, operation,
base hash, completion intent where applicable, and proposed history effect.
After stale validation, apply obtains the real UTC clock, makes one completed
instance, and writes that same instance to history and current. Recovery uses
`completion_time_policy: existing_history`.

Apply requires explicit approval and the matching preview hash. Reread current,
history and every hash dependency, recompute hashes and validate all dependencies; any relevant
change is `conflict/stale_preview`, zero writes. Validate every final object
before atomic replacement. Apply is only `success`, `no_change`, `conflict` or
`error`; `partial` is preview-only and never authorizes partial application.

## 6. Output and quality

`before_current`, `after_current`, `history_before` and `history_after` are
null or complete canonical check-ins through external references. Output is
transient only. Report sources, validation, conflicts, gaps, warnings and every
planned or applied effect. Use real UTC timestamps for execution-generated
fields and never commit or push.

Test in memory using Draft 2020-12 and `referencing.Registry`, cases A-AN:
save/ready/complete transitions and no-ops/conflicts; real completion time;
history creation/collision; identity, evidence, task and plan validation;
stale state; full-content preservation; no unrelated canonical mutation;
recovery with matching/divergent history; apply-partial rejection; canonical
refs; output schema validity; integration cases AO-BJ: logical current/history
dedupe, real ambiguity/collision, pointer rotation, completion intent, recovery
timestamp, missing-history repair, dependency stale checks, direct-draft
relational validation, semantic equality, and non-ACID recovery semantics.
