---
name: week-close
description: End-of-week operational snapshot for one client — promised vs. executed, blockers, BI movement, SMART evidence, open flags, carry-forward candidates and ROPRE-prep inputs. Never creates carry-over automatically.
---

# Week Close

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/week-close/output.schema.json`

## 2. Objetivo

Fechar a semana com honestidade: o que foi prometido (due_at nesta semana) vs. o que foi de fato executado (status completed com completed_at nesta semana), sem inventar execução nem criar carry-over automaticamente.

## 3. Quando usar

A pedido do operador ("feche a semana de `<cliente>`"), tipicamente no fim da semana, antes de um `prepare-ropre`.

## 4. Quando NÃO usar

- para decidir o que fazer com tarefas não executadas — isso é decisão do operador; esta skill só lista `carry_forward_candidates`, nunca cria/reagenda uma task;
- para gerar o ROPRE em si — isso é `prepare-ropre`, que pode consumir este output como um dos inputs, sem duplicar o task ledger.

## 5. Inputs

Obrigatório: `client_id`. Opcional: `quarter_id`.

## 6. Procedimento

1. Determinar `week_of` (semana corrente, relógio real do sistema).
2. Ler `clients/<client_id>/tasks.json`: `promised` = `due_at` dentro de `week_of`; `executed` = dentre essas, `status: completed` com `completed_at` dentro de `week_of`; `not_executed` = dentre `promised`, ainda `pending` ou `cancelled` ao fim da semana.
3. `blockers`: motivos conhecidos de não-execução, quando declarados em evidência/replanejamento (nunca supor motivo não evidenciado).
4. `bi_movement`: snapshot de `media_monitoring` do Quarter atual, se disponível — `null` quando não há leitura de BI recente, nunca inventado.
5. `smart_evidence`: `objective_progress` atual do Quarter, tal como está — preservar `null`/`unknown` exatamente.
6. `open_flags`: flags abertas em `monitoring.json`.
7. `carry_forward_candidates`: cada item de `not_executed` com `reason` explícito — apenas uma lista para revisão, nunca uma nova task nem uma mudança de `due_at`.
8. `ropre_preparation_inputs`: candidatos de `results`/`next_steps` derivados do que foi observado nesta semana — texto cru para o operador revisar antes de um `prepare-ropre`, não uma escrita no draft ROPRE em si.
9. Validar e escrever `week-close-preview.json`.

## 7. Regras e proibições

- nunca marcar uma task como executada sem `completed_at` real no ledger;
- nunca criar, reagendar ou cancelar uma task a partir desta skill;
- nunca inventar `bi_movement`/`smart_evidence` quando a fonte está ausente.

## 8. Idempotência

Mesmo ledger/monitoring + mesma semana ⇒ mesmo output.
