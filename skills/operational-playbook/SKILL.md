---
name: operational-playbook
description: Project approved Autopilot actions onto the period's playbook tab (duplicate template once, then content) as update-google-sheet patches.
---

# Operational Playbook

- **Classe:** INTELLIGENCE (prepara o patch; a execução é a ACTION `update-google-sheet`)
- **Versão:** 1.0.0
- **Canonical Side Effects:** NONE (somente o receipt da ACTION delegada é persistido)
- **Contrato do cliente:** `clients/<client_id>/sheet-contracts/operational-playbook.json`
- **Implementação:** `scripts/lib/sheet_playbook.py`
- **Output:** `skills/operational-playbook/output.schema.json` (= `schemas/sheet-module-result.schema.json`)

## Objetivo

Classifica itens em `CONFIRMED_ACTION` (tasks, operations agendadas/aprovadas, decisões ativas, recomendação sazonal explicitamente aprovada), `RECOMMENDATION`, `CLIENT_CONFIRMATION_REQUIRED`, `DEPENDENCY` (operations deferred) e `DECISION_REQUIRED` (decision_pending). Recomendação nunca vira ação confirmada nem task em silêncio. Datas só de `due_at`, `scheduled_for` ou data ISO explícita — "última semana do mês" fica sem data. Ciclo: `duplicate_sheet` do template para a aba-alvo de título estável (uma vez; identidade provada pelo receipt persistido), depois patch de conteúdo nos blocos do contrato. Aba-alvo existente sem receipt, cópias com sufixo ou cabeçalho divergente → `CONFLICT_REVIEW_REQUIRED`; mais itens que linhas → `CONFIG_REQUIRED` (nunca trunca).

## Fluxo (comum aos três módulos)

`scripts/lib/sheet_modules.py`: contrato → leitura via `read-google-sheet` → patch (`schemas/google-sheet-patch.schema.json`) → **preview do `update-google-sheet`** (hash-bound, diff, `no_change`, conflitos de fórmula) → aprovação do operador sobre esse preview exato → **apply do `update-google-sheet`** (gate, escrita, verificação pós-escrita) → o receipt dessa ACTION é persistido em `clients/<client_id>/receipts/`. O resultado do módulo (`schemas/sheet-module-result.schema.json`) só referencia `business_operation_id`, `patch_hash`, `approval_ref`, `google_receipt_ref` e `verification` — sem ledger paralelo.

Status: `NO_CHANGE`, `PATCH_READY`, `CONFLICT_REVIEW_REQUIRED`, `CONFIG_REQUIRED` (e `APPLIED` após o apply delegado). A planilha divergente nunca é sobrescrita em silêncio: o humano não é tratado como errado.

## Proibições

Nunca importar ou chamar transport Google, HTTP ou API diretamente (guard em `tests/google_sheets/test_business_modules.py`); nunca escrever memória canônica; nunca inventar célula, valor, data ou ação; nunca agir sem aprovação.
