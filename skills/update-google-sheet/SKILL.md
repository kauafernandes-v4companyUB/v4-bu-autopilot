---
name: update-google-sheet
description: Preview and, only with explicit hash-locked operator approval, apply a previously prepared cell patch (content + number format only) to one client's declared Google Sheet — preserving formulas and formatting, verifying after write.
---

# SKILL — UPDATE GOOGLE SHEET

## 1. Identificação

Nome: Update Google Sheet

Slug: update-google-sheet

Categoria: action

Versão: 1.0.0

Canonical Side Effects: EXTERNAL (somente `apply` bem-sucedido); NONE em `preview`.

Output contract: `skills/update-google-sheet/output.schema.json`

Input contract: `schemas/google-sheet-patch.schema.json`

Reference logic: `scripts/lib/google_sheets_patch.py` (preview/apply/verificação), `scripts/lib/google_sheets_transport.py` (transport real e fake), `scripts/lib/approval.py` (hash-lock). CLI: `python scripts/google_sheets.py preview|approve|apply`.

---

## 2. Objetivo

Materializar numa planilha Google, sem reinterpretar, um patch estruturado já preparado por outra skill.

Esta skill NÃO decide quais métricas preencher, NÃO interpreta BI, NÃO cria planejamento nem Account Plan. Se o patch estiver errado, ela bloqueia — nunca corrige.

---

## 3. Quando usar

- quando existe um patch válido (`schemas/google-sheet-patch.schema.json`) para uma planilha declarada `writable: true` no `sources.json` do cliente;
- sempre `preview` primeiro; `apply` somente após pedido explícito do operador.

## 4. Quando NÃO usar

- para decidir conteúdo, recalcular valores ou "ajustar" o patch;
- para operações estruturais ou de estilo (inserir/remover linhas ou abas, renomear, merges, cores, fontes, bordas, validações) — não suportadas; o tipo de operação é rejeitado (`UNSUPPORTED_OPERATION`). A única operação estrutural é `duplicate_sheet`; a única de formatação é `set_number_format`;
- para planilhas não declaradas pelo cliente, com `writable: false` ou `contains_multiple_clients: true`.

---

## 5. Inputs

- `client_id`;
- `patch` (`patch_id`, `client_id`, `source_id` e/ou `spreadsheet_id`, `operations`, opcional `permissions.allow_clear`);
- `mode`: `preview` (padrão) ou `apply`;
- para `apply`: o output de `preview` aprovado e um registro de aprovação (`schemas/approval.schema.json`) cujo item `google_sheet_patch` (item_id = `patch_id`) está hash-locked ao `preview_hash`/`base_state_hash` desse preview.

Operações:

| type | conteúdo | regra |
|---|---|---|
| `write_value` | `values` (grade exata do range) | `input_option` `RAW` (padrão) ou `USER_ENTERED`; string iniciando com `=` é rejeitada |
| `write_formula` | `formulas` (strings iniciando com `=`) | sempre `USER_ENTERED`; sintaxe da API (separador `,`, nomes em inglês) |
| `clear_value` | — | exige `permissions.allow_clear: true`; executado via `values.batchClear` (remove valor/fórmula, preserva formato e validação) |
| `duplicate_sheet` | `source_sheet_title`, `new_sheet_title`, `insert_index?` | estrutural, **sozinha no patch**; `duplicateSheet` nativo da API (nunca reconstrução célula a célula); destino existente ⇒ `conflict DESTINATION_EXISTS` (ou `no_change` se já for cópia idêntica); origem inexistente ⇒ `conflict SOURCE_SHEET_NOT_FOUND`; o preview traz `sheet_plan` (ids, grid, mesclas, validações, fórmulas, links, notas, larguras, hash de conteúdo, destino/índice) |
| `set_number_format` | `number_format` `{type, pattern?}` | altera **somente** `userEnteredFormat.numberFormat` (`repeatCell`, `fields=userEnteredFormat.numberFormat`); nunca toca valor, fórmula, outro formato ou validação; não pode dividir célula com outra operação |

`replace_existing_formula: true` é a única forma de sobrescrever, substituir ou limpar uma célula que hoje contém fórmula.

---

## 6. Procedimento — preview (nunca escreve)

