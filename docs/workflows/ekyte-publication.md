# eKyte publication — capability audit and workflow

Audited: 2026-09-16T13:31:19Z, against the engine repo and the private
workspace (`~/Documentos/Trabalho/v4-bu-workspace-private`, read-only,
nothing copied out).

## What was searched

`grep -ril "ekyte"` across the entire workspace (excluding binary media)
and across the engine's `.md`/`.json` files.

## What was found

Every hit is a **conceptual mention** of eKyte as an external system
name — never a URL, API shape, token, webhook, connector config, or
example request:

- `schemas/task-ledger.schema.json` — a nullable `ekyte_url` field on
  each task (a human pastes a URL after manually creating the task in
  eKyte's web UI).
- `skills/manage-task-ledger/SKILL.md` — the `link_ekyte` operation,
  explicitly documented as *not* calling any eKyte API: "não requer
  eKyte para operar e performa nenhuma chamada de API eKyte, publicação,
  atualização remota ou interpretação de status remoto."
- `context/generated/walmaq/client-context.json` (workspace) — eKyte
  named twice as "a fonte mais recente a confrontar" for freshness,
  alongside check-ins and `decisions.json`. No integration detail.
- `README.md`, `CLAUDE.md`, `operation/*.md`, `docs/workflows/*.md` —
  all conceptual/architectural mentions from earlier hardening passes,
  consistent with the above.

**Conclusion: no API, connector, webhook, MCP server, or browser-automation
integration for eKyte is documented or configured anywhere accessible
to this engine.** The only real, working integration today is the one
`manage-task-ledger` already implements: a human manually creates the
task in eKyte's web UI and pastes the resulting URL back via
`link_ekyte`.

## Capability classification

| Capability | Available today? |
|---|---|
| `API` | No — no documented endpoint, no token, no request shape found. |
| `CONNECTOR` | No — no MCP server or SDK connector configured. |
| `BROWSER_AUTOMATION` | No — not implemented; would be a legitimate future path if eKyte's web UI is stable enough to automate reliably, but nothing here builds it speculatively. |
| `MANUAL_EXPORT` | **Yes** — already exists via `manage-task-ledger link_ekyte`; this is what `scripts/lib/ekyte_transport.py::discover_ekyte_capability()` returns by default. |
| `NONE` | Fallback if even manual linking isn't desired for a given run. |

`discover_ekyte_capability()` only ever returns `API` if
`V4_BU_EKYTE_API_URL` and `V4_BU_EKYTE_API_TOKEN` are actually set in
the environment — which they are not today, anywhere in this setup.
Nothing in this codebase invents a URL or token to make that condition
true artificially.

## What was built anyway (`skills/publish-ekyte/`)

Given no real transport, the mission was to make the MVP **not fail
entirely** just because eKyte lacks programmatic access, while never
pretending publication happened. The result:

- `scripts/lib/ekyte_transport.py` — the `EkyteTransport` interface a
  real transport would need to satisfy (`create_task`, `fetch_task`,
  `update_task`), plus `FakeEkyteTransport` (in-memory, deterministic,
  used by tests and by anyone who wants to dry-run the full mechanical
  path without touching anything real).
- `skills/publish-ekyte/` — always supports `preview` (payload mapping,
  blockers, approval status, zero external effect). `apply`:
  - with an explicit `transport` (e.g. `FakeEkyteTransport` in tests):
    creates the remote task for real (in that fake store), returns a
    `link_ekyte_operation` for the orchestrator to apply via
    `manage-task-ledger` — `publish-ekyte` itself never writes
    `tasks.json`.
  - with no transport (the real, current situation): produces a
    complete, correct **manual export packet** — `publication_mode:
    "manual_export"` — and is explicit that `status: success` here
    means "the packet is ready", never "eKyte has the task".
- Idempotency: a task with an existing `external` binding is `no_change`
  on republish, never a duplicate — checked before any transport call.
- `schemas/task-ledger.schema.json` gained an optional, additive
  `external` object (`system`, `external_id`, `url`, `published_at`,
  `last_verified_at`) alongside the pre-existing `ekyte_url` — fully
  backward compatible (existing tasks without it remain valid).

## Honest final status: `IMPLEMENTED_DRY_RUN`

Contract, payload mapping, approval gating, idempotency, and the
manual-export path are all real and tested (`FakeEkyteTransport` +
`tests/operating_loop/`). Real programmatic publication is blocked only
by the absence of a documented eKyte API/connector — the moment one
exists, implementing `RealEkyteTransport` against the already-defined
`EkyteTransport` interface is the only remaining work, with no change
needed to `publish-ekyte`'s contract, the approval model, or
idempotency logic.

## What would unblock `IMPLEMENTED_REAL`

1. A documented eKyte API (auth model, task-creation endpoint, response
   shape) or an official connector/MCP server, **or** a deliberate
   decision to build and maintain browser automation against eKyte's
   web UI.
2. Credentials provisioned via environment variables
   (`V4_BU_EKYTE_API_URL`, `V4_BU_EKYTE_API_TOKEN`) or an equivalent
   secret-management path — never hardcoded, never committed.
3. A `RealEkyteTransport(EkyteTransport)` implementation, tested the
   same way `FakeEkyteTransport` already is.

Until then, `MANUAL_EXPORT` (already fully supported) remains the real
operational path.
