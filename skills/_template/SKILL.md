# SKILL TEMPLATE

## 1. Identificação

Nome:

Slug:

Categoria:

- source
- intelligence
- action

Versão:

---

## 2. Objetivo

Descrever em uma frase o que esta skill faz.

A skill deve possuir uma responsabilidade principal clara.

---

## 3. Quando usar

Usar quando:

- condição 1;
- condição 2;
- condição 3.

---

## 4. Quando NÃO usar

Não usar quando:

- condição 1;
- condição 2;
- a responsabilidade pertencer a outra skill.

---

## 5. Responsabilidade

Esta skill é responsável por:

- responsabilidade 1;
- responsabilidade 2;
- responsabilidade 3.

Esta skill NÃO é responsável por:

- responsabilidade externa 1;
- responsabilidade externa 2;
- responsabilidade externa 3.

---

## 6. Inputs

Inputs obrigatórios:

- client_id;
- fonte ou referência necessária.

Inputs opcionais:

- período;
- filtros;
- contexto anterior;
- parâmetros específicos.

Nunca assumir valores ausentes silenciosamente.

---

## 7. Fontes permitidas

Listar explicitamente as fontes que esta skill pode consultar.

Exemplo:

- arquivo local;
- Google Drive;
- API;
- memória canônica do cliente;
- contexto temporário.

Não consultar outras fontes sem necessidade operacional ou autorização definida.

---

## 8. Pré-condições

Antes de executar, verificar:

1. cliente identificado;
2. fonte disponível;
3. fonte pertence ao cliente correto;
4. parâmetros mínimos presentes;
5. autorização necessária, caso exista ação externa.

Se alguma pré-condição falhar, registrar o problema em vez de inventar informação.

---

## 9. Procedimento

Executar na ordem definida para a skill.

Procedimento-base:

1. identificar input;
2. validar fonte;
3. coletar somente o contexto necessário;
4. extrair informações relevantes;
5. classificar informações;
6. gerar evidências;
7. normalizar output;
8. registrar lacunas;
9. validar output.

Skills específicas devem substituir este procedimento pelo fluxo adequado.

---

## 10. Classificação de conhecimento

Quando aplicável, utilizar somente os tipos padronizados:

- fact
- metric
- decision
- hypothesis
- request
- commitment
- pending
- risk
- idea
- dependency

Nunca alterar a natureza de uma informação sem justificativa.

---

## 11. Evidências

Informações relevantes devem gerar evidências compatíveis com:

schemas/evidence.schema.json

Toda evidência deve ser rastreável até sua origem.

Não criar evidência sem fonte.

---

## 11.1 Timestamps de Execução

Ver CLAUDE.md seção 26 (regra completa).

Resumo obrigatório para toda skill:

- campos como `generated_at`, `observed_at`, `promoted_at`, `historized_at`, `applied_at`, `updated_at` e `created_at` (quando criado pela execução) devem vir do relógio REAL do sistema no momento da execução — nunca estimados, arredondados, inferidos pelo horário da conversa, copiados de um exemplo, ou definidos como horário futuro;
- formato UTC RFC3339, obtido por exemplo via `date -u +"%Y-%m-%dT%H:%M:%SZ"` ou equivalente confiável do ambiente;
- `observed_at` (quando o sistema observou/leu algo) nunca deve ser confundido com `source_date` (data que a própria fonte declara); se a fonte não informa data, `source_date` fica `null`/ausente — nunca preenchido com a data de execução;
- antes de concluir, comparar os timestamps de execução gerados com o relógio atual: um timestamp significativamente no futuro é falha de validação, não um resultado aceitável.

---

## 12. Output

O output estruturado deve validar contra:

skills/<skill-name>/output.schema.json

Quando houver output temporário, salvar em:

context/generated/<client_id>/

O nome do arquivo deve ser definido pela própria skill.

---

## 13. Status de execução

Utilizar:

- success
- partial
- failed

SUCCESS:
A skill conseguiu cumprir seu objetivo.

PARTIAL:
A skill produziu resultado útil, mas existem fontes, dados ou condições ausentes.

FAILED:
A skill não conseguiu produzir resultado confiável.

Não marcar como success quando informações obrigatórias estiverem ausentes.

---

## 14. Missing Data

Toda ausência relevante deve ser registrada.

Para cada ausência informar, quando possível:

- campo ou dado ausente;
- fonte esperada;
- impacto;
- se bloqueia ou não a execução posterior.

---

## 15. Warnings

Registrar situações como:

- dado possivelmente desatualizado;
- fonte inconsistente;
- conflito entre informações;
- identificação ambígua;
- baixa confiança;
- limitação técnica.

Warnings não devem ser silenciosamente descartados.

---

## 16. Freshness

Quando a temporalidade for relevante, registrar:

- data da fonte;
- data da coleta;
- período coberto.

A skill deve informar quando uma fonte parece desatualizada para o objetivo solicitado.

Não existe prazo universal de validade.

Cada skill define suas próprias regras de freshness.

---

## 17. Confiança

Quando aplicável, utilizar:

- low
- medium
- high

Confiança deve refletir qualidade e quantidade das evidências.

Não utilizar high apenas porque uma informação parece plausível.

---

## 18. Regras

Toda skill deve:

- respeitar CLAUDE.md;
- operar somente no cliente solicitado;
- carregar somente contexto necessário;
- preservar rastreabilidade;
- diferenciar observação de interpretação;
- declarar lacunas;
- evitar duplicação desnecessária.

---

## 19. Proibições

Toda skill é proibida de:

- inventar dados;
- inventar fontes;
- misturar clientes;
- ocultar conflitos relevantes;
- transformar hipótese em fato;
- extrapolar sua responsabilidade;
- executar ações externas não autorizadas.

---

## 20. Side Effects

Declarar explicitamente um dos níveis:

NONE:
Somente leitura e geração de contexto temporário.

MEMORY:
Pode atualizar memória canônica local.

EXTERNAL:
Pode executar ações em sistemas externos.

Skills com side effect EXTERNAL exigem autorização conforme CLAUDE.md.

---

## 21. Idempotência

Sempre que possível, executar a skill duas vezes sobre a mesma fonte deve produzir semanticamente o mesmo resultado.

Não duplicar registros apenas porque a skill foi executada novamente.

---

## 22. Critérios de qualidade

Antes de concluir, verificar:

1. O objetivo da skill foi atendido?
2. O output corresponde ao schema?
3. As evidências possuem origem?
4. Fatos e hipóteses estão diferenciados?
5. Existem lacunas não declaradas?
6. Houve mistura de clientes?
7. A skill ultrapassou sua responsabilidade?
8. Alguma informação importante foi descartada?
9. O status de execução está correto?
10. Todo timestamp de execução veio do relógio real do sistema, e nenhum está no futuro (CLAUDE.md seção 26)?
11. `observed_at` e `source_date` não foram confundidos entre si?

---

## 23. Falhas

Em caso de falha:

- não fabricar output válido artificialmente;
- registrar motivo;
- preservar outputs anteriores confiáveis quando aplicável;
- informar o que seria necessário para uma nova tentativa.

---

## 24. Exemplos

Exemplos aprovados devem ficar em:

skills/<skill-name>/examples/

Preferencialmente contendo:

- input;
- expected-output;
- observações de qualidade.

Os exemplos funcionam como referência comportamental da skill.