1. Relógio real para `generated_at` + sanity check de futuro.
2. Isolamento: `patch.client_id == client_id`; binding resolvida no `sources.json` do cliente; `writable: true`; fonte não multi-cliente.
3. Normalizar operações: range A1 limitado com aba explícita, aba em `allowed_tabs`, grade com formato exato, `op_id` únicos, nenhuma célula alvo de duas operações. Qualquer falha ⇒ `error`, nada é lido além do necessário.
4. Ler metadata: planilha/título corretos (`WRONG_SPREADSHEET`), aba existe (`SHEET_NOT_FOUND`), range dentro do grid (`RANGE_OUT_OF_GRID` — crescer o grid é estrutural).
5. Reler estado atual: valores, valores formatados e fórmulas das células-alvo; todas as fórmulas das abas tocadas; fingerprint de estrutura/formatação (grid, merges, formatação condicional, proteções, filtros, bandas, `userEnteredFormat` e validação das células-alvo).
6. Construir `before`, `after`, `diff` (apenas células que mudam) e `mutation_plan` (`write_requests` com `method`, `formula_replacements` explícitas, `content_only` = `false` só quando há `set_number_format`). Para `set_number_format`, `before`/`after` trazem `number_format`. `write_value` `RAW` com texto sobre célula com formato numérico gera warning `NUMBER_FORMAT_WILL_BE_RESET` (a API remove o formato; a verificação vai acusar).
7. Célula com fórmula tocada sem `replace_existing_formula` ⇒ `conflict` (`FORMULA_OVERWRITE_BLOCKED` / `FORMULA_REPLACE_NOT_DECLARED`).
8. `base_state_hash` = SHA-256 do JSON canônico de {planilha, abas tocadas, estado das células-alvo, fórmulas fora do patch nas abas tocadas, fingerprint de estrutura}. `preview_hash` = SHA-256 de {client_id, patch_id, spreadsheet_id, base_state_hash, operações normalizadas, after, formula_replacements}.
9. Status: `success` (mudança material sem conflito), `no_change`, `conflict` ou `error`.

## 7. Procedimento — apply

1. Exigir preview aplicável (`mode: preview`, `status: success`) do mesmo cliente/patch e aprovação explícita do operador cobrindo o `patch_id`, não stale (`scripts/lib/approval.py::validate_approval`). Sem isso ⇒ `error` (`NO_PREVIEW`, `NO_APPROVAL`, `STALE_APPROVAL`, `PATCH_MISMATCH`, `CLIENT_ISOLATION`), zero escrita. Nenhuma skill aprova a própria proposta: o registro vem de `approval.apply_operator_decision` a partir de pedido explícito (`python scripts/google_sheets.py approve ... --approved-by <operador>`).
2. Reler tudo e recomputar hashes. Estado desejado já presente ⇒ `no_change`, zero escrita (idempotência). `preview_hash` diferente ⇒ `conflict STALE_PREVIEW` (base mudou) ou `PATCH_MISMATCH` (patch mudou), zero escrita — nunca adaptar.
3. Executar apenas as operações com mudança, nesta ordem: `values.batchClear` (clears), `values.batchUpdate` `RAW`, `values.batchUpdate` `USER_ENTERED`, `repeatCell` de `numberFormat`. Nunca limpar escrevendo `""`: na API real isso também apaga `userEnteredFormat.numberFormat` (teste descartável de 2026-09-29).
4. Reler e verificar: células-alvo = `after` (inclui `number_format` de `set_number_format`); fórmulas fora do patch intactas; fingerprint de estrutura idêntico (`userEnteredFormat` + validação por célula — nunca `effectiveFormat`), exceto o `numberFormat` das células de `set_number_format`, cujo restante do formato e validação precisa ser idêntico. Tudo ok ⇒ `success`; qualquer diferença ⇒ `conflict VERIFICATION_FAILED`, com `verification.structure_differences` indicando aba/célula/propriedade.
4b. `duplicate_sheet`: base = lista de abas + snapshot completo da origem (`get_sheet_snapshot`); verificação = aba nova com conteúdo idêntico ao snapshot da origem (identidade à parte), origem inalterada, nenhuma outra aba alterada (`verification.duplicate_sheet`). Semântica confirmada na API real em planilha descartável (2026-09-29): cópia nativa idêntica pelo snapshot normalizado.
5. Gerar `receipt` (`schemas/action-receipt.schema.json`). Persistir o receipt em memória canônica é decisão separada do orquestrador — esta skill não escreve `clients/`.

---

## 8. Output e status

Validar contra `output.schema.json`. Salvar por orquestração em `context/generated/<client_id>/google-sheets/`.

Falha de escrita na segunda requisição após sucesso da primeira é reportada como `error` com a verificação mostrando o estado real (a planilha pode estar parcialmente atualizada) — nunca como sucesso.

## 9. Regras e proibições

- nunca reescrever workbook inteiro, reconstruir planilha ou converter fórmulas em valores;
- nunca tocar célula fora do patch; nunca apagar fórmula não incluída;
- nunca sobrescrever fórmula com valor silenciosamente;
- nunca alterar formatação em patch de conteúdo; a única exceção declarada é `set_number_format`, restrita ao number format;
- nunca aplicar sem aprovação explícita não stale; nunca aplicar preview de outro cliente/patch;
- nunca imprimir tokens/segredos; nunca hardcodar ids reais no engine.

## 10. Critérios de qualidade

Preview sem nenhuma escrita; diff mínimo e explícito; toda substituição de fórmula listada em `formula_replacements`; apply verificado após escrita; timestamps reais; output válido no schema.

## 11. Idempotência

Reaplicar um patch já aplicado ⇒ `no_change` sem nenhuma requisição de escrita.
