# SKILL — READ BU

## 1. Identificação

Nome: Read BU

Slug: read-bu

Categoria: source

Versão: 1.1.0

Side Effects: NONE

---

## 2. Objetivo

Ler uma Business Unit de clientes e transformar sua estrutura visível e seus hyperlinks em um registro estruturado e rastreável.

A skill identifica clientes e fontes.

Ela não interpreta o conteúdo das fontes vinculadas.

A skill só extrai clientes quando a fonte recebida é, de fato, estruturalmente uma BU/carteira/índice de clientes (ver seção 8 — Qualificação da Fonte). Mencionar múltiplos clientes não torna uma fonte narrativa em uma BU.

---

## 3. Quando usar

Usar quando for necessário:

- identificar clientes existentes na BU;
- descobrir status e flags registrados;
- localizar hyperlinks por cliente;
- atualizar o índice de clientes;
- descobrir fontes disponíveis para cada cliente;
- verificar mudanças estruturais na carteira.

---

## 4. Quando NÃO usar

Não usar para:

- entender estratégia de um cliente;
- ler documentação vinculada;
- ler conversas de WhatsApp;
- interpretar contratos;
- analisar BI;
- gerar diagnóstico;
- gerar replanejamento;
- gerar tarefas;
- extrair registros de cliente a partir de fontes narrativas (handoff de Account Manager, documentação estratégica, relatório de cliente, transcrição, conversa, briefing) — mesmo quando essas fontes citam múltiplos clientes. Essas fontes devem ser apenas classificadas e rejeitadas pela Qualificação da Fonte (seção 8), nunca processadas como BU.

Essas responsabilidades pertencem a outras skills.

---

## 5. Inputs

Obrigatórios:

- source_path ou source_url;
- identificação da BU.

Opcionais:

- client_filter;
- force_refresh.

Exemplo de intenção:

ler BU atual

ou:

localizar cliente específico na BU

---

## 6. Fontes permitidas

A skill pode ler:

- PDF;
- planilha;
- documento tabular;
- arquivo exportado;
- fonte autorizada que represente a BU.

Para PDF, deve considerar:

- texto visível;
- posição das células;
- hyperlinks embutidos;
- anotações de link.

Nem todo arquivo desses formatos é uma BU válida. O formato do arquivo (PDF, planilha) não qualifica a fonte — quem qualifica é a estrutura de conteúdo, avaliada na seção 8.

---

## 7. Estrutura esperada

A BU pode conter campos como:

- cliente;
- grupo;
- contrato;
- status;
- flag;
- documentação;
- anexos.

A skill não deve assumir que todas as BUs terão exatamente as mesmas colunas.

Colunas adicionais devem ser preservadas quando forem relevantes.

---

## 8. Qualificação da Fonte (Source Qualification)

Esta etapa é **obrigatória** e deve ser executada **antes de qualquer extração semântica de clientes**, independentemente do formato do arquivo recebido.

### 8.1 Objetivo

Impedir que uma fonte narrativa (que apenas menciona clientes) seja processada como se fosse uma BU estruturada.

Mencionar múltiplos clientes não é suficiente para qualificar uma fonte como BU.

### 8.2 O que caracteriza uma fonte compatível

Uma fonte é compatível com read-bu (`source_kind = client_portfolio_index`, `source_compatible = true`) quando apresenta **as duas condições a seguir, simultaneamente**:

1. organização explícita por cliente (linhas de tabela, cards de índice, entradas de carteira — não páginas de prosa corrida por cliente);
2. presença de ao menos um campo estrutural de estado/cadastro de carteira por cliente, equivalente a: status, flag, documentação, grupo, contrato, ou links/hyperlinks padronizados por cliente.

### 8.3 O que caracteriza uma fonte incompatível

São incompatíveis com read-bu, entre outras:

- Handoff de Account Manager (narrativo, uma seção longa de texto por cliente);
- documentação estratégica;
- relatório de cliente;
- transcrição;
- conversa (ex.: exportação de WhatsApp);
- briefing.

Essas fontes podem citar nomes de clientes, CNPJs, hyperlinks e até status pontuais dentro do texto — isso **não** as torna uma BU. O sinal decisivo é a ausência de organização estrutural em nível de carteira (condição 1) e/ou de um campo de estado de carteira (condição 2), e não a presença ou ausência de qualquer menção a cliente.

Em caso de dúvida real entre os dois cenários, classificar como incompatível (`source_compatible = false`) e declarar a incerteza em `warnings` — não extrapolar a favor da extração.

### 8.4 Procedimento de qualificação

Executar antes da seção 9 (Procedimento de extração):

