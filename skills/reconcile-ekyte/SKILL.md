---
name: reconcile-ekyte
description: Compare the local task ledger's external bindings against eKyte and report divergences — never decides a resolution strategy, never auto-corrects.
---

# Reconcile eKyte

## 1. Identity

- **Class:** INTELLIGENCE (read-only)
- **Version:** 1.0.0
- **Canonical Side Effects:** NONE
- **Output contract:** `skills/reconcile-ekyte/output.schema.json`
- **Policy:** `operation/task-rules.md` (Task Completion Authority)

## 2. Objetivo

Responder objetivamente "o que o ledger local diz sobre tarefas publicadas no eKyte, e isso ainda bate com o que o eKyte diz (quando dá para checar)?" — sem decidir o que fazer com a diferença.

## 3. Quando usar

Periodicamente, ou antes de um `week-close`/ROPRE, para saber se alguma tarefa publicada divergiu.

## 4. Quando NÃO usar

- para corrigir a divergência — isso é decisão do operador, materializada depois por `manage-task-ledger` (nunca por esta skill);
- para publicar ou vincular nada — isso é `publish-ekyte`.

## 5. Inputs

Obrigatório: `client_id`. Opcional: `transport` (instância de `scripts/lib/ekyte_transport.py::EkyteTransport`; ausente ⇒ `capability` efetiva de leitura é a reportada por `discover_ekyte_capability()`, tipicamente `MANUAL_EXPORT`, e toda comparação de tarefa com binding vira `UNKNOWN` por falta de acesso ao estado remoto).

## 6. Procedimento

1. Ler `clients/<client_id>/tasks.json`.
2. Para cada task:
   - sem `external` (nem `ekyte_url` nem `external.*`): `LOCAL_ONLY` — nunca foi publicada, nada a comparar.
   - com `external`/`ekyte_url` mas sem `transport` disponível: `UNKNOWN`, `details` explica a ausência de capability de leitura.
   - com `external` e `transport` disponível: `transport.fetch_task(external_id)`. Se retornar `None`: `UNKNOWN` (`details`: "binding local existe mas o transport não encontrou o registro remoto — precisa de investigação, não é o mesmo que nunca ter sido publicada"). Se retornar um registro: comparar `status` e `due_at`; ambos batendo ⇒ `MATCHED`; `status` divergente ⇒ `STATUS_MISMATCH` (mesmo que `due_at` também divirja — reportar ambos em `details`); só `due_at` divergente ⇒ `DUE_DATE_MISMATCH`.
3. `REMOTE_ONLY` (uma tarefa que existe no eKyte mas não no ledger local) **não é detectável** com a interface mínima de transport atual (`create_task`/`fetch_task`/`update_task` — sem `list_tasks`). Declarar essa limitação explicitamente em `limitations`, nunca fingir cobertura completa.
4. Agregar `summary` e escrever o output. `status: partial` quando `capability` não permite verificar remotamente nenhuma task com binding (tudo `UNKNOWN`) — não é falha da skill, é limitação de capability, mas deve ser visível.

## 7. Regras e proibições

- nunca alterar `tasks.json`;
- nunca chamar `transport.update_task` (essa skill só lê);
- nunca decidir qual lado (local/remoto) está "certo" — isso é sempre uma decisão do operador;
- nunca inventar um estado remoto quando não há transport.

## 8. Idempotência

Mesmo ledger local + mesmo estado remoto (quando acessível) → mesma classificação para cada task.
