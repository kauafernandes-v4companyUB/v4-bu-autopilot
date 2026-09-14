# SKILL — READ ACCOUNT × GT

## 1. Identificação

Nome: Read Account × GT

Slug: read-account-gt

Categoria: source

Versão: 1.0.0

Side Effects: NONE

---

## 2. Objetivo

Ler uma transcrição ou ata da reunião semanal entre Account Manager e Gestor de Tráfego (GT) e transformar SOMENTE o que foi efetivamente dito em contexto operacional estruturado e evidências rastreáveis, para UM `client_id` específico.

A skill observa e normaliza uma fonte interna de planejamento semanal. Ela não diagnostica, não calcula gap, não replaneja, não gera tarefas e não atualiza memória.

---

## 3. Quando usar

Usar quando for necessário ler, para um `client_id` específico:

- transcrição da reunião semanal Account × GT (`account_gt_transcript`);
- ata/notas de planejamento da reunião Account × GT (`account_gt_meeting_notes`).

---

## 4. Quando NÃO usar

Não usar para:

- ler check-in com o cliente (`client_checkin_transcript` — pertence a outra skill de leitura de check-in);
- ler handoff de Account Manager ou de cliente (`read-client-context`);
- ler exportação de WhatsApp (`read-whatsapp`);
- ler BI/dashboard/planilha de métricas (`read-bi`);
- ler CRM (`crm_export`);
- ler eKyte ou qualquer exportação/lista de tarefas (`read-ekyte`, `task_export`, `task_list`);
- diagnosticar performance (`diagnose-client`);
- calcular gap (`calculate-gap`);
- definir prioridades (`identify-priorities`);
- gerar replanejamento (`replan-client`);
- gerar tarefas (`generate-tasks`);
- atualizar memória canônica (`update-client-state`, `update-history`);
- publicar qualquer coisa (`publish-ekyte`).

Essas responsabilidades pertencem a outras skills.

---

## 5. Responsabilidade

Esta skill é responsável por:

- qualificar a fonte antes de qualquer extração semântica;
- localizar e isolar a seção/discussão pertencente ao `client_id` solicitado, quando a reunião cobrir múltiplos clientes;
- preservar speaker attribution e inferir `normalized_role` quando seguro;
- extrair metadados da reunião (`meeting_type`, `source_date`, período discutido) somente quando sustentados pela fonte;
- extrair, por bloco semântico: menções de performance, campanhas/iniciativas, feedback comercial, contexto relatado do cliente, decisões internas, propostas de planejamento, ações planejadas, requests, commitments, pending, risks, dependencies, flags, referências e lacunas;
- aplicar corretamente a hierarquia de autoridade da fonte (seção 16) a cada tipo de informação extraída;
- gerar evidências rastreáveis para todo elemento operacionalmente relevante;
- registrar freshness (data da reunião) e declarar quando não sustentada;
- declarar lacunas relevantes e conflitos aparentes.

Esta skill NÃO é responsável por:

- diagnosticar performance, maturidade ou saúde do cliente;
- calcular gap entre resultado e meta;
- definir ou validar estratégia nova;
- decidir prioridades ou gerar replanejamento;
- gerar tarefas ou publicar no eKyte;
- atualizar `clients/<client_id>/*` (memória canônica);
- transformar relato indireto (fala do Account sobre o cliente) em fala direta do cliente;
- transformar métrica verbal de reunião interna em dado canônico de BI;
- abrir links ou buscar informação externa;
- misturar conteúdo de dois clientes.

---

## 6. Inputs

Obrigatórios:

- `client_id`;
- referência da fonte (`source_path` ou `source_url`).

Opcionais:

- `client_selector` — nome/termo usado para localizar a discussão do cliente na reunião (ex.: nome fantasia). Quando ausente, a skill tenta usar `display_name` conhecido do cliente ou o próprio `client_id`;
- `expected_meeting_date` — data aproximada esperada da reunião, quando conhecida previamente (ex.: a partir de `sources.json` ou de rotina semanal), usada apenas para apoiar a localização — nunca para preencher `meeting.source_date` silenciosamente;
- contexto anterior (ex.: `clients/<client_id>/client.json`) apenas para apoiar a identificação do cliente na fonte — nunca para preencher lacunas de conteúdo.

Nunca assumir `client_selector` silenciosamente quando o nome puder ser ambíguo dentro da fonte.

---

## 7. Fontes permitidas

A skill pode ler:

