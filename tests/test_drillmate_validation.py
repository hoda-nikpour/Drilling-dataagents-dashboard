import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drillmate_validation import ValidationError, evaluate_events

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dt(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def event(ident, start, end, *, agent="TRQSpike"):
    return {"id": ident, "agent": agent, "start": dt(start), "end": dt(end)}


def window(start, end):
    return {"start": dt(start), "end": dt(end)}


def payload(expert=None, pred=None, reviewed=None, coverage=None, threshold=0.25):
    r = reviewed if reviewed is not None else [window(0, 100)]
    return {"schema_version": 1, "well": "Well A", "section": "12.25",
            "agent": "TRQSpike", "agent_kind": "symptom",
            "reviewed_intervals": r,
            "prediction_coverage": coverage if coverage is not None else copy.deepcopy(r),
            "predictions_complete": True, "prediction_generation": "continuous",
            "expert_tags": expert if expert is not None else [],
            "predictions": pred if pred is not None else [],
            "matching": {"version": "event-v1.0", "method": "iou_one_to_one",
                         "min_iou": threshold, "min_overlap_seconds": 0}}


class ValidationTests(unittest.TestCase):
    def test_matching_events(self):
        out = evaluate_events(payload([event("e", 10, 20)], [event("p", 10, 20)]))
        self.assertEqual(out["event_counts"], {"TP": 1, "FP": 0, "FN": 0, "FP_lower_bound": None})
        self.assertEqual(out["metrics"]["f1"], 1)

    def test_tiny_overlap_not_hit(self):
        out = evaluate_events(payload([event("e", 10, 30)], [event("p", 29, 49)]))
        self.assertEqual((out["event_counts"]["TP"], out["event_counts"]["FN"]), (0, 1))
        self.assertEqual(out["event_counts"]["FP"], 1)
        self.assertGreater(out["metrics"]["expert_time_covered_fraction"], 0)

    def test_false_positive_without_expert_events(self):
        out = evaluate_events(payload(pred=[event("p", 10, 20)]))
        self.assertEqual(out["event_counts"]["FP"], 1)
        self.assertIsNone(out["metrics"]["recall"])
        self.assertEqual(out["metrics"]["precision"], 0)

    def test_false_negative_no_prediction(self):
        out = evaluate_events(payload(expert=[event("e", 10, 20)]))
        self.assertEqual(out["event_counts"]["FN"], 1)
        self.assertEqual(out["metrics"]["recall"], 0)
        self.assertIsNone(out["metrics"]["precision"])

    def test_outside_review_never_false_positive(self):
        out = evaluate_events(payload(pred=[event("outside", 120, 130)]))
        self.assertEqual(out["event_counts"]["FP"], 0)
        self.assertEqual(out["excluded_unreviewed_prediction_ids"], ["outside"])

    def test_review_coverage_missing_fails_closed(self):
        p = payload(coverage=[window(0, 50)])
        with self.assertRaisesRegex(ValidationError, "coverage"):
            evaluate_events(p)

    def test_no_reviewed_intervals_fails(self):
        with self.assertRaisesRegex(ValidationError, "reviewed_intervals"):
            evaluate_events(payload(reviewed=[]))

    def test_predictions_must_be_marked_complete(self):
        p = payload()
        del p["predictions_complete"]
        with self.assertRaisesRegex(ValidationError, "predictions_complete"):
            evaluate_events(p)

    def test_unverified_windows_not_allowed(self):
        p = payload()
        p["prediction_generation"] = "unverified_windows"
        with self.assertRaisesRegex(ValidationError, "generation"):
            evaluate_events(p)

    def test_expert_must_be_contained_in_review(self):
        with self.assertRaisesRegex(ValidationError, "Expert event"):
            evaluate_events(payload(expert=[event("e", 90, 110)]))

    def test_no_double_credit_one_prediction_two_experts(self):
        out = evaluate_events(payload([event("e1", 10, 20), event("e2", 20, 30)],
                                      [event("p", 10, 30)], threshold=0.3))
        self.assertEqual((out["event_counts"]["TP"], out["event_counts"]["FN"]), (1, 1))
        self.assertEqual(out["metrics"]["expert_time_covered_fraction"], 1)

    def test_two_predictions_one_expert(self):
        out = evaluate_events(payload([event("e", 10, 20)],
                                      [event("p1", 10, 20), event("p2", 11, 19)]))
        self.assertEqual((out["event_counts"]["TP"], out["event_counts"]["FP"]), (1, 1))

    def test_maximum_cardinality_not_just_greedy(self):
        # e1 can match both; e2 can match only p1. Correct cardinality is 2.
        out = evaluate_events(payload([event("e1", 10, 30), event("e2", 10, 20)],
                                      [event("p1", 10, 20), event("p2", 20, 30)], threshold=0.25))
        self.assertEqual(out["event_counts"]["TP"], 2)

    def test_touching_boundaries_are_not_overlap(self):
        out = evaluate_events(payload([event("e", 10, 20)], [event("p", 20, 30)], threshold=0))
        self.assertEqual(out["event_counts"]["TP"], 0)

    def test_zero_duration_pred_requires_cadence(self):
        p = payload([event("e", 10, 12)], [event("p", 11, 11)])
        with self.assertRaisesRegex(ValidationError, "sample_cadence"):
            evaluate_events(p)
        p["sample_cadence_seconds"] = 1
        self.assertEqual(evaluate_events(p)["event_counts"]["TP"], 1)

    def test_zero_duration_expert_disallowed(self):
        with self.assertRaisesRegex(ValidationError, "Zero-duration expert"):
            evaluate_events(payload(expert=[event("e", 10, 10)]))

    def test_naive_timestamp_disallowed(self):
        p = payload()
        p["reviewed_intervals"][0]["start"] = "2026-01-01T00:00:00"
        with self.assertRaisesRegex(ValidationError, "Timezone offset"):
            evaluate_events(p)

    def test_timezone_offsets_work(self):
        p = payload([event("e", 10, 20)], [event("p", 10, 20)])
        p["expert_tags"][0]["start"] = "2026-01-01T01:00:10+01:00"
        self.assertEqual(evaluate_events(p)["event_counts"]["TP"], 1)

    def test_duplicate_event_id_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Duplicate event id"):
            evaluate_events(payload(pred=[event("p", 10, 20), event("p", 10, 20)]))

    def test_duplicate_times_different_id_not_silently_deduped(self):
        out = evaluate_events(payload(pred=[event("p1", 10, 20), event("p2", 10, 20)]))
        self.assertEqual(out["event_counts"]["FP"], 2)

    def test_wrong_agent_rejected(self):
        with self.assertRaisesRegex(ValidationError, "must have agent"):
            evaluate_events(payload(expert=[event("e", 10, 20, agent="PSpike")]))

    def test_boundary_partial_prediction_not_fp(self):
        out = evaluate_events(payload(pred=[event("p", 95, 110)]))
        self.assertEqual(out["status"], "partial_boundary_predictions_review_required")
        self.assertIsNone(out["event_counts"]["FP"])
        self.assertEqual(out["event_counts"]["FP_lower_bound"], 0)
        self.assertIsNone(out["metrics"]["precision"])
        self.assertEqual(out["partial_boundary_prediction_ids"], ["p"])

    def test_boundary_partial_prediction_can_match(self):
        # Match requires enough overlap relative to entire event, not only the visible 5 seconds.
        out = evaluate_events(payload([event("e", 90, 100)], [event("p", 95, 110)], threshold=0.2))
        self.assertEqual(out["event_counts"]["TP"], 1)
        self.assertEqual(out["status"], "evaluated")

    def test_prediction_across_adjacent_windows_not_double_counted(self):
        p = payload([event("e", 45, 55)], [event("p", 45, 55)],
                    reviewed=[window(0, 50), window(50, 100)],
                    coverage=[window(0, 50), window(50, 100)])
        self.assertEqual(evaluate_events(p)["event_counts"]["TP"], 1)

    def test_disjoint_review_windows_and_unreviewed_gap(self):
        p = payload([event("e", 10, 20)], [event("p", 10, 20), event("outside", 40, 60)],
                    reviewed=[window(0, 30), window(70, 100)],
                    coverage=[window(0, 30), window(70, 100)])
        self.assertEqual(evaluate_events(p)["excluded_unreviewed_prediction_ids"], ["outside"])

    def test_no_events_metrics_are_undefined(self):
        out = evaluate_events(payload())
        self.assertEqual(out["event_counts"]["TP"], 0)
        self.assertIsNone(out["metrics"]["precision"])
        self.assertIsNone(out["metrics"]["recall"])
        self.assertIsNone(out["metrics"]["f1"])

    def test_inputs_not_mutated(self):
        p = payload([event("e", 10, 20)], [event("p", 10, 20)])
        original = copy.deepcopy(p)
        evaluate_events(p)
        self.assertEqual(p, original)

    def test_bad_matching_rule(self):
        p = payload()
        p["matching"]["method"] = "any_overlap"
        with self.assertRaisesRegex(ValidationError, "iou_one_to_one"):
            evaluate_events(p)

    def test_bad_iou(self):
        p = payload()
        p["matching"]["min_iou"] = 1.1
        with self.assertRaisesRegex(ValidationError, "min_iou"):
            evaluate_events(p)

    def test_empty_well_is_bad(self):
        # Empty strings have no useful provenance: improve guard when encountered.
        p = payload()
        p["well"] = None
        with self.assertRaisesRegex(ValidationError, "well and section"):
            evaluate_events(p)


if __name__ == "__main__":
    unittest.main()
