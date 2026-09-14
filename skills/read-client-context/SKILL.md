# SKILL — READ CLIENT CONTEXT

## 1. Identificação

Nome: Read Client Context

Slug: read-client-context

Categoria: source

Versão: 1.0.0

Side Effects: NONE

---

## 2. Objetivo

Ler documentação narrativa ou contextual sobre UM cliente específico — dedicada ou compartilhada entre múltiplos clientes — e transformar o trecho pertencente a esse cliente em contexto estruturado, classificado e rastreável.

A skill observa e normaliza contexto. Ela não interpreta performance, não define estratégia nova e não decide prioridades.

---

## 3. Quando usar

Usar quando for necessário ler, para um `client_id` específico:

- handoff de Account Manager;
- documento de onboarding;
- direcionamento estratégico documentado;
- documentação consolidada do cliente;
- briefing mestre;
- documento narrativo contendo um único cliente;
- documento narrativo contendo múltiplos clientes, quando apenas um precisa ser extraído.

---

## 4. Quando NÃO usar

Não usar para:

- ler uma BU/carteira/índice de clientes estruturado em linhas/cards (isso é responsabilidade de `read-bu`);
- ler BI/dashboard/planilha de métricas;
- ler transcrição de reunião (`read-transcript`);
- ler exportação de WhatsApp (`read-whatsapp`);
- ler account x GT (`read-account-gt`);
- ler eKyte ou sistemas de execução (`read-ekyte`);
- diagnosticar performance (`diagnose-client`);
- calcular gap (`calculate-gap`);
- definir prioridades (`identify-priorities`);
- gerar replanejamento (`replan-client`);
- gerar tarefas (`generate-tasks`);
- atualizar memória canônica (`update-client-state`, `update-history`).

Essas responsabilidades pertencem a outras skills.

---

## 5. Responsabilidade

Esta skill é responsável por:

- qualificar a fonte antes de qualquer extração;
- localizar e isolar a seção pertencente ao cliente solicitado, quando a fonte contiver múltiplos clientes;
- extrair contexto narrativo/estruturado em blocos semânticos;
- classificar cada elemento relevante segundo os tipos de conhecimento do CLAUDE.md;
- extrair, preservar e classificar hyperlinks sem abri-los;
- gerar evidências rastreáveis para o que for extraído;
- declarar lacunas relevantes e conflitos aparentes;
- registrar freshness (data da fonte) quando disponível.

Esta skill NÃO é responsável por:

- diagnosticar performance ou maturidade do cliente;
- definir ou validar estratégia nova;
- decidir prioridades ou gerar replanejamento;
- gerar tarefas;
- atualizar `clients/<client_id>/client.json`, `strategy.md`, `current-state.json`, `decisions.json` ou `sources.json`;
- abrir ou executar qualquer link descoberto;
- absorver conteúdo pertencente a outro cliente presente na mesma fonte.

---

## 6. Inputs

Obrigatórios:

- `client_id`;
- referência da fonte (`source_path` ou `source_url`).

Opcionais:

- `client_selector` — nome ou termo usado para localizar a seção do cliente na fonte (ex.: nome fantasia, razão social). Quando ausente, a skill tenta usar `display_name` conhecido do cliente ou o próprio `client_id`;
- `page_hint` — página ou intervalo aproximado onde o cliente pode estar, quando conhecido previamente (ex.: a partir de `sources.json`);
- contexto anterior (ex.: `clients/<client_id>/client.json`) apenas para apoiar a identificação do cliente na fonte — nunca para preencher lacunas de conteúdo.

Nunca assumir `client_selector` silenciosamente quando o nome puder ser ambíguo dentro da fonte.

---

## 7. Fontes permitidas

A skill pode ler:

- PDF;
- documento de texto (Google Docs exportado, .docx, .md, .txt);
- apresentação exportada como texto/PDF;
- outra fonte narrativa autorizada em `clients/<client_id>/sources.json`.

Para PDF, deve considerar:

- texto visível;
- posição/página de cada trecho;
- hyperlinks embutidos e suas âncoras;
- estrutura de seções (títulos, cabeçalhos, quebras de página).

