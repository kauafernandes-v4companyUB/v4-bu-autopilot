# SKILL — PROMOTE CLIENT MEMORY

## 1. Identificação

Nome: Promote Client Memory

Slug: promote-client-memory

Categoria: action

Versão: 1.0.0

Side Effects: MEMORY

---

## 2. Objetivo

Transformar contexto temporário já normalizado e validado (output de skills de observação ou de inteligência) em memória canônica persistente de UM cliente, decidindo item a item o que merece promoção, para onde vai, e registrando conflitos em vez de sobrescrevê-los silenciosamente.

Esta skill materializa conhecimento já produzido por outras skills. Ela não observa fontes brutas, não diagnostica, não replaneja e não cria tarefas.

---

## 3. Quando usar

Usar quando:

- existir um output confiável em `context/generated/<client_id>/` (ex.: `client-context.json`) e for necessário decidir o que dele deve virar memória canônica;
- a operação disser explicitamente algo como "atualize o contexto da walmaq", "promova isso para a memória", "consolide o que aprendemos sobre X";
- uma skill de inteligência (`diagnose-client`, `replan-client`, ...) tiver produzido conclusões validadas que precisem persistir para execuções futuras;
- for necessário registrar formalmente uma decisão, meta, stakeholder, fonte nova ou elemento de estratégia já observado, com evidência.

---

## 4. Quando NÃO usar

Não usar para:

- ler PDF, WhatsApp, transcrição, BI, eKyte ou qualquer fonte bruta diretamente (`read-bu`, `read-client-context`, `read-transcript`, `read-whatsapp`, `read-account-gt`, `read-bi`, `read-ekyte`);
- diagnosticar performance, maturidade ou saúde do cliente (`diagnose-client`);
- calcular gap, identificar prioridades ou gerar replanejamento (`calculate-gap`, `identify-priorities`, `replan-client`);
- auditar um plano (`audit-plan`);
- gerar tarefas (`generate-tasks`);
- executar ações externas (`publish-ekyte`, criação de tarefa em sistema externo, envio de mensagem, etc.);
- transformar automaticamente todo output temporário em memória — isso viola a seção 16 do CLAUDE.md.

Essas responsabilidades pertencem a outras skills.

---

## 5. Responsabilidade

Esta skill é responsável por:

- ler outputs confiáveis já produzidos por outras skills (source ou intelligence) e a memória canônica atual do cliente;
- avaliar cada informação candidata quanto a utilidade futura, sustentação por evidência, pertencimento ao cliente correto, adequação ao destino canônico e temporalidade;
- classificar cada candidato como `promote`, `skip`, `conflict`, `supersede` ou `historize`;
- montar um `promotion_plan` completo e auditável antes de qualquer escrita;
- em modo `apply`, escrever somente o que está no plano validado, preservando histórico e provenance;
- registrar conflitos não resolvidos em vez de sobrescrever silenciosamente;
- criar `schemas/client-knowledge.schema.json` como contrato de `clients/<client_id>/knowledge.json` (o arquivo em si só é criado na primeira promoção real).

Esta skill NÃO é responsável por:

- decidir se uma métrica é boa ou ruim, ou se uma estratégia está funcionando (`diagnose-client`);
- gerar novas hipóteses, prioridades ou replanejamento (`identify-priorities`, `replan-client`);
- gerar tarefas (`generate-tasks`);
- publicar ou alterar sistemas externos (`publish-ekyte` e equivalentes);
- reinterpretar ou corrigir o conteúdo dos outputs de origem — se um output de origem estiver incoerente ou incompleto, isso deve ser registrado como `warning`/`missing_data`, não silenciosamente corrigido.

---

## 6. Inputs

Obrigatórios:

- `client_id`;
- `source_outputs` — um ou mais caminhos de outputs confiáveis a considerar (ex.: `context/generated/walmaq/client-context.json`, `context/generated/walmaq/diagnosis.json`).

Opcionais:

- `mode` — `preview` (padrão) ou `apply`;
- `target_filter` — lista de `target_file` a considerar, quando o operador quiser restringir a promoção (ex.: apenas `knowledge.json`);
- `promotion_plan` previamente gerado — quando o input já é um plano revisado, a skill pode pular direto para a validação/execução em modo `apply` em vez de gerar um novo plano do zero.

Nunca assumir `client_id` ou `source_outputs` silenciosamente. Nunca inferir `source_outputs` vasculhando todo `context/generated/` sem indicação — isso violaria lazy loading (CLAUDE.md seção 3).

---

## 7. Fontes permitidas

A skill pode ler:

- outputs temporários em `context/generated/<client_id>/*.json` (contexto já observado/normalizado por outra skill);
- outputs de skills de inteligência já validados, quando fornecidos explicitamente como input (ex.: `diagnosis.json`, `replanning.json`);
- a memória canônica atual do cliente, exclusivamente para comparação/detecção de conflito e temporalidade:
  - `clients/<client_id>/client.json`;
  - `clients/<client_id>/sources.json`;
  - `clients/<client_id>/knowledge.json` (se existir);
  - `clients/<client_id>/current-state.json`;
  - `clients/<client_id>/decisions.json`;
  - `clients/<client_id>/strategy.md`;
  - `clients/<client_id>/history/`;
- `schemas/evidence.schema.json` e `schemas/client-knowledge.schema.json`, para validação.

A skill NUNCA lê diretamente:

- `private/**` (WhatsApp, transcrições, documentos brutos);
- PDFs, planilhas ou qualquer fonte primária;
- memória canônica de outro `client_id`.

---

## 8. Pré-condições

Antes de executar, verificar:

1. `client_id` identificado;
2. ao menos um `source_output` existe, é legível, e pertence ao `client_id` informado (campo `client_id` do próprio arquivo deve bater);
3. os arquivos canônicos de destino existem (mesmo que vazios/`unknown`) — se `knowledge.json` ainda não existir, isso não bloqueia o preview, apenas significa que toda promoção para essa categoria criará o arquivo pela primeira vez;
4. se `mode = apply`, um `promotion_plan` válido (gerado nesta execução ou fornecido como input) precisa existir antes de qualquer escrita.

Se alguma pré-condição falhar, registrar o problema em `missing_data`/`warnings` em vez de inventar informação, e retornar `status = failed` quando a falha impedir qualquer trabalho útil.

---

## 9. Destinos canônicos

| target_file | Uso |
|---|---|
| `clients/<client_id>/client.json` | Identidade básica, campos estruturais, metadados relativamente estáveis (ex.: `display_name`, `status`, `health`). |
| `clients/<client_id>/sources.json` | Novas fontes úteis, IDs de integração, referências permanentes. |
| `clients/<client_id>/knowledge.json` | Fatos estáveis/semiestáveis por categoria (ver seção 10). Contrato: `schemas/client-knowledge.schema.json`. |
| `clients/<client_id>/strategy.md` | Estratégia vigente documentada, objetivos estratégicos, posicionamento, ofertas, direcionamentos, marca, regras criativas, restrições, princípios. |
| `clients/<client_id>/current-state.json` | Situação atual, metas atuais, flags, pendências e dependências vigentes, estado operacional temporário. |
| `clients/<client_id>/decisions.json` | Decisões explícitas, com data, evidência, origem e vigência/status quando aplicável. |
| `clients/<client_id>/history/` | Snapshots que merecem preservação histórica, contextos substituídos relevantes, decisões superadas que não devem ser apagadas. |

Resumo semântico obrigatório dos cinco destinos com conteúdo substantivo (a memorizar antes de classificar qualquer candidato):

- **`knowledge.json`** = fatos e conhecimentos relativamente estáveis/semiestáveis sobre o cliente, independentes de qual mês ou campanha está em curso.
- **`strategy.md`** = orientação estratégica e operacional qualitativa — como pensar e decidir, não o que está acontecendo agora.
- **`current-state.json`** = fotografia temporal do agora — o que muda de mês a mês ou de campanha a campanha. Nunca um depósito genérico para qualquer `dependency`/`pending` só porque a fonte usou esse rótulo.
- **`decisions.json`** = decisões explícitas, tomadas de fato, nunca hipóteses, pedidos ou pendências.
- **`history/`** = informação passada relevante que não é mais vigente, mas merece rastreabilidade.

