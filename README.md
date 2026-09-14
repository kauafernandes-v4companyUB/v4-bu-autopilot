# V4 BU Autopilot

Cérebro operacional versionado para suporte ao replanejamento dos clientes da BU.

## Objetivo

Usar Claude Code como agente operacional capaz de carregar, sob demanda, o contexto de um cliente e executar skills especializadas para:

- leitura da BU;
- leitura do contexto do cliente;
- leitura de check-ins;
- leitura da call Account × Gestor de Tráfego;
- leitura de WhatsApp;
- leitura de BI;
- leitura de tarefas;
- diagnóstico;
- replanejamento;
- geração de tarefas;
- auditoria;
- publicação operacional.

## Arquitetura

- `CLAUDE.md` — constituição global do agente.
- `skills/` — capacidades especializadas.
- `operation/` — regras da operação da BU.
- `schemas/` — contratos estruturados entre skills.
- `clients/` — memória consolidada por cliente.
- `context/` — contexto temporário gerado sob demanda.
- `outputs/` — entregáveis produzidos.
- `private/` — fontes privadas locais, nunca versionadas.

## Cliente piloto

Walmaq.
