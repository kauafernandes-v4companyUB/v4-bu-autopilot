# eKyte capability discovery

Audit date: 2026-09-16.

No documented eKyte API, connector, MCP server, credentialed transport, or
safe browser-automation contract is present in this engine. The only available
path is a manual export packet for an operator to use in eKyte's UI. That is
not external execution and does not create an execution receipt.

`publish-ekyte` therefore remains **IMPLEMENTED_DRY_RUN**. A real integration
may be added only after its actual API/connector documentation, transport
compatibility and authorization requirements are available. No browser
selectors are inferred or automated.
