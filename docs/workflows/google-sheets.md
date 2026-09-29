# Google Sheets — fundação (read-google-sheet / update-google-sheet)

Camada genérica e reutilizável para ler e escrever diretamente em Google
Sheets. Não contém lógica de negócio: skills futuras (Planilha de
Métricas, Playbook, Account Plan, planejamento sazonal) apenas
**preparam patches**; somente `update-google-sheet` escreve.

```
SOURCE        read-google-sheet    observa (snapshot de ranges)
INTELLIGENCE  <skills futuras>     prepara patch (schemas/google-sheet-patch.schema.json)
ACTION        update-google-sheet  preview → aprovação explícita → apply → verificação
```

Duas APIs, duas responsabilidades:

```
Google Drive  → resolve / copia / converte o ARQUIVO   (infraestrutura, CLI do operador)
      ↓            file-metadata · convert-xlsx · copy-sheet
Google Sheets → lê / escreve o CONTEÚDO                 (skills read-/update-google-sheet)
```

O lifecycle de arquivo **não é uma skill**: é um passo de provisionamento
pontual, sem lógica de negócio, executado explicitamente pelo operador
antes de o novo id ser declarado no `sources.json`. As skills continuam
operando só sobre conteúdo.

## Peças

| Arquivo | Papel |
|---|---|
| `scripts/lib/google_sheets_transport.py` | interface `GoogleSheetsTransport`, `GoogleApiSheetsTransport` (API oficial v4), `FakeGoogleSheetsTransport` (testes/dry run), erros tipados |
| `scripts/lib/google_sheets_auth.py` | credenciais via env: OAuth do operador (padrão) ou service account (opcional) |
| `scripts/lib/google_sheets_sources.py` | resolve a planilha a partir de `clients/<id>/sources.json` (isolamento) |
| `scripts/lib/google_sheets_read.py` | lógica de `read-google-sheet` |
| `scripts/lib/google_sheets_patch.py` | lógica de `update-google-sheet` (preview/apply/hash/verificação) |
| `scripts/lib/a1_notation.py` | parsing A1 (aba sempre explícita) |
| `scripts/lib/google_drive_transport.py` | interface `GoogleDriveTransport`, `GoogleApiDriveTransport` (Drive API v3), `FakeGoogleDriveTransport`; só metadata, download e **criação** de arquivos — não existe operação de update/move/rename/delete |
| `scripts/lib/google_drive_lifecycle.py` | `convert_xlsx` / `copy_sheet` com plan/apply, checagem de MIME real, anti-duplicação e verificação de preservação do original (`schemas/google-drive-file-operation.schema.json`) |
| `scripts/google_sheets.py` | CLI do operador: `auth`, `auth-status`, `file-metadata`, `convert-xlsx`, `copy-sheet`, `read`, `preview`, `approve`, `apply` |

## Declarar uma planilha (workspace privado)

IDs reais vivem só em `$V4_BU_WORKSPACE_ROOT/clients/<client_id>/sources.json`,
como entrada `type: "google_sheet"` (`schemas/google-sheet-source.schema.json`):

```json
{
  "source_id": "<client_id>-metrics-sheet",
  "type": "google_sheet",
  "scope": "client",
  "location": null,
  "contains_multiple_clients": false,
  "google_sheet": {
    "spreadsheet_id": "<id da URL /spreadsheets/d/<id>/>",
    "expected_title": "<título exato, opcional mas recomendado>",
    "purpose": "metrics",
    "allowed_tabs": null,
    "writable": false
  }
}
```

`writable: true` é necessário para `update-google-sheet`. Planilhas
multi-cliente nunca recebem escrita. `doctor.py --workspace` valida essas
entradas e acusa a mesma planilha declarada por dois clientes.

## Setup OAuth local (uma vez por máquina)

