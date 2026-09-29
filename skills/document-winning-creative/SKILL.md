---
name: document-winning-creative
description: Document ONE creative the operator declared the winner — what is objectively in it, the metrics the operator provided (plus clearly derived ratios), replication hypotheses and what must not be generalized — without searching other creatives, inventing benchmarks or claiming causality.
---

# SKILL — DOCUMENT WINNING CREATIVE

## 1. Identificação

Nome: Document Winning Creative

Slug: document-winning-creative

Categoria: intelligence

Versão: 1.2.0

Canonical Side Effects: NONE (escreve apenas contexto de trabalho em `context/generated/<client_id>/creative-performance/`).

Input contract: `skills/document-winning-creative/input.schema.json` (brief do operador)

Output contract: `skills/document-winning-creative/output.schema.json`

Reference logic: `scripts/lib/creative_performance.py` (contexto lazy, isolamento, metadados do asset, normalização/derivação de métricas, validação, render). CLI: `python scripts/creative_performance.py context|validate|write`.

---

## 2. Objetivo

Registrar de forma rastreável o criativo que o **operador** declarou campeão: o que está objetivamente na peça, quais números ele teve, o que vale testar de novo e o que não pode virar regra — separando sempre **observação** de **hipótese sobre desempenho**.

A skill não prova que o criativo venceu (isso é declaração do operador) e não explica por que venceu (sem evidência comparativa isso é só hipótese).

---

## 3. Quando usar

- "documente o criativo campeão da `<cliente>`" com a peça e as métricas em mãos;
- depois de um fechamento de período, para registrar o vencedor que o operador escolheu;
- antes de um briefing que queira replicar elementos de um vencedor (como hipótese a testar).

## 4. Quando NÃO usar

- para ranquear, comparar criativos, analisar perdedores ou montar benchmark — não é comparador (seria outra capacidade);
- para pesquisar biblioteca de anúncios ou outros criativos do cliente;
- para escrever em Sheets, Playbook, eKyte, Meta, Google Ads ou memória canônica — isso é ACTION;
- para decidir verba, pausar/escalar campanha ou produzir criativo novo.

---

## 5. Inputs (brief do operador)

Um JSON conforme `input.schema.json`:

- `client_id`, `creative_id` (id escolhido pelo operador);
- `winner_declaration.statement` — as palavras do operador ("esse foi o criativo campeão"). Isso é entrada válida: vira `winner_status.source = OPERATOR_DECLARED`, `statistically_compared = false`;
- `assets[]` — o(s) arquivo(s) do criativo (imagem, vídeo, PDF, texto), caminho relativo ao workspace **dentro da árvore do cliente** (`private/clients/<id>/…`, `clients/<id>/…` ou `context/generated/<id>/…`). Duração de vídeo, se conhecida, vem do operador (`duration_seconds`);
- `metrics[]` — `{metric, value, unit, source}`; `value: null` = não disponível. `source` é `operator` ou o caminho de um `metric_sources[]` (ex.: export de BI fornecido);
- opcionais: `period`, `campaign_context`, `operator_instructions[]` (viram `OP-01`, `OP-02`…), `comparative_evidence[]` (só se o operador fornecer uma comparação real, ex.: resultado de teste A/B), `load_client_identity` (padrão `false`).

### 5.1 Seleção da linha de métricas (regra do operador) — opcional

Quando as métricas vêm de um export **por anúncio** e o operador define qual linha pertence ao campeão, o brief traz `metric_row_selection`:

- `rule: MAX_RESULTS`, `source: OPERATOR_RULE`, `source_path` (um dos `metric_sources`, CSV UTF-8), `column` (ex.: `Resultados`);
- opcionais: `result_type_column` (ex.: `Indicador de resultados`), `ad_name_column`, `ad_set_name_column`, `campaign_name_column`, `metric_columns[]` (`{metric, column, unit}` lidos da linha escolhida), `notes`;
- `confirmed_row_number` só para resolver um empate, escolhido pelo operador entre as linhas empatadas.

O código aplica a regra, e a regra é do operador, não uma conclusão estatística:

