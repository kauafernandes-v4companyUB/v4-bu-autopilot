---
name: plan-seasonal-calendar
description: Build a connected seasonal plan (campaigns, timeline, priorities, dependencies, client decisions, risks) for one client and any reasonable horizon, from that client's own context — classifying every element and never inventing products, offers, prices, stock, budget, team, capacity, channels or agreed dates.
---

# SKILL — PLAN SEASONAL CALENDAR

## 1. Identificação

Nome: Plan Seasonal Calendar

Slug: plan-seasonal-calendar

Categoria: intelligence

Versão: 1.0.0

Canonical Side Effects: NONE (escreve apenas contexto de trabalho em `context/generated/<client_id>/seasonal-planning/`).

Output contract: `skills/plan-seasonal-calendar/output.schema.json`

Reference logic: `scripts/lib/seasonal_planning.py` (calendário, lazy loading, validação, render). CLI: `python scripts/seasonal_planning.py context|validate|write`. Dados de calendário: `skills/plan-seasonal-calendar/calendar-catalog.json` (regras de datas, **sem relevância**).

---

## 2. Objetivo

Transformar o contexto real de UM cliente em um planejamento sazonal conectado para um horizonte solicitado (um mês, um trimestre, um semestre, até ~13 meses): o que trabalhar, quando, por quê, para quem, com que papel no funil, como cada etapa prepara a seguinte, que insumos e decisões do cliente são necessários e até quando.

A skill raciocina (o agente segue este procedimento); o código só fornece calendário, contexto, validação e render.

---

## 3. Quando usar

- "planejamento sazonal da `<cliente>` de `<início>` a `<fim>`";
- antes de briefings/campanhas de um período com datas comerciais relevantes;
- para revisar um planejamento sazonal anterior com contexto novo (gera outro artefato, nunca sobrescreve).

## 4. Quando NÃO usar

- para escrever em Google Sheets, alterar Playbook, criar tarefas, publicar campanha, alterar métricas ou memória canônica — isso é ACTION;
- para Estruturação Estratégica, Account Plan ou criativo campeão;
- para decidir preço, desconto, estoque, verba ou equipe — isso é do cliente.

---

## 5. Inputs

Obrigatórios: `client_id`, `start_date`, `end_date` (7–400 dias; pode atravessar o ano).

Opcionais: instruções do operador (`--instruction`, repetível). Cada instrução vira `OP-01`, `OP-02`… e pode ser citada em `source_refs`. Uma instrução do operador que declara uma decisão já tomada é `CONFIRMED_OPERATIONAL_DECISION`; uma instrução que só descreve preferência é contexto.

---

## 6. Fontes (lazy loading)

`python scripts/seasonal_planning.py context --client <id> --start <d> --end <d> [--instruction ...]` carrega somente:

1. memória canônica do cliente: `client.json`, `current-state.json`, `strategy.md`, `knowledge.json`, `decisions.json`, `evidence.json`, `tasks.json`, `sources.json` — cada uma marcada `loaded`, `empty` ou `missing`;
2. artefatos gerados do próprio cliente, por tipo conhecido: `replanning/*.json`, `bi-imports/*/bi-import-*.json`, `bi-imports/*/read-bi/*.json`, contratos (`*contract*.json`), planejamentos sazonais anteriores, e — quando existirem — `account-plan/`, `creative-learnings/`, `product-context/`, `campaigns/`.

Nunca lê `private/`, outros clientes, previews/patches de Sheets ou artefatos de tipo não listado. Artefato com `client_id` de outro cliente é rejeitado (`rejected_other_client`). Ausência de qualquer fonte não bloqueia: o plano continua, com as lacunas declaradas.

O contexto devolve: `sources` (com `source_id` S-nn, caminho, sha256, status), `confirmed_decisions` (todo item `type: DECISION` encontrado, com origem), `scheduled_actions` (ações de replanejamento com a base do prazo), `metrics` (observações de BI por janela), `observed_channels`, `unknown_topics`, e o calendário real (`weeks` seg–dom, `months`, `crosses_year`, `calendar_occurrences` do catálogo — sem relevância).

---

## 7. Procedimento

