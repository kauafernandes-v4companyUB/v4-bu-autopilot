# Project Orchestration

## Horizontes

- Estratégico: memória canônica e visão de longo prazo do cliente.
- Tático: Quarter, objetivo SMART, planejamento e monitoramento de mídia.
- Operacional: check-ins semanais ROPRE, próximos passos e ledger local de tarefas.

## Quarter

O Quarter é a unidade oficial de planejamento tático. Cada `YYYY-QN` possui `plan.json`, `monitoring.json` e check-ins. A virada de Quarter exige fechamento, avaliação e novo replanejamento, mesmo que o objetivo anterior tenha sido cumprido, parcialmente cumprido ou não cumprido. O SMART pertence exclusivamente ao Quarter: pode ser semelhante ao anterior, mas nunca é carregado silenciosamente. A baseline pode ser desconhecida (`null`); o target continua obrigatório e mensurável.

Convenção futura, sem criar dados nesta rodada:

```text
clients/<client_id>/
  quarters/YYYY-QN/
    plan.json
    monitoring.json
    check-ins/current.json
    check-ins/history/
  tasks.json
```

`plan.json` registra o planejado, inclusive orçamento mensal por canal em BRL decimal. `monitoring.json` registra somente o realizado/observado. O monitoring pode espelhar orçamento planejado para cálculo, mas não redefine o plano. `attainment_percent` é realizado/planejado; `variance_value` é realizado menos planejado; `pacing_percent` só existe quando o ritmo esperado do mês puder ser calculado. Não há tolerância ou risco automático implícito.

## Flags e ROPRE

Flags vivem no monitoring do Quarter, com identidade estável e ciclo `open`/`resolved`; uma mesma premissa ou risco é revalidado, não recriado semanalmente. O check-in oficial usa ROPRE: Resultados, Objetivos, Premissas, Riscos, Próximos Passos e Visão de Longo Prazo. Objetivos referenciam o SMART ativo; premissas e riscos podem referenciar flags existentes; próximos passos podem originar tarefas.

```text
Fontes → Quarter Monitoring → ROPRE → Próximos Passos → Tasks
       → Execução → Resultados → próximo ROPRE
```

## Tarefas e eKyte

`tasks.json` é um ledger longitudinal: cada tarefa preserva o `quarter_id` de origem mesmo se atravessar a virada. Toda tarefa possui `raised_at` e `due_at` obrigatórios em `YYYY-MM-DD`; `completed_at` é data ou `null`. A origem preserva `type` e `evidence_ids` que provocaram sua criação, enquanto `task.evidence_ids` reúne as evidências relacionadas ao longo da vida da tarefa. Carry-over poderá ser registrado futuramente, sem migração automática agora. `overdue` é cálculo em runtime (`status == pending` e `due_at < data atual`), não status persistido. O ledger funciona sem eKyte; quando houver integração autorizada, `ekyte_url` vincula o registro local ao sistema externo, sem substituir a referência operacional local.

```text
Quarter atual → fechamento → avaliação → replanejamento obrigatório
                → novo Quarter → novo SMART → novo plano de mídia
```