- transcrição de reunião (texto, .vtt/.srt convertido, ou exportação de texto de gravação);
- ata/notas de planejamento da reunião Account × GT;
- outra fonte autorizada em `clients/<client_id>/sources.json` compatível com os tipos da seção 8.2.

Não consultar outras fontes sem necessidade operacional ou autorização definida. Não seguir links encontrados dentro da fonte.

---

## 8. Qualificação da Fonte (Source Qualification)

Etapa **obrigatória**, executada **antes de qualquer extração semântica**.

### 8.1 Objetivo

Impedir que uma fonte estruturalmente incompatível seja processada como se fosse uma reunião de planejamento Account × GT. A simples presença de palavras como "tráfego", "campanha" ou "Account" não basta — a fonte precisa representar claramente uma conversa/ata de planejamento entre Account e responsável de mídia/tráfego.

### 8.2 Tipos compatíveis (`source_compatible = true`)

- `account_gt_transcript` — transcrição da reunião semanal Account × GT;
- `account_gt_meeting_notes` — ata/notas de planejamento da reunião Account × GT.

### 8.3 Tipos incompatíveis (`source_compatible = false`)

- `client_checkin_transcript` — transcrição de check-in com o cliente;
- `client_handoff` — handoff específico de cliente;
- `account_handoff` — handoff de Account Manager;
- `whatsapp_export` — exportação de WhatsApp;
- `bi_dashboard` — BI, dashboard, export de métricas;
- `crm_export` — export de CRM;
- `task_export` — exportação de tarefas;
- `task_list` — lista de tarefas;
- `unrelated_document` — arquivo sem relação identificável com o cliente solicitado;
- `unknown` — não foi possível determinar com segurança.

### 8.4 Procedimento de qualificação

1. observar a forma geral da fonte (conversa/ata de planejamento interno Account × GT vs. outra natureza);
2. verificar se os participantes identificáveis são compatíveis com uma reunião interna Account × GT (não uma call com o cliente presente como parte central, não um export estruturado de dados);
3. verificar se a fonte contém, em algum ponto, conteúdo identificável como pertencente ao `client_id`/`client_selector` solicitado;
4. classificar `source_kind` conforme 8.2/8.3;
5. definir `source_compatible` (`true` somente para os tipos listados em 8.2);
6. atribuir `confidence` (`low`/`medium`/`high`) à classificação;
7. registrar uma evidência (`type: fact`) descrevendo a natureza observada da fonte — fato sobre a fonte, não sobre o cliente;
8. se `source_compatible = false`, seguir 8.5 e **parar** — não prosseguir para a seção 9;
9. se `source_compatible = true`, prosseguir para a seção 9 (Client Isolation).

### 8.5 Tratamento de fonte incompatível

Quando `source_compatible = false`:

- **não** realizar extração semântica;
- `status = failed`;
- `data` deve conter apenas os blocos vazios ou ausentes (nenhuma extração);
- `client_section.client_found = false`;
- registrar em `warnings` uma mensagem clara de *source type mismatch*, citando o `source_kind` detectado;
- registrar em `missing_data` que a extração não foi realizada por incompatibilidade de fonte;
- sugerir, quando possível, a skill/categoria adequada (ex.: `read-client-context`, `read-whatsapp`, `read-bi`) em `source_qualification.suggested_skill`, **sem executá-la**.

---

## 9. Client Isolation

Etapa **obrigatória** quando `source_compatible = true`, executada **antes da extração de dados** (seção 15).

### 9.1 Objetivo

A reunião pode conter um ou vários clientes. Garantir que somente o conteúdo pertencente ao `client_id` solicitado seja extraído.

### 9.2 Procedimento

1. confirmar que o cliente solicitado aparece ou pode ser identificado na fonte, usando `client_selector` (ou `display_name`/`client_id` como fallback);
2. localizar o início da discussão do cliente (ex.: menção explícita ao nome, mudança de assunto, marcador textual, timecode);
3. localizar o fim da discussão do cliente (ex.: início da discussão do próximo cliente, encerramento da pauta, fim do documento);
4. usar conteúdo adjacente somente para confirmar com segurança os limites da discussão — nunca para complementar conteúdo do cliente;
5. se a conversa alternar entre clientes sem seções formais, usar menções, mudança explícita de assunto e contexto para delimitar, reduzindo `confidence` quando necessário;
6. impedir que qualquer conteúdo identificado como pertencente a outro cliente seja incluído em `data`, `references` ou `evidence` deste output;
7. registrar como a delimitação foi feita (`start_reference`, `end_reference`) e a confiança dessa delimitação em `client_section`.

