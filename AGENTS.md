# V4 BU Autopilot — Codex Operating Map

Este repositório é um cérebro operacional versionado, não uma aplicação tradicional.

## Economia de contexto

- Use lazy loading.
- Leia somente arquivos necessários para a tarefa atual.
- Não faça varredura do repositório inteiro sem necessidade.
- Prefira `rg`, `sed` e leitura direcionada.
- Não resuma arquivos lidos ao usuário.
- Não repita conteúdo já existente no repositório.
- Finalize com relatório curto: arquivos alterados, validações, riscos e git status.

## Fonte de verdade

- `CLAUDE.md`: constituição operacional completa. Leia somente quando a tarefa envolver regras globais, arquitetura, memória, evidência, temporalidade ou quando houver ambiguidade.
- `skills/_template/`: contrato-base para novas skills.
- `schemas/`: contratos JSON compartilhados.
- `skills/<skill>/`: comportamento específico.
- `clients/<client_id>/`: memória canônica.
- `context/generated/`: workspace temporário; não é memória permanente.
- `private/`: fontes privadas; nunca versionar.

## Regras obrigatórias

- Nunca inventar informação ausente.
- Preservar FACT / METRIC / DECISION / HYPOTHESIS / REQUEST / COMMITMENT / PENDING / RISK / IDEA / DEPENDENCY.
- Nunca elevar semanticamente uma evidência.
- Timestamps de execução devem vir do relógio real do sistema.
- `source_date` só existe quando sustentada pela fonte.
- Respeitar isolamento por cliente.
- Não transformar observação em diagnóstico.
- Não transformar planejamento em execução.
- Não transformar pending em tarefa.
- Não transformar relato indireto em fala direta.

## Side effects

SOURCE skills:
- leitura apenas;
- não alterar memória.

MEMORY actions:
- preview antes de apply quando aplicável.

EXTERNAL actions:
- exigem autorização explícita.

## Git

Por padrão:
- não fazer commit;
- não fazer push;
- executar `git diff --check` após alterações.

Commit/push somente quando o usuário pedir explicitamente.

## Execução econômica

Antes de começar:
1. identificar a tarefa;
2. listar mentalmente os poucos arquivos necessários;
3. ler apenas esses arquivos;
4. executar;
5. validar apenas o necessário;
6. parar.

Não explorar assuntos adjacentes.