1. `pip install -r requirements-google.txt`
2. Google Cloud Console → projeto próprio → **APIs & Services → Library** → habilitar **Google Sheets API** e **Google Drive API**.
3. **OAuth consent screen**: tipo *Internal* (Workspace) ou *External* em modo teste com seu e-mail como *test user*; escopos da seção "Scopes" abaixo.
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → baixar o JSON **para fora do repositório** (ex.: `~/.config/v4-bu-autopilot/google-oauth-client.json`).
5. Definir no ambiente do shell (o CLI **não** carrega `.env` sozinho; `.env` serve de referência local, nunca versionada): `V4_BU_GOOGLE_OAUTH_CLIENT_SECRETS=<caminho do JSON>`; opcional `V4_BU_GOOGLE_OAUTH_TOKEN_PATH` (padrão `~/.config/v4-bu-autopilot/google-sheets-token.json`).
6. `python scripts/google_sheets.py auth` — abre o navegador uma vez; o token é salvo fora do repo (permissão 0600 quando o SO suporta).
7. `python scripts/google_sheets.py auth-status` — confirma sem imprimir segredos.

O engine recusa qualquer caminho de credencial/token dentro do
repositório. Skills nunca abrem o navegador sozinhas: token ausente ou
expirado sem refresh vira `AUTH_ERROR`.

## Scopes

Um único login local cobre Sheets + Drive:

| Scope | Para quê |
|---|---|
| `https://www.googleapis.com/auth/spreadsheets` | ler/escrever conteúdo (Sheets API) |
| `https://www.googleapis.com/auth/drive.readonly` | metadata e download de arquivos **existentes** endereçados por file id (detectar nativo vs `.xlsx`, baixar o `.xlsx` para converter) |
| `https://www.googleapis.com/auth/drive.file` | **criar** arquivos (cópia convertida/cópia nativa) e gerenciar somente os arquivos criados por este app |

Por que não só `drive.file`: sem Google Picker, `drive.file` só alcança
arquivos criados/abertos pelo próprio app — não enxergaria o `.xlsx` ou o
template existentes a partir de um id em `sources.json`. Por que não
`drive` (acesso total de leitura **e escrita** a todo o Drive): a
combinação acima dá leitura ampla, mas escrita só nos arquivos que o app
criou; nada do Drive existente pode ser alterado pelo token.

Limitações da escolha:
- `drive.readonly` é scope *restricted*: em app *External* publicado exige verificação do Google; em modo teste (ou app *Internal* do Workspace) funciona para os usuários autorizados.
- Colocar o arquivo novo numa pasta (`--folder`) que o app não criou depende da política do Drive para `drive.file`; se o Drive negar, o comando retorna `PERMISSION_DENIED` e nada é criado — rode sem `--folder` e mova manualmente.
- Conversão `.xlsx` → Sheets é a importação do próprio Drive: recursos Excel sem equivalente (macros, alguns gráficos/formatos condicionais) podem não sobreviver. Conferir a cópia antes de declará-la.

Tokens antigos (criados só com `spreadsheets`) continuam valendo para
Sheets; operações de Drive falham com `INSUFFICIENT_SCOPE` e a instrução
de rodar `python scripts/google_sheets.py auth` de novo.
`auth-status` mostra `sheets_scopes_granted`/`drive_scopes_granted`.

## Lifecycle de arquivo (Drive)

```
python scripts/google_sheets.py file-metadata <file_id>
python scripts/google_sheets.py convert-xlsx <file_id> --name "<novo nome>" [--folder <folder_id>]           # plano
python scripts/google_sheets.py convert-xlsx <file_id> --name "<novo nome>" [--folder <folder_id>] --apply   # cria
python scripts/google_sheets.py copy-sheet   <file_id> --name "<novo nome>" [--folder <folder_id>] [--apply]
```

