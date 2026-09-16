# `acme-demo` — cliente 100% fictício

Este diretório demonstra a forma final de uma memória canônica de cliente
(`clients/<client_id>/` no workspace privado), populada com um ciclo
completo e coerente:

```
client
→ sources
→ evidence
→ knowledge
→ current-state
→ decisions
→ strategy
→ quarter (plan + monitoring)
→ tasks
→ ROPRE check-in
```

**Todo o conteúdo é sintético.** "Acme Demo Ltda", "Ana Fictícia", os
valores de mídia, as evidências, as tarefas e o check-in ROPRE não
correspondem a nenhuma empresa, pessoa ou campanha real. Nenhum dado aqui
veio de uma execução real de skill — os timestamps foram escritos à mão
para contar uma história coerente, e são marcados como `synthetic_demo`
onde o contrato normalmente exigiria o relógio real do sistema (CLAUDE.md
seção 26 — essa regra vale para execuções reais de skills, não para esta
fixture estática versionada).

## Como foi gerado

O esqueleto (`client.json`, `current-state.json`, `decisions.json`,
`evidence.json`, `knowledge.json`, `sources.json`, `strategy.md`,
`tasks.json`, `history/`, `quarters/`) veio de
`python scripts/bootstrap_client.py acme-demo --workspace <tmp>` a partir
de `templates/client/`, depois enriquecido manualmente com a narrativa
sintética abaixo.

## Narrativa sintética

- Acme Demo Ltda é um e-commerce fictício de utilidades domésticas.
- Quarter `2026-Q1`, SMART: gerar 8 vendas atribuídas às ações digitais
  até 2026-03-31.
- Mídia planejada de janeiro/2026: Meta Ads R$ 1.000,00, Google Ads R$ 0,00.
- Um BI fictício reporta R$ 400,00 investidos em Meta Ads (01/01–15/01,
  month-to-date) — promovido a evidência canônica e refletido em
  `quarters/2026-Q1/monitoring.json` (`attainment_percent = 40.0`,
  `variance_value = -600.0`).
- Uma tarefa pendente, uma concluída e uma cancelada em `tasks.json`.
- Um check-in ROPRE em `draft`, com `scheduled_for` sintético — ilustra a
  forma do contrato, não uma reunião real agendada.

## Uso

Use este cliente para testar `scripts/doctor.py`, a suite de testes
(`tests/`) e para entender a forma dos contratos antes de rodar as skills
contra dados reais em `$V4_BU_WORKSPACE_ROOT`.
