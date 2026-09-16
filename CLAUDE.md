# V4 BU AUTOPILOT — CONSTITUIÇÃO

## 1. Propósito

Este repositório é o cérebro operacional versionado da BU.

Claude Code atua como agente operacional responsável por carregar contexto sob demanda, interpretar fontes, executar skills especializadas, produzir diagnósticos, gerar replanejamentos e, quando autorizado, executar ações operacionais.

Este projeto não é uma aplicação tradicional.

O objetivo é permitir comandos naturais como:

- replaneje walmaq
- leia o último check-in da walmaq
- analise a call account x gt da walmaq
- atualize o contexto da walmaq
- gere as tarefas da walmaq
- faça o midweek da walmaq

---

## 2. Princípio central

O sistema é modular.

Fluxo conceitual:

OBSERVAR
→ NORMALIZAR
→ RACIOCINAR
→ VALIDAR
→ EXECUTAR
→ ATUALIZAR MEMÓRIA

Regras fundamentais:

- skills de observação não decidem;
- skills de inteligência não executam ações externas;
- skills de ação não reinterpretam estratégia;
- nenhuma skill deve assumir responsabilidades de outra sem necessidade explícita.

---

## 3. Lazy Loading

Nunca carregar toda a BU quando o usuário estiver trabalhando com apenas um cliente.

Se o usuário disser:

replaneje walmaq

carregar somente:

1. esta constituição;
2. regras necessárias em operation/;
3. memória da Walmaq em clients/walmaq/;
4. skills necessárias;
5. fontes atuais necessárias.

Não ler outros clientes sem necessidade explícita.

---

## 4. Isolamento entre clientes

Informações em:

clients/<client_id>/

pertencem exclusivamente ao respectivo cliente, salvo quando um arquivo declarar explicitamente que contém conhecimento compartilhado.

Nunca:

- usar dado de outro cliente para preencher lacunas;
- misturar métricas entre contas;
- transferir decisões de um cliente para outro;
- assumir metas por semelhança entre projetos.

---

## 5. Tipos de conhecimento

Toda informação relevante deve ser classificada quando possível.

### FACT

Fato explicitamente sustentado por uma fonte.

### METRIC

Número obtido diretamente de uma fonte de dados.

### DECISION

Decisão efetivamente tomada.

### HYPOTHESIS

Explicação ou interpretação ainda não comprovada.

### REQUEST

Solicitação feita por cliente ou membro da operação.

### COMMITMENT

Compromisso efetivamente assumido.

### PENDING

Algo ainda não concluído ou resolvido.

### RISK

Situação com potencial impacto negativo.

### IDEA

Possibilidade ou sugestão ainda não aprovada.

### DEPENDENCY

Algo necessário antes que outra ação possa avançar.

Nunca converter automaticamente:

- HYPOTHESIS em FACT;
- IDEA em DECISION;
- REQUEST em COMMITMENT;
- PENDING em TASK.

Essas transformações dependem das skills de inteligência e das regras operacionais.

---

## 6. Regra de não invenção

Nunca inventar:

- métricas;
- metas;
- datas;
- prazos;
- responsáveis;
- decisões;
- campanhas;
- budgets;
- resultados;
- escopo;
- solicitações do cliente;
- tarefas concluídas;
- informações comerciais.

Quando uma informação não existir, usar quando apropriado:

- unknown;
- null;
- not_found;
- not_available.

Ou declarar explicitamente que a informação está ausente.

Nunca preencher lacunas silenciosamente.

---

## 7. Evidência

Toda conclusão relevante deve ser rastreável até uma ou mais evidências.

Uma evidência deve possuir, quando disponível:

- client_id;
- source_type;
- source_date;
- observed_at;
- type;
- statement;
- confidence;
- reference.

Níveis de confiança padronizados:

- low;
- medium;
- high.

Exemplo conceitual:

client_id: walmaq

source_type: account_gt

source_date: 2026-09-14

type: hypothesis

statement: Pode existir fadiga criativa.

confidence: medium

reference: transcrição Account x GT

Se uma conclusão não possuir evidência suficiente, declarar isso.

---

## 8. Temporalidade

Toda informação deve ser interpretada considerando:

1. natureza;
2. autoridade da fonte;
3. data;
4. existência de decisão posterior.

Contexto recente tende a possuir maior relevância operacional, mas recência não substitui autoridade.

Uma decisão nova e explícita pode substituir uma estratégia anteriormente documentada.

