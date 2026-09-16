# Contributing

## Setup

```bash
make venv
cp .env.example .env   # optional — only needed for real workspace operations
```

## Before opening a PR

```bash
make check   # py_compile + pytest + doctor (engine-only mode)
```

All three must pass. `make check` never touches a private workspace —
it validates only the engine repo and `examples/demo-client/`.

## Rules that apply to every contribution

- Never commit real client data. If you're testing something that needs
  client-shaped data, use `examples/demo-client/acme-demo/` or generate
  your own synthetic fixture — never anonymize/lightly-modify real data
  (see `docs/security-model.md`).
- Never weaken preview/apply safety, provenance requirements, or
  evidence_id determinism in a skill without updating its `SKILL.md` and
  the corresponding tests in the same change.
- A skill directory isn't "real" until it's registered in
  `skills/registry.json` with `implemented: true` — see
  `tests/skills/test_registry_consistency.py`.
- Execution timestamps in real skill output come from the system clock,
  never estimated (CLAUDE.md section 26). Fixtures under
  `examples/`/`tests/fixtures/` are the one exception — they're static
  and should say so.
- If you touch `schemas/evidence.schema.json` or
  `schemas/client-evidence.schema.json`, run
  `pytest tests/contracts/test_evidence_drift.py` — it's the explicit
  drift guard between the two.

## Adding a new skill

1. Copy `skills/_template/`.
2. Fill in every required section of `SKILL.md` (category, version, side
   effects, inputs, preview/apply semantics if applicable).
3. Add `skills/<id>/output.schema.json`.
4. Add an entry to `skills/registry.json` (`implemented: true` only once
   the above two exist and are wired up — `planned: true` before that).
5. Add tests under `tests/skills/` for anything with real logic (ID
   generation, arithmetic, resolution rules) — not just schema shape.

## Adding a new client-facing script

Anything that touches real client data must go through
`scripts/lib/workspace.py` — never hardcode a path into `clients/`,
`private/`, or `context/generated/` relative to the repo root outside of
`examples/`/`tests/fixtures/`.