### 9.3 Quando a delimitação não é segura

- cliente não encontrado → `client_found = false`, `status = failed`, `data` sem extração, warning obrigatório;
- limites parcialmente inseguros (cliente encontrado, mas início ou fim ambíguo) → `status = partial`, extrair apenas o que estiver claramente dentro dos limites seguros, `confidence = low` em `client_section`, warning obrigatório;
- nunca atribuir ao cliente, como fato, conteúdo situado em região ambígua entre duas discussões.

---

## 10. Speakers

Preservar speaker attribution quando possível, em `speakers` (top-level).

Para cada speaker identificado dentro da seção do cliente, registrar:

- `speaker_label` — rótulo original (nome, "Speaker 1", cargo, etc.);
- `normalized_role` — quando identificável com segurança:
  - `account`;
  - `traffic_manager`;
  - `other_internal`;
  - `client`;
  - `unknown`.
- `name` — apenas quando a identidade puder ser inferida com segurança; caso contrário `null`.

Nunca inventar identidade de speaker. Se apenas o papel puder ser inferido com segurança, preservar o papel e deixar `name` ausente (`null`).

---

## 11. Meeting Metadata

Extrair, em `meeting`, quando sustentado pela fonte:

- `meeting_type` — ex.: "account_gt_weekly"; `null` se não sustentado;
- `source_date` — data da reunião, **somente se explicitamente sustentada pela fonte** (timecode com data, cabeçalho da ata, menção textual inequívoca); caso contrário `null`;
- `period_discussed` — período (semana/mês) referido na conversa, quando sustentado; caso contrário `null`;
- `notes` — observações relevantes sobre os metadados, quando necessário; caso contrário `null`.

Nunca usar data do arquivo ou data de execução como data da reunião silenciosamente. Nunca inferir `meeting.source_date` a partir de `expected_meeting_date` (input opcional) sem confirmação textual na própria fonte — nesse caso, permanece `null` e a expectativa vira, no máximo, um `warning`.

---

## 12. Timestamps de Execução

`generated_at` e todo `observed_at` de evidência:

- devem vir do relógio REAL do sistema no momento da execução;
- formato UTC RFC3339;
- consultar via `date -u +"%Y-%m-%dT%H:%M:%SZ"` ou equivalente confiável;
- nunca estimar, nunca arredondar, nunca copiar de exemplo, nunca inferir do conteúdo da fonte;
- antes de concluir, comparar com o relógio real — um timestamp de execução significativamente no futuro é falha de validação, refletida em `warnings` e no `status`.

Ver CLAUDE.md seção 26 para a regra completa. `observed_at` (quando o sistema leu a evidência) nunca deve ser confundido com `meeting.source_date` ou `source_date` de uma evidência específica (quando a própria fala/trecho sustenta uma data distinta da data geral da reunião).

---

## 13. Pré-condições

Antes de executar, verificar:

1. `client_id` identificado;
2. fonte disponível e acessível;
3. fonte pertence, declarada ou plausivelmente, ao cliente correto (`clients/<client_id>/sources.json`, quando existir entrada correspondente);
4. Qualificação da Fonte (seção 8) executada;
5. Client Isolation (seção 9) executada, quando `source_compatible = true`.

Se alguma pré-condição falhar, registrar o problema em vez de inventar informação.

---

## 14. Procedimento

Executar nesta ordem:

0. executar Qualificação da Fonte (seção 8); se `source_compatible = false`, seguir 8.5 e encerrar;
1. executar Client Isolation (seção 9); se `client_found = false`, seguir 9.3 e encerrar;
2. identificar e registrar `speakers` (seção 10) dentro da seção do cliente;
3. extrair `meeting` metadata (seção 11), somente o sustentado pela fonte;
4. ler somente o conteúdo dentro dos limites determinados da discussão do cliente;
5. extrair informações relevantes por bloco semântico (seção 15), aplicando a Hierarquia de Autoridade (seção 16) a cada item;
6. classificar cada elemento segundo os tipos de conhecimento (CLAUDE.md seção 5);
7. gerar evidências para todo elemento operacionalmente relevante (seção 17), preservando referência em transcrição (seção 18);
8. registrar `missing_data` relevante (seção 21);
9. registrar `warnings` relevantes (seção 22);
10. registrar freshness (seção 23);
11. montar e validar o output contra `output.schema.json`.

