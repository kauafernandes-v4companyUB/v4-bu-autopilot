---
name: generate-tasks
description: Turn approved, audit-passed replanning actions into task proposals compatible with manage-task-ledger — preview only, never writes tasks.json itself.
---

# Generate Tasks

## 1. Identity

- **Class:** ACTION
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE in this MVP — `mode` is always `"preview"`; this skill never calls `manage-task-ledger`'s `apply` and never writes `tasks.json` (`operation/replanning-rules.md`, `operation/task-rules.md`).
- **Output contract:** `skills/generate-tasks/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Task readiness", `operation/task-rules.md`.

## 2. Objetivo

Converter as `actions` de uma `replanning.json` já auditada (`audit_status != fail`) em propostas de operação compatíveis com `manage-task-ledger`, classificadas por prontidão — sem duplicar a responsabilidade de `manage-task-ledger` e sem nunca escrever o ledger diretamente.

## 3. Quando usar

Depois de `audit-plan` retornar `pass` ou `pass_with_warnings` (nunca `fail`).

## 4. Quando NÃO usar

- se `audit-plan` retornou `fail` — parar, não gerar propostas;
- para aplicar de fato uma tarefa — isso é `manage-task-ledger` (`apply`), executado separadamente pelo operador depois de revisar as propostas;
- para converter automaticamente todo `action`/`pending`/`dependency` em tarefa — ver seção 6.

## 5. Inputs

`replanning` + `audit` (ambos validados; `audit.audit_status != "fail"` é pré-condição obrigatória, `error` caso contrário).

## 6. Classificação — nem toda action vira task

Para cada `action` de cada `workstream`:

- `task_candidate` — pode plausivelmente virar tarefa interna (ex.: "analisar campanha").
- `decision_required` — precisa de decisão do operador/cliente antes (ex.: "budget deveria aumentar" é recomendação, não execução).
- `external_action` — requer tocar sistema/parte fora deste repositório (CLAUDE.md seção 20 — aprovação explícita necessária, fora do escopo desta skill).
- `information_request` — depende do cliente fornecer algo (ex.: "cliente precisa definir estoque") — é dependência, não tarefa interna automática.
- `monitoring_item` — algo a observar, não a executar.
- `not_task` — não justifica virar tarefa.

## 7. `readiness` e `due_at` — nunca inventar data

Só `readiness: ready` recebe `manage_task_operation` preenchido, e só quando `due_at` puder ser sustentado por: deadline explícito, compromisso existente, regra operacional explícita, ou decisão do operador (mesmas fontes de `deadline_requirement` em `replan-client`). Caso contrário, `readiness: needs_scheduling` (ou `needs_decision`/`dependency`/`external`/`not_task` conforme a classificação) e `reason_if_blocked` explica o que falta — **nunca inventar uma data para poder preencher `manage_task_operation`.**

Mapeamento obrigatório classificação → readiness permitida (`scripts/lib/replanning_lint.py::lint_task_proposals` valida):

```
task_candidate    -> ready | needs_scheduling
decision_required -> needs_decision
external_action   -> external
information_request -> dependency
monitoring_item   -> ready | needs_scheduling
not_task          -> not_task
```

## 8. `manage_task_operation`

Quando presente, tem exatamente a forma de um `create_task` de `manage-task-ledger` (`skills/manage-task-ledger/SKILL.md` seção 6) **sem** `client_id` — `manage-task-ledger` sempre preenche `client_id` a partir do próprio contexto de execução, nunca de uma proposta upstream (`operation/task-rules.md`). Nunca inclui `responsible`/`owner`/`priority`/qualquer campo fora de `schemas/task-ledger.schema.json`.

## 9. Procedimento

1. Verificar `audit.audit_status != "fail"`; se `fail`, `status: failed`, não gerar propostas.
2. Para cada `action`, classificar (seção 6), derivar `readiness` (seção 7), montar `manage_task_operation` só quando `ready`.
3. Preencher `summary` (contagem por readiness).
4. Validar e escrever `task-proposals.json`. `mode: "preview"` sempre.

## 10. Regras e proibições

- nunca escrever `clients/<client_id>/tasks.json`;
- nunca chamar `manage-task-ledger` em modo `apply`;
- nunca inventar `due_at`, `responsible`, ou `quarter_id` fora do já validado upstream;
- nunca converter `information_request`/`monitoring_item`/`decision_required` em `task_candidate` só para simplificar.

## 11. Idempotência

Mesma `replanning.json`/`audit.json` → mesmo conjunto de propostas, mesma classificação/readiness.
