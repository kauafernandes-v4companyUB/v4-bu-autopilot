# New client — operator onboarding

Everything below runs against the private workspace
(`export V4_BU_WORKSPACE_ROOT=/path/to/v4-bu-workspace-private`, or pass
`--workspace`). Nothing here changes the engine. Storage rules:
`operation/storage-contract.md`. Every canonical change is
**preview → your approval → apply → receipt** (`operation/action-contract.md`).

## 1. Create the client

```bash
python scripts/bootstrap_client.py <client-id> --display-name "Client Name"
# optional: --initial-context notes.md  (stored as RAW, not as memory)
python scripts/doctor.py            # a fresh client with no Quarter is valid
```

`<client-id>` is lowercase letters, digits and `-`. Re-running is `NO_CHANGE`;
a client that already diverged is `CONFLICT` and is never overwritten. No
Quarter, SMART, budget, task, decision or evidence is created.

## 2. Put raw sources in place

```
private/clients/<client-id>/
  client-context/   handoffs, context notes
  account-gt/       Account x GT transcripts
  whatsapp/         WhatsApp exports
  bi/               BI exports (.pdf / .csv)
  google-sheets/    *.gsheet.json pointers
  manual/           operator-authorized inputs
```

Raw files never go under `clients/` (doctor fails on "Raw isolation") and
never become memory just by existing. No source type is mandatory.

## 3. Run source intake

Say: **"processe as novas fontes da <cliente>"**. The agent runs
`source-intake` and shows `NEW_SOURCE / NO_CHANGE / NEW_REVISION / MISSING`;
on your approval `manage-source-manifest` records the manifest
(`scripts/lib/source_manifest.py`). Then the matching SOURCE skill reads each
new revision (`read-client-context`, `read-account-gt`, `read-whatsapp`,
`read-bi`) and the manifest is marked processed.

## 4. Promote memory

Say: **"atualize o contexto da <cliente>"**. `promote-client-memory` previews
what goes to `evidence.json`, `knowledge.json`, `current-state.json`,
`decisions.json` (and `history/`), each item tied to evidence. Approve the
exact preview; any later change to those files makes it stale.

## 5. Create the first Quarter

Decide SMART and media plan with the client, then say:
**"crie o quarter <YYYY-QN> da <cliente>"** with that plan. `manage-quarter`
validates period, SMART deadline and media months and, on approval, writes an
`active` plan. A seasonal draft is never converted automatically.

## 6. Start operating

| Say | What happens |
|---|---|
| "replaneje <cliente>" | Intelligence chain → task proposals (preview only) |
| "aplique as tarefas aprovadas da <cliente>" | approved READY proposals → `manage-task-ledger` |
| "me prepara pra tocar a <cliente> hoje" | operator brief (overdue tasks/operations, decisions, external review) |
| "faça o midweek da <cliente>" / "feche a semana da <cliente>" | weekly snapshots |
| "prepare o ropre da <cliente>" → "complete o ropre da <cliente>" | ROPRE draft → ready → completed |
| "feche o quarter <YYYY-QN> da <cliente>" | needs ended period + completed ROPRE; lists carry-over |

`context/generated/<client-id>/` can be deleted at any time: everything the
operator needs is rebuilt from `clients/<client-id>/`.