- escolhe a linha com o maior valor válido de `column`;
- célula vazia ou inválida nunca vira zero;
- linha sem nome de anúncio (total) é excluída;
- **nunca soma linhas**: o mesmo anúncio em outros conjuntos fica listado em `same_ad_name_rows`;
- em empate não escolhe nada: `RESULT_TIE` e confirmação do operador.

`winner_status` continua `OPERATOR_DECLARED`; a regra só escolhe a **linha de métricas** do campeão já declarado.

Tipo de resultado:

- o identificador original do export é preservado em `source_result_type` (ou `UNKNOWN`);
- `normalized_label` é um rótulo amigável opcional e nunca o substitui;
- `Resultados` nunca é mapeado para mensagens ou leads;
- tipos diferentes no mesmo export geram `HETEROGENEOUS_RESULT_TYPES` em `warnings`, sem bloquear.

Métricas lidas da linha levam `source_row`/`source_column` (e `result_type` no resultado). Todo `PERFORMANCE_FACT` que as cita traz `source_trace` com fonte, linha, coluna e tipo (use `scripts.lib.creative_performance.source_trace`).

### 5.2 Referência do post — opcional

`post_reference.url` é só rastreabilidade (`OPERATOR_PROVIDED`, `metric_row_match_required: false`, `opened: false`). Não é aberto e não precisa corresponder à linha nem a um ad_id.

### 5.3 Metadados técnicos de vídeo (ffprobe opcional)

Para cada asset `video` **carregado e nomeado no brief**, o contexto roda `ffprobe`, se o ambiente tiver. É uma capacidade opcional: nunca é instalada e nunca é exigida. Roda com lista de argumentos, sem shell e com timeout.

`asset_metadata[].technical_metadata` traz:

- `probe`: `status` (`OK`, `FFPROBE_UNAVAILABLE` ou `FFPROBE_FAILED`), `tool_version`, `probed_sha256` (o hash do arquivo medido) e `values` (a resposta do ffprobe);
- `fields`: `duration_seconds`, `width`, `height`, `frame_rate`, `video_codec`, `audio_codec`, `audio_channels`, `audio_sample_rate`, cada um com `value`, `source`, `operator_value`, `ffprobe_value` e `status`;
- `orientation` e `aspect_ratio` com `source: DERIVED`, calculados a partir de largura, altura e rotação.

Proveniência:

- `OPERATOR_PROVIDED` (brief);
- `FFPROBE` (medido);
- `DERIVED` (calculado);
- `NOT_AVAILABLE` (nada é inventado);
- `FILE_HEADER` continua sendo a base das dimensões de imagem.

Os campos antigos `dimensions_basis` e `duration_basis` passam a aceitar `ffprobe`.

Precedência:

- valor do operador **nunca é sobrescrito**;
- se o ffprobe concorda dentro da tolerância, o campo fica `CONFIRMED`;
- se diverge, fica `METADATA_INCONSISTENT`, com os dois valores guardados e um aviso;
- o ffprobe só preenche o que o operador não informou.

Tolerâncias:

- duração: ±0,5 s ou ±1 %;
- frame rate: ±0,05 fps;
- demais campos: exatos (codec sem diferenciar maiúsculas).

Sem ffprobe: os campos ficam `NOT_AVAILABLE`, com o aviso `FFPROBE_UNAVAILABLE`, e nada bloqueia.

Validação entre réplicas:

- onde o ffprobe roda, o relatório precisa bater com a medição atual;
- onde não roda, os campos são recalculados a partir de `probe.values` gravado, preso ao `probed_sha256` do arquivo;
- relatório sem `technical_metadata` (anterior à 1.2.0) continua válido.

---

## 6. Fontes (lazy loading)

`python scripts/creative_performance.py context --brief <brief.json>` lê **somente** os arquivos nomeados no brief e, apenas se `load_client_identity: true`, `clients/<id>/client.json` e `strategy.md`.

Nunca lê: outros criativos do cliente, bibliotecas de anúncios/internet, histórico de BI além do `metric_sources` informado, Account Plan, outros clientes, qualquer arquivo não nomeado.

