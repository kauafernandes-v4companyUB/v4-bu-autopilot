# SKILL — READ BI

## 1. Identificação

Nome: Read BI

Slug: read-bi

Categoria: source

Versão: 1.0.0

Canonical Side Effects: NONE

---

## 2. Objetivo

Transformar uma única exportação de BI (PDF ou CSV) em observações estruturadas, rastreáveis e independentes da ferramenta de origem, para um `client_id` explicitamente informado.

O BI é a fonte externa primária de performance. Esta versão recebe exportações manuais; futuras origens automatizadas devem alimentar o mesmo contrato de saída.

---

## 3. Quando usar

Usar para ler um único arquivo `.pdf` ou `.csv` exportado de BI, com `client_id` e `source_path` explícitos.

---

## 4. Quando NÃO usar

Não usar para CRM, Windsor, Data Studio, APIs, links encontrados no arquivo, merge de PDF e CSV, diagnóstico, priorização, SMART, Quarter, monitoring, ROPRE, tarefas, evidência canônica ou memória do cliente.

Não inferir `client_id` pelo nome, caminho ou conteúdo do arquivo.

---

## 5. Inputs e fontes permitidas

Obrigatórios:

- `client_id` explícito;
- `source_path` explícito para exatamente um arquivo `.pdf` ou `.csv`.

Permitido somente: arquivo local fornecido, inclusive em `private/clients/<client_id>/bi/`. Arquivos reais permanecem fora do Git. Nome do arquivo é metadata/hint, nunca autoridade temporal.

---

## 6. Procedimento

