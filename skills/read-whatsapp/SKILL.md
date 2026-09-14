# SKILL — READ WHATSAPP

## 1. Identificação

Nome: Read WhatsApp

Slug: read-whatsapp

Categoria: SOURCE

Versão: 1.1.0

Side Effects: NONE

## 2. Objetivo

Ler exportação textual WhatsApp de UM `client_id`, isolar somente o contexto pertinente e produzir observações/evidências rastreáveis com baseline ou processamento incremental determinístico. A skill apenas observa: não diagnostica, replaneja, gera tarefa, promove memória, persiste cursor, altera `clients/` ou executa ação externa.

## 3. Fonte, qualificação e isolamento

Compatíveis: `whatsapp_export`, `whatsapp_chat_export`, `client_whatsapp_export`. Incompatíveis: `account_gt_transcript`, `client_checkin_transcript`, `account_handoff`, `client_handoff`, `bi_dashboard`, `crm_export`, `task_export`, `task_list`, `unrelated_document`, `unknown`.

Pode ler conversa individual, grupo cliente/time ou exportação que referencia anexos. Não abrir links, buscar conteúdo externo ou interpretar mídia que não foi fornecida como legível. Fonte incompatível retorna `failed`, sem extração e com `data` vazio.

Em fonte multi-cliente, isolar somente mensagens inequivocamente do `client_id`; adjacência serve apenas a boundary. Alternância ambígua reduz confidence e gera warning. Se o cliente não for isolável, retornar `failed`, sem atribuir conteúdo.

## 4. Inputs e modos de ingestão

São obrigatórios `client_id`, fonte legível e `ingestion_mode`: `baseline` ou `incremental`. Em incremental, `previous_cursor` aprovado é obrigatório. Memória canônica mínima só pode resolver identidade de stakeholder, nunca preencher conversa.

**baseline** processa todo histórico textual disponível, constrói baseline e produz cursor final; não presume leitura semântica de toda mídia.

**incremental** recebe cursor, localiza a sequência contígua e ordenada dos três `anchor_fingerprints` no novo export completo e, se houver exatamente uma correspondência segura, processa apenas mensagens posteriores ao último anchor em SOURCE ORDER. Histórico anterior só pode ser lido como contexto mínimo de reply/referência. Se o anchor não existir, ocorrer mais de uma vez, ou edição/export o quebrar, não usar data como fallback, não adivinhar e não perder mensagens: registrar `cursor_resolution`, warning e `missing_data`; retornar `failed` se não houver fronteira segura para avançar e `partial` somente quando a limitação estiver declarada sem alegar processamento posterior seguro.

`next_cursor` é produzido, mas nunca persistido em `clients/`; não criar source-state.

## 5. Parser e normalização

O arquivo principal é normalmente `_chat.txt`. Uma nova mensagem humana começa **somente** em linha que casa com `[DD/MM/YYYY, HH:MM:SS] Participante: conteúdo`. Toda linha seguinte sem novo header pertence ao body da mensagem anterior. Evento de sistema só é reconhecido quando a própria exportação o apresentar como tal; nunca se inventa participante ou conteúdo humano para ele.

Preservar `source_sequence` (ordem física), `message_date`, `local_time_reference`, `participant_raw`, participante resolvido quando sustentado, body/raw context necessário, anexos e markers. Não ordenar destrutivamente por timestamp: `source_sequence` é a referência de cursor; data/hora não a substitui.

Para parsing/matching: CRLF→LF, Unicode NFC e remoção de caracteres invisíveis de controle/formatação somente quando necessária ao matching. Nunca alterar semanticamente mensagem/nome; preservar raw participant/body quando necessário. Normalizar identidade é camada separada da fonte.

`message_fingerprint` = SHA-256 (hexadecimal minúsculo) do JSON UTF-8 sem whitespace extra, com chaves nesta ordem: `message_date` (ISO), `local_time_reference` (literal da fonte), `participant_matching`, `body_matching` e `attachment_filenames` (na ordem em que aparecem no body). Os campos `*_matching` usam somente CRLF→LF, NFC e remoção de controles/formatação invisíveis estritamente necessária ao matching. Não depende de execução, linha ou apenas data; não é evidência de negócio e deve reproduzir a mesma mensagem em novo export.

