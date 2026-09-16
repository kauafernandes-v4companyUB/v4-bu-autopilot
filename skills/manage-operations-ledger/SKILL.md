---
name: manage-operations-ledger
description: Maintains the private canonical ledger of pending operator decisions without creating tasks or executing external actions.
---

# Manage Operations Ledger

## Identity

- Class: ACTION
- Canonical Side Effects: OPERATIONS_LEDGER
- Version: 1.0.0
- Canonical target: clients/<client_id>/operations.json
- Output contract: skills/manage-operations-ledger/output.schema.json

## Contract

This skill persists only operational state between a proposal and its later,
separately authorised materialization or external execution. It never replaces
`tasks.json`, ROPRE, evidence, or approval receipts. The Operator Inbox is a
transient view rebuilt from this ledger plus current canonical state.

It supports explicit lifecycle transitions only: `scheduled` to `completed`,
`cancelled`, `materialized`, or `superseded`; `deferred` to `active`,
`cancelled`, or `superseded`; and an externally approved operation from
`approved` to `executed`, `revoked`, or `superseded`. Passing time causes no
transition. A materialized operation retains its history and stores only the
task reference; manage-task-ledger remains the task authority.

An external approval records its payload hash. If the intended payload changes,
the approval is stale and is not executable. External execution additionally
requires explicit session authorization and a durable receipt reference.

## Side effects

Preview is read-only. Apply writes only the selected client's
`operations.json` atomically after schema, duplicate-ID, task-reference and
receipt-reference validation. It never invokes a transport, publishes eKyte,
or changes a campaign.