Cada `promotion_candidate` deve declarar exatamente um `target_file`.

---

## 9.1 `current-state.json` é fotografia temporal, não depósito genérico

`current-state.json` armazena **somente** o que está vigente **agora**:

- metas atuais;
- campanhas atuais;
- pendências atuais **confirmadas** (ver seção 12.1 — freshness de PENDING);
- dependências atuais;
- flags atuais;
- bloqueios atuais.

Regras permanentes de operação — válidas independentemente de qual mês, campanha ou produto está em jogo — **não são estado atual**. Elas são conhecimento estável sobre como a conta opera e pertencem a `knowledge.json` (tipicamente `operation_context`) ou a `strategy.md` quando forem orientação qualitativa de processo.

Exemplos que NUNCA vão para `current-state.json` só porque a fonte os descreveu como "dependency" ou "pending":

- "validar estoque antes de fechar campanha";
- "validar condição comercial antes de publicar preço/desconto em arte";
- "validar área exata de entrega antes de expandir mídia para nova região".

Essas são regras permanentes de como a conta funciona — não bloqueios do momento presente. Um candidato só pertence a `current-state.json/dependencies` quando descreve um bloqueio pontual amarrado a uma ação em andamento agora (ex.: "campanha de outubro está bloqueada aguardando confirmação de estoque de X"), não a uma regra geral que se aplica a qualquer campanha, de qualquer mês.

Antes de propor `target_file: current-state.json`, perguntar: "isso descreve o estado do cliente hoje, ou é uma regra permanente de como esta conta sempre funciona?" No segundo caso, o destino é `knowledge.json`/`operation_context` ou `strategy.md`.

---

## 9.2 Contratos e termos comerciais documentados em fonte histórica

Quando uma fonte narrativa/histórica (ex.: handoff sem data de emissão confiável) informar fee, escopo, data de início de contrato ou condições contratuais, a skill **não pode declarar que esses valores estão vigentes agora**. Vigência de contrato depende de confirmação por contrato atual ou fonte autorizada mais recente — não é assumida automaticamente pela existência do dado na fonte.

Ao promover esse tipo de informação (tipicamente a `knowledge.json/operation_context`), o `statement` deve deixar explícito que se trata de uma base documentada na origem, não de um fato confirmado como vigente hoje. Formulação recomendada: prefixar com algo como "Base contratual documentada na fonte:" (ou equivalente), preservando `knowledge_type: "fact"` apenas para a existência do registro documental, nunca para a alegação implícita de que o valor é o vigente atualmente.

Isso não impede a promoção — impede a promoção **como se fosse confirmação de vigência atual**.

---

## 10. Categorias de `knowledge.json`

`clients/<client_id>/knowledge.json` segue `schemas/client-knowledge.schema.json` e organiza itens em:

- `business_identity` — razão social, CNPJ, localização, segmento, área de atuação;
- `stakeholders` — pessoas, papéis, contatos;
- `products_services` — produtos, serviços, linhas de negócio;
- `market_context` — público, região, particularidades de mercado;
- `commercial_context` — ticket, condições comerciais, diferenciais, ofertas;
- `operation_context` — serviços V4 contratados, fee, canais operacionais, escopo operacional vigente;
- `technology` — ferramentas, CRM, analytics, pixel, integrações;
- `brand` — identidade, cores, restrições, regras criativas (quando o fato é cadastral/estável — direcionamento estratégico de marca em profundidade vai para `strategy.md`);
- `other_facts` — fatos relevantes que não se encaixam nas categorias acima.

`knowledge.json` NÃO é um dump integral de `client-context.json`. Cada item promovido deve ser um fato individualizado, com `statement` próprio, não um bloco inteiro copiado.

### 10.1 `knowledge_type` — preservar a natureza semântica original

