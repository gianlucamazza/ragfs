"""Run with PYTHONPATH=benchmarks python -m ragfs_bench."""
from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path

from .facts import answer, validate_facts
from .protocol import load_protocol, read_jsonl


def validate(path: Path):
    protocol, pins = load_protocol(path)
    paths = {pin["name"]: Path(pin["resolved_path"]) for pin in pins}
    facts = read_jsonl(paths["facts"])
    lookup = validate_facts(facts)
    queries = read_jsonl(paths["queries"])
    seen = set()
    for query in queries:
        if query["id"] in seen or query.get("phase") not in (1, 2):
            raise ValueError("Invalid or duplicate query")
        seen.add(query["id"])
        if any(rid not in lookup for rid in query["gold_ids"]):
            raise ValueError("Unknown gold evidence")
        answer(facts, query, lookup)
    scenario = json.loads(paths["scenario"].read_text())
    if [step["id"] for step in scenario["steps"]] != list(range(1, 9)):
        raise ValueError("The frozen scenario requires all eight ordered steps")
    for step in scenario["steps"]:
        if step.get("operation") == "query" and step.get("query") not in seen:
            raise ValueError("Scenario refers to an unknown query")
        if any(rid not in lookup for rid in step.get("revisions", [])):
            raise ValueError("Scenario refers to an unknown revision")
    return protocol, pins, facts, queries


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--binary", type=Path)
    run.add_argument("--snapshot", type=Path)
    run.add_argument("--model-manifest", type=Path)
    run.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        protocol, pins, facts, queries = validate(args.protocol)
        if not args.dry_run:
            if not all((args.binary, args.snapshot, args.model_manifest, args.output)):
                raise ValueError("Measured runs require --binary, --snapshot, --model-manifest and a new --output directory")
            from .runner import run as run_scenario
            run_scenario(args.protocol, protocol, pins, facts, queries, binary=args.binary,
                         snapshot=args.snapshot, model_manifest=args.model_manifest, output=args.output)
            print(f"Raw evidence written to {args.output / 'results.json'}")
            return 0
        print(json.dumps({"schema_version": 1, "protocol_id": protocol["protocol_id"],
                          "validation": "passed", "n_revisions": len(facts),
                          "n_queries": len(queries), "pins": len(pins),
                          "metrics": "TBD (to be measured)"}, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Benchmark validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
