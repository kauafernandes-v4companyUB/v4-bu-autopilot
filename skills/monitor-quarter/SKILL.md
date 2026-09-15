---
name: monitor-quarter
description: Safely preview and apply evidence-backed observations to one existing Quarter's monitoring.json without changing its plan.
---

# Monitor Quarter

## 1. Identidade

- **Classe:** ACTION
- **Canonical Side Effects:** `QUARTER_MONITORING`
- **Versão:** 1.0.0
- **Contrato de output:** `skills/monitor-quarter/output.schema.json`
- **Destino canônico exclusivo:** `clients/<client_id>/quarters/<quarter_id>/monitoring.json`

## 2. Objetivo e limites

Manter somente o estado **observado** de um Quarter existente: progresso do SMART, realizado de mídia e flags sustentadas por evidência. `plan.json` é imutável e somente leitura para esta skill.

Não usar para criar/ativar/fechar Quarter, replanejar, alterar SMART, target, baseline, planning ou `planned_budget`, migrar plano anterior, diagnosticar, inferir risco/pacing/status, criar tarefas, alterar `evidence.json` ou realizar qualquer ação externa. Uma observação que contradiz o plano pode gerar uma observação ou flag sustentada; nunca uma correção do plano.

## 3. Inputs e pré-condições

Input mínimo: `client_id`; `quarter_id` é opcional. `mode` é `preview` por padrão ou `apply`. O input contém um conjunto explícito e ordenado de `operations`; somente estes tipos são aceitos nesta versão:

1. `update_objective_progress`
2. `upsert_media_actual`
3. `create_flag`
4. `validate_flag`
5. `resolve_flag`

Cada operação observacional material requer `evidence_ids` existentes, sustentados e não vazios. A única exceção é uma tentativa idempotente de resolver flag já resolvida sem evidência nova: ela é um no-op, não uma nova observação. Esta skill não cria fatos, evidências ou registros no evidence ledger; se a proveniência exigida não estiver disponível, retorna `missing_data`/`error` e não escreve. Uma entrada manual só é admissível se for explicitamente identificada e permitida pelas regras canônicas vigentes; nunca é presumida por esta skill.

Antes de qualquer plano de mutação, validar o `plan.json` selecionado contra `schemas/quarter-plan.schema.json`. Ele precisa existir, ser válido e ter `client_id`/`quarter_id` coerentes com o caminho. Se `monitoring.json` existir, validá-lo integralmente contra `schemas/quarter-monitoring.schema.json` e confirmar a mesma identidade; não reparar, normalizar ou continuar sobre um monitoring inválido.

## 4. Resolução do Quarter

Reutilizar conceitualmente a resolução de `read-quarter`:

1. com `quarter_id`, usar exatamente esse Quarter;
2. sem ele, se houver exatamente um `plan.status = active`, usá-lo;
3. sem active, calcular `YYYY-QN` pela data real do sistema e usá-lo somente se o Quarter existir;
4. múltiplos active geram `error` de ambiguidade;
5. Quarter atual inexistente gera `error`; nunca criar Quarter.

Na descoberta automática, um plano inválido não se qualifica como active e é reportado em `warnings`; um plano explicitamente selecionado inválido é erro.

## 5. Preview, hash e apply

### Preview (padrão)

Ler, validar, normalizar operações e calcular `before`, `after` e o `mutation_plan`, sem escrever arquivo canônico. Se `monitoring.json` estiver ausente, o preview pode propor sua criação. O arquivo inicial proposto usa `schema_version` compatível, identidade do plano, `objective_progress` com `status: unknown`, `current_value: null`, `target_value` igual ao valor numérico do target do SMART, `progress_percent: null`, `observed_at: null` e `evidence_ids: []`, além de `media_monitoring: []` e `flags: []`. Isso não afirma realizado, progresso, gasto zero ou flags; só espelha o target já planejado para atender ao contrato canônico.

O preview produz `preview_hash`: SHA-256 de uma serialização JSON canônica (chaves ordenadas, UTF-8, sem espaços supérfluos) de `client_id`, `quarter_id`, o estado canônico relevante `before`, as operações já normalizadas e o `after` proposto. O plano deve também preservar esse snapshot/base hash e as precondições verificadas.

### Apply

