"""Small deterministic router for the Account Manager's known commands.

It intentionally does not execute workflows or attempt general NLP.  Callers
must supply a resolved client id (or let their runtime resolve a client name)
before any workspace reads happen.
"""
from __future__ import annotations

import re

_ROUTES = (
    ("post_call", "process-client-call", (r"acabei de sair", r"processa(r)? (isso|a call|call)"), True, True),
    ("pre_call", "prepare-client-call", (r"prepara.*call", r"prepara.*tocar"), False, False),
    ("daily_brief", "operator-brief", (r"o que eu preciso fazer hoje", r"o que tenho que cobrar", r"brief"), False, False),
    ("what_changed", "what-changed", (r"o que mudou",), False, False),
    ("midweek", "midweek", (r"midweek",), False, False),
    ("week_close", "week-close", (r"feche a semana", r"fechamento semanal"), False, False),
    ("prepare_ropre", "prepare-ropre", (r"prepare o ropre", r"rascunho de check-in"), False, False),
    ("replan", "replan-client", (r"replaneje", r"replan"), False, False),
    ("show_pending_decisions", "operator-brief", (r"decisões.*esperando", r"decisoes.*esperando"), False, False),
    ("show_overdue", "operator-brief", (r"atrasad", r"overdue"), False, False),
    ("source_intake", "source-intake", (r"processe as novas fontes", r"novas fontes"), False, False),
    ("external_action_review", "external-action-review", (r"ação externa", r"acao externa", r"ekyte"), False, True),
)

_CONTEXT = {
    "daily_brief": ["tasks", "operations", "quarter", "monitoring", "evidence"],
    "pre_call": ["tasks", "operations", "quarter", "monitoring", "evidence"],
    "post_call": ["call_notes", "canonical_evidence", "tasks", "operations"],
    "what_changed": ["canonical_state", "evidence", "tasks", "operations", "monitoring"],
}

def route_command(command: str, client_id: str | None = None) -> dict:
    normalized = " ".join(command.casefold().split())
    for intent, workflow, patterns, mutation, approval in _ROUTES:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return {"intent": intent, "client_id": client_id,
                    "required_context": _CONTEXT.get(intent, ["client_id"]), "workflow": workflow,
                    "mutation_allowed": mutation, "approval_required": approval}
    raise ValueError("unknown operator command; use one of the registered operational intents")