Não consultar outras fontes sem necessidade operacional ou autorização definida. Não seguir hyperlinks encontrados dentro da fonte para buscar contexto adicional.

---

## 8. Qualificação da Fonte (Source Qualification)

Etapa **obrigatória**, executada **antes de qualquer extração de conteúdo**.

### 8.1 Objetivo

Impedir que uma fonte estruturalmente incompatível (BI, transcrição, WhatsApp, lista de tarefas, índice de carteira sem contexto narrativo, ou arquivo sem relação identificável com o cliente) seja processada como se fosse documentação contextual.

### 8.2 Tipos compatíveis (`source_compatible = true`)

- `account_handoff` — handoff de Account Manager, dedicado ou compartilhado entre clientes;
- `client_handoff` — handoff específico de um único cliente;
- `onboarding_document` — documento de onboarding;
- `strategic_document` — direcionamento estratégico documentado;
- `client_documentation` — documentação consolidada do cliente;
- `master_briefing` — briefing mestre;
- `other_client_context` — outro documento narrativo/contextual claramente sobre o cliente, não coberto pelos tipos acima.

### 8.3 Tipos incompatíveis (`source_compatible = false`)

- `bi_dashboard` — BI, dashboard, export de métricas;
- `meeting_transcript` — transcrição de reunião;
- `whatsapp_export` — exportação de WhatsApp;
- `task_list` — lista de tarefas;
- `bu_index` — BU/índice de carteira sem contexto narrativo por cliente (pertence a `read-bu`);
- `unrelated_document` — arquivo sem relação identificável com o cliente solicitado;
- `unknown` — não foi possível determinar com segurança.

### 8.4 Procedimento de qualificação

1. observar a forma geral da fonte (narrativa/contextual vs. tabular de métricas vs. transcrição vs. conversa vs. índice de carteira);
2. verificar se a fonte contém, em algum ponto, conteúdo identificável como pertencente ao `client_id`/`client_selector` solicitado;
3. classificar `source_kind` conforme 8.2/8.3;
4. definir `source_compatible` (`true` somente para os tipos listados em 8.2);
5. atribuir `confidence` (`low`/`medium`/`high`) à classificação;
6. registrar uma evidência (`type: fact`) descrevendo a natureza observada da fonte — fato sobre a fonte, não sobre o cliente;
7. se `source_compatible = false`, seguir 8.5 e **parar** — não prosseguir para a seção 9;
8. se `source_compatible = true`, prosseguir para a seção 9 (Isolamento e Detecção de Seção).

### 8.5 Tratamento de fonte incompatível

Quando `source_compatible = false`:

- **não** extrair contexto;
- `status = failed`;
- `data` deve ser `{}` (vazio);
- `section_detection.client_found = false`;
- registrar em `warnings` uma mensagem clara de *source type mismatch*, citando o `source_kind` detectado;
- registrar em `missing_data` que a extração não foi realizada por incompatibilidade de fonte;
- sugerir, quando possível, a skill/categoria adequada (ex.: `read-bi`, `read-transcript`, `read-whatsapp`, `read-bu`) em `warnings`, **sem executá-la**.

---

## 9. Isolamento e Detecção de Seção do Cliente (Client Isolation)

Etapa **obrigatória** quando `source_compatible = true`, executada **antes da extração de dados** (seção 11).

### 9.1 Objetivo

Garantir que somente o conteúdo pertencente ao cliente solicitado seja extraído, mesmo quando a fonte contém outros clientes.

### 9.2 Procedimento

1. confirmar que o cliente solicitado aparece ou pode ser identificado na fonte, usando `client_selector` (ou `display_name`/`client_id` como fallback);
2. determinar o início da seção do cliente (ex.: título, cabeçalho, quebra de página, marcador textual);
3. determinar o fim da seção do cliente (ex.: início da seção do próximo cliente, fim do documento, quebra estrutural clara);
4. ler conteúdo imediatamente adjacente somente quando necessário para confirmar com segurança os limites da seção — nunca para complementar conteúdo do cliente;
5. registrar como a delimitação foi feita (`start_reference`, `end_reference`) e a confiança dessa delimitação;
6. impedir que qualquer conteúdo identificado como pertencente a outro cliente seja incluído em `data`, `discovered_sources` ou `evidence` deste output.

