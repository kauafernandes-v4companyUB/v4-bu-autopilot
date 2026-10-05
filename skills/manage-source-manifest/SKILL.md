---
name: manage-source-manifest
description: Persist the source-intake discovery of one client's private raw files into clients/<client_id>/source-manifest.json, hash-locked to an operator approval.
---

# Manage Source Manifest

- **Classe:** ACTION
- **Versão:** 1.0.0
- **Canonical Side Effects:** `MEMORY` — somente `clients/<client_id>/source-manifest.json` e `clients/<client_id>/receipts/`
- **Contrato de output:** `skills/manage-source-manifest/output.schema.json`
- **Implementação de referência:** `scripts/lib/source_manifest.py`

## Objetivo

Registrar identidade e processamento das fontes brutas em `private/clients/<client_id>/` (`operation/storage-contract.md`). O manifest guarda `source_id` (estável por caminho), `source_type`, `revision`, `fingerprint` (sha256), `discovered_at`/`observed_at`, `processed_at`, `processor`, `processor_version` e `output_ref`. Nunca copia conteúdo bruto; uma fonte nunca vira memória canônica por existir — isso exige uma SOURCE skill e depois `promote-client-memory`.

## Descoberta (source-intake, somente leitura)

- caminho nunca visto → `NEW_SOURCE` (revisão 1);
- mesmo caminho e mesmo hash → `NO_CHANGE`;
- mesmo caminho e hash novo → `NEW_REVISION` (mesmo `source_id`, revisão n+1);
- caminho no manifest sem arquivo → `MISSING`: só reportado; nada é apagado, nenhuma evidência é tocada.

Tipos: `client_context`, `account_gt_transcript`, `whatsapp_export`, `bi_pdf`, `bi_csv`, `google_sheet`, `manual_authorized_input`, `unknown` — classificação conservadora por pasta, depois nome/extensão. Nenhuma fonte é obrigatória.

## Operações

- `record_revision` — registra uma revisão descoberta (`status: new` ou `new_revision`).
- `mark_processed` — após uma SOURCE skill: `source_id` + `revision`, `processor`, `processor_version`, `output_ref`; `processed_at` vem do relógio real do apply.

## Preview, aprovação e apply

Contrato V1 (`operation/action-contract.md`): preview com `base_state_hash` (sobre `source-manifest.json`) e `preview_hash`; aprovação `source_manifest_change` vinculada ao preview; apply recalcula tudo (`STALE_APPROVAL` → zero escrita), valida contra `schemas/source-manifest.schema.json` e grava manifest + receipt numa única escrita atômica. Replay idêntico é `no_change`.

## Proibições

Nunca ler conteúdo semântico das fontes, apagar entradas, alterar evidências, promover memória ou acessar fontes de outro cliente.
