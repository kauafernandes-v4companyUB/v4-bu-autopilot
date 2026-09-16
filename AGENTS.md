# V4 BU Autopilot — Codex Operating Map

Este repositório é um cérebro operacional versionado, não uma aplicação tradicional.

## Economia de contexto

- Use lazy loading.
- Leia somente arquivos necessários para a tarefa atual.
- Não faça varredura do repositório inteiro sem necessidade.
- Prefira `rg` quando disponível; se não estiver instalado, usar `grep`/`find`/`sed` — nunca falhar uma tarefa só porque `ripgrep` está ausente.
- Não resuma arquivos lidos ao usuário.
- Não repita conteúdo já existente no repositório.
- Rodar `python scripts/doctor.py` primeiro quando a integridade do projeto (schemas, registry, workspace, evidence/Quarter/tasks) estiver em dúvida — mais barato que reler o repositório inteiro.
- Rodar testes focados (`pytest tests/<area> -q`), não a suite inteira, quando a tarefa é local a uma área.
- Finalize com relatório curto: arquivos alterados, validações, riscos e git status.

## Fonte de verdade

- `CLAUDE.md`: constituição operacional completa. Leia somente quando a tarefa envolver regras globais, arquitetura, memória, evidência, temporalidade ou quando houver ambiguidade.
- `skills/_template/`: contrato-base para novas skills.
- `schemas/`: contratos JSON compartilhados.
- `schemas/quarter-*.schema.json`, `schemas/check-in-ropre.schema.json` e `schemas/task-ledger.schema.json`: contratos táticos e operacionais; a convenção está em `docs/project-orchestration.md`.
- `skills/<skill>/`: comportamento específico.
- `skills/registry.json`: autoridade sobre quais skills existem de fato (`implemented` vs `planned`) — nunca assumir que uma skill existe só porque é mencionada em prosa.
- `docs/security-model.md`: fronteira engine público / workspace privado.
- `clients/<client_id>/`: memória canônica — vive no **workspace privado** (`$V4_BU_WORKSPACE_ROOT`, resolvido por `scripts/lib/workspace.py`), nunca dentro deste repositório. Em `examples/demo-client/acme-demo/` há um exemplo 100% fictício com a mesma forma.
- `context/generated/`: workspace temporário; não é memória permanente. Também vive no workspace privado para dados reais.
- `private/`: fontes privadas; nunca versionar. Também no workspace privado.

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
- Nunca escrever dado real de cliente dentro deste repositório (engine público) — sempre no workspace privado via `scripts/lib/workspace.py`. Ver `docs/security-model.md`.

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