Todo `knowledge_item` escrito em `knowledge.json` deve declarar `knowledge_type` (contrato em `schemas/client-knowledge.schema.json`), herdado diretamente do `type` da evidência de origem (`schemas/evidence.schema.json`): `fact`, `metric`, `decision`, `hypothesis`, `request`, `commitment`, `pending`, `risk`, `idea` ou `dependency`.

A promoção para memória canônica **nunca eleva o tipo semântico**:

- um `risk` promovido continua `knowledge_type: "risk"` — nunca vira `fact`;
- uma `hypothesis` promovida continua `knowledge_type: "hypothesis"`;
- um `request` promovido continua `knowledge_type: "request"`, nunca é lido como `commitment`;
- um `pending` promovido (quando aplicável a `knowledge.json`, não a `current-state.json`) continua `knowledge_type: "pending"`.

Isso vale mesmo quando o `category` de destino (`business_identity`, `operation_context`, etc.) parece sugerir um fato consolidado — a categoria descreve **onde** o conhecimento se encaixa tematicamente, não **que grau de certeza** ele carrega. `confidence` e `knowledge_type` continuam sendo a fonte de verdade sobre certeza e natureza.

`promotion_candidate.value` (no `promotion_plan`) deve incluir o `knowledge_type` proposto sempre que `target_file = knowledge.json`, para que a decisão fique auditável antes da escrita.

---

## 11. Princípio central de promoção

Nem toda informação observada deve virar memória permanente.

Promover somente conhecimento que seja:

- útil para execuções futuras;
- suficientemente sustentado por evidências;
- pertencente ao cliente correto;
- adequado ao arquivo canônico de destino;
- não substituído por informação mais recente;
- não puramente circunstancial quando não houver valor histórico.

Informação puramente circunstancial (ex.: um detalhe de agenda de uma única call, sem recorrência ou impacto futuro) deve ser `skip`, com a razão registrada.

---

## 12. Regras de decisão (Promotion Rules)

Para cada candidato, decidir uma das cinco ações:

- **promote** — a informação merece memória canônica; não existe conflito com o que já está registrado.
- **skip** — a informação não precisa persistir (circunstancial, já coberta, confiança insuficiente, ou não pertence a nenhum destino canônico com valor futuro).
- **conflict** — existe informação canônica diferente e não é seguro decidir automaticamente qual prevalece (mesma autoridade/data, ou incerteza real). Nunca sobrescrever silenciosamente — registrar em `conflicts` com `resolution = needs_user_decision` e não escrever nada nesse candidato.
- **supersede** — a nova informação substitui explicitamente a anterior, e isso é sustentado por temporalidade e/ou evidência (ex.: decisão posterior explícita, fonte mais recente e mais autoritativa cobrindo o mesmo fato). Em modo `apply`, o valor antigo é movido para `history/` antes da substituição (ver seção 15).
- **historize** — a informação antiga deve sair do estado vigente, mas merece ser preservada em `clients/<client_id>/history/` (ex.: decisão superada, estado anterior relevante). Usada tanto isoladamente quanto como parte de uma `supersede`.

Nunca sobrescrever silenciosamente informação conflitante. Toda `conflict` fica registrada e nada é escrito até haver decisão explícita (nova execução com o conflito resolvido, ou decisão do operador).

---

## 12.1 Freshness de PENDING (obrigatório antes de `current-state.json/pending`)

Um item classificado como `pending` na fonte de origem **não vira automaticamente** `current-state.json/pending` só porque a fonte o descreveu como pendência. Isso vale mesmo com `confidence: high` na evidência — freshness e confidence são avaliações independentes.

Antes de propor `target_file: current-state.json` com `action: promote` para um `pending`, verificar se existe evidência razoável de que a pendência **continua aberta/ativa** (ex.: `source_date`/`observed_at` recente e confiável, confirmação em check-in mais recente, menção em `decisions.json` ou fonte estruturada equivalente).

Quando essa confirmação não existir — por exemplo, a fonte é uma narrativa sem data de emissão confiável (ver seção 23 — Freshness) — o candidato **não** pode ser `promote` para `current-state.json`. As alternativas são:

