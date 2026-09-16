---
name: calculate-gap
description: Measure the difference between observed state and objective/plan only when mathematically possible — never inventing a current value to force a number.
---

# Calculate Gap

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/calculate-gap/output.schema.json`
- **Policy:** `operation/replanning-rules.md` section "Gap invariant" — read it before writing a single gap.

## 2. Objetivo

Quantificar, quando matematicamente possível, a diferença entre o estado observado (Context Pack) e o objetivo/plano vigente — e declarar explicitamente quando não é possível, em vez de inventar um valor atual.

## 3. Quando usar

Depois de `diagnose-client`, antes de `identify-priorities`.

## 4. Quando NÃO usar

- sem Context Pack e diagnóstico validados;
- para julgar se um gap numérico é "bom" ou "ruim" (isso é `diagnose-client`, e só com modelo de pacing explícito — que este MVP não possui);
- para redefinir target/planned_budget — este skill lê `plan.json`, nunca o altera.

## 5. Inputs

Obrigatórios: `context_pack`, `diagnosis` (ambos validados; `context_pack_ref`/`diagnosis_ref` computados via `scripts/lib/artifact_hash.py`).

## 6. Tipos de gap

`objective_gap` (SMART: target vs. resultado observado), `media_gap` (planned vs. actual spend/mídia), `execution_gap` (algo planejado/comprometido vs. executado), `measurement_gap` (o que precisaria ser medido mas não está sendo), `data_gap` (dado necessário simplesmente ausente), `dependency_gap` (bloqueado por algo externo ao cliente/operação).

## 7. A regra crítica — `calculable`

`calculable: false` ⇒ `current: null` e `delta: null`, sempre. Nunca `current = 0` quando o valor atual é simplesmente desconhecido — `0` é uma afirmação factual ("zero vendas"), não o mesmo que "não sabemos".

Exemplo (forma, não valor fixo): target de vendas = N, sem evidência de vendas atual ⇒ `gap.calculable = false`, `current = null`, `delta = null`, `interpretation`: "não é possível quantificar o gap de vendas sem evidência atual de vendas."

Para mídia (planned vs. actual), quando ambos são conhecidos, calcular normalmente: `delta = current - target` (ou a direção que fizer sentido semântico para o tipo — documentar no próprio `interpretation`). `interpretation` é **só o fato aritmético** — nunca "isso é underpacing" ou qualquer julgamento de qualidade sem modelo de pacing explícito e citado.

## 8. Procedimento

1. Ler `context-pack.json` + `diagnosis.json`.
2. Para cada gap candidato (SMART, cada `media_monitoring` planejado, cada compromisso/execução relevante), verificar se `target` e `current` são ambos conhecidos e com unidade compatível.
3. Se sim: `calculable: true`, calcular `delta`, escrever `interpretation` factual.
4. Se não: `calculable: false`, `current: null`, `delta: null`, `interpretation` explicando o que falta.
5. Anexar `evidence_ids` (resolvíveis em `context_pack.evidence_index`) e `limitations`.
6. Validar e escrever `gaps.json`.

## 9. Regras e proibições

- nunca inventar `current` nem `target`;
- nunca aplicar um modelo de pacing/threshold que não existe no contrato atual;
- nunca redefinir `plan.json`;
- todo `gap` calculável precisa de `evidence_ids` para `target` e `current`.

## 10. Idempotência

Mesmos `context-pack.json`/`diagnosis.json` (mesmos hashes) → mesmo conjunto de gaps, mesmos valores.