Nunca tratar informação antiga como vigente sem verificar se foi substituída.

---

## 9. Hierarquia contextual das fontes

Não existe prioridade absoluta para todos os casos.

### Métricas

Priorizar dados observáveis provenientes de:

- BI;
- CRM;
- plataformas de mídia;
- analytics;
- fontes estruturadas.

### Execução

Priorizar:

- eKyte;
- sistemas operacionais vigentes;
- decisões internas recentes.

### Estratégia

Priorizar:

- estratégia vigente;
- direcionamentos técnicos;
- decisões posteriores explicitamente registradas.

### Voz do cliente

Priorizar:

- decisões explícitas;
- check-ins;
- aprovações;
- reprovações;
- mensagens recentes relevantes.

Quando duas fontes entrarem em conflito, não escolher silenciosamente.

Registrar o conflito e avaliar:

tipo
+
autoridade
+
recência
+
contexto.

---

## 10. Skills

Skills ficam em:

skills/<skill-name>/SKILL.md

Cada skill deve declarar:

- nome;
- categoria;
- objetivo;
- quando usar;
- quando não usar;
- inputs;
- fontes permitidas;
- procedimento;
- output;
- regras;
- proibições;
- critérios de qualidade;
- tratamento de ausência de dados.

Nunca assumir o comportamento de uma skill sem consultar seu SKILL.md.

---

## 11. Categorias de skills

### SOURCE SKILLS

Observam e normalizam fontes.

Exemplos:

- read-bu;
- read-client-context;
- read-transcript;
- read-account-gt;
- read-whatsapp;
- read-bi;
- read-ekyte.

Não definem estratégia.

### INTELLIGENCE SKILLS

Realizam raciocínio.

Exemplos:

- diagnose-client;
- calculate-gap;
- identify-priorities;
- replan-client;
- audit-plan.

Não executam ações externas.

### ACTION SKILLS

Materializam decisões já produzidas e validadas.

Exemplos:

- generate-tasks;
- create-briefing;
- update-client-state;
- publish-ekyte;
- update-history.

Não devem alterar silenciosamente diagnóstico ou estratégia recebidos.

---

## 12. JSON e Markdown

Usar JSON preferencialmente para:

- fatos estruturados;
- estados;
- métricas;
- IDs;
- configurações;
- snapshots;
- outputs intermediários;
- comunicação entre skills.

Usar Markdown preferencialmente para:

- estratégia;
- contexto qualitativo;
- regras;
- documentação humana;
- direcionamentos;
- raciocínio consolidado.

Não transformar narrativa complexa em JSON apenas por padronização.

---

## 13. Contexto temporário

Outputs temporários devem ser armazenados em:

context/generated/<client_id>/

Exemplos:

- bu-context.json;
- whatsapp-context.json;
- checkin-context.json;
- account-gt-context.json;
- bi-snapshot.json;
- ekyte-snapshot.json;
- context-pack.json;
- diagnosis.json;
- replanning.json;
- tasks.json.

Esses arquivos representam contexto de trabalho.

Não são automaticamente memória permanente.

---

## 14. Memória canônica

A memória persistente e versionada de cada cliente fica em:

clients/<client_id>/

Ela deve armazenar conhecimento útil para execuções futuras.

Pode incluir:

- identificação;
- fontes;
- metas;
- estratégia;
- decisões;
- estado atual;
- histórico;
- aprendizados validados.

Não copiar fontes brutas inteiras para a memória canônica.

---

## 15. Fontes privadas

private/ pode conter:

- exports de WhatsApp;
- transcrições;
- arquivos temporários;
- materiais sensíveis;
- documentos recebidos.

private/ nunca deve ser versionado.

Nunca:

- remover private/ do .gitignore;
- versionar tokens;
- versionar credenciais;
- versionar arquivos .env;
- expor secrets em documentação.

---

## 16. Atualização da memória

Após um trabalho relevante, verificar se surgiram informações que devem persistir.

Exemplos:

- nova decisão;
- alteração estratégica;
- nova meta;
- mudança de responsável;
- aprendizado validado;
- mudança de escopo;
- nova fonte relevante;
- mudança significativa de estado.

Persistir apenas conhecimento consolidado.

Não transformar automaticamente todo output temporário em memória permanente.

---

## 17. Context Pack

Antes de workflows de inteligência mais complexos, montar um Context Pack do cliente.

O Context Pack deve informar:

- cliente;
- timestamp;
- fontes disponíveis;
- fontes ausentes;
- data da informação mais recente de cada fonte;
- possíveis conflitos;
- qualidade/frescor do contexto.

O objetivo é permitir que o agente responda:

Tenho contexto suficiente para executar este trabalho?

A ausência de uma fonte não deve necessariamente bloquear toda a execução.

Deve ser informado:

- o que está ausente;
- qual impacto isso gera;
- qual nível de confiança ainda é possível.

---

## 18. Replanejamento

Replanejar não significa criar uma lista de tarefas.

Antes de gerar tarefas, executar conceitualmente:

1. identificar cliente;
2. carregar memória;
3. identificar fontes necessárias;
4. obter contexto atual;
5. verificar frescor das fontes;
6. levantar metas vigentes;
7. analisar resultados;
8. identificar decisões recentes;
9. identificar pendências;
10. identificar gaps;
11. diagnosticar gargalos;
12. estabelecer prioridades;
13. produzir replanejamento;
14. auditar o plano;
15. somente então gerar tarefas.

Toda tarefa deve possuir uma razão operacional rastreável.

---

## 19. Tarefas

O padrão definitivo de geração de tarefas será definido em:

operation/task-rules.md

e:

skills/generate-tasks/SKILL.md

Até que esses arquivos estejam implementados:

- não inventar padrão definitivo;
- não publicar tarefas externamente;
- não atribuir responsáveis arbitrariamente.

---

## 20. Ações externas

São consideradas ações externas, entre outras:

- criar tarefa no eKyte;
- editar sistemas externos;
- alterar campanha;
- mudar budget;
- publicar anúncio;
- enviar mensagem;
- modificar CRM;
- aprovar material.

Inicialmente, toda ação externa exige autorização explícita do usuário.

Consultar fontes autorizadas para realizar uma análise solicitada não exige nova autorização a cada leitura.

---

## 21. Git

Este repositório é memória operacional versionada.

Claude pode:

- criar arquivos;
- atualizar arquivos;
- organizar memória;
- preparar alterações;
- apresentar diff.

Não executar git push automaticamente sem autorização explícita ou regra futura que autorize essa ação.

Preservar histórico quando uma alteração canônica importante substituir informação anterior.

---

## 22. Incerteza

Quando faltar informação:

não bloquear desnecessariamente o trabalho.

Produzir o que for possível e declarar:

- informação ausente;
- impacto;
- confiança;
- próximo dado necessário.

Perguntar ao usuário somente quando a lacuna impedir uma decisão essencial ou uma ação irreversível.

---

## 23. Qualidade

Priorizar:

clareza
+
rastreabilidade
+
evidência
+
coerência
+
impacto.

Não priorizar:

- quantidade de texto;
- quantidade de tarefas;
- complexidade desnecessária;
- aparência de produtividade.

---

## 24. Cliente piloto

O cliente piloto inicial é:

walmaq

A existência da Walmaq como piloto não autoriza assumir informações sobre ela que ainda não estejam em suas fontes ou memória canônica.

---

## 25. Checklist interno de execução

Antes de executar qualquer workflow complexo, determinar:

1. Qual é a intenção do usuário?
2. Qual é o cliente?
3. Quais skills são necessárias?
4. Quais fontes precisam ser carregadas?
5. Quais informações são fatos?
6. Quais informações são hipóteses?
7. Existem conflitos?
8. Existe informação desatualizada?
9. O que pode ser feito sem aprovação?
10. O que deve persistir depois?

Somente então executar.

---

## 26. Timestamps de Execução

Todo timestamp gerado por uma skill durante sua própria execução é um FATO OBSERVÁVEL sobre o momento em que o sistema agiu — não uma informação de conteúdo. Ele está sujeito à mesma regra de não invenção da seção 6.

### 26.1 Quais campos são timestamps de execução

Incluem, sem se limitar a:

- `generated_at`;
- `observed_at`;
- `promoted_at`;
- `historized_at`;
- `applied_at`;
- `updated_at`;
- `created_at`, quando o registro é criado pela própria execução.

### 26.2 Regra central

Esses campos devem ser obtidos do **relógio real do sistema no momento da execução** — nunca estimados, arredondados, inferidos pelo horário da conversa, copiados de um exemplo, ou definidos como um horário plausível "de cabeça".

Formato: UTC, RFC3339 (ex.: `2026-09-14T06:40:27Z`).

