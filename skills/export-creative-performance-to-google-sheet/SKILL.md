---
name: export-creative-performance-to-google-sheet
description: Export one or more final creative-performance.json reports (document-winning-creative) to five managed tabs of one operational BU Google Sheet — idempotent upsert, preview first, hash-locked approval, apply through update-google-sheet, re-read verification. The JSON stays the source of truth; the sheet is a derived view.
---

# SKILL — EXPORT CREATIVE PERFORMANCE TO GOOGLE SHEET

## 1. Identificação

Nome: Export Creative Performance to Google Sheet

Slug: export-creative-performance-to-google-sheet

Categoria: action

Versão: 1.0.0

Canonical Side Effects: EXTERNAL (somente `apply` bem-sucedido, via `update-google-sheet`); NONE em `preview` e `dry-run`.

Input contract: `skills/export-creative-performance-to-google-sheet/input.schema.json`

Output contract: `skills/export-creative-performance-to-google-sheet/output.schema.json`

Reference logic: `scripts/lib/creative_performance_sheet_export.py` (relatórios → linhas, planejamento de upsert, geração de patch). Escrita, aprovação e verificação: `update-google-sheet` (`scripts/lib/google_sheets_patch.py`). CLI: `python scripts/creative_performance_sheet_export.py dry-run|preview|approve|apply`.

---

## 2. Objetivo

Materializar, sem reinterpretar, os relatórios finais de criativo campeão numa planilha operacional consolidada, para leitura humana. `creative-performance.json` continua sendo a fonte de verdade: nada da planilha volta para o relatório.

## 3. Quando usar

- "exporte os criativos campeões da `<cliente>` (e da `<cliente2>`) para a planilha" — sempre com escopo explícito;
- depois de um relatório novo ou regenerado, para atualizar a visão (o preview mostra `UPDATE` e as células que mudam).

## 4. Quando NÃO usar

- para gerar, corrigir ou reinterpretar um relatório (isso é `document-winning-creative`);
- para exportar "todos os clientes" sem lista — o escopo é sempre explícito;
- para planilha que não esteja declarada no registro BU com `allowed_client_ids`;
- para faturamento, margem, ROI, ROAS ou LTV — esta visão é de mídia e aprendizado criativo.

---

## 5. Destino (registro BU)

Uma planilha consolidada contém vários clientes, então não pode ser declarada no `sources.json` de um cliente (lá, `contains_multiple_clients: true` continua bloqueando escrita). Ela é declarada em `<workspace>/bu/sources.json`:

```json
{
  "schema_version": "1.0.0", "registry_scope": "bu", "client_id": "bu",
  "sources": [{
    "source_id": "<id>", "type": "google_sheet", "scope": "bu", "contains_multiple_clients": true,
    "allowed_client_ids": ["<cliente-a>", "<cliente-b>"],
    "google_sheet": {"spreadsheet_id": "<id fornecido pelo operador>", "expected_title": "<título>", "writable": true}
  }]
}
```

Só clientes em `allowed_client_ids` podem ser exportados para esse destino. O patch declara `data_client_ids` e o `update-google-sheet` confere o subconjunto. `bu` é um id reservado, nunca um cliente.

## 6. Input

`export_id`, `destination.source_id` (e opcionalmente `spreadsheet_id` para conferência), `scope.client_ids` (todos os relatórios finais de cada cliente listado) e/ou `scope.report_paths` (caminhos relativos exatos). Escopo vazio é erro.

## 7. Fontes (lazy loading)

Lê **somente** `context/generated/<cliente>/creative-performance/<creative_id>/creative-performance.json` do escopo. Nunca lê o Markdown, imagens, vídeos, frames, CSV, WhatsApp, BI, Account Plan ou a memória do cliente. Cada relatório é validado contra o schema de saída da `document-winning-creative`, e sua identidade (`client_id`/`creative_id`) precisa bater com o caminho. Revalidação completa do relatório (com as fontes) é da skill que o gerou.

## 8. Layout gerenciado (cinco abas)

Cada aba tem cabeçalho canônico na linha 1 e colunas `A..` exatamente as listadas em `TABS` (`scripts/lib/creative_performance_sheet_export.py`). O exportador só escreve dentro desse retângulo; outras abas e colunas à direita não são tocadas.

| Aba | Linha por | Chave lógica |
|---|---|---|
| `CRIATIVOS CAMPEÕES` | relatório | `client_id` + `creative_id` |
| `PADRÕES OBSERVADOS` | elemento `OBSERVED` | + `pattern_id` |
| `HIPÓTESES` | `REPLICATION_HYPOTHESIS` | + `hypothesis_id` |
| `NÃO GENERALIZAR` | `DO_NOT_GENERALIZE` | + `item_id` |
| `FONTES` | fonte usada | + `source_id` |

Regras de conteúdo:

- **Métricas.** Ausente vira célula **vazia**, nunca 0; zero só quando o relatório traz 0. Os valores vêm do relatório (inclusive CPM e frequência derivados) e nada é recalculado. `metricas_derivadas` lista as colunas que vieram de `DERIVED_METRIC`; as demais são métricas fornecidas.
- **Resultado.** `resultado_valor` fica separado de `resultado_tipo_original`, que é o identificador do export. `resultado_rotulo` é um rótulo amigável opcional.
- **Hipóteses.** Ficam só na aba `HIPÓTESES`, com `classe = REPLICATION_HYPOTHESIS` e o texto original. Nunca aparecem como fato.
- **Fontes.** `referencia` é sempre um caminho relativo ao workspace; caminho absoluto ou com `..` vira vazio. O `sha256` vem do relatório e fica vazio quando o relatório não o traz (caso do CSV).
- **Avisos.** A coluna `avisos` traz só os códigos, por exemplo `HETEROGENEOUS_RESULT_TYPES`.

Formatação é mínima: as abas criadas pelo exportador já nascem com a linha 1 congelada. Formatos numéricos (moeda, percentual) ficam para uma extensão futura; `set_number_format` não pode dividir célula com escrita no mesmo patch.

## 9. Upsert e idempotência

Para cada linha desejada:

- **chave ausente:** `INSERT` na próxima linha livre;
- **chave existente com o mesmo `report_sha256`:** `NO_CHANGE`. Se as células foram editadas à mão, sai o aviso `MANAGED_CELLS_EDITED` e nada é sobrescrito;
- **chave existente com `report_sha256` diferente:** `UPDATE` só das células que mudam. Valor que ficou ausente é limpo com `clear_value` (preserva formato), nunca escrito como 0 ou "".

Linhas nunca são apagadas. Um item que saiu de um relatório atualizado vira `ORPHAN_ROW` (aviso), e a linha fica. A planilha representa a versão vigente; o histórico real está no Git/workspace.

Rodar de novo sem mudanças dá `no_change`, sem patch e sem escrita.

## 10. Procedimento

Fase 1, `structure`, só quando falta alguma aba gerenciada:

1. `preview` gera um patch só com `add_sheet` (grade com o número de colunas do layout, ≥ 1000 linhas, linha 1 congelada).
2. O operador aprova explicitamente (`approve`).
3. `apply` cria as abas e verifica.

Fase 2, `content`:

1. `preview` gera o patch de cabeçalhos e linhas, com o resumo de `INSERT`/`UPDATE`/`NO_CHANGE`/órfãos e as células que mudam.
2. O operador aprova.
3. `apply` confere se algum relatório mudou e bloqueia com `SOURCE_REPORT_CHANGED`.
4. Refaz o plano e bloqueia com `STALE_PREVIEW` se o patch mudou.
5. Delega ao `apply` do `update-google-sheet`, que reconfere aprovação e hash, escreve, relê e verifica.
6. Planeja de novo: tudo precisa dar `NO_CHANGE` (`post_apply.content_converged`).

`dry-run` planeja localmente, contra uma planilha vazia, sem transporte e sem destino. Serve para validar a transformação de relatórios reais sem Google.

## 11. Conflitos (bloqueiam; zero escrita)

`SCHEMA_MISMATCH` (cabeçalho diferente ou dados sem cabeçalho), `DUPLICATE_LOGICAL_KEY`, `CORRUPTED_KEY`, `GRID_TOO_SMALL` (crescer grade é estrutural e não é automatizado), `UNSAFE_CELL_TEXT` (texto começando com `=`), `SOURCE_REPORT_CHANGED`, `STALE_PREVIEW`, `CLIENT_NOT_ALLOWED`, `CLIENT_ISOLATION`, `INVALID_REPORT`, `DUPLICATE_REPORT_KEY`, `WRONG_SPREADSHEET`, e — do `update-google-sheet` — `FORMULA_OVERWRITE_BLOCKED` (fórmula dentro de célula gerenciada), `NO_APPROVAL`, `STALE_APPROVAL`, `DESTINATION_EXISTS`.

## 12. Side effects e memória

Escreve apenas na planilha declarada, e só com aprovação. Não escreve memória canônica, relatórios ou outras skills. O recibo (`receipt`) vem do `update-google-sheet`. Persistir recibos é decisão separada do orquestrador.

## 13. Dependências opcionais

Google só é necessário em `preview`/`apply` (import tardio de `google_sheets_auth`). `dry-run`, a biblioteca e os testes (transport fake) não exigem `requirements-google.txt`.

## 14. Proibições

Nunca exportar sem escopo explícito, cliente fora de `allowed_client_ids`, relatório de outro cliente, Markdown como fonte, 0 no lugar de ausência, hipótese como fato, caminho absoluto, ou qualquer escrita sem preview aprovado.