Cada arquivo recebe `source_id` (S-nn), `sha256` e status `loaded` / `missing` / `rejected_other_client`. É rejeitado (e nunca usado) o arquivo na árvore de outro cliente, com `client_id` declarado diferente, ou JSON cujo `client_id` interno seja de outro cliente. Caminho fora de qualquer árvore de cliente ou fora do workspace é erro.

O contexto devolve: `winner_status`, `period`, `campaign_context`, `operator_notes`, `sources`, `assets` (metadados objetivos), `provided_metrics`, `derived_metrics`, `metrics_not_available`, `required_unknowns`, `comparative_evidence_ids`, `warnings`, `not_read`.

---

## 7. Procedimento

1. Montar o brief com o que o operador forneceu. Não completar lacunas.
2. Rodar `context` e ler o resultado inteiro.
3. Abrir cada asset `loaded` (imagem/PDF/texto diretamente; vídeo pelos frames/descrição disponíveis) e documentar **cada uma** das dimensões em `observed_elements`: formato, tipo de peça, orientação, duração, headline, texto principal, CTA, oferta, produto/serviço, benefício, promessa, prova, urgência, elementos visuais, hierarquia, presença de pessoa, presença de produto, branding, estilo, estrutura narrativa, primeiro frame/hook, fechamento, destino. Status:
   - `OBSERVED` — está na peça; descrever o que é e onde (`location`), vinculado ao `asset_id`;
   - `NOT_PRESENT` — verificável e ausente;
   - `NOT_OBSERVABLE` — não dá para verificar com o material (ex.: destino do clique a partir de uma imagem);
   - `NOT_APPLICABLE` — não se aplica ao formato (ex.: duração em imagem estática).
4. Copiar `asset_metadata`, `provided_metrics`, `derived_metrics`, `winner_status`, `period`, `campaign_context`, `operator_notes` e, quando existirem, `metric_row_selection` e `post_reference` **exatamente** como vieram do contexto.
5. `performance_summary` (`PERFORMANCE_FACT`): frases que só repetem números disponíveis, citando `metric_refs` (M-nn/D-nn). Todo número escrito tem que ser o valor de uma métrica citada. Sem juízo de "bom/ruim" contra benchmark.
6. `replication_hypotheses` (`REPLICATION_HYPOTHESIS`): o que vale testar de novo, apoiado em elementos `OBSERVED` (`based_on_elements`), com `test_suggestion` (replicação controlada) e `confidence` `low`/`medium` — nunca `high`.
7. `do_not_generalize` (`DO_NOT_GENERALIZE`): o que não pode virar regra só porque apareceu num vencedor (ex.: cor do botão, formato, horário).
8. `unknowns`: toda métrica `NOT_AVAILABLE` (`metric:<chave>`, conforme `required_unknowns`), período ausente e o que mais faltar (destino, público, criativos comparáveis…).
9. `comparisons`: vazio, salvo se houver `comparative_evidence`; então cada comparação cita a fonte comparativa.
10. `memory_promotion_candidates`: apenas `PERFORMANCE_FACT`, elementos `OBSERVED` e decisões explícitas do operador (`OP-nn`). Nunca hipótese.
11. Carregar `warnings` do contexto; preencher `learning_summary` (`scripts.lib.creative_performance.learning_counts`).
12. `validate` até não haver issues; então `write` (JSON + Markdown derivado). Dry-run: `--out-subdir`.

---

## 8. Classes de aprendizado

| Classe | Onde | O que é |
|---|---|---|
| `OBSERVED_PATTERN` | `observed_elements` (status `OBSERVED`) | elemento objetivamente presente na peça |
| `PERFORMANCE_FACT` | `performance_summary` | número fornecido (`METRIC`) ou derivado (`DERIVED_METRIC`) |
| `REPLICATION_HYPOTHESIS` | `replication_hypotheses` | o que vale testar/repetir — nunca fato |
| `DO_NOT_GENERALIZE` | `do_not_generalize` | o que não pode virar regra a partir de um único vencedor |