Nunca é implícito. Requer pedido explícito, o `preview_hash` aprovado e o plano aprovado correspondente. Antes de escrever, reler e revalidar plano e monitoring, reconstruir a representação canônica de `before` e compará-la ao snapshot/base hash do preview. Se diferir, ou se o hash não reproduzir o plano aprovado, retornar `status: conflict` com `stale_preview`; não aplicar nada.

Aplicar somente o `after` lógico aprovado; `updated_at` é o único metadado de execução substituído pelo relógio real no momento do apply. Primeiro validar o objeto final inteiro contra `quarter-monitoring.schema.json`; então escrever uma única substituição atômica de `monitoring.json` (arquivo temporário no mesmo diretório, fsync e rename). Em operações múltiplas, qualquer operação inválida, conflito ou falha de validação aborta toda a aplicação: zero mutações canônicas. Apenas um apply material altera `updated_at`, com o relógio real UTC RFC3339 imediatamente antes da validação/escrita. Preview não muda timestamp; no-op apply conserva o arquivo e não finge alteração.

## 6. Operações

### `update_objective_progress`

Atualiza somente `monitoring.objective_progress`. Pode trazer `status`, `current_value`, `target_value`, `progress_percent`, `observed_at` e `evidence_ids`. `target_value` deve ser exatamente coerente com o target numérico e unidade do SMART do plano; não pode redefini-lo. Incompatibilidade é `conflict`/`error`.

Nunca inventar `current_value` nem inferir `on_track`, `at_risk`, `off_track` ou `achieved`. Esses status exigem classificação explícita sustentada pela operação/evidência. Calcular `progress_percent` apenas quando a aritmética, unidade e direção forem objetivamente compatíveis com o SMART; caso contrário, preservar `null` ou apenas valor explicitamente sustentado. `observed_at` deve ser um timestamp observacional permitido e rastreável, nunca `source_date` inferida do conteúdo.

### `upsert_media_actual`

Exige `month`, `channel`, `actual_spend >= 0` (decimal BRL) e `evidence_ids`. A chave lógica é `(month, channel)`: nenhum par existente cria um registro; um único par é atualizado; mais de um par existente é `conflict` e nada é escolhido, somado ou escrito. A operação idêntica não cria duplicata.

Para par planejado, copiar `planned_budget` exclusivamente do `plan.json` e recalcular deterministicamente `attainment_percent = actual_spend / planned_budget * 100` e `variance_value = actual_spend - planned_budget`. Quando o planejado é zero, attainment é `null`; variance continua aritmética. `pacing_percent` só é preservado quando explicitamente sustentado e aceito pelo schema; nunca é inventado. Para par não planejado, preservar o actual com `planned_budget`, attainment e variance como `null`, emitir o warning `unplanned_media_actual` e nunca adicionar linha ao plano ou criar flag.

### Flags

`create_flag` exige `flag_id`, tipo canônico, `statement` e evidências. Cria somente uma observação explícita como `open`, `resolved_at: null`; usa o relógio real UTC para `first_seen_at` e `last_validated_at`, salvo temporalidade explícita permitida pelo contrato. Não criar risco automaticamente a partir de budget, progresso ou atraso.

`validate_flag` exige `flag_id` existente e evidências. Preserva `first_seen_at`, `statement` e `type`, mantém `open`, atualiza `last_validated_at` pelo relógio real e une `evidence_ids` sem duplicar. Flag resolvida não é reaberta: retornar conflito; `reopen` não existe nesta versão.

`resolve_flag` exige `flag_id` existente e incorpora evidências da resolução, preserva `first_seen_at`, define `status: resolved`, `resolved_at` e `last_validated_at` pelo relógio real. Não exclui a flag. Repetir em uma flag já resolvida sem informação material nova é `no_change`; com nova evidência apenas incorpora a proveniência e atualiza a validação, sem recriar a flag.

## 7. Output, status e qualidade

O output é transitório em `context/generated/<client_id>/` quando persistido e valida contra o contrato desta skill. Deve declarar fontes, operações, `mutation_plan`, `preview_hash`, `before`, `after`, alterações aplicadas, conflitos, lacunas, warnings e validação. `before`/`after` não nulos usam os objetos integrais do schema canônico, não projeções locais.