### 9.3 Registro obrigatório

Todo output deve conter `section_detection` com:

- `client_found` (`boolean`);
- `selector` — o termo efetivamente usado para localizar o cliente;
- `start_reference` — referência (ex.: página, trecho, título) de onde a seção começa;
- `end_reference` — referência de onde a seção termina;
- `confidence` (`low`/`medium`/`high`).

### 9.4 Quando a delimitação não é segura

Se o cliente não for encontrado, ou os limites da seção não puderem ser determinados com segurança:

- `client_found = false` → `status = failed`, `data = {}`, warning obrigatório explicando a impossibilidade;
- limites parcialmente inseguros (cliente encontrado, mas início ou fim ambíguo) → `status = partial`, extrair apenas o que estiver claramente dentro dos limites seguros, `confidence = low` em `section_detection`, warning obrigatório;
- nunca atribuir ao cliente, como fato, conteúdo situado em região ambígua entre duas seções.

---

## 10. Pré-condições

Antes de executar, verificar:

1. `client_id` identificado;
2. fonte disponível e acessível;
3. fonte pertence, declarada ou plausivelmente, ao cliente correto (`clients/<client_id>/sources.json`, quando existir entrada correspondente);
4. Qualificação da Fonte (seção 8) executada;
5. Isolamento/Detecção de Seção (seção 9) executada, quando `source_compatible = true`.

Se alguma pré-condição falhar, registrar o problema em vez de inventar informação.

---

## 11. Procedimento

Executar nesta ordem:

0. executar Qualificação da Fonte (seção 8); se `source_compatible = false`, seguir 8.5 e encerrar;
1. executar Isolamento e Detecção de Seção (seção 9); se `client_found = false`, seguir 9.4 e encerrar;
2. ler somente o conteúdo dentro dos limites determinados da seção do cliente;
3. extrair informações relevantes por bloco semântico (seção 12);
4. classificar cada elemento segundo os tipos de conhecimento (CLAUDE.md seção 5);
5. extrair hyperlinks presentes na seção e classificá-los (seção 13), sem abri-los;
6. gerar evidências para fatos e contexto operacionalmente relevantes (seção 14);
7. registrar `missing_data` relevante (seção 17);
8. registrar `warnings` relevantes (seção 18);
9. registrar freshness da fonte (seção 19);
10. montar e validar o output contra `output.schema.json`.

---

## 12. Blocos de dados a extrair

Extrair, quando presentes na seção do cliente, organizados em `data`:

1. **business_identity** — razão social, nome fantasia, CNPJ, localização, segmento, área de atuação.
2. **stakeholders** — lista de `{ nome, papel, contato, observações }`.
3. **commercial_context** — produtos, serviços, ofertas, ticket, condições comerciais, diferenciais.
4. **market_context** — públicos mencionados, região, particularidades de mercado.
5. **operation_scope** — serviços V4 mencionados, investimento, fee, mídia, canais.
6. **documented_strategy** — objetivos explicitamente registrados, frentes, campanhas, direcionamentos, posicionamento. Preservar como conteúdo **documentado pela fonte**; nunca produzir estratégia nova aqui.
7. **brand_and_creative** — identidade, cores, fontes, restrições, CTAs, regras criativas.
8. **tracking_and_technology** — ferramentas, CRM, analytics, pixel, landing pages, integrações.
9. **operational_history** — acontecimentos relevantes, entregas mencionadas, problemas registrados, mudanças documentadas.
10. **decisions** — itens `type: decision`.
11. **requests** — itens `type: request`.
12. **commitments** — itens `type: commitment`.
13. **pending** — itens `type: pending`.
14. **risks** — itens `type: risk`.
15. **dependencies** — itens `type: dependency`.
16. **links_and_references** — ver seção 13 (também espelhado em `discovered_sources`).
17. **missing_relevant_information** — lacunas percebidas que não se encaixam em `missing_data` estruturado, mas que são relevantes para entendimento do cliente.

