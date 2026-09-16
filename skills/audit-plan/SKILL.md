---
name: audit-plan
description: Try to break the replanning before generate-tasks ever sees it — unsupported claims, invented deadlines, semantic elevation, and more.
---

# Audit Plan

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/audit-plan/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Audit".

## 2. Objetivo

Auditar adversarialmente a proposta de replanejamento e toda a cadeia que a sustenta, antes que qualquer tarefa seja gerada a partir dela.

## 3. Quando usar

Depois de `replan-client`, sempre antes de `generate-tasks`.

## 4. Quando NÃO usar

- sem uma `replanning.json` completa;
- para corrigir o plano silenciosamente — auditoria relata problemas, não os conserta.

## 5. Inputs

`replanning` (e, transitivamente, `context_pack`/`diagnosis`/`gaps`/`priorities` para verificar as citações).

## 6. Procedimento

1. Ler `replanning.json` e toda a cadeia upstream.
2. Para cada `workstream`/`action`, verificar cada código da seção 7.
3. Registrar um `issue` por problema encontrado, com `severity`, `code`, `related_ids` e `required_fix` (o que precisaria mudar para o issue deixar de existir).
4. Derivar `audit_status` (seção 8) — nunca declarado independentemente dos `issues`.

## 7. Códigos de auditoria (o que procurar)

`unsupported_claim` (afirmação sem evidence_ids resolvíveis), `missing_evidence`, `contradiction` (entre actions, ou contra uma decisão canônica em `decisions.json`), `duplicate_action`, `action_without_reason`, `action_unrelated_to_smart`, `invented_deadline` (deadline_requirement inconsistente com deadline_source), `invented_responsible` (qualquer campo de responsável — nunca deveria existir, `operation/task-rules.md`), `action_requiring_missing_dependency`, `external_action_without_approval` (external_action_required=true sem indicação de que o operador foi/será consultado), `hypothesis_presented_as_fact` (semantic_type divergente do finding/gap de origem), `budget_change_disguised_as_execution`, `task_like_item_without_operational_readiness`, `stale_or_ambiguous_evidence` (evidence_id não resolve mais, ou resolve para algo diferente do citado), `conflicting_client_decision` (contradiz `decisions.json`), `semantic_elevation` (qualquer elevação hypothesis→fact, request→commitment, pending→task em qualquer ponto da cadeia), `other`.

## 8. `audit_status` — regra de derivação

Qualquer `issue` `severity: high` ⇒ `fail`. Só `low`/`medium` ⇒ `pass_with_warnings`. Nenhum issue ⇒ `pass`. `scripts/lib/replanning_lint.py::lint_audit` recalcula essa regra e falha se o `audit_status` declarado divergir.

**Nenhum plano com `audit_status: fail` pode alimentar `generate-tasks`.**

## 9. Regras e proibições

- nunca suprimir um issue encontrado;
- nunca marcar `pass` com issues pendentes;
- nunca reescrever `replanning.json`.

## 10. Idempotência

Mesma `replanning.json` (mesma cadeia de hashes) → mesmo conjunto de issues, mesmo `audit_status`.
