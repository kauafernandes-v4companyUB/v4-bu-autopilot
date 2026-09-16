---
name: midweek
description: Mid-week operational snapshot for one client — planned, completed, pending, overdue, blocked, changed evidence, risks, and decisions needed. Never invents execution.
---

# Midweek

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/midweek/output.schema.json`

## 2. Objetivo

Responder "como está a semana até agora" sem criar nova inteligência complexa — é leitura e consolidação do que já existe (task ledger, último replanejamento, BI atual, flags), não um novo diagnóstico.

## 3. Quando usar

A pedido do operador ("faça o midweek de `<cliente>`"), tipicamente no meio da semana.

## 4. Quando NÃO usar

- para marcar algo como concluído — isso é `manage-task-ledger complete_task`, feito separadamente pelo operador;
- para gerar novo diagnóstico/replanejamento — isso é o pipeline `replan-client`.

## 5. Inputs

Obrigatório: `client_id`. Opcional: `quarter_id` (default: resolução por `read-quarter`).

## 6. Procedimento

1. Determinar `week_of` a partir do relógio real do sistema: semana corrente (segunda a domingo, ISO).
2. Ler `clients/<client_id>/tasks.json`. Classificar cada task: `planned_this_week` = `due_at` dentro de `week_of`; `completed` = `status: completed` (independente de quando); `pending` = `status: pending`; `overdue` = `status: pending` E `due_at` < hoje (derivado em runtime, nunca persistido); `blocked` = tasks cujo `origin`/contexto aponta para uma dependência/decisão aberta (cruzar com o `task-proposals.json` mais recente, se existir, para tasks `needs_decision`/`dependency` que não viraram `create_task`).
3. Se existir um `context/generated/<client_id>/replanning/` recente, ler `task-proposals.json` para `actions_needing_decision` (itens `needs_decision`) e `diagnosis.json`/`gaps.json` para `risks` (findings `finding_class: risk`) e `changed_evidence_or_results` (comparar `context-pack.json` mais recente, se houver mais de uma execução, com a anterior — quando só existir uma execução, `changed_evidence_or_results` fica vazio, nunca inventado).
4. Ler `monitoring.json` do Quarter para flags abertas relevantes.
5. Validar e escrever `midweek-preview.json` (nome definido pelo caller/orquestração — `operation/replanning-rules.md` define a pasta `context/generated/<client_id>/operating-loop/`).

## 7. Regras e proibições

- nunca marcar uma task como `completed` sem que `tasks.json` já diga isso;
- `overdue` é sempre derivado, nunca lido de um campo persistido;
- nunca inventar `changed_evidence_or_results` quando não há execução anterior para comparar — declarar ausência em `missing_data`.

## 8. Idempotência

Mesmo estado do ledger/replanejamento/monitoring + mesma janela de semana ⇒ mesmo output (exceto `generated_at`, timestamp de execução).