1. Validar extensão e legibilidade sem executar conteúdo, fórmulas, macros, links ou URLs.
2. Calcular SHA-256 dos bytes originais; nunca usar mtime como identidade.
3. Registrar `observed_at` e `generated_at` com o relógio real UTC RFC3339. `source_date` somente vem de conteúdo explícito; caso contrário é `null`.
4. Para PDF, executar fluxo VISUAL-FIRST: abrir/inspecionar visualmente quando possível ou renderizar páginas localmente para PNG com `pdftoppm -png` e inspecioná-las visualmente. A renderização é transformação visual, não OCR. Screenshot, FireShot e dashboard rasterizado são suportados; ausência de text layer não é erro. Sem leitura visual e sem renderizador, retornar `pdf_visual_unavailable` — nunca cair silenciosamente para `pdftotext` como interpretação semântica.
5. Para CSV, usar `csv` da biblioteca padrão e `io.StringIO` (nunca `splitlines`), preservando campos quoted com vírgula ou quebra de linha, UTF-8/UTF-8-SIG, cabeçalhos, linha lógica do registro, coluna e valor bruto. Detectar delimitador estruturalmente: primeiro `csv.Sniffer().sniff(sample, delimiters=",;\\t")`, validando pelo menos duas colunas e largura consistente; se falhar, avaliar cada delimitador permitido pelas mesmas regras. Empate material ou estrutura irregular retorna `csv_delimiter_ambiguous`. Arquivo realmente de uma coluna é aceito como `single_column`, sem alegar delimitador nem inventar tabela multicoluna.
6. Identificar apenas período, filtros, dimensões, canal e métricas explicitamente visíveis. Dimensões preservam `name`, `value` e `source_ref`. `report_period` usa `explicit_range`, `month_to_date`, `full_month`, `quarter_to_date`, `single_date`, `snapshot` ou `unknown`; datas ausentes ficam `null`.
7. Preservar toda observação como métrica observada: label, `metric_key` determinística, valor bruto, normalização somente inequívoca, unidade, canal, período, `source_ref`, confiança e `derived: false`. `metric_key` é Unicode NFKD, sem diacríticos, lowercase, caracteres não alfanuméricos convertidos em `_`, underscores colapsados e extremos removidos (por exemplo, `Taxa de Conversão` → `taxa_de_conversao`; `Faturamento (R$)` → `faturamento_r`).
8. Mapear apenas semanticamente inequívoco para: `spend`, `impressions`, `reach`, `clicks`, `leads`, `conversions`, `sales`, `revenue`, `cpm`, `cpc`, `ctr`, `cpl`, `cpa`, `conversion_rate`, `roas`. Métrica desconhecida mantém `canonical_metric: null`; por exemplo, “Conversas iniciadas” não vira lead.
9. Gerar `observation_id` determinístico: serializar em JSON canônico UTF-8 (`sort_keys=true`, separadores compactos) `{file_sha256, metric_key, channel, period, source_ref}`; aplicar SHA-256 e usar `biobs-` mais os 16 primeiros hex. Para deduplicação, ordenar `source_refs` canonicamente e usar o primeiro `source_ref` ordenado como referência primária do ID; a ordem de descoberta nunca muda o ID.
10. Deduplicar somente observações semanticamente iguais (métrica/canal/período/valor), preservando todos os `source_refs`. Valores distintos no mesmo scope geram `metric_value_conflict`, sem escolha automática.
11. Produzir `result_observations` somente como referências a observações existentes, sem diagnóstico ou causalidade.
12. Produzir `monitoring_candidates` apenas para spend explícito e canal conhecido. Um `report_period.basis = explicit_range` continua factual e pode, separadamente, gerar candidate `month_to_date` quando `start_date` for dia 1, `end_date` estiver no mesmo mês/ano e o mês for inequívoco; `as_of_date` é o `end_date`, sem consultar o relógio atual. Se o range cobrir o último dia do mês, preferir candidate `full_month`. Range que não começa no dia 1, atravessa meses ou tem uma única data é `period_total` e inelegível (`period_total_not_monthly_cumulative`). Nunca somar exports.
13. Derivar apenas CTR, CPC, CPM, CPL e ROAS quando os insumos têm mesmo período/scope, unidades compatíveis e denominador não zero. `conversion_rate` só é derivada com denominador explicitamente definido. Não substituir métricas exibidas; divergência material gera warning/conflito.
14. Calcular `age_days` apenas se `report_period.end_date` for conhecido, usando a data real do sistema.
15. Validar contra `output.schema.json` e validações relacionais de runtime: cada ID em `result_observations`, em `source_observation_ids` de derivadas e em `monitoring_candidates.observation_ids` precisa existir exatamente uma vez em `metric_observations`. ID duplicado com mesma semântica é deduplicado; com conteúdo divergente é `observation_id_collision` e `conflict`. Referência derivada órfã é `derived_source_observation_missing`; referências órfãs de result/candidate rejeitam o output. JSON Schema não é apresentado como garantia suficiente para essas relações entre arrays.

O extrator opcional `scripts/extract_bi.py` faz somente preparação bruta: validação, hash, `observed_at`, contagem de páginas e detecção/renderização PDF local por `--render-dir` explícito. Ele não lê semanticamente PDF, não conhece cliente, estratégia, ROPRE ou Walmaq. Para output semântico PDF, `source.extractor` deve registrar `codex-visual` ou `pdf-render+codex-visual`, conforme o caminho efetivamente usado.

---

## 7. Normalização e rastreabilidade