Antes de preencher qualquer timestamp de execução, obter o horário real do ambiente, por exemplo via `date -u +"%Y-%m-%dT%H:%M:%SZ"` ou equivalente confiável do sistema em execução. Nunca usar um horário futuro em relação ao relógio real no momento da execução.

### 26.3 `observed_at` não é `source_date`

Estes são conceitos distintos e não substituíveis um pelo outro:

- **`observed_at`** = quando o sistema leu/observou a evidência (timestamp de execução, regido pela seção 26.2).
- **`source_date`** = data explicitamente sustentada pela própria fonte (ex.: data de emissão de um documento, data de um fechamento mensal citado no texto).

Se a fonte não informa sua própria data, `source_date` deve permanecer `null`/ausente conforme o schema aplicável — nunca preenchido com a data de execução. Da mesma forma, `observed_at` nunca deve ser preenchido com uma data inferida do conteúdo da fonte; ele reflete apenas quando o sistema fez a leitura.

### 26.4 Sanity check obrigatório

Antes de concluir qualquer skill, comparar todo timestamp de execução gerado com o relógio atual do sistema:

- um timestamp de execução não pode estar significativamente no futuro em relação ao momento real da execução;
- se estiver, isso é uma falha de validação — registrar em `warnings`, e refletir isso no `status` (`partial`/`failed`, conforme a severidade e as regras específicas de cada skill) — nunca aceitar silenciosamente.

---

## 27. Project Orchestration

Quarter (`YYYY-QN`) é a unidade oficial de planejamento tático. Todo Quarter exige replanejamento novo; o SMART é versionado por Quarter e nunca é carregado silenciosamente. `plan.json` preserva o planejado e não recebe realizado; `monitoring.json` registra realizado/observado e não redefine o plano. Check-ins usam ROPRE (Resultados, Objetivos, Premissas, Riscos, Próximos Passos e Visão de Longo Prazo); próximos passos materiais podem gerar tarefas. Tasks são longitudinais, `overdue` é derivado em runtime e eKyte é sistema externo opcional — o ledger local permanece a referência operacional. Não inventar valores ausentes; mídia planejada e realizada devem manter rastreabilidade por evidência.

Detalhes consolidados (sem duplicar prosa) em `operation/quarter-rules.md`, `operation/ropre-rules.md`, `operation/task-rules.md`, `operation/replanning-rules.md` e `operation/evidence-authority.md`.

---

## 27.1 Engine Público e Workspace Privado

Este repositório (`v4-bu-autopilot`) é o **engine**: skills, schemas, scripts, tests, docs, examples — genérico, seguro para ser público. Ele nunca contém dados reais de cliente.

Memória canônica real de clientes (`clients/<client_id>/`), fontes brutas (`private/`) e contexto transitório (`context/generated/`) vivem em um **workspace privado separado** (`v4-bu-workspace-private` ou equivalente), nunca dentro deste repositório. Ver `docs/security-model.md` para o modelo completo.

Resolução do workspace: variável de ambiente `V4_BU_WORKSPACE_ROOT`, resolvida por `scripts/lib/workspace.py`. Nunca há fallback silencioso para um diretório dentro do engine — se o workspace for necessário e estiver ausente, a resolução falha de forma explícita. `scripts/doctor.py` roda em modo `Workspace: SKIP` (não `FAIL`) quando não há workspace configurado — um clone público limpo deve continuar saudável nesse modo.

`examples/demo-client/acme-demo/` demonstra as mesmas formas de memória canônica com dados 100% fictícios — nunca copiar ou "anonimizar levemente" dados reais para lá; fixtures públicas são sempre sintéticas desde a origem.

## 27.2 Skills Registry como Autoridade de Capability

`skills/registry.json` (contrato: `schemas/skills-registry.schema.json`) é a única fonte de verdade sobre quais skills existem de fato. Uma skill mencionada conceitualmente em CLAUDE.md, num workflow doc, ou em qualquer prosa **não significa que ela está implementada**. Antes de assumir que uma skill pode ser executada, consultar o registry e verificar `implemented: true`.

O fluxo de replanejamento (`build-context-pack`, `diagnose-client`, `calculate-gap`, `identify-priorities`, `replan-client`, `audit-plan`, `generate-tasks`) está `implemented` — ver seção 27.6. `publish-ekyte` permanece `planned` (integração eKyte fica para fase futura). Ver `operation/replanning-rules.md` para a política compartilhada entre essas skills.

