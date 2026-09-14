# SKILL — READ BU

## 1. Identificação

Nome: Read BU

Slug: read-bu

Categoria: source

Versão: 1.0.0

Side Effects: NONE

---

## 2. Objetivo

Ler uma Business Unit de clientes e transformar sua estrutura visível e seus hyperlinks em um registro estruturado e rastreável.

A skill identifica clientes e fontes.

Ela não interpreta o conteúdo das fontes vinculadas.

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
- gerar tarefas.

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

## 8. Procedimento

Executar nesta ordem:

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

## 9. Identificador do cliente

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

## 10. Hyperlinks

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

## 11. WhatsApp

Links de convite de WhatsApp podem ser registrados como:

type: whatsapp_group

A skill não deve:

- entrar no grupo;
- assumir que possui acesso às mensagens;
- interpretar o histórico do grupo;
- inferir membros.

O link representa apenas uma referência de fonte.

---

## 12. Documentação

Links de documentação devem ser registrados, mas não abertos por esta skill.

Exemplo:

Google Docs associado ao cliente

deve resultar em uma source do tipo:

documentation

O conteúdo será responsabilidade de read-client-context ou skill equivalente.

---

## 13. Contratos e anexos

Se a BU exibir:

- nome de arquivo;
- referência;
- texto sem hyperlink;

preservar exatamente o que estiver visível.

Não assumir existência de arquivo acessível apenas porque existe um nome na célula.

---

## 14. Status

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

## 15. Flags

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

## 16. Evidências

Gerar evidências para informações estruturais relevantes.

Exemplos:

- cliente existe na BU;
- status registrado;
- flag registrada;
- documentação vinculada;
- grupo vinculado.

Evidências devem seguir:

schemas/evidence.schema.json

---

## 17. Output

Salvar output temporário em:

context/generated/bu/bu-context.json

O output deve validar contra:

skills/read-bu/output.schema.json

---

## 18. Missing Data

Registrar quando:

- coluna esperada estiver ausente;
- cliente não possuir documentação;
- link estiver quebrado ou indisponível;
- contrato estiver apenas referenciado;
- associação entre link e cliente for ambígua.

Ausência de um campo não autoriza inferência.

---

## 19. Warnings

Gerar warning quando:

- hyperlink não puder ser associado com segurança;
- estrutura tabular estiver quebrada;
- cliente aparecer duplicado;
- status for desconhecido;
- flag não possuir valor reconhecido;
- arquivo contiver links sem contexto suficiente.

---

## 20. Freshness

Registrar:

- data de leitura;
- data da fonte quando disponível.

A skill não assume que a BU está atualizada apenas porque foi lida com sucesso.

---

## 21. Proibições

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
- preencher campos ausentes usando conhecimento externo.

---

## 22. Idempotência

Executar read-bu novamente sobre a mesma versão da fonte deve produzir semanticamente o mesmo registro.

Não duplicar clientes ou sources.

---

## 23. Critérios de qualidade

Antes de concluir:

1. todos os clientes visíveis foram capturados?
2. nomes originais foram preservados?
3. hyperlinks foram capturados?
4. hyperlinks estão associados corretamente?
5. ambiguidades foram declaradas?
6. status e flags foram preservados?
7. nenhuma documentação vinculada foi interpretada?
8. nenhuma informação foi inventada?
9. o output valida contra o schema?

---

## 24. Resultado esperado

read-bu responde essencialmente:

Quem está na BU?

Qual o estado cadastrado de cada cliente?

Quais referências e fontes estão associadas a cada cliente?

Ela não responde:

O que está acontecendo no cliente?

Essa responsabilidade pertence às skills seguintes.