1. observar a forma geral da fonte (tabular/índice vs. narrativa/prosa longa por cliente);
2. verificar se há organização explícita por cliente (condição 8.2.1);
3. verificar se há ao menos um campo estrutural de carteira por cliente (condição 8.2.2);
4. classificar `source_kind` (ver enum em `output.schema.json`: `client_portfolio_index`, `account_handoff`, `strategic_documentation`, `client_report`, `transcript`, `conversation`, `briefing`, `other_narrative`, `unknown`);
5. definir `source_compatible` (`true` somente se `source_kind = client_portfolio_index`);
6. registrar uma evidência (`type: fact`) descrevendo a natureza observada da fonte — isto é um fato sobre a fonte, não sobre um cliente;
7. se `source_compatible = false`, seguir a seção 8.5 e **parar** — não prosseguir para a seção 9;
8. se `source_compatible = true`, prosseguir normalmente para a seção 9.

### 8.5 Tratamento de fonte incompatível

Quando `source_compatible = false`:

- **não** executar extração semântica de clientes a partir do conteúdo narrativo;
- **não** gerar evidências do tipo "cliente pertence à BU" ou qualquer fato de pertencimento de carteira a partir dessa fonte;
- `clients` deve ser `[]` (vazio);
- `status` final do output deve ser `failed`;
- registrar em `warnings` uma mensagem clara de *source type mismatch*, citando o `source_kind` detectado e o motivo da incompatibilidade (condição 8.2 não satisfeita);
- registrar em `missing_data` que a extração de clientes não foi realizada por incompatibilidade de fonte;
- preencher `suggested_skill` com uma sugestão textual de qual categoria/skill deveria tratar aquela fonte (ex.: skill de leitura de handoff narrativo, read-client-context, read-transcript, read-whatsapp), **sem executar** essa skill;
- nunca inferir metadados de cliente (nome, CNPJ, contrato, hyperlink) a partir do conteúdo narrativo só porque "parecem confiáveis" — isso pertence a outra skill, com seu próprio contrato de evidência.

`bu.name` e `bu.source` continuam sendo preenchidos normalmente mesmo com `source_compatible = false`, pois descrevem a fonte em si, não um fato sobre clientes.

---

## 9. Procedimento

Executar nesta ordem:

0. executar a Qualificação da Fonte (seção 8); se `source_compatible = false`, seguir a seção 8.5 e encerrar sem prosseguir para os passos abaixo;
1. identificar a fonte;
2. verificar se a fonte está acessível;
3. identificar estrutura tabular;
4. identificar cabeçalhos;
5. identificar cada linha de cliente;
6. preservar o valor visível de cada célula;
7. identificar hyperlinks associados às células;
8. classificar hyperlinks quando possível;
9. normalizar identificador do cliente;
10. gerar evidências;
11. registrar ambiguidades;
12. produzir output estruturado.

---

## 10. Identificador do cliente

Gerar client_id normalizado a partir do nome visível.

Regras:

- minúsculas;
- sem acentos;
- espaços convertidos para hífen;
- remover caracteres especiais desnecessários;
- não alterar semanticamente o nome.

Exemplos:

Glam Houz -> glam-houz

Rei do Pano -> rei-do-pano

O display_name deve preservar o nome original.

---

## 11. Hyperlinks

A skill deve identificar hyperlinks presentes na BU.

Classificações possíveis:

- whatsapp_group;
- documentation;
- spreadsheet;
- contract;
- attachment;
- crm;
- operational_routine;
- unknown.

A classificação deve considerar:

- domínio;
- texto da célula;
- posição do hyperlink;
- contexto da coluna.

Não classificar apenas pela ordem em que links aparecem no arquivo quando a associação com a célula não for segura.

Quando a associação for ambígua:

- preservar o link;
- usar type = unknown quando necessário;
- gerar warning.

---

## 12. WhatsApp

Links de convite de WhatsApp podem ser registrados como:

type: whatsapp_group

A skill não deve:

- entrar no grupo;
- assumir que possui acesso às mensagens;
- interpretar o histórico do grupo;
- inferir membros.

O link representa apenas uma referência de fonte.

---

## 13. Documentação

Links de documentação devem ser registrados, mas não abertos por esta skill.

Exemplo:

Google Docs associado ao cliente

deve resultar em uma source do tipo:

documentation

O conteúdo será responsabilidade de read-client-context ou skill equivalente.

---

## 14. Contratos e anexos

Se a BU exibir:

- nome de arquivo;
- referência;
- texto sem hyperlink;

preservar exatamente o que estiver visível.

Não assumir existência de arquivo acessível apenas porque existe um nome na célula.

