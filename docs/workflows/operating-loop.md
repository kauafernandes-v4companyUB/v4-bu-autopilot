# The operating loop

```
REPLANEJAMENTO (Intelligence, docs/workflows/replan-client.md)
        ↓
AUDIT (audit-plan — pode bloquear a cadeia)
        ↓
APPROVAL (schemas/approval.schema.json — nunca automática)
        ↓
LOCAL ACTION (manage-task-ledger, via scripts/lib/task_bridge.py)
        ↓
EXTERNAL ACTION (publish-ekyte — sempre gated por approval não-stale)
        ↓
RECONCILIATION (reconcile-ekyte — read-only, nunca corrige sozinho)
```

`INTELLIGENCE -> EXTERNAL` diretamente **nunca** acontece — todo passo
que muta estado canônico ou toca um sistema externo passa por
`AUDIT -> APPROVAL` primeiro. Ver `examples/demo-client/acme-demo/operating-loop/`
para a cadeia completa, sintética, gerada pelos módulos reais listados
abaixo (nunca hand-waved).

## Peças reais (não um framework de agents — apenas tooling determinístico)

- `schemas/approval.schema.json` + `scripts/lib/approval.py` — o
  contrato entre "Claude propôs" e "o operador autorizou". Ver
  `docs/workflows/task-approval.md`.
- `scripts/lib/task_identity.py` — `task_id` determinístico
  (`client_id` + `quarter_id` + `action_id`), nunca timestamp — é isso
  que impede replanejar de novo duplicar a mesma tarefa.
- `scripts/lib/task_bridge.py` — só converte propostas `readiness: ready`
  e aprovadas em operações `create_task` de `manage-task-ledger`; ao receber
  o ledger vigente, trata um replay com conteúdo canônico idêntico como
  `no_change` e bloqueia conteúdo divergente sob o mesmo `task_id`; nunca
  escreve `tasks.json` diretamente.
- `schemas/action-receipt.schema.json` + `scripts/lib/receipt.py` —
  todo ACTION real que executa gera um receipt auditável; o receipt
  nunca substitui o estado canônico.
- `scripts/lib/ekyte_transport.py` + `scripts/lib/ekyte_publish.py` —
  ver `docs/workflows/ekyte-publication.md`.
- `scripts/lib/reconciliation.py` — comparação local vs. remoto,
  puramente mecânica, nunca decide o que fazer com uma divergência
  (`operation/task-rules.md`, seção "Task Completion Authority").
- `scripts/lib/task_ledger_views.py` — janela de semana e `overdue`
  derivados em runtime, nunca persistidos.
- `schemas/operator-inbox.schema.json` — fila única e organizada
  (aprovações, agendamentos, decisões, ações externas) em vez de
  perguntas espalhadas durante a execução.
- `schemas/workflow-report.schema.json` — trilha de auditoria de uma
  execução de workflow (`workflows/registry.json`).

## `workflows/registry.json`

Autoridade sobre quais workflows de linguagem natural existem de fato
(`implemented`/`partial`/`planned`) e qual cadeia real de skills cada
um encadeia — consultado antes de qualquer "faça X da Y", nunca
assumido pela prosa deste documento. Ver `schemas/workflow-registry.schema.json`.

## Comandos naturais suportados

Ver CLAUDE.md seção sobre roteamento de comando e `AGENTS.md`. Nenhum
parser NLP é criado — Claude/Codex interpreta a frase e consulta
`workflows/registry.json` para resolver a cadeia e os gates de
aprovação corretos.
