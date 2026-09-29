#!/usr/bin/env python3
"""Operator/agent CLI for skills/plan-seasonal-calendar/SKILL.md.

    python scripts/seasonal_planning.py context  --client <id> --start YYYY-MM-DD --end YYYY-MM-DD [--instruction "..."] [--out context.json]
    python scripts/seasonal_planning.py validate --client <id> --start ... --end ... --plan plan.json [--instruction ...]
    python scripts/seasonal_planning.py write    --client <id> --start ... --end ... --plan plan.json [--out-subdir NAME] [--instruction ...]

`context` lazily loads ONE client's workspace context and the real calendar
of the horizon (read-only). The plan itself is reasoned by the agent
following the SKILL.md. `validate` checks schema + no-invention invariants.
`write` validates and writes seasonal-plan.json + seasonal-plan.md (derived)
under <workspace>/context/generated/<client>/seasonal-planning/<period_id>/
— never overwriting, never outside that client's tree. No external writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from scripts.lib import seasonal_planning as sp  # noqa: E402
from scripts.lib.workspace import require_workspace  # noqa: E402


def _context(args) -> tuple[Path, dict]:
    ws = require_workspace(args.workspace)
    ctx = sp.load_client_context(ws.root, args.client, date.fromisoformat(args.start), date.fromisoformat(args.end),
                                 operator_instructions=args.instruction)
    return ws.root, ctx


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(sp.OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("context", "validate", "write"):
        p = sub.add_parser(name)
        p.add_argument("--client", required=True)
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        p.add_argument("--workspace", default=None)
        p.add_argument("--instruction", action="append", default=[], help="operator instruction (repeatable; cited as OP-01, OP-02…)")
        if name == "context":
            p.add_argument("--out", default=None)
        else:
            p.add_argument("--plan", required=True)
        if name == "write":
            p.add_argument("--out-subdir", default=None, help="write under seasonal-planning/<NAME>/ instead of <period_id> (dry runs)")
    args = ap.parse_args(argv)
    root, ctx = _context(args)
    if args.cmd == "context":
        text = json.dumps(ctx, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"context written: {args.out}")
        else:
            print(text)
        return 0
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if args.cmd == "validate":
        issues = sp.validate_plan(plan, ctx, schema_validator=_validator())
        print(json.dumps({"valid": not issues, "issues": issues, "semantic_summary": sp.semantic_counts(plan)}, ensure_ascii=False, indent=2))
        return 0 if not issues else 1
    try:
        out = sp.write_plan(root, plan, ctx, out_subdir=args.out_subdir, schema_validator=_validator())
    except sp.SeasonalPlanningError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps({k: str(v) for k, v in out.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