1. Rodar `context` e ler o resultado inteiro antes de planejar. Ler também o conteúdo das fontes `loaded` que forem relevantes.
2. Identificar o que é FACT/METRIC (sustentado por fonte), CONFIRMED_OPERATIONAL_DECISION (decisão existente no contexto ou instrução do operador), e o que é desconhecido.
3. Segmentos: declarar apenas segmentações que existam no contexto (B2B/B2C, categorias, regiões, unidades, serviços…), com `source_refs`. Sem segmentação no contexto ⇒ `segments: []` e mensagens gerais (`segment_id: null`).
4. Sazonalidades: avaliar cada `calendar_occurrence` do horizonte (e momentos sem data fixa do negócio, com `occurrence_id: null`) **à luz do negócio do cliente** e classificar `HIGH/MEDIUM/LOW_RELEVANCE` ou `NOT_RECOMMENDED` com justificativa. Não incluir data só por existir; feriados entram quando afetam execução ou oportunidade. A relevância nunca vem do catálogo.
5. Arquitetura do período: fases encadeadas (ex.: preparar → capturar → continuar), cada uma com papel e datas dentro do horizonte.
6. Campanhas: para cada uma, preencher todos os campos do schema (período, objetivo, público, segmentos, papéis de funil, oportunidade, mensagens por segmento, oferta, CTA, canais, função da mídia, materiais, dependências, decisão do cliente, campanha anterior/seguinte, prioridade). Decisões confirmadas do contexto são base — não contradizer.
7. Cronograma: uma entrada por semana (horizonte até ~4 meses) ou por mês (horizontes longos), exatamente as semanas/meses do `context`. Distinguir `CONFIRMED_OPERATIONAL_DECISION` (quando a ação/data já existe no contexto) de `PLANNING_RECOMMENDATION`.
8. Prioridades P0–P3 por oportunidade temporal, aderência, dependências, esforço, preparação, evidência e risco de perder a janela.
9. Decisões do cliente com prazo recomendado (tema: produto, estoque, preço, desconto, oferta, verba, equipe, capacidade, canal, calendário, material), dependências, riscos (com mitigação) e anti-prioridades baseadas no plano.
10. Métricas sugeridas: marcar `available_in_sources` e `required` com honestidade; nunca exigir faturamento; nunca exigir métrica sem fonte.
11. Listar cada decisão do contexto em `confirmed_decisions` (com `source_refs` para o id da decisão) **ou** em `context_decisions_not_applicable` com o motivo.
12. Preencher `semantic_summary` com as contagens (`scripts.lib.seasonal_planning.semantic_counts`).
13. `validate` até não haver issues; então `write` (JSON + Markdown derivado). Para teste/dry-run usar `--out-subdir`.

---

## 8. Classificação semântica

| Classe | Quando | Exige `source_refs` |
|---|---|---|
| `FACT` | afirmado por uma fonte do cliente | sim |
| `METRIC` | número vindo de fonte de dados | sim |
| `CONFIRMED_OPERATIONAL_DECISION` | decisão existente no contexto ou instrução do operador | sim (id da decisão ou `OP-nn`) |
| `PLANNING_RECOMMENDATION` | proposta deste plano | opcional |
| `CLIENT_CONFIRMATION_REQUIRED` | depende do cliente (produto, estoque, preço, desconto, oferta, verba, equipe, capacidade, canal ativo, data combinada) | opcional |
| `UNKNOWN` | não há informação e não é decisão do cliente | opcional |

Nunca converter recomendação em fato. Prazo inferido pelo planejamento é `PLANNING_RECOMMENDATION`, nunca "combinado com o cliente".

---

## 9. Validação (`validate`)

Além do schema, `validate_plan` rejeita: classe evidenciada sem evidência; decisão confirmada sem decisão/instrução de origem; decisão do contexto sumida ou rebaixada; segmento não evidenciado; campanha usando segmento não declarado; oferta classificada como recomendação; valor monetário/percentual de desconto em campanha ou cronograma de recomendação; canal dado como ativo sem evidência; datas fora do horizonte; cronograma que não segue as semanas/meses reais; prioridade ausente/duplicada; sazonalidade descartada sem justificativa; métrica obrigatória sem fonte; faturamento obrigatório; fonte de outro cliente ou não descoberta; `generated_at` no futuro.

---

## 10. Output e status

`seasonal-plan.json` (fonte estruturada, `output.schema.json`) e `seasonal-plan.md` (derivado por `render_markdown`, com `plan_sha256` no cabeçalho — nunca editar à mão) em `<workspace>/context/generated/<client_id>/seasonal-planning/<period_id>/`. `period_id`: `YYYY-MM`, `YYYY-qN`, `YYYY-hN`, `YYYY` ou `YYYYMMDD-YYYYMMDD`. `status`: `draft_for_operator_review` por padrão.

---

## 11. Side effects, memória e idempotência

- Side effects: nenhum externo. Não escreve Sheets, Playbook, tarefas, métricas, campanhas nem memória canônica.
- Memória: o plano não é memória canônica. `FACT`/`CONFIRMED_OPERATIONAL_DECISION` podem, depois, ser candidatos à promoção pelo mecanismo existente (`promote-client-memory`); `PLANNING_RECOMMENDATION` nunca vira fato por aparecer no plano; `CLIENT_CONFIRMATION_REQUIRED` continua pendente até haver evidência.
- Idempotência: `write` nunca sobrescreve um plano existente; rodar de novo exige outro `--out-subdir`.

---

## 12. Proibições

Nunca inventar produto, estoque, preço, desconto, condição, verba, equipe, capacidade operacional, calendário acordado, público ou canal ativo. Nunca criar segmentação que o contexto não tem. Nunca usar dado de outro cliente. Nunca tratar relevância de data como fixa.

## 13. Critérios de qualidade

Sequência conectada (cada campanha diz de onde vem e o que prepara); decisões confirmadas preservadas; lacunas explícitas com prazo; timeline no calendário real; nada monetário inventado; JSON e Markdown idênticos em conteúdo.
