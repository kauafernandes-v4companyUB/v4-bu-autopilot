---
name: identify-priorities
description: Rank where to concentrate operational attention using explicit, justifiable dimensions — never an arbitrary numeric score.
---

# Identify Priorities

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/identify-priorities/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Prioritization".

## 2. Objetivo

Decidir, de forma justificável e rastreável, onde concentrar atenção operacional — a partir do diagnóstico e dos gaps já produzidos, nunca por "parecer boa ideia".

## 3. Quando usar

Depois de `calculate-gap`, antes de `replan-client`.

## 4. Quando NÃO usar

- sem diagnóstico e gaps validados;
- para propor ações concretas (isso é `replan-client`) — uma priority é "onde olhar", não "o que fazer".

## 5. Inputs

Obrigatórios: `context_pack`, `diagnosis`, `gaps` (todos validados, refs computadas).

## 6. Dimensões permitidas (nunca um score único)

Toda posição em `order` precisa ser justificável por ao menos uma destas dimensões, preenchida em `rationale_dimensions`:

- `impact_on_active_smart` — relação com o SMART vigente do Quarter;
- `factual_urgency` — urgência sustentada por data/evento real, não "parece urgente";
- `dependency_or_blocking` — bloqueia outro trabalho;
- `evidence_strength` — quão bem sustentado é o finding/gap relacionado;
- `reversibility` — quão fácil é desfazer se a priorização se mostrar errada;
- `effort_known` — **só preencher quando o esforço é realmente conhecido**; nunca estimar esforço para justificar um rank;
- `client_request_or_decision` — o cliente pediu/decidiu isso explicitamente;
- `operational_obligation` — compromisso já assumido pela operação.

Uma dimensão sem sustentação (todas `null`) é proibida — `scripts/lib/replanning_lint.py::lint_priorities` rejeita.

## 7. Procedimento

1. Ler `diagnosis.json` + `gaps.json`.
2. Levantar candidatos a priority a partir de `findings`/`gaps` relevantes (um candidato pode agregar mais de um finding/gap relacionado).
3. Para cada candidato, preencher `rationale_dimensions` com o que de fato se aplica (demais campos `null`).
4. Ordenar (`order`, sequência contígua 1..N) — a ordem é permitida porque é priorização operacional do plano do próprio cliente, não avaliação política/externa (CLAUDE.md).
5. Candidatos considerados mas não promovidos vão em `excluded_candidates` com `reason_excluded`.
6. Validar e escrever `priorities.json`.

## 8. Regras e proibições

- nunca combinar dimensões numa média/score;
- nunca inventar `effort_known`;
- toda `priority` precisa de `evidence_ids` (≥1) e ao menos um `related_findings`/`related_gaps`.

## 9. Idempotência

Mesmos `diagnosis.json`/`gaps.json` → mesmo conjunto e ordem de priorities.