Nas etapas determinísticas de parsing, normalização/fingerprint e resolução de cursor, preferir o helper `scripts/parse_export.py`; seu JSON é artefato intermediário estrutural e não substitui o output final da skill.

`anchor_fingerprints` contém, em source order, as três últimas mensagens parseadas. Cursor só é emitido quando essas três âncoras existem; a resolução incremental exige exatamente essa sequência contígua uma única vez. O cursor não inclui body completo.

O range de conversa vem dos timestamps suportados de mensagens parseadas, e não da primeira/última linha física.

## 6. Participantes, direção e semântica

Em `participants`, preservar `participant_name`, `participant_role` (`client`, `account`, `traffic_manager`, `internal_team`, `external_partner`, `unknown`), `role_confidence`, `role_basis`. Sem sustentação, usar `unknown`.

Cada observação preserva `communication_direction`: `direct_client_statement`, `internal_statement`, `external_statement`, `quoted_statement`, `forwarded_statement`, `unknown`. Relato do time não equivale à fala direta. Reply/citação preserva mensagem atual, referência, participante original e relação, usando mínimo contexto auditável.

Usar somente `fact`, `metric`, `decision`, `hypothesis`, `request`, `commitment`, `pending`, `risk`, `idea`, `dependency`, sem elevar tipo. Métrica explicitamente declarada é reportada na conversa (`reported_in_conversation: true`) e nunca substitui BI/CRM/Ads Manager. Pedido é request; promessa de envio é commitment; opinião é hypothesis, não metric.

“ok”, “sim”, “pode”, “aprovado”, “fechado”, “manda”, emoji ou reação só são decision/approval se o objeto for inequivocamente resolvível por reply, citação ou contexto imediato. Reação isolada nunca basta. Referência ambígua não vira decisão e gera warning se relevante.

Cancelamento, alteração, aprovação, rejeição ou substituição explícita posterior deve ser ligado por evidence IDs; a skill observa a relação dentro da conversa, não resolve memória canônica.

## 7. Sistema, edição e mídia

Criação de grupo, inclusão/remoção, configuração/imagem e criptografia não geram evidência de negócio automaticamente, mas podem ajudar contexto, participantes e membership timeline. `<Mensagem editada>` preserva marker sem versão anterior inventada; mensagem apagada só é registrada se operacionalmente relevante, com conteúdo `unknown`; vídeo omitido/mídia indisponível não tem conteúdo inferido.

Construir índice de mídia sem abrir centenas de arquivos. Cada candidato relevante pode conter filename, tipo, sequence, data, participante, referência, relevância (`high`, `medium`, `low`), motivo e deep read (`not_needed`, `pending`, `completed`, `unavailable`). High inclui mídia do cliente ligada a request/decision/commitment, documento comercial/estratégico, mídia necessária para decisão, áudio operacional e mídia recente de current state. Stickers, memes, mídia social sem contexto e duplicatas evidentes são low por padrão. Conteúdo só é interpretado com leitura real.

`baseline_complete` só é true quando texto relevante foi processado, índice de mídia foi construído e mídia necessária para evidência importante foi lida ou marcada `pending`/`unavailable` com impacto declarado. Ler `_chat.txt` não basta; o bloco é avaliação de completude do baseline, não alegação de que toda mídia do ZIP foi lida.

## 8. Output e validação

Salvar em `context/generated/<client_id>/whatsapp.json`. O output contém source, qualification, ingestion, previous/next cursor, conversation_context, participants, baseline_completion, media index/candidates, data, evidence, warnings e missing_data. Evidências validam contra `schemas/evidence.schema.json`; metadados conversacionais ficam nos itens estruturados e `reference` identifica arquivo/participante/data/localização.

`generated_at`/`observed_at` vêm do relógio real UTC RFC3339. `source_date` é a data da mensagem `YYYY-MM-DD` ou null se não sustentada. Validar JSON, Draft 2020-12, refs absolutos, IDs únicos, timestamps não futuros, isolamento, cursor e `git diff --check`. Sem alteração em clients/, commit ou push.