- Unidades: `count`, `brl`, `percent`, `ratio`, `currency_other`, `seconds`, `days`, `other`, `unknown`.
- Normalização pt-BR aceita, quando inequívoco, `R$ 8.170,00` → `8170.00` BRL, `R$ 465` → `465.00` BRL, `17,5%` → `17.5` percent, `1.234,56` e `1234,56` → `1234.56`. `1.234` sem moeda, percentual, unidade ou contexto inequívoco não é decidido: `value: null`, confiança baixa e `numeric_value_ambiguous`.
- Mapeamentos canônicos inequívocos v1: Investimento/Gasto/Valor investido → `spend`; Faturamento/Receita → `revenue`; Vendas → `sales`; Leads → `leads`; Impressões → `impressions`; Cliques → `clicks`; Alcance → `reach`; ROAS/CTR/CPL → sua métrica homônima. Conversas iniciadas, Contatos, Oportunidades, Interessados e Resultados não são mapeados automaticamente.
- Canal explícito: Meta/Meta Ads/Facebook Ads/Instagram Ads → `meta_ads`; Google/Google Ads → `google_ads`; agregado explicitamente indicado → `all`; outro nome explícito → `other`; ausente → `null`. Nunca inferir canal pela métrica.
- PDF usa `{type, page, excerpt}` e CSV usa `{type, row, column, raw_cell}`. Excerpt é curto; nunca incluir página ou arquivo bruto completo no output.
- PDF é VISUAL-FIRST: cards, títulos, filtros, tabelas, legendas, gráficos e agrupamento espacial são interpretados pelo agente na página renderizada. `pdftotext`, quando usado como hint secundário, nunca é autoridade; divergência material entre texto e layout visual registra warning e o visual prevalece para associação semântica. Associação de cards a um canal é permitida somente quando o agrupamento visual for inequívoco (por exemplo, título “META ADS” imediatamente acima dos cards). Não estimar números pela altura de gráfico: só extrair valor escrito, tooltip presente no export ou tabela/label explícito.
- Filtros e período visíveis no PDF são explícitos e podem ser usados; filtros ocultos não são inferidos. Confiança alta exige label, valor e contexto visual inequívocos; média admite contexto secundário menos explícito; baixa preserva ambiguidade e não vira fato canônico.
- `source_date_missing`, `report_period_missing`, `no_metrics_found`, `channel_missing`, `unit_ambiguous`, `numeric_value_ambiguous`, `pdf_visual_unavailable` e `unsupported_file_type` são registrados quando aplicáveis.
- Períodos só são factuais quando visíveis: `01/09/2026 - 15/09/2026` → `explicit_range`; `Setembro até hoje` somente com ano/data de contexto explícitos no relatório → `month_to_date`; `Setembro de 2026` → `full_month`; uma data apresentada como data/período do relatório → `single_date`; ausência → `unknown`, datas nulas e `report_period_missing`. Filename, mtime e relógio de execução nunca completam período ou `source_date`.
- `age_days` só existe com `end_date`; se estiver no futuro, fica `null` e registra `report_period_in_future`.
- Uma candidata de monitoring `eligible: true` exige `media_actual`, referência a observação `spend`, valor, mês e canal conhecidos e base `month_to_date` ou `full_month`; então `reason` pode ser `null`. Para `explicit_range`, a base do candidate é `month_to_date` somente com início no primeiro dia e fim no mesmo mês; não altera `report_period.basis`. Se o range inclui o mês completo, a base é `full_month`. Em qualquer outro caso, `eligible: false` e `reason` não vazia. Exports semanais são `period_total_not_monthly_cumulative`; execuções são isoladas e nunca somam semanas.
- Para observações explícitas, `derived: false` exige `formula: null` e `source_observation_ids: []`. Derivadas exigem fórmula não vazia e ao menos dois IDs únicos que resolvam. Métrica explícita nunca é substituída pela derivada.

---

## 8. Output e status

O output valida em `skills/read-bi/output.schema.json`. Pode ser salvo apenas por orquestração em `context/generated/<client_id>/bi/`; esta skill não escreve automaticamente.

Status: `success`, `partial`, `error` ou `conflict`.

- `success`: fonte lida, output utilizável, métricas encontradas e sem conflito material; `source_date_missing` isolado não o impede.
- `partial`: resultado útil com lacunas ou ambiguidades declaradas.
- `conflict`: há valores/semânticas incompatíveis não resolvidos.
- `error`: arquivo ilegível, formato não suportado ou extração impossível.

---

## 9. Proibições

Nunca criar ou atualizar `clients/`, evidência canônica, `monitoring.json`, Quarter, SMART, ROPRE ou task ledger. Nunca chamar `monitor-quarter` nem `prepare-ropre`. Nunca integrar Data Studio, Windsor, CRM ou qualquer API externa. Nunca criar dados reais, inferir fatos ausentes, diagnosticar performance ou promover observação de baixa confiança a fato canônico.
