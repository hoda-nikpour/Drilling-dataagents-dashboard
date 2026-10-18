import unittest

from drillmate_validation import ValidationError
from drillmate_validation.activities import evaluate_activities
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

def dt(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()

def window(start, end):
    return {"start": dt(start), "end": dt(end)}


def act(ident, name, start, end):
    return {"id": ident, "activity": name, "start": dt(start), "end": dt(end)}


def dataset():
    return {"schema_version": 1, "agent_kind": "activity", "well": "A", "section": "8.5",
            "predictions_complete": True, "prediction_generation": "continuous",
            "reviewed_intervals": [window(0, 100)], "prediction_coverage": [window(0, 100)],
            "activity_labels": ["Drilling", "Reaming", "Other"],
            "expert_activities": [act("e1", "Drilling", 0, 60), act("e2", "Reaming", 60, 100)],
            "predicted_activities": [act("p1", "Drilling", 0, 50), act("p2", "Reaming", 50, 100)]}


class ActivityTests(unittest.TestCase):
    def test_weighted_confusion(self):
        r = evaluate_activities(dataset())
        self.assertAlmostEqual(r["accuracy"], 0.9)
        self.assertAlmostEqual(r["confusion_seconds"]["Drilling"]["Reaming"], 10)
        self.assertAlmostEqual(r["per_activity"]["Drilling"]["recall"], 50/60)

    def test_expert_gap_is_not_negative_by_default(self):
        p = dataset()
        p["expert_activities"].pop()
        with self.assertRaisesRegex(ValidationError, "completely cover"):
            evaluate_activities(p)

    def test_prediction_gap_fails(self):
        p = dataset()
        p["predicted_activities"][0]["end"] = dt(40)
        with self.assertRaisesRegex(ValidationError, "completely cover"):
            evaluate_activities(p)

    def test_overlapping_expert_labels_fails(self):
        p = dataset()
        p["expert_activities"][0]["end"] = dt(70)
        with self.assertRaisesRegex(ValidationError, "overlapping"):
            evaluate_activities(p)

    def test_partial_prediction_coverage_fails(self):
        p = dataset()
        p["prediction_coverage"] = [window(0, 50)]
        with self.assertRaisesRegex(ValidationError, "coverage incomplete"):
            evaluate_activities(p)

    def test_unsupported_activity_label_fails(self):
        p = dataset()
        p["expert_activities"][0]["activity"] = "Unknown"
        with self.assertRaisesRegex(ValidationError, "activity_labels"):
            evaluate_activities(p)

    def test_boundary_touch_allowed(self):
        self.assertEqual(evaluate_activities(dataset())["status"], "evaluated")

    def test_same_label_different_intervals_allowed(self):
        p = dataset()
        p["expert_activities"] = [act("a", "Drilling", 0, 20),
                                  act("b", "Drilling", 20, 60), act("c", "Reaming", 60, 100)]
        self.assertAlmostEqual(evaluate_activities(p)["accuracy"], 0.9)


if __name__ == "__main__":
    unittest.main()
