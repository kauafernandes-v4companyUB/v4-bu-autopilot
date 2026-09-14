# SKILL — READ WHATSAPP

## 1. Identificação

Nome: Read WhatsApp

Slug: read-whatsapp

Categoria: source

Versão: 1.0.0

Side Effects: NONE

---

## 2. Objetivo

Ler exportações de conversas do WhatsApp relacionadas a UM `client_id`, isolar estritamente o contexto pertinente e transformar apenas a comunicação observada em dados estruturados e evidências rastreáveis.

Esta skill observa. Não diagnostica, não replaneja, não gera tarefa, não promove memória e não executa ação externa.

---

## 3. Quando usar

Usar para uma exportação textual compatível de conversa individual, grupo com cliente e time interno, ou exportação que apenas referencie anexos:

- `whatsapp_export`;
- `whatsapp_chat_export`;
- `client_whatsapp_export`.

---

## 4. Quando NÃO usar

Não usar para `account_gt_transcript`, `client_checkin_transcript`, `account_handoff`, `client_handoff`, `bi_dashboard`, `crm_export`, `task_export`, `task_list`, `unrelated_document` ou `unknown`.

Também não usar para diagnosticar, calcular gap, priorizar, replanejar, criar briefing, gerar tarefa, alterar memória canônica, publicar, enviar mensagem ou abrir links. Essas responsabilidades pertencem a outras skills.

---

## 5. Responsabilidade

Esta skill é responsável por:

- qualificar a fonte antes da extração;
- isolar a conversa e as mensagens pertencentes ao cliente solicitado, inclusive em fonte multi-cliente;
- estruturar participantes sem inventar seus papéis;
- preservar direção, autoria, reply, citação e referência local da comunicação quando suportados;
- extrair observações conversacionais por bloco semântico e gerar evidências rastreáveis;
- observar cancelamento, alteração, aprovação, rejeição ou substituição explícita entre mensagens da própria conversa;
- registrar ambiguidades, lacunas e limitações da exportação.

Esta skill NÃO é responsável por:

- tratar relato indireto como fala direta do cliente;
- tratar métrica relatada como métrica validada em BI, CRM ou plataforma;
- interpretar mídia/anexo não fornecido como fonte legível;
- transformar request em decision, commitment em tarefa concluída, pending em tarefa, ou planejamento em execução;
- resolver conflitos com memória canônica ou promover qualquer memória.

---

## 6. Inputs e fontes permitidas

Obrigatórios: `client_id` e uma referência de exportação WhatsApp legível (`source_path` ou `source_url`). Opcionais: seletor do cliente e contexto explicitamente fornecido para identificar participantes.

Pode usar memória canônica mínima somente quando indispensável para resolver a identidade de um stakeholder. Nunca a use para completar o conteúdo da conversa. Não abra links das mensagens, não busque conteúdo externo e não interprete arquivo de mídia/anexo que não tenha sido fornecido nesta execução.

---

## 7. Qualificação e isolamento

Antes de extrair semântica:

1. classificar `source_kind` e definir `source_compatible = true` somente para `whatsapp_export`, `whatsapp_chat_export` ou `client_whatsapp_export`;
2. registrar a qualificação como fato sobre a fonte, não sobre o cliente;
3. se incompatível, retornar `failed`, sem extração semântica e com `data` vazio;
4. se houver múltiplos clientes, delimitar somente mensagens inequivocamente associadas ao `client_id`; conteúdo adjacente serve apenas para boundary;
5. reduzir confidence e emitir warning quando houver alternância ambígua; se não for possível isolar com segurança, retornar `failed` sem atribuição ao cliente.

`success` exige fonte compatível, cliente isolado e evidências úteis sem bloqueio; `partial` é para ambiguidade relevante, participantes não resolvidos ou temporalidade incompleta; `failed` é para fonte incompatível, ilegível ou cliente não isolável.

---

## 8. Participantes e direção