- **skip**, quando a pendência não tiver valor duradouro suficiente para justificar preservação sem confirmação;
- **historize**, quando a pendência tiver valor como registro histórico (ex.: algo que foi cogitado/planejado em determinado momento), mas não puder ser afirmada como ativa hoje;
- aguardar uma nova execução desta skill após confirmação por check-in, eKyte, transcrição ou outra fonte mais recente — registrar isso em `missing_data`, não inventar a confirmação.

Nunca promover um `pending` sem data confiável para `current-state.json` apenas para "não perder a informação" — perder a informação não é o risco aqui; a memória canônica ganhar um item que aparenta estar ativo sem sustentação é o risco que esta regra evita.

---

## 13. Confiança (Confidence)

- `low` — normalmente não deve ser promovido como fato canônico. Candidato deve ser `skip`, a menos que exista razão operacional forte para preservar como `hypothesis`/`pending` explicitamente marcado como tal (nunca como fato definitivo) — nesse caso, registrar com clareza no `statement` e manter `confidence: low` no destino.
- `medium` — não deve virar fato estrutural estável por padrão. Promover um item `medium` exige, cumulativamente: (a) preservar explicitamente `confidence: medium` no destino (nunca omitir ou arredondar para `high`); (b) utilidade futura forte e concreta — não basta ser "interessante", precisa mudar como uma execução futura seria conduzida; (c) ausência de uma fonte melhor e mais barata de confirmar o mesmo fato em breve. Quando a informação puder ser facilmente confirmada por uma fonte melhor logo à frente (ex.: um padrão comercial observável no CRM, algo que o próximo check-in naturalmente esclarece), **preferir `skip`** a promover um item `medium` como se já fosse conhecimento estável — registrar em `missing_data` o que confirmaria o item. Exemplo concreto: um padrão como "leads permanecem parados em negociação por semanas" não deve virar `knowledge_item` estável a partir de uma única menção narrativa sem data — a rota preferida é aguardar confirmação via CRM/Kommo ou check-in antes de promover.
- `high` — candidato normal à promoção, desde que passe pelos demais critérios (evidência, temporalidade, destino adequado).

A skill nunca eleva a confiança de um item ao promovê-lo. A confiança do `knowledge_item`/registro final não pode ser maior que a confiança da evidência de origem.

---

## 14. Temporalidade

Antes de decidir `promote`/`supersede`/`conflict`, verificar:

- data da fonte do candidato (`observed_at`/`source_date` do output de origem);
- data da informação canônica existente no destino (`updated_at`, `observed_at`, data da decisão);
- existência de decisão posterior explícita em `decisions.json` que já trate do mesmo assunto;
- indicação explícita de vigência no próprio candidato ou na memória existente.

Informação antiga não substitui automaticamente informação mais recente. Uma decisão nova e explícita pode substituir uma estratégia anteriormente documentada (`supersede`), mas o inverso nunca é assumido automaticamente.

Quando a data de qualquer um dos lados for `unknown`/ausente, tratar como sinal de baixa segurança temporal: preferir `conflict` a `supersede`.

---

## 15. Provenance

Toda promoção relevante deve preservar:

- `source_skill` — skill que produziu o output de origem;
- `source_output` — caminho do output de origem;
- `evidence_ids` — IDs (não o texto completo) das evidências que sustentam o item, referenciáveis em `schemas/evidence.schema.json`;
- `observed_at` — data observada na origem, quando disponível;
- `promoted_at` / `promoted_by: "promote-client-memory"` — metadados da própria promoção.

Não duplicar o texto completo da evidência no destino canônico se um ID/referência for suficiente para rastreabilidade.

---

## 16. Plano antes de escrever (Promotion Plan)

A skill deve **sempre** gerar primeiro um `promotion_plan`, com um item por candidato contendo, no mínimo:

- `candidate_id`;
- `target_file` (e `target_path`/`category` quando aplicável);
- `action` (`promote` | `skip` | `conflict` | `supersede` | `historize`);
- `summary` — resumo humano do que está sendo proposto;
- `value` — valor/estrutura proposta (ausente quando `action = skip`);
- `reason` — por que essa ação foi escolhida;
- `evidence_ids`;
- `confidence`.

