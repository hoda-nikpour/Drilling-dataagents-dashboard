#!/usr/bin/env python3
"""Run a separate validation report on a normalized input JSON file."""
import argparse
import json
import sys
from pathlib import Path

# Supports direct invocation from the project root or absolute script path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drillmate_validation import ValidationError, evaluate_events, evaluate_activities


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Normalized validation input (not raw dashboard session JSON)")
    parser.add_argument("--output", type=Path, help="Optional independent report path")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        report = evaluate_activities(payload) if isinstance(payload, dict) and payload.get("agent_kind") == "activity" else evaluate_events(payload)
        formatted = json.dumps(report, indent=2, sort_keys=True)
        if args.output:
            if args.output.resolve() == args.input.resolve():
                raise ValidationError("Output path cannot overwrite input")
            if args.output.exists():
                raise ValidationError("Output path already exists; preserve previous reports")
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(formatted + "\n")
        else:
            print(formatted)
        return 0 if report["status"] == "evaluated" else 3
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        print(f"NOT EVALUABLE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