---

## 15. Blocos de extração (`data`)

Extrair, quando presentes na discussão do cliente, organizados em `data`:

1. **performance_mentions** — métricas e resultados citados verbalmente na reunião. `type` sempre `metric`. Preservar `period` quando citado. Todo item carrega `reported_in_meeting: true` (fixo) para deixar explícito que é uma métrica reportada em reunião interna — nunca substitui BI/CRM/plataforma.
2. **campaigns_and_initiatives** — campanhas ativas, planejadas, a pausar, testes, frentes de mídia, produtos/ofertas discutidos. `campaign_status`: `active` / `planned` / `to_pause` / `test` / `unknown`.
3. **commercial_feedback** — vendas relatadas, qualidade de leads, feedback de vendedores, motivos de perda, estoque, prioridade comercial, e qualquer outra informação comercial relatada.
4. **client_reported_context** — informações que o Account diz terem vindo do cliente. Preservar `reported_by`, `attributed_to_client`, `indirect: true` (fixo). Ver regra de autoridade na seção 16.2.
5. **decisions** — somente decisões internas explicitamente tomadas entre os participantes. `type` sempre `decision`. Exigem `requires_client_validation` e ao menos um `evidence_id`.
6. **planning_proposals** — ideias/propostas ainda não decididas. `type` restrito a `idea` ou `hypothesis` — nunca `decision`.
7. **planned_actions** — movimentos operacionais combinados ou pretendidos. `status`: `proposed` / `agreed_internal` / `requires_client_validation` / `blocked` / `unknown`. **`planned_action` não significa tarefa existente no eKyte.**
8. **requests** — itens `type: request`.
9. **commitments** — itens `type: commitment`.
10. **pending** — itens `type: pending`.
11. **risks** — itens `type: risk`.
12. **dependencies** — itens `type: dependency`.
13. **flags** — sinalizações operacionais relevantes que não se encaixam nos tipos acima (ex.: ambiguidade relevante, item que merece atenção de outra skill).
14. **references** — links/anexos mencionados na reunião, preservados e classificados, **nunca abertos** (`opened: false` fixo).
15. **missing_relevant_information** — lacunas percebidas que não se encaixam em `missing_data` estruturado, mas relevantes para entendimento do que foi discutido.

Cada bloco é opcional — a ausência de um bloco inteiro não é, por si só, um erro (ver seção 21). Itens dos blocos 3, 8–12 devem conter, no mínimo: `statement`, `type` (correspondente ao bloco), `confidence`, e ao menos um `evidence_id` associado.

---

## 16. Hierarquia / Autoridade

Aplicar explicitamente a cada item extraído:

### 16.1 Métrica mencionada verbalmente

- classificar como `metric`;
- preservar o valor dito;
- marcar `reported_in_meeting: true`;
- não tratá-la como substituta de BI/CRM/plataforma — isso é papel de `read-bi`/`read-ekyte`/fontes estruturadas.

Exemplo: "ontem tivemos 12 leads a R$ 18" → `performance_mentions`, `type: metric`, `reported_in_meeting: true`.

### 16.2 Pedido do cliente relatado pelo Account

- preservar que é **relato indireto** (`indirect: true`);
- não equivaler automaticamente a fala direta do cliente;
- `confidence` normalmente não deve superar `medium` sem corroboração de check-in/WhatsApp/fonte direta (usar `corroborated: true` apenas quando essa corroboração já constar explicitamente na própria fonte lida nesta execução; do contrário manter `corroborated` ausente/`false`).

Exemplo: "Jean falou que quer focar aço essa semana", dita pelo Account, é modelada em `client_reported_context` com `reported_by: "Account"`, `attributed_to_client: "Jean"`, `indirect: true` — nunca como evidência direta de fala do Jean.

### 16.3 Decisão interna Account × GT

- pode ser classificada como `decision` apenas se estiver explicitamente decidida entre os participantes;
- se depender do cliente, preservar `requires_client_validation: true`.

Exemplo: "vamos subir aço amanhã", entre Account e GT, pode ser `decision` (se afirmada como decidida) ou `planned_action` (se ainda condicional), dependendo da clareza do compromisso.

### 16.4 Ideia ou sugestão

- nunca promover para `decision`;
- usar `idea` (possibilidade ainda não avaliada) ou `hypothesis` (interpretação ainda não comprovada) conforme a natureza.