Nenhuma escrita em memória canônica pode ocorrer sem que o candidato correspondente exista, com essa forma, no `promotion_plan`. Um `apply` nunca inventa uma ação fora do que já estava no plano gerado (ou fornecido) previamente.

---

## 17. Modo de execução

A skill suporta dois modos:

### preview (padrão)

- gera `source_outputs`, `promotion_plan`, `conflicts` e `skipped`;
- não altera nenhum arquivo em `clients/<client_id>/`;
- `applied_changes` permanece `[]`;
- `mode = "preview"` no output.

### apply

- só deve ser executado mediante pedido explícito do operador para aplicar a promoção (ex.: "aplique o plano", "promova de fato") — nunca assumido por padrão nem encadeado automaticamente após um preview sem confirmação;
- aplica **somente** os candidatos com `action` em `{promote, supersede, historize}` presentes no `promotion_plan` validado; candidatos `skip`/`conflict` nunca resultam em escrita;
- side effect: **MEMORY**;
- segue a seção 18 (Side Effect Safety) para cada escrita.

Nunca assumir `apply` sem pedido explícito. Na ausência de indicação, usar `preview`.

---

## 18. Side Effect Safety (obrigatório em modo apply)

Para cada escrita em `clients/<client_id>/`:

1. **Backup/snapshot** — antes de qualquer `supersede` ou `historize` que remova ou substitua conteúdo vigente, copiar o estado anterior do trecho/arquivo afetado para `clients/<client_id>/history/` com nome que preserve rastreabilidade (ex.: `<arquivo-origem>-superseded-<timestamp>.json`). Nunca apagar histórico silenciosamente.
2. **Escrita mínima** — aplicar apenas a mudança descrita no candidato; não reescrever seções do arquivo não relacionadas ao candidato.
3. **Validação sintática** — após escrever, validar que o JSON resultante é sintaticamente válido e, quando existir schema aplicável (`knowledge.json` contra `schemas/client-knowledge.schema.json`; evidências contra `schemas/evidence.schema.json`), validar contra o schema.
4. **`git diff --check`** — rodar `git diff --check` sobre as mudanças antes de finalizar, para capturar erros de whitespace/conflito. Registrar o resultado em `validation.git_diff_check_passed`.
5. **Sem commit, sem push** — a skill nunca executa `git commit` ou `git push`. Ela apenas prepara e apresenta as alterações (CLAUDE.md seção 21).
6. Se qualquer validação falhar, reverter a escrita problemática (ou não prosseguir com ela), registrar em `warnings`, e refletir isso em `status` (`partial` ou `failed`).

---

## 19. Output

Salvar output em:

```
context/generated/<client_id>/memory-promotion.json
```

O output deve validar contra `skills/promote-client-memory/output.schema.json` e conter, no mínimo:

- `schema_version`;
- `skill`;
- `client_id`;
- `generated_at`;
- `mode`;
- `status`;
- `source_outputs`;
- `promotion_plan`;
- `applied_changes`;
- `conflicts`;
- `skipped`;
- `evidence`;
- `missing_data`;
- `warnings`.

Este é um output temporário de trabalho (CLAUDE.md seção 13) — não é, em si, memória canônica. A memória canônica é o resultado das escritas em `clients/<client_id>/` feitas em modo `apply`.

---

## 20. Status de execução

- `success` — plano gerado (ou aplicado) sem candidatos bloqueantes pendentes; em modo `apply`, todas as escritas planejadas foram validadas com sucesso.
- `partial` — plano gerado com `conflicts` não resolvidos, `missing_data` relevante, ou (em modo `apply`) parte das escritas falhou validação e foi revertida.
- `failed` — nenhum `source_output` válido foi encontrado, nenhum candidato pôde ser avaliado, ou (em modo `apply`) a validação de side-effect safety impediu qualquer escrita segura.

Não marcar `success` quando existir `conflict` não resolvido tratado como se tivesse sido promovido.

---

## 21. Missing Data

Registrar `missing_data` quando:

