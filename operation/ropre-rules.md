# ROPRE rules

Consolidated from CLAUDE.md section 27 and
`skills/prepare-ropre/SKILL.md` + `skills/close-ropre/SKILL.md`. Read
those for the full contract (hashing, recovery semantics, relational
validation) — this is the cross-cutting summary.

## What ROPRE means

**R**esultados, **O**bjetivos, **P**remissas, **R**iscos, **P**róximos
Passos, and **V**isão de Longo Prazo (Results, Objectives, Premises,
Risks, Next Steps, Long-Term View). One check-in per cycle, scoped to
one client + one Quarter.

## Split: prepare (INTELLIGENCE, read-only) vs close (ACTION, writes)

- `prepare-ropre` assembles a read-only, evidence-traceable draft. It
  changes nothing canonical — its output is a transient artifact
  (`context/generated/<client_id>/ropre-draft.json`), never memory.
- `close-ropre` is the only skill that writes
  `quarters/<quarter_id>/check-ins/current.json` and
  `history/<check_in_id>.json`. It persists an already-approved draft —
  it never invents, corrects, or reinterprets content.

## State machine — only forward, only these transitions

```
absent -> draft -> ready -> completed
```

Any reverse or skipped transition (`draft -> completed`,
`ready -> draft`, `completed -> ready`/`draft`) is a conflict/error and
never writes. The identical target state replayed is a no-op
(idempotent) — never a duplicate write.

## First ROPRE requires a real `scheduled_for` — never invented

`current.json` legitimately does not exist yet for a client/Quarter that
has had no real draft/meeting. **This absence is valid and intentional**
— it is not a bug, not something to "fix" by fabricating a check-in.
`scheduled_for` is a required, non-null field of every check-in
(`schemas/check-in-ropre.schema.json`) — it must come from a real
scheduled meeting, never a plausible-looking guess. If there's no real
meeting yet, there's no check-in yet. This is the
`FIRST_ROPRE_SCHEDULE_REQUIRED` gap referenced elsewhere in the
project's operational reports — it's a legitimate open item, not
something a skill resolves on its own.

## History is immutable and never deleted

On completion, the completed object is written unchanged to
`history/<check_in_id>.json`, filename derived only from `check_in_id`.
An equivalent history entry replayed is idempotent; divergent content
under the same ID is a collision, never silently overwritten.
`current.json` is never deleted in this version — after completion it
still holds the completed object; history is the durable longitudinal
copy.

## Next steps -> tasks, only when material

A material next step in a completed check-in can generate a task
(`manage-task-ledger`, origin type `check_in`), but this is never
automatic just because a next step exists in a draft — see
`operation/task-rules.md`.

## Operating loop connection — ROPRE reads, never duplicates, the task ledger

`replan -> approved tasks -> execution -> midweek -> week-close ->
prepare-ropre -> close-ropre` is the full operating loop. ROPRE never
keeps its own copy of task state: `prepare-ropre` reads
`clients/<client_id>/tasks.json` directly (and, when available, the
most recent `week-close` output as a curated summary) to see proposed,
approved, executed and pending tasks — it never re-derives or
duplicates that state inside a check-in. `results`/`next_steps` in the
draft cite `evidence_ids`/`task_ids` exactly as `check-in-ropre.schema.json`
already requires; they do not embed a second copy of the task's fields.
