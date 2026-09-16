# Workflow: onboarding a new client

Implemented tooling: `scripts/bootstrap_client.py` +
`templates/client/`. Everything after step 1 is `planned` (see
`skills/registry.json`) — this doc says so explicitly rather than
implying a fuller pipeline exists.

```mermaid
flowchart LR
    A["operator decides to onboard <id>"] -->|scripts/bootstrap_client.py\n<id> --workspace $V4_BU_WORKSPACE_ROOT| B["clients/<id>/\nclient.json, current-state.json,\ndecisions.json, evidence.json,\nknowledge.json, sources.json,\nstrategy.md, tasks.json,\nhistory/, quarters/\n(schema-valid, all unknown/null/empty)"]
    B -->|read-bu / read-client-context /\nread-account-gt / read-whatsapp / read-bi\nSOURCE skills, as sources become available| C["context/generated/<id>/*.json"]
    C -->|promote-client-memory\nACTION, preview then apply| D["canonical memory populated\n(knowledge.json, strategy.md,\ncurrent-state.json, decisions.json,\nevidence.json)"]
    D -.->|not implemented yet — planned| E["diagnose-client -> ... -> replan-client\n-> generate-tasks\n(docs/workflows/replan-client.md)"]
```

## Step 1 — scaffold (implemented)

```bash
python scripts/bootstrap_client.py acme --workspace "$V4_BU_WORKSPACE_ROOT"
```

Every generated file comes verbatim from `templates/client/`
(schema-valid, `unknown`/`null`/`[]`/`{}` only — see CLAUDE.md section 6,
never invented commercial data). Re-running with `--force` only fills in
files that are missing or byte-identical to the template; anything a
human or a previous promotion already customized is left untouched — see
`scripts/bootstrap_client.py`'s docstring and
`tests/skills/` for the protection test.

## Step 2 — feed sources (implemented, per-source)

Run whichever SOURCE skills apply to this client
(`read-bu`, `read-client-context`, `read-account-gt`, `read-whatsapp`,
`read-bi`) as sources become available. Each is read-only — no canonical
memory changes yet.

## Step 3 — promote (implemented)

`promote-client-memory` in `preview` first, `apply` only on explicit
request, per candidate — see `operation/evidence-authority.md`.

## Step 4 — everything downstream of diagnosis (planned)

`diagnose-client`, `calculate-gap`, `identify-priorities`,
`replan-client`, `audit-plan`, `generate-tasks` are not implemented yet
— see `operation/replanning-rules.md` and
`docs/workflows/replan-client.md` for the intended shape once they land.