Exemplo — OBSERVED_PATTERN: "CTA de WhatsApp visível no rodapé." · PERFORMANCE_FACT: "CTR de 1,8% no período." · REPLICATION_HYPOTHESIS: "A exposição antecipada do CTA pode ter contribuído para os cliques; testar CTA visível em peças semelhantes." · DO_NOT_GENERALIZE: "Não afirmar que CTA verde gera CTR maior sem comparação."

---

## 9. Sem falsa causalidade

Sem `comparative_evidence`, o validador rejeita linguagem causal ou comparativa assertiva em qualquer seção analítica — ex.: "venceu porque", "performou melhor", "devido a", "graças a", "causou", "foi responsável por", "comprovadamente", "é superior", "melhor que os outros", "acima da média", "benchmark", "because", "due to", "outperformed".

Permitido: observação ("o criativo apresenta a oferta no primeiro bloco"), hipótese ("pode ter contribuído", "vale testar"), replicação controlada. `do_not_generalize`, `unknowns`, `warnings` e as palavras do operador (`winner_status`, `operator_notes`) são isentos porque descrevem/citam uma afirmação, não a fazem. Com evidência comparativa, só o item que cita essa fonte fica isento.

---

## 10. Métricas

- Nenhuma métrica é obrigatória; faturamento nunca é exigido.
- Aliases normalizados (`investimento`→`spend`, `mensagens`→`messages`, `custo por lead`→`cpl`…); rótulo desconhecido vira chave própria, nunca é descartado.
- Ausente = `NOT_AVAILABLE` (valor `null`), nunca zero. Zero só existe se o operador informou zero.
- Derivadas (`DERIVED_METRIC`, com fórmula e entradas) só quando a métrica não foi fornecida e as entradas existem com denominador > 0: CTR = cliques/impressões×100; CPC = investimento/cliques; CPM = investimento/impressões×1000; frequência = impressões/alcance; custo por mensagem = investimento/mensagens; CPL = investimento/leads.
- Métrica fornecida que diverge (>2%) da derivável gera `METRIC_INCONSISTENT` em `warnings`; nenhuma é corrigida.
- Métrica cuja fonte foi rejeitada/ausente vira `NOT_AVAILABLE` com nota.

---

## 11. Output e status

`creative-performance.json` (fonte estruturada, `output.schema.json`) e `creative-performance.md` (derivado por `render_markdown`, com `report_sha256` no cabeçalho — nunca editar à mão) em `<workspace>/context/generated/<client_id>/creative-performance/<creative_id>/`. `status`: `draft_for_operator_review`.

---

## 12. Side effects, memória e idempotência

- Side effects: nenhum externo. Não escreve Sheets, Playbook, eKyte, Meta, Google Ads nem memória canônica.
- Memória: o relatório não é memória canônica. `memory_promotion_candidates` são sugestões para `promote-client-memory`, executado depois e com aprovação; `REPLICATION_HYPOTHESIS` nunca vira fato.
- Idempotência: `write` nunca sobrescreve; rodar de novo exige outro `--out-subdir`.

---

## 13. Proibições

Nunca buscar outros criativos, comparar, ranquear, analisar perdedores, inventar benchmark, afirmar causa sem evidência comparativa, inventar elemento não observável, inventar número, trocar ausência por zero, exigir faturamento, usar arquivo de outro cliente ou acessar a internet.

## 14. Critérios de qualidade

Todas as dimensões endereçadas; observação separada de hipótese; números idênticos às fontes; derivadas marcadas; lacunas explícitas; hipóteses testáveis; JSON e Markdown idênticos em conteúdo.

## 15. Ausência de dados

Sem asset carregável: todas as dimensões `NOT_OBSERVABLE` (aviso `NO_LOADED_ASSET`), o relatório ainda registra métricas e lacunas. Sem métricas: `performance_summary` vazio e todas as métricas em `unknowns`. Sem período: `unknowns` inclui `period`. Nada disso bloqueia. Exceção: `RESULT_TIE` numa seleção de linha impede o relatório até o operador confirmar a linha.
