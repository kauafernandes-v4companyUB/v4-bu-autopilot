---
name: creative-performance-export
description: Export one document-winning-creative report as a normalized, stably keyed row of a client's creative sheet as an update-google-sheet patch.
---

# Creative Performance Export

- **Classe:** INTELLIGENCE (prepara o patch; a execução é a ACTION `update-google-sheet`)
- **Versão:** 1.0.0
- **Canonical Side Effects:** NONE (somente o receipt da ACTION delegada é persistido)
- **Contrato do cliente:** `clients/<client_id>/sheet-contracts/creative-performance-export.json`
- **Implementação:** `scripts/lib/sheet_creative_export.py`
- **Output:** `skills/creative-performance-export/output.schema.json` (= `schemas/sheet-module-result.schema.json`)

## Objetivo

Valida o relatório contra `skills/document-winning-creative/output.schema.json` (não repete a inteligência) e normaliza uma linha: chave `<client_id>:<creative_id>`, plataforma, período, status de vencedor declarado, métricas fornecidas, metadados técnicos, padrão observado, hipótese de replicação, `do_not_generalize` e `report_revision` (hash do conteúdo). Ausente → `NOT_AVAILABLE`, nunca 0. Chave ausente → `INSERT` na primeira linha livre; presente → `UPDATE_EXISTING` na mesma linha; idêntica → `NO_CHANGE`; chave duplicada ou sem linha livre → `CONFLICT_REVIEW_REQUIRED`.

## Fluxo (comum aos três módulos)

`scripts/lib/sheet_modules.py`: contrato → leitura via `read-google-sheet` → patch (`schemas/google-sheet-patch.schema.json`) → **preview do `update-google-sheet`** (hash-bound, diff, `no_change`, conflitos de fórmula) → aprovação do operador sobre esse preview exato → **apply do `update-google-sheet`** (gate, escrita, verificação pós-escrita) → o receipt dessa ACTION é persistido em `clients/<client_id>/receipts/`. O resultado do módulo (`schemas/sheet-module-result.schema.json`) só referencia `business_operation_id`, `patch_hash`, `approval_ref`, `google_receipt_ref` e `verification` — sem ledger paralelo.

Status: `NO_CHANGE`, `PATCH_READY`, `CONFLICT_REVIEW_REQUIRED`, `CONFIG_REQUIRED` (e `APPLIED` após o apply delegado). A planilha divergente nunca é sobrescrita em silêncio: o humano não é tratado como errado.

## Proibições

Nunca importar ou chamar transport Google, HTTP ou API diretamente (guard em `tests/google_sheets/test_business_modules.py`); nunca escrever memória canônica; nunca inventar célula, valor, data ou ação; nunca agir sem aprovação.