- um `source_output` esperado não existir ou não puder ser lido;
- um candidato não puder ser avaliado por falta de `evidence_ids` suficientes;
- a memória canônica de destino não existir ainda (ex.: `knowledge.json` ausente) — isso não bloqueia o preview, mas deve ser declarado;
- um campo necessário para decidir temporalidade (data da fonte ou da memória existente) estiver ausente;
- um `pending` sem freshness suficiente (seção 12.1) ficar de fora de `current-state.json` por falta de confirmação — declarar o que confirmaria a vigência (ex.: check-in mais recente, eKyte, CRM) e marcar `blocking: false`, salvo se a ausência dessa pendência comprometer decisão essencial.

---

## 22. Warnings

Gerar warning quando:

- um `source_output` pertencer a um `client_id` diferente do solicitado (e for descartado);
- um candidato tiver `confidence: low` e for promovido mesmo assim como hipótese explícita (ver seção 13);
- houver `conflict` entre candidato e memória existente;
- uma validação de side-effect safety (seção 18) falhar em modo `apply`;
- um output de origem estiver com `status: partial` ou `failed`, tornando os candidatos dele menos confiáveis;
- `knowledge.json` ainda não existir e uma promoção for a primeira a criá-lo;
- um `pending`, `dependency` ou termo contratual (fee/escopo/data de início) da fonte tiver sido mantido fora de `current-state.json`/tratado como "base documentada, não vigência confirmada" por falta de freshness (seções 9.1, 9.2, 12.1).

---

## 23. Freshness

Registrar, quando disponível:

- data de cada `source_output` consumido (`generated_at` do próprio output);
- data da memória canônica existente em cada destino comparado;
- data de geração deste output (`generated_at`).

Não tratar um `source_output` antigo como automaticamente vigente sem comparar com decisões/memória mais recentes (CLAUDE.md seção 8).

---

## 24. Regras

Esta skill deve:

- respeitar CLAUDE.md;
- operar somente no `client_id` solicitado, sem misturar dados de outro cliente;
- carregar somente os `source_outputs` necessários (lazy loading);
- gerar sempre um `promotion_plan` antes de qualquer escrita;
- preservar rastreabilidade (provenance + evidence_ids) em toda promoção;
- registrar conflitos em vez de decidir silenciosamente;
- respeitar os níveis de confiança (seção 13) e temporalidade (seção 14);
- aplicar side-effect safety (seção 18) em todo `apply`.

---

## 25. Proibições

promote-client-memory não pode:

- ler fontes brutas diretamente (PDF, WhatsApp, transcrição, BI, eKyte);
- diagnosticar performance, calcular gap, identificar prioridades, replanejar ou auditar plano;
- gerar tarefas ou executar ações externas;
- transformar automaticamente `hypothesis` em `fact`, `idea` em `decision`, `request` em `commitment`, ou `pending` em tarefa;
- misturar memória de clientes diferentes;
- sobrescrever silenciosamente informação canônica conflitante;
- assumir `mode = apply` sem pedido explícito;
- executar `git commit` ou `git push`;
- apagar `clients/<client_id>/history/` ou qualquer entrada de `decisions.json` — decisões superadas são marcadas/movidas, nunca apagadas;
- promover como fato definitivo algo com `confidence: low`;
- transformar `knowledge.json` em cópia integral de um `client-context.json`;
- escrever em `knowledge.json` um item sem `knowledge_type`, ou com `knowledge_type` diferente do `type` da evidência de origem (nunca elevar `risk`/`hypothesis`/`request`/`pending` a `fact` só pela promoção);
- promover para `current-state.json` uma regra permanente de operação (ex.: "validar estoque antes de campanha", "validar condição comercial antes de preço em arte", "validar área antes de expandir mídia") — essas pertencem a `knowledge.json`/`operation_context` ou `strategy.md` (seção 9.1);
- promover um `pending` para `current-state.json` sem freshness suficiente (seção 12.1), mesmo que a fonte o descreva como pendência;
- declarar fee, escopo ou data de início de contrato de uma fonte histórica sem data confiável como vigente hoje — deve ser preservado como base documentada na fonte, não como vigência confirmada (seção 9.2);
- promover um item `confidence: medium` a fato estrutural estável quando uma fonte melhor puder confirmá-lo em breve (seção 13) — nesses casos, `skip` é a ação padrão.