Status: `success` para plano/apply válido material; `no_change` para plano ou apply idempotente sem mutação; `partial` apenas para resultado útil com warning não bloqueante; `error` para entrada/validação ausente ou inválida; `conflict` para ambiguidade, incompatibilidade, flag resolvida ou `stale_preview`.

Antes de concluir, verificar: isolamento do cliente; `plan.json` intacto; schema Draft 2020-12 e referências externas pelo `referencing.Registry`; unicidade de mídia; proveniência; atomicidade; ausência de timestamps futuros; e `git diff --check`. Nunca commit ou push.

## 8. Casos de conformidade em memória

Implementações devem testar, sem persistir cliente fictício: criação proposta para monitoring ausente (A), preview sem escrita (B), apply aprovado válido (C), stale preview (D), mídia planejada e cálculos 1500/2000 (E), upsert idempotente (F), orçamento zero (G), mídia não planejada com warning e plano intacto (H), duplicidade existente conflitando (I), criação (J), validação (K) e resolução (L) de flag, resolução idempotente (M), tentativa de alterar target (N), actual ausente/inválido (O), `after` inválido sem escrita (P) e lote com operação inválida sem mutação parcial (Q), além de D2/R, N1/S, N2/T, N3/U, V, W, X, Y, Z, AA, AB, AC e AD: plan alterado após preview, binding correto/diferente/null do target, campo de outra operação, operation_id duplicado, duplicidade de mídia/flag, flag existente, evidência resolvível, warning sem partial e no-op preservando updated_at.

## 9. Esclarecimentos contratuais finais

Esta seção prevalece sobre formulações anteriores desta skill quando houver diferença.

base_state_hash é SHA-256 da serialização JSON canônica, com chaves ordenadas, UTF-8 e sem espaços supérfluos, de {"plan": <plan integral validado>, "monitoring": <monitoring integral atual ou null>}. preview_hash é SHA-256 da mesma serialização canônica de client_id, quarter_id, base_state_hash, operations normalizadas e after lógico aprovado. No apply, reler e revalidar plan e monitoring, recalcular base_state_hash e comparar ao preview. Qualquer alteração em qualquer um deles retorna conflict com o código stale_preview e causa zero escrita.

Ler evidence.json do mesmo cliente somente para validar. Toda operação material exige evidence_ids não vazios, presentes nesse ledger e pertencentes ao cliente; ausência, ID órfão ou evidência de outro cliente retorna error/missing_data com o código unresolved_evidence e aborta todo o lote. Nesta v1 não há operação manual sem evidência. A exceção é resolve_flag em flag já resolved, sem nova evidência, quando a execução é puro no-op.

operation_id deve ser único na execução; IDs repetidos são error ou conflict e causam zero mutações. Cada operation deve ser validada por sua variante discriminada: campos de outro tipo são rejeitados antes do planejamento.

objective_progress.target_value é sempre plan.smart_objective.target.value. A unidade semântica fica no SMART do plan. A criação inicial copia somente esse valor. Em update_objective_progress, target_value é opcional, mas quando fornecido deve ser número igual ao target do plan; null é inválido e divergência é conflict target_mismatch. O after final preserva obrigatoriamente esse vínculo.

Antes de upsert_media_actual, contar o par month+channel no plan e no monitoring. Mais de uma linha no plan é conflict ambiguous_planned_media; mais de uma no monitoring é conflict ambiguous_monitored_media. Nunca escolher ou somar. Antes de cada operação de flag, flag_id também deve ser único: create requer zero; validate e resolve requerem exatamente uma open; nenhuma é error/missing, duplicidade é conflict. Uma única resolved admite somente o no-op de resolve sem informação nova; validate não reabre flag.

Warnings não bloqueantes, inclusive unplanned_media_actual, não tornam uma execução válida partial: ela retorna success, preserva a observação e mantém o plan intacto. partial é somente preview informativo com dado não essencial incompleto e nunca autoriza apply parcial. Apply retorna somente success, no_change, conflict ou error.

No preview, after é proposta lógica válida e pode usar o relógio real do preview em updated_at. Em apply material, somente after.updated_at é substituído pelo relógio real do apply; todos os demais campos correspondem ao plano aprovado. No-op preserva updated_at e não reescreve arquivo.
