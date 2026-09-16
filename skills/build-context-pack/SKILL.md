---
name: build-context-pack
description: Consolidate already-normalized SOURCE/canonical outputs for one client into a single Context Pack, read-only, answering "do I have enough context to diagnose this client?"
---

# Build Context Pack

## 1. Identity

- **Class:** INTELLIGENCE (read-only — no canonical or external side effects; CLAUDE.md section 2)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/build-context-pack/output.schema.json` (= `schemas/context-pack.schema.json` directly — see that file's `description`)
- **Policy:** `operation/replanning-rules.md`, `operation/evidence-authority.md` (freshness categories)

## 2. Objetivo

Montar, para um `client_id` (e `quarter_id` quando aplicável), um Context Pack: a consolidação de tudo que já foi normalizado sobre o cliente — canonical memory + outputs de SOURCE já executados — em uma forma única, rastreável, que as demais skills INTELLIGENCE consomem sem precisar reabrir cada fonte.

Esta skill **não diagnostica**. Ver CLAUDE.md seção 17 e o exemplo canônico em `operation/replanning-rules.md`: "CTR caiu" pode entrar em `observed_results` se evidenciado; "o criativo está fatigado" nunca entra aqui como fato — isso é hipótese, pertence a `diagnose-client`.

## 3. Quando usar

- antes de `diagnose-client`, sempre;
- quando o operador pedir "replaneje `<cliente>`" ou equivalente (`docs/workflows/replan-client.md`);
- quando for necessário responder objetivamente "tenho contexto suficiente para este trabalho?" (CLAUDE.md seção 17), mesmo fora de um replanejamento completo.

## 4. Quando NÃO usar

- para diagnosticar, calcular gap, priorizar, replanejar, auditar ou gerar tarefas — cada uma dessas é uma skill própria a jusante;
- para ler uma fonte bruta diretamente — isso é responsabilidade das SOURCE skills (`read-bu`, `read-client-context`, `read-account-gt`, `read-whatsapp`, `read-bi`, `read-quarter`); esta skill só consolida o que elas (ou a memória canônica) já produziram.

## 5. Inputs

Obrigatório: `client_id`.

Opcional: `quarter_id` (default: resolução por `read-quarter` — exatamente um plano `active`, senão o Quarter atual pelo relógio real se existir); `sources` — lista explícita de quais fontes considerar, quando o operador quiser restringir (lazy loading, CLAUDE.md seção 3). Sem essa lista, considerar todas as fontes canônicas/normalizadas disponíveis para o cliente.

## 6. Fontes permitidas

No workspace do cliente (`<workspace_root>/`, `scripts/lib/workspace.py`):

- `clients/<client_id>/{client.json,current-state.json,decisions.json,evidence.json,knowledge.json,sources.json,strategy.md,tasks.json}`;
- `clients/<client_id>/quarters/<quarter_id>/{plan.json,monitoring.json,check-ins/*.json}`;
- outputs já normalizados de SOURCE em `context/generated/<client_id>/**` quando existirem e forem legíveis (ex.: `bi/read-bi.json`, `whatsapp.json`, `account-gt.json`), tratados como `source_observation` no `evidence_index`, nunca como canônicos.

Nunca ler `private/**` diretamente — essa é responsabilidade das SOURCE skills.

## 7. Procedimento

1. Resolver `client_id`/`quarter_id` (via `read-quarter` se não explícito).
2. Para cada fonte relevante, verificar disponibilidade, ler o output já normalizado (canonical ou `context/generated/`), e preencher uma entrada de `source_status` (seção 8) — `available: false` é um resultado válido, não uma falha da consolidação.
3. Extrair de `plan.json` o `strategic_context` (SMART, target, baseline, priorities, assumptions) — nunca reinterpretar, só copiar com `evidence_ids` apontando às evidências que sustentam o plano (`plan.json.planning.evidence_ids`).
4. Extrair de `monitoring.json` (se existir) `observed_results.media_monitoring`/`objective_progress`.
5. Extrair de `evidence.json` + outputs SOURCE normalizados: `observed_results.metrics`/`commercial_results`, `client_voice.{decisions,requests,feedback,ideas,dependencies}`, `operational_state.pending`. Cada item carrega `evidence_ids` que devem resolver em `evidence_index` (passo 7).
6. Extrair `operational_state.tasks_summary` de `tasks.json` (contagens apenas — nunca reescrever `overdue`, que é sempre derivado em runtime, `operation/task-rules.md`) e `operational_state.ropre_state` do `check-ins/current.json` mais recente (ou `absent`/`unknown` quando não existir — nunca inventar `scheduled_for`, `operation/ropre-rules.md`).
7. Montar `evidence_index`: toda evidência canônica citada (`kind: canonical`) mais qualquer observação de SOURCE ainda não promovida mas relevante ao pack (`kind: source_observation`) — cada uma com `id`, `type`, `statement`, `confidence`, `source`, `observed_at`.
8. Detectar conflitos explícitos entre fontes (duas evidências que se contradizem sobre o mesmo fato) e registrar em `conflicts`, nunca resolver silenciosamente (CLAUDE.md seção 9).
9. Registrar `missing_data` para toda fonte ausente/inacessível relevante, com `impact` e `blocking`.
10. Avaliar `quality.sufficient_for_diagnosis` e `quality.confidence`, com `reasons` explícitas — nunca uma métrica numérica composta.
11. Validar contra o schema e escrever `context-pack.json`.

## 8. `source_status` e freshness

Uma entrada por fonte considerada (`source_status[]`), com `freshness` restrito a `current` / `historical` / `unknown` (`operation/evidence-authority.md` — nunca um limiar de dias hardcoded). `status` é `success`/`partial`/`failed`/`not_run`/`not_applicable` (ex.: Google Ads sem spend disponível é `not_applicable`, não `failed`).

## 9. Output

`context/generated/<client_id>/replanning/context-pack.json`, validado contra `schemas/context-pack.schema.json`. `context_pack_id` conceitual pode ser o próprio `generated_at` combinado a `client_id`/`quarter_id` — não é referenciado por artifact_ref (é a raiz da cadeia); artefatos a jusante o referenciam via `schemas/artifact-ref.schema.json` (`scripts/lib/artifact_hash.py`).

## 10. Status, missing data, warnings, confiança

Seguir `skills/_template/SKILL.md` seções 13-17. `status: partial` é o resultado normal quando alguma fonte relevante está ausente mas o pack ainda é útil; `failed` só quando nenhuma fonte mínima (ao menos `plan.json` + `evidence.json`) está disponível.

## 11. Regras e proibições

Além do template (seções 18-19) e de `operation/replanning-rules.md`:

- nunca interpretar, diagnosticar ou hipotetizar — só consolidar e rastrear;
- nunca inventar `source_status` para uma fonte não verificada;
- nunca copiar texto de evidência sem `evidence_ids` correspondentes;
- nunca misturar `client_id`.

## 12. Idempotência

Mesmas fontes, mesmo estado canônico → mesmo `context-pack.json` semanticamente (mesmos `source_status`, `evidence_index`, `quality`). `generated_at` muda a cada execução (timestamp de execução real, CLAUDE.md seção 26) — isso é esperado e é exatamente por isso que artefatos a jusante usam `content_sha256` (que ignora `generated_at`? não — o hash cobre o JSON completo, então uma nova execução produz um novo hash mesmo com conteúdo semanticamente idêntico; isso é aceitável: o objetivo do artifact_ref é detectar *drift*, não perseguir idempotência byte-a-byte do pack inteiro).
