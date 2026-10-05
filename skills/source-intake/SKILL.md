---
name: source-intake
description: Discover new or revised private source files idempotently.
---

# Source intake

- **Class:** SOURCE
- **Version:** 1.0.0
- **Canonical side effects:** NONE

Reads only `private/clients/<client_id>/`, detects WhatsApp, Account x GT,
client-context and BI PDF/CSV sources by conservative file classification, and
previews a hashed source manifest: `NEW_SOURCE`, `NO_CHANGE`, `NEW_REVISION`
(same stable `source_id`, next revision) or `MISSING` (reported only, nothing
deleted). Raw data is never copied to canonical memory. Persisting the manifest
is the separate, approval-gated `manage-source-manifest` ACTION
(`scripts/lib/source_manifest.py`).
