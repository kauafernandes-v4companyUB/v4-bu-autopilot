---
name: read-google-sheet
description: Read a range-limited, structured snapshot (values + formulas) of one Google Sheet explicitly declared by the client in sources.json. Read-only.
---

# SKILL — READ GOOGLE SHEET

## 1. Identificação

Nome: Read Google Sheet

Slug: read-google-sheet

Categoria: source

Versão: 1.0.0

Canonical Side Effects: NONE

Output contract: `skills/read-google-sheet/output.schema.json`

Reference logic: `scripts/lib/google_sheets_read.py` (sobre `scripts/lib/google_sheets_transport.py`); CLI: `python scripts/google_sheets.py read`.

---

## 2. Objetivo

Ler abas/ranges explicitamente solicitados de UMA planilha Google declarada pelo cliente e produzir um snapshot estruturado (valores, fórmulas, abas, timestamp real de observação), sem interpretar o conteúdo.

---

## 3. Quando usar

- para observar o estado atual de uma planilha operacional do cliente (métricas, playbook, account plan etc.) antes de uma skill de inteligência preparar algo;
- para reler ranges específicos que um patch futuro vai tocar.

## 4. Quando NÃO usar

- para escrever qualquer coisa — isso é exclusivamente `update-google-sheet`, com preview e aprovação;
- para mapear métricas, diagnosticar, comparar com meta ou planejar — isso é INTELLIGENCE;
- para localizar uma planilha pelo nome — nunca; só por `source_id` ou spreadsheet id/URL declarado;
- para ler a planilha de outro cliente.

---

## 5. Inputs

Obrigatórios:

- `client_id` explícito;
- `source_id` (preferido) **ou** spreadsheet id / URL `docs.google.com/spreadsheets/d/<id>` — em ambos os casos precisa existir uma entrada `type: "google_sheet"` em `clients/<client_id>/sources.json` (`schemas/google-sheet-source.schema.json`);
- `ranges`: lista não vazia de ranges A1 com aba explícita (`'Métricas'!A1:F40`) ou abas inteiras (`'Métricas'`).

Opcional: `include_formatted` (também devolver os valores formatados como exibidos).

Nunca assumir planilha, aba ou range ausentes.

---

## 6. Fontes permitidas

Somente a API oficial do Google Sheets, via o transport configurado (`scripts/lib/google_sheets_auth.py` — OAuth do operador por padrão). Credenciais vêm de variáveis de ambiente e ficam fora do repositório.

---

## 7. Procedimento

1. Obter `generated_at`/`observed_at` do relógio real UTC (`scripts/lib/exec_clock.py`) e aplicar o sanity check de futuro (CLAUDE.md seção 26).
2. Resolver a binding em `sources.json` do próprio cliente (`resolve_sheet_binding`): `sources.json.client_id` diferente ⇒ `CLIENT_ISOLATION`; planilha não declarada ⇒ `SOURCE_NOT_REGISTERED`; `source_id` que aponta para outro id ⇒ `WRONG_SPREADSHEET`. Fonte com `contains_multiple_clients: true` gera warning `MULTI_CLIENT_SOURCE`.
3. Ler metadata (título, locale, fuso, abas). Id retornado diferente ou título ≠ `expected_title` ⇒ `WRONG_SPREADSHEET`, sem ler células.
4. Validar cada range: A1 inválido ⇒ `INVALID_RANGE`; aba fora de `allowed_tabs` ⇒ `TAB_NOT_ALLOWED`; aba inexistente ⇒ `missing_data SHEET_NOT_FOUND`; fora do grid ⇒ `missing_data RANGE_OUT_OF_GRID`. Ranges inválidos não impedem a leitura dos válidos.
5. Ler valores (`UNFORMATTED_VALUE`, datas como string formatada) e fórmulas (`FORMULA`) dos ranges válidos; formatted values só se pedido. Ranges limitados são preenchidos com `""` até o retângulo solicitado; ranges abertos/abas inteiras geram warning `RANGE_TRIMMED`.
6. Registrar fórmulas de forma esparsa (`cell`, `a1`, `formula`) e `content_sha256` por range.
7. Validar contra o output schema.

`source_date` é sempre `null`: a planilha não sustenta uma data própria do conteúdo; `observed_at` é somente o momento real da leitura.

---

## 8. Output e status

Salvar somente por orquestração em `context/generated/<client_id>/google-sheets/` (workspace privado).

- `success`: todos os ranges solicitados lidos;
- `partial`: parte dos ranges lida, lacunas em `missing_data`/`errors`;
- `error`: nada confiável lido (auth, API, planilha errada, isolamento, nenhum range válido).

Erros do transport são códigos estáveis: `AUTH_ERROR`, `PERMISSION_DENIED`, `SPREADSHEET_NOT_FOUND`, `INVALID_RANGE`, `API_ERROR`, `DEPENDENCY_MISSING`.

---

## 9. Regras e proibições

- Side effects: NONE — nunca chamar `write_values`/`batch_update`;
- ler não autoriza escrever;
- nunca buscar planilha por nome nem ler além dos ranges pedidos;
- nunca misturar clientes nem usar a planilha de um cliente para outro;
- nunca interpretar números como métricas canônicas nem gerar evidência canônica;
- nunca imprimir tokens/segredos.

## 10. Critérios de qualidade

Output valida no schema; toda leitura rastreável a `spreadsheet_id` + range; lacunas declaradas; timestamps reais e não futuros; `observed_at` ≠ `source_date`.

## 11. Idempotência

Ler duas vezes a mesma planilha sem alterações produz os mesmos `values`, `formulas` e `content_sha256` (apenas `generated_at`/`observed_at` mudam).