---

## 15. Status

Preservar o status conforme registrado na fonte.

Exemplos possíveis:

- On Going;
- Off Boarding.

Opcionalmente gerar uma representação normalizada adicional:

- ongoing;
- offboarding;
- unknown.

Nunca alterar o status baseado em inferência externa.

---

## 16. Flags

Preservar a flag conforme registrada.

Exemplos:

- Green;
- Yellow;
- Red.

Normalização permitida:

- green;
- yellow;
- red;
- unknown.

A skill não recalcula a flag.

---

## 17. Evidências

Gerar evidências para informações estruturais relevantes.

Exemplos:

- classificação da fonte (source_kind/source_compatible);
- cliente existe na BU;
- status registrado;
- flag registrada;
- documentação vinculada;
- grupo vinculado.

Evidências devem seguir:

schemas/evidence.schema.json

---

## 18. Output

Salvar output temporário em:

context/generated/bu/bu-context.json

O output deve validar contra:

skills/read-bu/output.schema.json

O output sempre inclui `source_kind` e `source_compatible`, mesmo quando a fonte é incompatível.

---

## 19. Missing Data

Registrar quando:

- coluna esperada estiver ausente;
- cliente não possuir documentação;
- link estiver quebrado ou indisponível;
- contrato estiver apenas referenciado;
- associação entre link e cliente for ambígua;
- extração de clientes não foi realizada por incompatibilidade de fonte (`source_compatible = false`).

Ausência de um campo não autoriza inferência.

---

## 20. Warnings

Gerar warning quando:

- hyperlink não puder ser associado com segurança;
- estrutura tabular estiver quebrada;
- cliente aparecer duplicado;
- status for desconhecido;
- flag não possuir valor reconhecido;
- arquivo contiver links sem contexto suficiente;
- a fonte recebida for incompatível com read-bu (source type mismatch — ver seção 8.5).

---

## 21. Freshness

Registrar:

- data de leitura;
- data da fonte quando disponível.

A skill não assume que a BU está atualizada apenas porque foi lida com sucesso.

---

## 22. Proibições

read-bu não pode:

- abrir documentação de cliente para interpretar conteúdo;
- resumir estratégia;
- analisar performance;
- gerar tarefas;
- alterar flag;
- alterar status;
- criar metas;
- deduzir escopo;
- acessar conteúdo de grupos de WhatsApp;
- preencher campos ausentes usando conhecimento externo;
- processar uma fonte narrativa (handoff, documentação estratégica, relatório de cliente, transcrição, conversa, briefing) como se fosse uma BU apenas porque ela cita múltiplos clientes;
- gerar evidência do tipo "cliente pertence à BU" (ou equivalente) a partir de uma fonte com `source_compatible = false`;
- retornar `status = success` (ou `partial`) quando `source_compatible = false` — o resultado correto nesse caso é `status = failed`;
- executar, sugerir com autoridade final, ou substituir a skill apropriada para a fonte incompatível — apenas sugerir seu tipo em `suggested_skill`.

---

## 23. Idempotência

Executar read-bu novamente sobre a mesma versão da fonte deve produzir semanticamente o mesmo registro, incluindo a mesma classificação de `source_kind`/`source_compatible`.

Não duplicar clientes ou sources.

---

## 24. Critérios de qualidade

Antes de concluir:

1. a Qualificação da Fonte (seção 8) foi executada antes de qualquer extração?
2. `source_kind` e `source_compatible` foram registrados no output?
3. se `source_compatible = false`, `clients` está vazio, `status = failed`, e não há evidência de pertencimento de cliente à BU?
4. todos os clientes visíveis foram capturados (quando `source_compatible = true`)?
5. nomes originais foram preservados?
6. hyperlinks foram capturados?
7. hyperlinks estão associados corretamente?
8. ambiguidades foram declaradas?
9. status e flags foram preservados?
10. nenhuma documentação vinculada foi interpretada?
11. nenhuma informação foi inventada?
12. o output valida contra o schema?

---

## 25. Resultado esperado

Quando `source_compatible = true`, read-bu responde essencialmente:

Quem está na BU?

Qual o estado cadastrado de cada cliente?

Quais referências e fontes estão associadas a cada cliente?

Ela não responde:

O que está acontecendo no cliente?

Essa responsabilidade pertence às skills seguintes.

Quando `source_compatible = false`, read-bu responde apenas:

Esta fonte é uma BU válida? (Não.)

Que tipo de fonte parece ser, e qual categoria de skill deveria tratá-la?

Ela explicitamente não tenta responder "quem está na BU" a partir de uma fonte que não é uma BU.