Exemplo: "acho que cadeira pode funcionar" → `idea`/`hypothesis` em `planning_proposals`.

### 16.5 Planejamento para execução

- não confundir com tarefa já criada no eKyte;
- registrar apenas como `planned_action` / commitment / pending conforme o que foi efetivamente dito.

---

## 17. Evidências

Gerar evidências (`schemas/evidence.schema.json`) para:

- classificação da fonte (`source_kind`/`source_compatible`);
- resultado do Client Isolation (`client_found`, limites);
- cada fato, métrica, decisão, hipótese, request, commitment, pending, risk, idea ou dependency operacionalmente relevante extraído.

Tipos oficiais (nunca elevar semanticamente): `fact`, `metric`, `decision`, `hypothesis`, `request`, `commitment`, `pending`, `risk`, `idea`, `dependency`.

Não criar evidência para cada palavra ou frase irrelevante — apenas para conteúdo operacionalmente relevante.

---

## 18. Referência em Transcrição

`reference` de cada evidência (`schemas/evidence.schema.json`) deve tentar preservar, dentro de `reference.location`:

- `speaker` — quem falou, quando identificável;
- timestamp da gravação/transcrição, quando houver;
- linha/bloco/parágrafo, quando houver;
- label textual suficiente para localizar o trecho, em `reference.label`.

Não inventar timecode. Quando um desses elementos não existir na fonte, omiti-lo — não preencher com valor plausível.

---

## 19. Output

Salvar futuramente em:

```
context/generated/<client_id>/account-gt.json
```

Esta skill **não** grava neste caminho durante seu desenho/teste, e **não** grava em `clients/<client_id>/`. Nenhum arquivo de memória canônica é alterado.

O output deve validar contra `skills/read-account-gt/output.schema.json`.

---

## 20. Status de execução

- `success` — fonte compatível, cliente encontrado, discussão delimitada com confiança adequada, extração concluída;
- `partial` — fonte compatível, cliente encontrado, mas limites parcialmente inseguros, trechos ilegíveis, ou lacunas relevantes que não impedem uso parcial do resultado;
- `failed` — fonte incompatível (seção 8.5) ou cliente não encontrado / discussão não delimitável com segurança (seção 9.3).

---

## 21. Missing Data

Registrar `missing_data` quando a ausência:

- limita entendimento relevante do que foi discutido sobre o cliente;
- contradiz expectativa explícita da fonte (ex.: ata referencia um anexo/decisão que deveria constar mas não foi encontrada);
- será importante para workflows posteriores (diagnóstico, replanejamento) — ex.: `meeting.source_date` ausente.

Não registrar como `missing_data` a simples ausência de um bloco opcional sem indício de que deveria existir.

---

## 22. Warnings

Gerar warning quando:

- a fonte for incompatível (source type mismatch);
- o cliente não for encontrado ou a discussão não puder ser delimitada com segurança;
- houver ambiguidade entre o conteúdo do cliente solicitado e o de outro cliente na mesma reunião;
- `meeting.source_date` não puder ser sustentada pela fonte;
- houver conflito aparente entre trechos da própria discussão;
- uma métrica verbal parecer inconsistente com o que seria esperado (sem corrigir — apenas sinalizar);
- um timestamp de execução gerado estiver no futuro em relação ao relógio real (CLAUDE.md seção 26.4).

---

## 23. Freshness

Esta skill é particularmente temporal. Registrar:

- `meeting.source_date` — data da reunião, somente se sustentada pela fonte; caso contrário `null` com warning;
- `generated_at` — timestamp de execução (seção 12);
- para cada evidência sensível ao tempo (ex.: `performance_mentions`), `period` quando citado no trecho.

Se a data da reunião for conhecida e recente, isso poderá ser usado **futuramente por outra skill** para alimentar `current-state.json`. `read-account-gt` **não altera** `current-state.json` nem qualquer outro arquivo em `clients/<client_id>/`.

---

## 24. Confiança

Usar `low`/`medium`/`high` em:

- `source_qualification.confidence`;
- `client_section.confidence`;
- `confidence` de cada evidência e de cada item classificado em `data`.

Não usar `high` apenas porque a informação parece plausível. Para `client_reported_context`, ver regra de teto de confiança na seção 16.2.

---

## 25. Regras

Esta skill deve:

- respeitar CLAUDE.md;
- operar somente no `client_id` solicitado;
- carregar somente a fonte necessária;
- preservar rastreabilidade (evidência para todo elemento relevante);
- diferenciar observação (o que foi dito) de interpretação — esta skill faz apenas o primeiro;
- aplicar a Hierarquia de Autoridade (seção 16) sem exceção;
- declarar lacunas e conflitos aparentes.

---

## 26. Proibições

`read-account-gt` não pode:

- diagnosticar;
- calcular gap;
- recomendar estratégia nova;
- gerar replanejamento;
- criar tarefas;
- alterar eKyte;
- alterar memória (`clients/<client_id>/*`);
- abrir links;
- buscar informações externas;
- transformar plano em execução (planned_action ≠ tarefa eKyte);
- transformar relato indireto em fala direta do cliente;
- transformar métrica verbal em dado estruturado de BI;
- misturar clientes;
- inventar dados, métricas, metas, datas, prazos, responsáveis, decisões, campanhas, budgets, resultados, escopo, solicitações do cliente, tarefas concluídas ou informações comerciais;
- promover `hypothesis`/`idea` a `decision`, `request` a `commitment`, ou `pending` a tarefa;
- retornar `status = success` quando `source_compatible = false` ou `client_found = false` — nesses casos o correto é `status = failed`;
- executar outra skill.

---

## 27. Side Effects

**NONE.**

Somente leitura da fonte informada e (quando executada) geração de contexto temporário em `context/generated/<client_id>/account-gt.json`.

---

## 28. Idempotência

Executar `read-account-gt` novamente sobre a mesma versão da fonte, com o mesmo `client_id`/`client_selector`, deve produzir semanticamente o mesmo resultado — mesma classificação de fonte, mesma delimitação de discussão, mesmo conjunto de dados e evidências.

Não duplicar registros apenas porque a skill foi executada novamente.

---

## 29. Critérios de qualidade

Antes de concluir, verificar:

1. a fonte correta foi lida e corretamente qualificada?
2. o cliente correto foi identificado e a discussão corretamente delimitada?
3. não houve contaminação de conteúdo de outro cliente?
4. a Hierarquia de Autoridade (seção 16) foi aplicada a cada item (métrica verbal ≠ BI; relato indireto ≠ fala direta; decisão ≠ ideia)?
5. toda decisão possui `evidence_ids` não vazio e `requires_client_validation` preenchido?
6. nenhuma `planning_proposal` foi classificada como `decision`?
7. `planned_actions` não foram confundidas com tarefas do eKyte?
8. toda conclusão relevante possui evidência rastreável, com referência em transcrição preservada quando disponível?
9. nenhum dado foi inventado?
10. nenhuma ação externa foi executada?
11. o output valida contra `output.schema.json`?
12. o `status` reflete corretamente o resultado (success/partial/failed)?
13. `generated_at` e todo `observed_at` vieram do relógio real do sistema, sem estar no futuro (CLAUDE.md seção 26)?
14. `meeting.source_date` não foi preenchido com a data de execução nem inferido/estimado quando a fonte não sustenta sua própria data?

---

## 30. Falhas

Em caso de falha (`source_compatible = false` ou `client_found = false`):

- não fabricar output válido artificialmente;
- registrar o motivo em `warnings`;
- preservar outputs anteriores confiáveis de `context/generated/<client_id>/account-gt.json`, quando existirem, em vez de sobrescrevê-los com um resultado vazio sem necessidade;
- informar o que seria necessário para uma nova tentativa (ex.: fonte correta, `client_selector` mais preciso, trecho aproximado).

---

## 31. Exemplos

Exemplos aprovados devem ficar em:

```
skills/read-account-gt/examples/
```

Preferencialmente contendo `input`, `expected-output` e observações de qualidade. Nenhum exemplo foi salvo neste desenho inicial — instâncias de teste foram validadas apenas em memória (ver processo de validação da skill).

---

## 32. Resultado esperado

`read-account-gt` responde:

O que foi efetivamente dito, por quem, com que grau de autoridade e confiança, na reunião Account × GT sobre este cliente específico — e a partir de qual trecho exato?

Ela não responde:

O cliente está indo bem? O que devemos fazer agora? Essas informações substituem o BI?

Essas responsabilidades pertencem às skills de inteligência (`diagnose-client`, `calculate-gap`, `identify-priorities`, `replan-client`) e às fontes estruturadas de métricas (`read-bi`, `read-ekyte`).