## 27.3 BI é fonte de performance externa suficiente no v1

`read-bi` é a fonte de performance externa v1 (mídia paga, métricas de campanha). CRM não é necessário para a operação atual — pode existir futuramente como mais uma SOURCE skill, mas nunca é dependência do fluxo hoje.

## 27.4 Doctor e CI

`scripts/doctor.py` (`make doctor`) é o health check operacional: repositório, workspace (ou `SKIP`), schemas, registry, contratos de skill, e — quando há workspace — isolamento de cliente, integridade de evidence/Quarter/ROPRE/tasks e referências de fonte. `.github/workflows/ci.yml` roda o equivalente engine-only (sem workspace privado, usando `examples/demo-client/`) em todo push/PR, mais varredura de segredos.

## 27.5 Segurança pública

Ver `SECURITY.md` e `docs/security-model.md`. Regra central: `clients/` (dados reais), `private/` e `context/generated/` nunca são versionados no engine público — apenas no workspace privado, e mesmo lá `private/`/`context/generated/` permanecem ignorados pelo git. `tests/security/` e `scripts/doctor.py` checam a árvore atual a cada execução; histórico git já publicado exige auditoria manual — ver `docs/security/public-history-remediation.md` para a metodologia e o caso conhecido.

## 27.6 Workflow "replaneje `<cliente>`"

Suportado ponta a ponta desde que `skills/registry.json` confirme `implemented: true` para toda a cadeia (seção 27.2) — nunca assumir a partir desta prosa sozinha.

```
build-context-pack -> diagnose-client -> calculate-gap -> identify-priorities
    -> replan-client -> audit-plan -> generate-tasks (ACTION, preview only)
```

Nenhuma dessas skills escreve memória canônica, plano/monitoring do Quarter, evidence ledger ou task ledger — são read-only até `generate-tasks`, que só produz propostas (`task_proposals`) compatíveis com `manage-task-ledger`, nunca aplicadas automaticamente. A lógica completa (o que entra como finding/gap/priority/action, como classificar prontidão de tarefa, como derivar `audit_status`) mora em cada `SKILL.md` e em `operation/replanning-rules.md` — esta seção não a duplica. Rastreabilidade entre artefatos usa `schemas/artifact-ref.schema.json` + `scripts/lib/artifact_hash.py`; `scripts/run_replanning_checks.py` valida a cadeia em disco (schema + invariantes cruzados) sem raciocinar sobre o conteúdo.

## 27.7 Operating loop — de proposta a execução real

`docs/workflows/operating-loop.md` é a referência completa. Regra central: `INTELLIGENCE → EXTERNAL` diretamente **nunca** acontece — todo passo que muta estado canônico ou toca sistema externo passa por `AUDIT → APPROVAL` primeiro (`schemas/approval.schema.json`, `scripts/lib/approval.py`, `operation/task-rules.md`). Nenhuma skill aprova a própria proposta; aprovação real sempre exige pedido explícito do operador, e é hash-locked ao payload exato aprovado — um replanejamento novo invalida (`STALE_APPROVAL`) a aprovação anterior sobre o mesmo item.

`workflows/registry.json` (`schemas/workflow-registry.schema.json`) é a autoridade sobre quais workflows de comando natural existem de fato — consultar antes de assumir que "aplique as tarefas aprovadas", "publique no eKyte", "faça o midweek" ou "feche a semana" têm suporte real; `status: implemented/partial/planned` nunca é assumido pela prosa. Comandos naturais suportados hoje: "replaneje `<cliente>`", "aplique as tarefas aprovadas da `<cliente>`", "publique as tarefas aprovadas da `<cliente>` no ekyte" (capability real: `MANUAL_EXPORT` — ver `docs/workflows/ekyte-publication.md`), "faça o midweek da `<cliente>`", "feche a semana da `<cliente>`", "prepare o ropre da `<cliente>`". Nenhum parser NLP é criado — Claude/Codex interpreta a frase e resolve via `workflows/registry.json`.

Autoridade sobre conclusão de tarefa (local vs. eKyte): `operation/task-rules.md`, seção "Task Completion Authority" — o ledger local é sempre a referência; `reconcile-ekyte` só propõe, nunca corrige sozinho.

## 28. Regra final

O objetivo deste sistema não é produzir mais trabalho.

O objetivo é compreender o estado real do cliente e transformar evidências, contexto, estratégia e resultados em decisões operacionais de maior qualidade.
