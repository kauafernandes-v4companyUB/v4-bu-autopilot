#!/usr/bin/env python3
"""Operator/agent CLI for skills/document-winning-creative/SKILL.md.

    python scripts/creative_performance.py context  --brief brief.json [--out context.json]
    python scripts/creative_performance.py validate --brief brief.json --report report.json
    python scripts/creative_performance.py write    --brief brief.json --report report.json [--out-subdir NAME]

`context` reads the operator's brief and ONLY the files it names (read-only):
asset metadata, normalized + derived metrics, client-isolation status of each
file. The analysis itself is written by the agent following the SKILL.md.
`validate` checks schema + invariants (no altered metrics, no ungrounded
observations, no causal/comparative claims without comparative evidence).
`write` validates and writes creative-performance.json + .md (derived) under
<workspace>/context/generated/<client>/creative-performance/<creative_id>/ —
never overwriting, never outside that client's tree. No external writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from scripts.lib import creative_performance as cp  # noqa: E402
from scripts.lib.workspace import require_workspace  # noqa: E402


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("context", "validate", "write"):
        p = sub.add_parser(name)
        p.add_argument("--brief", required=True)
        p.add_argument("--workspace", default=None)
        if name == "context":
            p.add_argument("--out", default=None)
        else:
            p.add_argument("--report", required=True)
        if name == "write":
            p.add_argument("--out-subdir", default=None, help="write under creative-performance/<NAME>/ instead of <creative_id> (dry runs)")
    args = ap.parse_args(argv)
    ws = require_workspace(args.workspace)
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    try:
        ctx = cp.load_context(ws.root, brief, input_validator=_validator(cp.INPUT_SCHEMA_PATH))
    except cp.CreativePerformanceError as e:
        print(str(e), file=sys.stderr)
        return 1
    if args.cmd == "context":
        text = json.dumps(ctx, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"context written: {args.out}")
        else:
            print(text)
        return 0
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if args.cmd == "validate":
        issues = cp.validate_report(report, ctx, schema_validator=_validator(cp.OUTPUT_SCHEMA_PATH))
        print(json.dumps({"valid": not issues, "issues": issues, "learning_summary": cp.learning_counts(report)}, ensure_ascii=False, indent=2))
        return 0 if not issues else 1
    try:
        out = cp.write_report(ws.root, report, ctx, out_subdir=args.out_subdir, schema_validator=_validator(cp.OUTPUT_SCHEMA_PATH))
    except cp.CreativePerformanceError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps({k: str(v) for k, v in out.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
