---
name: manage-quarter
description: Preview and apply the canonical Quarter lifecycle (create_quarter, close_quarter) for one client, hash-locked to an operator approval.
---

# Manage Quarter

## 1. Identidade

- **Classe:** ACTION
- **Versão:** 1.0.0
- **Canonical Side Effects:** `QUARTER_PLAN` — `clients/<client_id>/quarters/<quarter_id>/plan.json`, `.../closure.json` e `clients/<client_id>/receipts/`
- **Contrato de output:** `skills/manage-quarter/output.schema.json`
- **Implementação de referência:** `scripts/lib/quarter_lifecycle.py` (contrato comum de ACTION: `scripts/lib/canonical_action.py`)

## 2. Objetivo e limites

Criar e fechar formalmente um Quarter (`operation/quarter-rules.md`). **O fim do calendário não fecha Quarter**; a passagem do tempo nunca muda status canônico.

Não usar para replanejar, decidir SMART ou mídia (isso vem de `replan-client` e de decisão do operador), registrar realizado (`monitor-quarter`), mexer em check-ins (`close-ropre`), concluir tasks (`manage-task-ledger`) ou resolver operations (`manage-operations-ledger`).

## 3. Operações

### `create_quarter`

Input: `client_id`, `quarter_id` (`YYYY-QN`) e um plan input com exatamente `period`, `smart_objective`, `planning` e `media_plan` (formato `schemas/quarter-plan.schema.json`). `status`, `planned_at` e identidade são definidos por esta ACTION.

Valida: `client.json` do cliente; formato do `quarter_id`; período dentro dos limites de calendário do Quarter; SMART válido com `deadline` dentro do período; `media_plan` com meses dentro do período e no máximo uma linha por `(month, channel)`.

Escreve somente `plan.json` com `status: "active"`. Não lê nem converte seasonal draft, não cria check-in, monitoring ou tasks, não carrega SMART do Quarter anterior.

- Mesmo Quarter já existente com conteúdo idêntico (ignorando `planned_at`) → `no_change`.
- Mesmo Quarter com conteúdo diferente → `conflict` `QUARTER_EXISTS_DIVERGENT` (nunca sobrescreve).
- Outro Quarter ainda `active` → `conflict` `ANOTHER_QUARTER_ACTIVE`.

Não há operação separada de ativação: criar é ativar, e no máximo um Quarter fica `active` por cliente (o que `read-quarter` exige). O status `planned` do schema permanece reservado e não é escrito por esta skill.

### `close_quarter`

Input: `client_id`, `quarter_id`, `as_of_date` opcional (padrão: data real do sistema; nunca futura).

Pré-condições: plano válido e `active`; `as_of_date` posterior a `period.end`; `monitoring.json`, se existir, válido (ausência gera warning); `check-ins/current.json` do Quarter `completed` (contrato adotado de ROPRE final — `close-ropre` antes).

Escreve `plan.json` com `status: "closed"` (nada mais muda no plano) e `closure.json` (`schemas/quarter-closure.schema.json`). Lista em `carry_over_candidates` as tasks `pending` e as operations ainda abertas do Quarter, com `overdue_as_of` derivado de `as_of_date` — **sem** concluir tasks, resolver operations ou criar o próximo Quarter.

- Já fechado com `closure.json` → `no_change`; fechado sem `closure.json` → `conflict`.

## 4. Preview, aprovação e apply

Padrão V1 de ACTION: **PREVIEW → preview_hash → aprovação vinculada → APPLY → receipt**.

- `base_state_hash`: SHA-256 do estado canônico em `base_state_files` (`client.json`, `quarters/` inteiro, `tasks.json`, `operations.json`).
- `preview_hash`: SHA-256 (JSON canônico, sem timestamps de execução) de cliente, Quarter, operação, `base_state_hash`, `proposed` e `carry_over_candidates`.
- Aprovação: item `quarter_lifecycle` com payload `{client_id, base_state_hash, preview_hash}`; o artefato-fonte é o preview inteiro. Só existe por pedido explícito do operador (`approval.apply_operator_decision`).
- Apply: recalcula `preview_hash` e `base_state_hash`; qualquer divergência → `STALE_APPROVAL` e zero escrita. Valida o resultado contra os schemas, escreve tudo numa única escrita multi-arquivo atômica e persiste o receipt (`schemas/action-receipt.schema.json`). `planned_at`/`closed_at` vêm do relógio real no apply.

## 5. Proibições

Nunca criar Quarter automaticamente, fechar por calendário, inventar SMART, budget ou check-in, concluir tasks, resolver operations, aplicar sem aprovação, ou executar qualquer ação externa.