Em `participants`, preservar `participant_name`, `participant_role`, `role_confidence` e `role_basis`. Os únicos papéis são `client`, `account`, `traffic_manager`, `internal_team`, `external_partner` e `unknown`. Sem sustentação suficiente, usar `unknown`.

Toda observação relevante deve preservar `communication_direction`: `direct_client_statement`, `internal_statement`, `external_statement`, `quoted_statement`, `forwarded_statement` ou `unknown`. Uma fala relatada pelo time sobre o que o cliente teria dito não equivale a uma fala direta do cliente.

Quando houver reply/citação, preservar a mensagem atual, a referência da mensagem respondida, participante original e a relação. Use o menor contexto necessário para auditoria; nunca copie a conversa inteira.

---

## 9. Semântica, aprovações e superação interna

Usar exclusivamente `fact`, `metric`, `decision`, `hypothesis`, `request`, `commitment`, `pending`, `risk`, `idea` e `dependency`, preservando o tipo original. Pedido direto de criativo é `request`; concordância inequívoca sobre oferta é `decision`; promessa de envio é `commitment`; espera de estoque é `pending` ou `dependency` conforme o contexto; opinião sobre anúncio é `hypothesis`; número explicitamente declarado é `metric` reportada.

Respostas curtas como “ok”, “sim”, “pode”, “aprovado”, “fechado”, “manda”, emoji ou reação só são `decision`/approval se o objeto estiver inequivocamente resolvível pela mensagem citada, reply ou contexto imediato. Reação isolada nunca basta. Quando o referente não for claro, não inventar decisão e registrar ambiguity/warning se relevante.

Uma mensagem posterior que explicitamente cancela, altera, aprova, rejeita ou substitui outra deve preservar a relação em `supersedes_evidence_ids`/`superseded_by_evidence_ids` dos itens estruturados. Isto descreve apenas a conversa e não resolve conflito com memória canônica.

---

## 10. Temporalidade e métricas

`generated_at` e `observed_at` vêm do relógio real do sistema, em UTC RFC3339. `source_date` de cada evidência é a data da mensagem que a sustenta, em `YYYY-MM-DD`, ou `null` quando a própria fonte não permitir determiná-la. `conversation_start_date` e `conversation_end_date` só aparecem quando suportadas. Horário local sem timezone confiável deve permanecer como `local_time_reference`, sem conversão artificial para UTC.

Métricas de WhatsApp devem declarar `reported_in_conversation: true`, autoria e direção. Nunca substituem BI, CRM, Ads Manager ou outra fonte estruturada autoritativa.

---

## 11. Procedimento

1. validar inputs e qualificar a fonte;
2. isolar o cliente e seus limites com segurança;
3. identificar participantes e direção de cada fala relevante;
4. extrair apenas mensagens no limite seguro, replies/citações e relações temporais suportadas;
5. classificar, deduplicar por mensagem/afirmação e gerar uma evidência por observação equivalente;
6. preencher `data`, usando os mesmos `evidence_ids` em blocos distintos quando necessário;
7. registrar warnings/missing_data e validar o output.

Os blocos possíveis em `data` são `client_requests`, `client_decisions`, `commitments`, `pending`, `dependencies`, `campaign_feedback`, `commercial_feedback`, `performance_mentions`, `risks`, `ideas`, `references` e `unresolved_questions`. Não preencher blocos sem suporte.

---

## 12. Evidência, output e validação

Cada evidência valida contra `schemas/evidence.schema.json`. Como esse contrato é estrito, metadados conversacionais adicionais ficam no item estruturado correspondente; a `reference` universal identifica arquivo, participante, data e horário/localização disponíveis.

O output vai para `context/generated/<client_id>/whatsapp.json` e valida contra `skills/read-whatsapp/output.schema.json`. Antes de concluir, validar JSON, Draft 2020-12, refs, IDs únicos, timestamps não futuros, isolamento do cliente e `git diff --check`. Esta skill não altera `clients/`, não faz commit e não faz push.
