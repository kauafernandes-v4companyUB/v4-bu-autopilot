---
name: publish-ekyte
description: Map an approved, canonical task into an eKyte-shaped payload and publish it — preview always available, apply only with explicit approval and a real capability (today: manual export only).
---

# Publish eKyte

## 1. Identity

- **Class:** ACTION (EXTERNAL)
- **Version:** 1.0.0
- **Canonical Side Effects:** EXTERNAL (apply, only when a programmatic transport is actually used); NONE in preview and in `manual_export` apply (no remote write happens — a packet is prepared for a human to act on).
- **Output contract:** `skills/publish-ekyte/output.schema.json`
- **Policy:** `operation/task-rules.md`, `docs/workflows/ekyte-publication.md`
- **Reference logic:** `scripts/lib/ekyte_publish.py` (payload mapping, blocker/idempotency/approval decision tree — tested in `tests/operating_loop/test_ekyte_publish.py`) and `scripts/lib/ekyte_transport.py` (transport interface + `FakeEkyteTransport`).

## 2. Capability audit result (do not re-audit — read this)

As of this skill's authoring, no real eKyte API, connector, webhook, MCP server, or browser-automation integration is documented anywhere in this engine or in the private workspace (`docs/workflows/ekyte-publication.md` has the full audit trail). `scripts/lib/ekyte_transport.py::discover_ekyte_capability()` reflects this honestly: it returns `MANUAL_EXPORT` unless `V4_BU_EKYTE_API_URL`/`V4_BU_EKYTE_API_TOKEN` are actually set in the environment (which they are not, today). **Never claim `API`/`CONNECTOR`/`BROWSER_AUTOMATION` capability without one of those actually being true at execution time.**

## 3. Quando usar

- para preparar o payload eKyte de uma tarefa canônica já aprovada, sempre em `preview` primeiro;
- para `apply` somente com aprovação explícita e não obsoleta, e task `pending`.

## 4. Quando NÃO usar

- sem uma tarefa canônica existente em `clients/<client_id>/tasks.json`;
- sem `approval_id` válido referenciando exatamente essa tarefa (`schemas/approval.schema.json`, `scripts/lib/approval.py`);
- para criar a tarefa local — isso é `generate-tasks` + `manage-task-ledger`, não esta skill;
- para registrar o binding externo diretamente em `tasks.json` — isso é sempre `manage-task-ledger link_ekyte`, nunca escrito por esta skill.

## 5. Inputs

Obrigatórios: `client_id`, `task_id`, `mode` (`preview` padrão ou `apply`).

Para `apply`: `approval_id` (obrigatório — sem ele, `error`/`blocker NO_APPROVAL`); `transport` — instância de `scripts/lib/ekyte_transport.py::EkyteTransport` quando disponível (ex.: `FakeEkyteTransport` em testes/dry-run) ou ausente (capability `MANUAL_EXPORT`/`NONE`).

## 6. Procedimento

1. Ler a task canônica (`clients/<client_id>/tasks.json`); se `task_id` não existir ou não for `pending`, `blocker TASK_NOT_PENDING`.
2. Verificar `local_task.existing_external`: se já houver `external` com `system: ekyte` e `external_id` diferente do que esta execução produziria, `blocker EXISTING_EXTERNAL_BINDING_CONFLICT` — nunca sobrescrever silenciosamente.
3. Montar `payload`: `title`, `description`, `due_at` mapeados diretamente da task local. Qualquer campo local sem mapeamento sustentado (ex.: `evidence_ids`, `origin`) vai para `omitted_fields`, nunca é silenciosamente perdido nem inventado do lado eKyte.
4. Determinar `capability` via `discover_ekyte_capability()`. Se uma interface real algum dia exigir um campo de responsável obrigatório e não houver regra local para preenchê-lo, `blocker EKYTE_RESPONSIBLE_REQUIRED` — nunca escolher uma pessoa arbitrariamente (`operation/task-rules.md`: tasks locais nunca têm `responsible`).
5. **Preview**: monta tudo acima, `remote_result: null`, `link_ekyte_operation: null`, `receipt_ref: null`, zero ação externa. `approval_valid` é `null` se nenhum `approval_id` foi passado ainda (preview pode ser explorado sem aprovação), ou o resultado de `scripts/lib/approval.py::validate_approval` se um `approval_id` foi passado.
6. **Apply**: exige `approval_id` presente e `validate_approval` retornando fresh para o item `task_id`; caso contrário `blocker STALE_APPROVAL`/`NO_APPROVAL`, zero efeito.
   - Se `transport` foi fornecido (capability efetivamente testável, ex. `FakeEkyteTransport`): chama `transport.create_task(payload)`; sucesso ⇒ `remote_result` preenchido, `publication_mode: "programmatic"`, `status: success`, e `link_ekyte_operation` montado (forma de `link_ekyte` de `manage-task-ledger`, com `external.system=ekyte`, `external.external_id`, `external.url`, `external.published_at` = relógio real, `external.last_verified_at` = mesmo timestamp) — **esta skill não aplica essa operação**; ela é devolvida para o orquestrador encadear com `manage-task-ledger apply` como uma ACTION separada.
   - Se nenhum `transport` real está disponível (capability `MANUAL_EXPORT`/`NONE`, o caso real hoje): `publication_mode: "manual_export"`, `remote_result: null`, `link_ekyte_operation: null`, `status: success` quando o pacote de payload está completo e correto (o "sucesso" aqui é "pacote pronto para colar manualmente no eKyte", nunca "tarefa publicada"). Gerar um `warning` explícito deixando isso inequívoco.
7. Nunca afirmar sucesso de publicação real sem uma resposta/receipt do transport — `create_task` levantando exceção é `status: failed`, zero binding.
8. Gerar `receipt_ref` (via `scripts/lib/receipt.py`) somente quando `publication_mode: "programmatic"` e a chamada teve sucesso.

## 7. Regras e proibições

Além do template:

- nunca inventar endpoint, token, ou forma de request de uma API eKyte real não documentada;
- nunca chamar `manage-task-ledger apply` a partir desta skill — devolve a operação, quem encadeia é o orquestrador/operador;
- nunca publicar duas vezes a mesma tarefa sem detectar o binding existente (idempotência via `existing_external`);
- nunca aceitar `approval` stale;
- nunca escolher um responsável para satisfazer um campo obrigatório hipotético do eKyte.

## 8. Idempotência

Reexecutar `apply` com a mesma tarefa já tendo `external` vinculado é `no_change` (retorna o binding existente, não cria um novo) — nunca um segundo `external_id` para a mesma tarefa.
