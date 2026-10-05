---
name: metrics-sheet
description: Project canonical Quarter metrics (plan, monitoring, evidence) onto a client's metrics sheet as an update-google-sheet patch.
---

# Metrics Sheet

- **Classe:** INTELLIGENCE (prepara o patch; a execução é a ACTION `update-google-sheet`)
- **Versão:** 1.0.0
- **Canonical Side Effects:** NONE (somente o receipt da ACTION delegada é persistido)
- **Contrato do cliente:** `clients/<client_id>/sheet-contracts/metrics-sheet.json`
- **Implementação:** `scripts/lib/sheet_metrics.py`
- **Output:** `skills/metrics-sheet/output.schema.json` (= `schemas/sheet-module-result.schema.json`)

## Objetivo

Lê o contrato `clients/<client_id>/sheet-contracts/metrics-sheet.json` (`schemas/sheet-module-contract.schema.json`), resolve cada campo canônico mapeado (`media.<mês>.<canal>.*`, `objective.*`, `evidence.<id>.value`) e monta um patch de células explícitas. Autoridade: **canônico → planilha**; um valor da planilha nunca volta para a memória canônica. Campo sem valor canônico é `NOT_AVAILABLE` e não é escrito (nunca 0). Sem contrato ou mapping → `CONFIG_REQUIRED`; cabeçalho divergente, aba ausente ou fórmula na célula-alvo → `CONFLICT_REVIEW_REQUIRED`.

## Fluxo (comum aos três módulos)

`scripts/lib/sheet_modules.py`: contrato → leitura via `read-google-sheet` → patch (`schemas/google-sheet-patch.schema.json`) → **preview do `update-google-sheet`** (hash-bound, diff, `no_change`, conflitos de fórmula) → aprovação do operador sobre esse preview exato → **apply do `update-google-sheet`** (gate, escrita, verificação pós-escrita) → o receipt dessa ACTION é persistido em `clients/<client_id>/receipts/`. O resultado do módulo (`schemas/sheet-module-result.schema.json`) só referencia `business_operation_id`, `patch_hash`, `approval_ref`, `google_receipt_ref` e `verification` — sem ledger paralelo.

Status: `NO_CHANGE`, `PATCH_READY`, `CONFLICT_REVIEW_REQUIRED`, `CONFIG_REQUIRED` (e `APPLIED` após o apply delegado). A planilha divergente nunca é sobrescrita em silêncio: o humano não é tratado como errado.

## Proibições

Nunca importar ou chamar transport Google, HTTP ou API diretamente (guard em `tests/google_sheets/test_business_modules.py`); nunca escrever memória canônica; nunca inventar célula, valor, data ou ação; nunca agir sem aprovação.
