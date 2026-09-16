---
name: diagnose-client
description: Reason over a Context Pack to produce evidence-traceable findings, explicitly distinguishing observed issues, neutral observations, hypotheses, missing data, and risks — never a numeric health score.
---

# Diagnose Client

## 1. Identity

- **Class:** INTELLIGENCE (read-only — no canonical/external side effects)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/diagnose-client/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Diagnosis vs observation" — read it before writing a single finding.

## 2. Objetivo

Produzir um diagnóstico rastreável do estado do cliente a partir de um Context Pack já validado — identificando o que está observado, o que é hipótese, o que está faltando, e que riscos existem — sem nunca reduzir isso a uma nota/score artificial.

## 3. Quando usar

Depois de `build-context-pack`, antes de `calculate-gap`.

## 4. Quando NÃO usar

- sem um Context Pack validado como input;
- para calcular gap numérico (isso é `calculate-gap`);
- para priorizar ou propor ações (isso é `identify-priorities`/`replan-client`);
- para escrever memória canônica — um `finding`, mesmo `confidence: high`, nunca é promovido a `knowledge.json` por esta skill (isso seria `promote-client-memory`, e só com autorização explícita separada).

## 5. Inputs

Obrigatório: `context_pack` (path para `context-pack.json`, validado contra `schemas/context-pack.schema.json`). Se `context_pack.quality.sufficient_for_diagnosis == false`, a skill pode prosseguir com `status: partial`, mas deve declarar explicitamente, em `warnings`, quais `missing_data` do pack limitam o diagnóstico — nunca prosseguir como se o pack fosse suficiente.

## 6. Procedimento

1. Ler e validar `context-pack.json`; computar `context_pack_ref` (`scripts/lib/artifact_hash.py`).
2. Para cada domínio relevante (`objective`, `acquisition`, `media`, `creative`, `funnel`, `commercial`, `client_dependency`, `operation`, `measurement`, `retention`, `other`) presente no pack, avaliar se há sinal suficiente para um `finding`.
3. Classificar cada finding em exatamente uma `finding_class` (seção 7) — nunca misturar hipótese com fato no mesmo item.
4. Todo finding de classe `observed_issue`/`observation`/`risk` precisa de `evidence_ids` não vazio, resolvíveis em `context_pack.evidence_index`.
5. Todo finding de classe `hypothesis` precisa de `hypothesis_when_applicable.would_be_confirmed_by` explícito — o que precisaria ser observado para essa hipótese virar `observation`/`observed_issue`.
6. Buscar ativamente `opposing_evidence` — evidência do próprio pack que complica ou contradiz o finding — e declará-la, não escondê-la.
7. Escrever `executive_summary`: 3-6 frases, sem adjetivos de avaliação não sustentados ("ruim", "ótimo") — descrever o que foi observado, o que falta, e o risco de maior atenção.
8. Validar e escrever `diagnosis.json`.

## 7. `finding_class` — a distinção central

Ver `operation/replanning-rules.md`. Resumo:

- **OBSERVED_ISSUE** — problema diretamente evidenciado.
- **OBSERVATION** — fato neutro evidenciado, não necessariamente problema.
- **HYPOTHESIS** — explicação plausível e não comprovada; nunca apresentada como fato.
- **MISSING_DATA** — ausência de dado limita/bloqueia uma conclusão; ausência não é, por si, um problema operacional a corrigir.
- **RISK** — potencial resultado negativo, evidenciado ou estruturalmente implícito pela forma de medição/operação.

Exemplo (não copiar valores — apenas a forma): "spend MTD está abaixo do orçamento mensal total" é `observed_issue` (ou `observation`, conforme o contexto) se sustentado por `media_monitoring`; "sem evidência de vendas atuais não é possível medir progresso do SMART" é `missing_data`; "atribuição lead→venda pode limitar a leitura do SMART" é `risk`; qualquer coisa como "a campanha está com fadiga de criativo" só entra se houver evidência — caso contrário é `hypothesis`, nunca fato.

## 8. `impact` — nunca um score

`impact` é `unknown`/`low`/`medium`/`high`, sempre acompanhado de `impact_rationale` textual explicando o porquê. Nunca combinar múltiplos findings numa nota composta.

## 9. Confidence

- `high`: conclusão diretamente sustentada por evidência `confidence: high`/`medium` explícita e não contestada.
- `medium`: inferência razoável, sustentada mas não conclusiva, ou evidência única de `confidence: medium`.
- `low`: hipótese plausível com dado insuficiente.

## 10. Regras e proibições

Além do template e de `operation/replanning-rules.md`:

- nunca inventar finding sem `evidence_ids` (exceto `missing_data`, cuja natureza é a ausência);
- nunca elevar `hypothesis`/`risk` a `observed_issue`;
- nunca confundir "não sabemos X" com "X está ruim" — são `missing_data` e `observed_issue` respectivamente, e exigem evidência diferente;
- nunca reescrever `context-pack.json` ou qualquer canonical.

## 11. Idempotência

Mesmo `context-pack.json` (mesmo `content_sha256`) → mesmo conjunto de findings semanticamente. `diagnosis_id` pode ser estável por execução (ex.: derivado de `client_id` + `quarter_id` + `context_pack_ref.content_sha256`) para facilitar detecção de replay idêntico — documentado aqui, não overengenheirado com um algoritmo extra.
