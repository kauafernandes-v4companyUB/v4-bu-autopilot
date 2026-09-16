"""Deterministic task identity (mission: avoid a task like 'Criar
criativos Semana do Cliente' being duplicated every time replan-client
runs again).

Identity = client_id + quarter_id + origin action_id (the replan-client
action_proposal.action_id a task_proposal was derived from) — never a
timestamp. Same action, same Quarter, same client -> same task_id,
always. This is what lets manage-task-ledger's own duplicate_task_id
protection do the deduplication work across repeated replanning runs,
instead of inventing a second dedup mechanism.
"""

from __future__ import annotations

import hashlib
import json

PREFIX = "t-"
HEX_LENGTH = 16


def compute_task_id(client_id: str, quarter_id: str, action_id: str) -> str:
    if not client_id or not quarter_id or not action_id:
        raise ValueError("client_id, quarter_id and action_id are all required to compute a stable task_id")
    identity = {"client_id": client_id, "quarter_id": quarter_id, "action_id": action_id}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return PREFIX + digest[:HEX_LENGTH]