---

## 26. Side Effects

**MEMORY.**

Em modo `preview`: nenhum side effect — apenas leitura e geração de `context/generated/<client_id>/memory-promotion.json`.

Em modo `apply`: pode criar/atualizar arquivos em `clients/<client_id>/`, incluindo `clients/<client_id>/history/`. Nunca side effect `EXTERNAL` — esta skill não toca sistemas fora deste repositório.

---

## 27. Idempotência

Executar `promote-client-memory` novamente com os mesmos `source_outputs`, sobre a mesma memória canônica, deve produzir o mesmo `promotion_plan` (mesmas ações, mesmos candidatos).

Em modo `apply`, reaplicar um plano já aplicado não deve duplicar itens em `knowledge.json`, `decisions.json` ou `sources.json` — um candidato já promovido (mesmo `knowledge_id`/fato equivalente já presente com a mesma proveniência) deve ser reavaliado como `skip` ("já promovido") na execução seguinte, não promovido de novo.

---

## 28. Critérios de qualidade

Antes de concluir, verificar:

1. o objetivo da skill foi atendido (plano claro e, se aplicável, escrita segura)?
2. todo candidato do `promotion_plan` possui `evidence_ids` e `reason`?
3. nenhuma informação de outro cliente foi misturada?
4. nenhuma promoção contorna a regra de confiança (seção 13)?
5. todo conflito foi registrado em vez de resolvido silenciosamente?
6. a temporalidade foi verificada antes de qualquer `supersede`?
7. em modo `apply`, todo `supersede`/`historize` gerou backup em `history/`?
8. em modo `apply`, os JSONs resultantes validam contra seus schemas e `git diff --check` passou?
9. nenhum commit ou push foi executado?
10. o output valida contra `output.schema.json`?
11. o `status` reflete corretamente o resultado?
12. todo `knowledge_item` proposto para `knowledge.json` declara `knowledge_type` igual ao `type` da evidência de origem (seção 10.1)?
13. nenhuma regra permanente de operação foi proposta para `current-state.json` (seção 9.1)?
14. todo `pending` proposto para `current-state.json` possui freshness suficiente para sustentar vigência atual (seção 12.1)?
15. todo dado de fee/escopo/contrato vindo de fonte histórica sem data confiável foi preservado como "base documentada na fonte", não como vigência confirmada (seção 9.2)?
16. nenhum item `confidence: medium` foi promovido a fato estrutural estável quando uma fonte melhor poderia confirmá-lo em breve (seção 13)?

---

## 29. Falhas

Em caso de falha:

- não fabricar um `promotion_plan` ou `applied_changes` artificial;
- registrar o motivo em `warnings`/`missing_data`;
- preservar a memória canônica existente exatamente como estava — nunca escrever parcialmente um destino e deixá-lo inconsistente;
- se uma escrita em `apply` falhar a validação (seção 18), reverter essa escrita específica antes de finalizar, mantendo as demais escritas já validadas;
- informar o que seria necessário para uma nova tentativa (ex.: `source_output` ausente, conflito a resolver, `client_id` divergente).

---

## 30. Exemplos

Exemplos aprovados devem ficar em:

```
skills/promote-client-memory/examples/
```

Preferencialmente contendo `input` (source_outputs + memória canônica de partida), `expected-output` (promotion_plan em modo preview) e observações de qualidade.

---

## 31. Resultado esperado

promote-client-memory responde:

Do que já observamos e validamos sobre este cliente, o que merece virar memória permanente, para onde vai, e o que ainda está em conflito ou não deve persistir?

Ela não responde:

O cliente está indo bem? O que fazer a seguir? Quais tarefas gerar?

Essas responsabilidades pertencem às skills de inteligência (`diagnose-client`, `identify-priorities`, `replan-client`) e às demais skills de ação (`generate-tasks`, `publish-ekyte`).
