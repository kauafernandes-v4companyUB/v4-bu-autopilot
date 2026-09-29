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
previews a hashed source manifest. Exact replay is `no_change`; changed bytes are
a new revision. Raw data is never copied to canonical memory. Manifest apply is
a separate explicit memory action.