- O MIME real decide: `convert-xlsx` só aceita `.xlsx` (`NOT_XLSX`), `copy-sheet` só Google Sheets nativo (`NOT_GOOGLE_SHEET`).
- Sem `--apply` nada é criado (`status: planned`).
- O original nunca é alterado (o transport não tem operação para isso) e sua metadata é relida depois (`original_preserved`).
- Arquivos criados recebem `appProperties` (`v4_source_file_id`, `v4_lifecycle_operation`); repetir o mesmo comando com o mesmo nome devolve o arquivo já criado (`no_change`), nunca uma segunda cópia. Mais de uma cópia pré-existente ⇒ `DUPLICATE_OPERATIONAL_COPIES`, nada é criado.
- O `file_id` retornado em `created.spreadsheet_id` é o que se declara em `sources.json`.

Service account (alternativa): `V4_BU_GOOGLE_AUTH_MODE=service_account`,
`V4_BU_GOOGLE_SERVICE_ACCOUNT_FILE=<json fora do repo>`, e compartilhar a
planilha com o e-mail da service account.

## Fluxo de escrita

```
python scripts/google_sheets.py preview --client <id> --patch patch.json
# operador revisa diff/formula_replacements e aprova explicitamente
python scripts/google_sheets.py approve --preview <...>-preview.json --approval-id <id> --approved-by <operador>
python scripts/google_sheets.py apply   --client <id> --patch patch.json --preview <...>-preview.json --approval <...>-approval.json
```

- A aprovação é hash-locked ao preview (`scripts/lib/approval.py`). Um preview novo invalida a aprovação anterior.
- `apply` relê a planilha; qualquer mudança na base (células-alvo, fórmulas das abas tocadas, estrutura/formatação) ⇒ `STALE_PREVIEW`, zero escrita.
- Reaplicar o mesmo patch ⇒ `no_change`, zero escrita.
- Escrita de conteúdo via `values.batchUpdate`; limpeza via `values.batchClear` (preserva formato e validação). Formatação, merges, validações e tamanhos não são tocados e são verificados depois (`userEnteredFormat`, não `effectiveFormat`).
- `duplicate_sheet` é a única operação estrutural: duplica uma aba existente via `duplicateSheet` nativo, sozinha no patch, sem nunca sobrescrever um destino existente; mesmo fluxo preview → aprovação → apply → verificação (cópia idêntica à origem, origem e demais abas inalteradas). Escritas na aba nova vão em patch separado, depois que ela existir.
- `set_number_format` é a única operação de formatação: altera só `userEnteredFormat.numberFormat` e passa pelo mesmo preview → aprovação → apply → verificação.
- Fórmula existente só é sobrescrita/limpa com `replace_existing_formula: true` na operação — e aparece em `mutation_plan.formula_replacements` do preview aprovado.

## Limitações conhecidas (v1)

- Sem operações estruturais/de estilo (linhas, abas, merges, cores, fontes, bordas) — rejeitadas. Só `set_number_format`.
- Comportamento medido na API real (planilha descartável, 2026-09-29): `values.batchUpdate` com `""` ou texto `RAW` **remove** `userEnteredFormat.numberFormat` (fundo e validação sobrevivem); números (`RAW` ou `USER_ENTERED`) e `values.batchClear` preservam. Escrever texto `RAW` numa célula com formato numérico gera o warning `NUMBER_FORMAT_WILL_BE_RESET` no preview e `VERIFICATION_FAILED` após o apply. `USER_ENTERED` com texto e escrita de fórmula não foram medidos.
- Fórmulas devem estar na sintaxe da API (nomes de função em inglês, separador `,`), mesmo em planilhas pt-BR. A comparação tolera caixa e espaços fora de strings.
- `write_value` com `USER_ENTERED` é verificado por igualdade numérica ou pelo valor formatado; parsing de locale fica a cargo do Sheets.
- Com valores `RAW` e `USER_ENTERED` no mesmo patch há duas requisições de escrita; se a segunda falhar, o resultado é `error` com a verificação mostrando o estado real (possível atualização parcial).
- Texto literal iniciando com `=` (ex.: `'=abc`) é indistinguível de fórmula na leitura `FORMULA`.
- `source_date` é sempre `null` (a API do Sheets não expõe data do conteúdo; `modifiedTime` exigiria Drive API).