Cada bloco é opcional — a ausência de um bloco inteiro não é, por si só, um erro (ver seção 17). Não forçar todos os clientes a caber exatamente nesses blocos: campos adicionais relevantes podem ser preservados dentro do bloco mais próximo semanticamente, sem inventar estrutura rígida demais.

Itens dos blocos 10–15 (decisions, requests, commitments, pending, risks, dependencies) devem conter, no mínimo: `statement`, `type`, `confidence`, e ao menos um `evidence_id` associado.

---

## 13. Hyperlinks e Taxonomia de Links

Extrair todos os hyperlinks presentes na seção isolada do cliente. Preservar. Classificar quando possível. **Nunca abrir.**

Taxonomia:

- `website`;
- `landing_page`;
- `whatsapp`;
- `whatsapp_group`;
- `google_doc`;
- `spreadsheet`;
- `drive_folder`;
- `contract`;
- `crm`;
- `bi`;
- `social_profile`;
- `public_registry`;
- `attachment`;
- `documentation`;
- `unknown`.

Classificação deve considerar domínio, texto âncora, e contexto do trecho. Quando ambígua: preservar o link, usar `type: unknown`, gerar warning.

Todo link identificado deve aparecer em `discovered_sources`, com `opened: false` (a skill nunca abre links).

---

## 14. Evidências

Gerar evidências (`schemas/evidence.schema.json`) para:

- classificação da fonte (`source_kind`/`source_compatible`);
- resultado da detecção de seção (`client_found`, limites);
- cada fato, métrica, decisão, hipótese, request, commitment, pending, risk, idea ou dependency relevante extraído;
- existência de cada link relevante descoberto.

Não criar evidência para cada palavra ou frase irrelevante — apenas para conteúdo operacionalmente relevante.

Para PDF, `reference.location` deve preservar a página (e, quando possível, a seção/parágrafo) de onde o conteúdo foi extraído.

---

## 15. Output

Salvar output temporário em:

```
context/generated/<client_id>/client-context.json
```

O output deve validar contra `skills/read-client-context/output.schema.json`.

Esta skill **não** grava em `clients/<client_id>/`. Nenhum arquivo de memória canônica é alterado.

---

## 16. Status de execução

- `success` — cliente encontrado, seção delimitada com confiança adequada, extração concluída;
- `partial` — cliente encontrado, mas limites de seção parcialmente inseguros, fonte parcialmente ilegível, ou lacunas relevantes que não impedem uso parcial do resultado;
- `failed` — fonte incompatível (seção 8.5) ou cliente não encontrado / seção não delimitável com segurança (seção 9.4).

---

## 17. Missing Data

Registrar `missing_data` somente quando a ausência:

- limita entendimento relevante do cliente;
- contradiz expectativa explícita da fonte (ex.: a fonte referencia um anexo/seção que deveria existir mas não foi encontrada);
- será importante para workflows posteriores (diagnóstico, replanejamento).

Não registrar como `missing_data` a simples ausência de um bloco opcional sem indício de que deveria existir.

---

## 18. Warnings

Gerar warning quando:

- a fonte for incompatível (source type mismatch);
- o cliente não for encontrado ou a seção não puder ser delimitada com segurança;
- um link não puder ser associado ou classificado com segurança;
- houver conflito aparente entre trechos da própria seção;
- houver indício de que informação documentada pode estar desatualizada;
- houver ambiguidade entre o conteúdo do cliente solicitado e o de outro cliente na mesma fonte.

---

## 19. Freshness

Registrar, quando disponível:

- data do documento/fonte (`source.source_date`);
- data de execução da leitura (`generated_at`);
- para cada evidência sensível ao tempo, a data associada ao trecho de origem, quando diferente da data geral do documento.

Não assumir que informação de um handoff antigo continua vigente. Quando algo parecer temporalmente sensível (ex.: estratégia, budget, responsável), preservar a data e sinalizar isso via warning, permitindo que workflows posteriores confrontem com fontes mais recentes.

---

