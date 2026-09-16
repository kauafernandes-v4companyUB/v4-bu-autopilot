---
name: replan-client
description: Turn priorities into a replanning proposal — workstreams and action proposals, never Quarter plan mutations, never tasks yet.
---

# Replan Client

## 1. Identity

- **Class:** INTELLIGENCE (read-only — no canonical/external side effects)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/replan-client/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Replanning", and `operation/quarter-rules.md` (plan immutability).

## 2. Objetivo

Produzir uma proposta de replanejamento — direção estratégica, workstreams e ações propostas — a partir das prioridades já identificadas, sem tocar o plano canônico do Quarter e sem criar tarefas ainda.

## 3. Quando usar

Depois de `identify-priorities`, antes de `audit-plan`.

## 4. Quando NÃO usar

- sem prioridades validadas;
- para alterar `plan.json` (SMART, target, baseline, `planned_budget`) — isso nunca é responsabilidade desta skill nem de nenhuma skill atual; uma mudança real de plano é um fluxo futuro explícito, fora deste MVP;
- para gerar tarefas de fato (isso é `generate-tasks`, e só depois de `audit-plan` não falhar).

## 5. Inputs

Obrigatórios: `context_pack`, `diagnosis`, `gaps`, `priorities` (todos validados, refs computadas).

## 6. Procedimento

1. Ler os quatro artefatos upstream.
2. `objective_alignment`: relacionar a proposta ao SMART vigente (`context_pack.strategic_context`) — nunca redefini-lo.
3. `what_changed`/`what_remains`: o que este replanejamento altera na direção operacional vs. o que continua igual desde a última estratégia registrada.
4. Para cada `priority` relevante (tipicamente as de maior `order`), criar um `workstream`: objetivo, racional, evidências, e uma lista de `actions` propostas.
5. Cada `action` é uma **proposta**, nunca uma tarefa: precisa de `reason`, `expected_effect`, `evidence_ids`, e — crucialmente — `deadline_requirement` correto (seção 7).
6. Marcar `external_action_required`/`irreversible` honestamente — isso alimenta `audit-plan` e, depois, a decisão do operador.
7. Preencher `do_not_do` quando relevante (algo que parece óbvio mas que o contexto desaconselha, com `rationale` implícito no texto).
8. Validar e escrever `replanning.json`.

## 7. `deadline_requirement` — nunca inventar prazo

- `explicit`: já existe um deadline real, evidenciado (`deadline_source` = evidence_id).
- `derived_from_existing_commitment`: herda uma data já comprometida em outro lugar (`deadline_source` aponta para essa evidência/decisão).
- `needs_operator_decision`: a ação precisaria de prazo, mas nenhum existe — isso é um resultado válido e esperado, não uma falha.
- `none`: a ação não tem natureza de prazo (ex.: um monitoramento contínuo).

## 8. Preservar o plano do Quarter

`replan-client` **nunca** escreve em `plan.json`. Uma recomendação como "revisar o budget de Meta Ads" entra como `statement`/`reason` de uma `action` — nunca como mutação. Qualquer fluxo futuro que de fato altere o plano exige um mecanismo explícito e separado (fora do escopo desta skill).

## 9. Regras e proibições

- toda `action` precisa de `evidence_ids` (pode ser vazio somente quando a ação deriva puramente de uma priority já evidenciada — preferir sempre citar evidência própria);
- nunca marcar `external_action_required: false` para algo que na prática requer sistema/parte externa;
- nunca disfarçar uma mudança de budget como "execução";
- nunca transformar uma `hypothesis` do diagnóstico em premissa afirmada de uma action sem repetir o caráter hipotético no `reason`.

## 10. Idempotência

Mesmos quatro artefatos upstream → mesmos workstreams/actions semanticamente.
