# Storage contract (V1)

Executable form: `scripts/lib/storage_contract.py` (used by `scripts/doctor.py`,
`promote-client-memory` and the tests). Workspace root always comes from
`V4_BU_WORKSPACE_ROOT` or an explicit `--workspace` argument.

| Class | Location | Rule |
|---|---|---|
| RAW | `private/clients/<client_id>/` | Source files as received. Never canonical by existing; never in the public engine; ignored by git in the workspace (curated exceptions are an explicit workspace decision). |
| CANONICAL | `clients/<client_id>/` | Durable memory. Only `.json`/`.md` (+ `.gitkeep`). Every JSON file has a schema; only ACTIONs with an approved preview write here. |
| TRANSIENT | `context/generated/<client_id>/` | Skill outputs, previews, intermediate artifacts. Must be deletable at any time with **no durable state loss**. |
| RECEIPT | `clients/<client_id>/receipts/` | One `schemas/action-receipt.schema.json` record per material ACTION apply, written in the same atomic write. |

## Canonical files

REQUIRED_AT_BOOTSTRAP (written by `scripts/bootstrap_client.py`, schema-valid,
no invented content): `client.json`, `sources.json`, `knowledge.json`,
`evidence.json`, `current-state.json`, `decisions.json`, `tasks.json`,
`strategy.md`, `history/`, `quarters/`.

CREATED_LAZILY (absence is a valid state; the owning ACTION creates it):

| File | Created by |
|---|---|
| `operations.json` | `manage-operations-ledger` |
| `source-manifest.json` | `manage-source-manifest` |
| `receipts/` | first canonical ACTION apply |
| `quarters/<quarter_id>/plan.json` | `manage-quarter` create_quarter |
| `quarters/<quarter_id>/monitoring.json` | `monitor-quarter` |
| `quarters/<quarter_id>/check-ins/current.json` | `close-ropre` |
| `quarters/<quarter_id>/closure.json` | `manage-quarter` close_quarter |
| `sheet-contracts/<module>.json` | operator configuration of a Sheets business module (`schemas/sheet-module-contract.schema.json`) |

Schemas: `client.schema.json`, `client-sources.schema.json`,
`client-knowledge.schema.json`, `client-evidence.schema.json`,
`current-state.schema.json`, `client-decisions.schema.json`,
`task-ledger.schema.json`, `operations-ledger.schema.json`,
`source-manifest.schema.json`, `quarter-plan.schema.json`,
`quarter-monitoring.schema.json`, `check-in-ropre.schema.json`,
`quarter-closure.schema.json`.

A directory under `clients/` that only holds `.workspace-placeholder` is a
reserved name, not a client: doctor skips it until it is bootstrapped.

## Doctor guarantees

`scripts/doctor.py --workspace <root>` fails on: incomplete client, invalid
canonical JSON/schema, raw files inside `clients/` ("Raw isolation"), Quarter
path/id mismatch, closed plan without `closure.json`, more than one active
Quarter, broken source manifest, receipts that are invalid or point to a
missing canonical file, and registry/route inconsistencies. A freshly
bootstrapped client with no Quarter is valid.