## 20. Confiança

Usar `low`/`medium`/`high` em:

- `source_qualification.confidence`;
- `section_detection.confidence`;
- `confidence` de cada evidência.

Não usar `high` apenas porque a informação parece plausível — refletir qualidade e clareza real da fonte.

---

## 21. Regras

Esta skill deve:

- respeitar CLAUDE.md;
- operar somente no `client_id` solicitado;
- carregar somente a fonte necessária;
- preservar rastreabilidade (evidência para todo elemento relevante);
- diferenciar observação (o que a fonte diz) de interpretação (o que isso significa) — esta skill faz apenas o primeiro;
- declarar lacunas e conflitos aparentes;
- preservar conteúdo estratégico documentado como *documentado*, não como estratégia validada ou vigente.

---

## 22. Proibições

read-client-context não pode:

- inventar dados, métricas, metas, datas, prazos, responsáveis, decisões, campanhas, budgets, resultados, escopo, solicitações do cliente, tarefas concluídas ou informações comerciais;
- absorver conteúdo pertencente a outro cliente presente na mesma fonte;
- transformar `hypothesis` em `fact`, `idea` em `decision`, `request` em `commitment`, ou `pending` em tarefa;
- abrir ou seguir qualquer hyperlink descoberto;
- diagnosticar performance, maturidade ou saúde do cliente;
- gerar estratégia nova, replanejamento ou tarefas;
- atualizar `clients/<client_id>/client.json`, `strategy.md`, `current-state.json`, `decisions.json` ou `sources.json`;
- processar uma fonte estruturalmente incompatível (BI, transcrição, WhatsApp, lista de tarefas, BU/índice) como se fosse documentação contextual;
- retornar `status = success` quando `source_compatible = false` ou `client_found = false` — nesses casos o correto é `status = failed`;
- executar outra skill.

---

## 23. Side Effects

**NONE.**

Somente leitura da fonte informada e geração de contexto temporário em `context/generated/<client_id>/client-context.json`.

---

## 24. Idempotência

Executar `read-client-context` novamente sobre a mesma versão da fonte, com o mesmo `client_id`/`client_selector`, deve produzir semanticamente o mesmo resultado — mesma classificação de fonte, mesma delimitação de seção, mesmo conjunto de dados e evidências.

Não duplicar evidências ou links apenas porque a skill foi executada novamente.

---

## 25. Critérios de qualidade

Antes de concluir, verificar:

1. a fonte correta foi lida?
2. o cliente correto foi identificado?
3. a seção correta (limites) foi determinada e registrada?
4. não houve contaminação de conteúdo de outro cliente?
5. fatos e hipóteses estão diferenciados corretamente?
6. toda conclusão relevante possui evidência rastreável?
7. todos os links foram preservados sem serem abertos?
8. nenhuma estratégia nova foi inventada — apenas a documentada foi preservada?
9. nenhum dado foi inventado?
10. nenhuma ação externa foi executada?
11. o output valida contra `output.schema.json`?
12. o `status` reflete corretamente o resultado (success/partial/failed)?

---

## 26. Falhas

Em caso de falha (`source_compatible = false` ou `client_found = false`):

- não fabricar output válido artificialmente;
- registrar o motivo em `warnings`;
- preservar outputs anteriores confiáveis de `context/generated/<client_id>/client-context.json`, quando existirem, em vez de sobrescrevê-los com um resultado vazio sem necessidade;
- informar o que seria necessário para uma nova tentativa (ex.: fonte correta, `client_selector` mais preciso, página aproximada).

---

## 27. Exemplos

Exemplos aprovados devem ficar em:

```
skills/read-client-context/examples/
```

Preferencialmente contendo `input`, `expected-output` e observações de qualidade.

---

## 28. Resultado esperado

read-client-context responde:

O que esta fonte documenta sobre este cliente específico, com que confiança, e a partir de qual trecho exato?

Ela não responde:

O cliente está indo bem? O que devemos fazer agora?

Essas responsabilidades pertencem às skills de inteligência (`diagnose-client`, `identify-priorities`, `replan-client`) e de ação subsequentes.
