"""Read-only self-test for deployed validators using fixed synthetic examples.

This does NOT validate any real well, data loader, agent generation, or expert labels.
"""
from __future__ import annotations

import json
from pathlib import Path

from .events import evaluate_events
from .activities import evaluate_activities

_EXAMPLES = Path(__file__).resolve().parents[1] / "docs"


def run_builtin_validation_selftest() -> dict:
    """Exercise BOTH production evaluation entry points; raise on any regression."""
    symptom_input = json.loads((_EXAMPLES / "validation_example_symptom.json").read_text(encoding="utf-8"))
    symptom = evaluate_events(symptom_input)
    counts = symptom.get("event_counts", {})
    metrics = symptom.get("metrics", {})
    if not (symptom.get("status") == "evaluated"
            and counts.get("TP") == 1 and counts.get("FP") == 1
            and counts.get("FN") == 0
            and abs(metrics.get("precision", -1) - 0.5) < 1e-9
            and abs(metrics.get("recall", -1) - 1.0) < 1e-9
            and abs(metrics.get("f1", -1) - 2/3) < 1e-9):
        raise AssertionError("Symptom reference result differs from expected counts/metrics")

    activity_input = json.loads((_EXAMPLES / "validation_example_activity.json").read_text(encoding="utf-8"))
    activity = evaluate_activities(activity_input)
    if not (activity.get("status") == "evaluated"
            and abs(activity.get("accuracy", -1) - 11/12) < 1e-9):
        raise AssertionError("Activity reference result differs from expected duration-weighted accuracy")

    return {
        "status": "passed",
        "scope": "SYNTHETIC EXAMPLES ONLY — not real drilling data or end-to-end validation",
        "symptom": {"agent": symptom_input["agent"],
                    "TP": counts["TP"], "FP": counts["FP"], "FN": counts["FN"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"], "f1": metrics["f1"]},
        "activity": {"time_weighted_accuracy": activity["accuracy"]},
    }
