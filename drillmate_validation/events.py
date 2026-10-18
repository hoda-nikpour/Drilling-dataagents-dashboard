"""Versioned event-level validator independent of the Streamlit/React dashboard.

Input is *normalized* JSON, not a raw dashboard session. See docs/VALIDATION_PATCH.md.
All times are converted to UTC instants. Intervals use [start, end) semantics.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

RULE_VERSION = "event-v1.0"


class ValidationError(ValueError):
    """A report cannot be computed safely from the supplied input."""


@dataclass(frozen=True)
class Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Event:
    ident: str
    interval: Interval


def _timestamp(value: str) -> float:
    if not isinstance(value, str):
        raise ValidationError("Timestamps must be ISO 8601 strings with UTC offsets")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Invalid timestamp: {value!r}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValidationError(f"Timezone offset required: {value!r}")
    return dt.astimezone(timezone.utc).timestamp()


def _interval(obj: dict, *, allow_point: bool = False, cadence: float | None = None) -> Interval:
    if not isinstance(obj, dict) or "start" not in obj or "end" not in obj:
        raise ValidationError("Every interval needs start and end")
    start, end = _timestamp(obj["start"]), _timestamp(obj["end"])
    if end < start:
        raise ValidationError("Interval end must not precede start")
    if end == start:
        if not allow_point:
            raise ValidationError("Zero-duration expert/review/coverage interval")
        if cadence is None or not isfinite(cadence) or cadence <= 0:
            raise ValidationError("Zero-duration detection needs positive sample_cadence_seconds")
        end = start + cadence
    return Interval(start, end)


def _positive_float(v: Any, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(v, bool):
        raise ValidationError(f"{name} must be numeric")
    try:
        v = float(v)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{name} must be numeric") from exc
    if not isfinite(v) or v < 0 or (not allow_zero and v == 0):
        raise ValidationError(f"Invalid {name}: {v}")
    return v


def _merged(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for item in sorted(intervals, key=lambda i: (i.start, i.end)):
        if out and item.start <= out[-1].end:
            out[-1] = Interval(out[-1].start, max(out[-1].end, item.end))
        else:
            out.append(item)
    return out


def _covered(interval: Interval, merged: list[Interval]) -> bool:
    return any(w.start <= interval.start and w.end >= interval.end for w in merged)


def _intersection(a: Interval, b: Interval) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def _exposure(event: Interval, reviewed: list[Interval]) -> float:
    return sum(_intersection(event, w) for w in reviewed)


def _event_list(items: Any, agent: str, *, predictions: bool, cadence: float | None) -> list[Event]:
    if not isinstance(items, list):
        raise ValidationError("expert_tags and predictions must be lists")
    out: list[Event] = []
    seen: set[str] = set()
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValidationError(f"Event #{i} must be an object")
        ident = raw.get("id")
        if not isinstance(ident, str) or not ident.strip():
            raise ValidationError(f"Event #{i} needs a stable, nonempty id")
        if ident in seen:
            raise ValidationError(f"Duplicate event id: {ident!r}; resolve during normalization")
        seen.add(ident)
        if raw.get("agent") != agent:
            raise ValidationError(f"Event {ident!r} must have agent {agent!r}; display tag names are not agent labels")
        out.append(Event(ident, _interval(raw, allow_point=predictions, cadence=cadence)))
    return out


def _candidate_score(a: Interval, b: Interval) -> tuple[float, float]:
    ov = _intersection(a, b)
    union = a.duration + b.duration - ov
    return ov, (ov / union if union > 0 else 0.0)


def _max_cardinality_match(experts: list[Event], predictions: list[Event], minimum_iou: float,
                           min_overlap_seconds: float) -> list[tuple[int, int, float, float]]:
    # Deterministic maximum-cardinality bipartite matching (not greedy matching).
    # Score-descending edges are used for reproducible preferences; tie choices do
    # not claim to globally maximize sum(IoU).
    edges: list[list[tuple[int, float, float]]] = []
    for expert in experts:
        row = []
        for j, pred in enumerate(predictions):
            ov, iou = _candidate_score(expert.interval, pred.interval)
            if ov > 0 and ov >= min_overlap_seconds and iou >= minimum_iou:
                row.append((j, iou, ov))
        row.sort(key=lambda v: (-v[1], -v[2], predictions[v[0]].ident))
        edges.append(row)
    # Alternating-path BFS avoids recursion limits on long, densely matched
    # drilling logs. Matched predictions have a single owner at all times.
    owner: dict[int, int] = {}  # prediction-index -> expert-index
    mate: dict[int, int] = {}   # expert-index -> prediction-index

    def augment(root: int) -> bool:
        queue = deque([root])
        seen_experts = {root}
        parent_pred: dict[int, int] = {}  # prediction-index -> predecessor expert
        while queue:
            i = queue.popleft()
            for j, _, _ in edges[i]:
                if j in parent_pred:
                    continue
                parent_pred[j] = i
                if j not in owner:
                    # Trace back the alternating path and flip the matching.
                    current_j = j
                    while True:
                        current_i = parent_pred[current_j]
                        old_j = mate.get(current_i)
                        owner[current_j] = current_i
                        mate[current_i] = current_j
                        if old_j is None:
                            return True
                        current_j = old_j
                elif owner[j] not in seen_experts:
                    seen_experts.add(owner[j])
                    queue.append(owner[j])
        return False

    # Process constrained experts first, without dropping unmatched experts.
    for i in sorted(range(len(experts)), key=lambda k: (len(edges[k]), experts[k].ident)):
        augment(i)
    matches = []
    for j, i in owner.items():
        ov, iou = _candidate_score(experts[i].interval, predictions[j].interval)
        matches.append((i, j, ov, iou))
    return sorted(matches, key=lambda pair: (experts[pair[0]].interval.start, experts[pair[0]].ident))


def _union_overlap(a: list[Interval], b: list[Interval]) -> float:
    i = j = 0
    duration = 0.0
    aa, bb = _merged(a), _merged(b)
    while i < len(aa) and j < len(bb):
        duration += _intersection(aa[i], bb[j])
        if aa[i].end <= bb[j].end:
            i += 1
        else:
            j += 1
    return duration


def _clip_to_windows(intervals: list[Interval], windows: list[Interval]) -> list[Interval]:
    return [Interval(max(a.start, w.start), min(a.end, w.end))
            for a in intervals for w in windows if _intersection(a, w) > 0]


def evaluate_events(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute independent symptom *event* metrics; never mutates payload.

    Fails closed unless reviewed AND model prediction coverage are explicit.
    Boundary-crossing predictions can earn a TP but not an unmatched FP.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValidationError("schema_version must equal 1")
    agent = payload.get("agent")
    if not isinstance(agent, str) or not agent.strip():
        raise ValidationError("Nonempty selected agent required")
    if payload.get("agent_kind") != "symptom":
        raise ValidationError("This event validator supports symptom agents only; use a separate activity evaluator")
    if (not isinstance(payload.get("well"), str) or not payload["well"].strip() or
            not isinstance(payload.get("section"), str) or not payload["section"].strip()):
        raise ValidationError("well and section must be nonempty strings")
    if payload.get("predictions_complete") is not True:
        raise ValidationError("Not evaluable: predictions_complete must be explicitly true")
    if payload.get("prediction_generation") not in {"continuous", "state_preserving_windows"}:
        raise ValidationError("Not evaluable: prediction generation must be verified continuous or state_preserving_windows")
    if not isinstance(payload.get("reviewed_intervals"), list) or not payload["reviewed_intervals"]:
        raise ValidationError("Not evaluable: reviewed_intervals must be explicitly supplied")
    if not isinstance(payload.get("prediction_coverage"), list) or not payload["prediction_coverage"]:
        raise ValidationError("Not evaluable: prediction_coverage must be explicitly supplied")
    reviewed = _merged([_interval(i) for i in payload["reviewed_intervals"]])
    coverage = _merged([_interval(i) for i in payload["prediction_coverage"]])
    if any(not _covered(w, coverage) for w in reviewed):
        raise ValidationError("Not evaluable: prediction coverage does not fully cover reviewed intervals")
    rules = payload.get("matching")
    if not isinstance(rules, dict) or rules.get("version") != RULE_VERSION:
        raise ValidationError(f"Explicit matching.version={RULE_VERSION!r} required")
    if rules.get("method") != "iou_one_to_one":
        raise ValidationError("Only method 'iou_one_to_one' is supported for distinct symptom events")
    threshold = _positive_float(rules.get("min_iou"), "min_iou", allow_zero=True)
    if threshold > 1:
        raise ValidationError("min_iou must be <= 1")
    min_overlap = _positive_float(rules.get("min_overlap_seconds"), "min_overlap_seconds", allow_zero=True)
    cadence = None
    if "sample_cadence_seconds" in payload and payload["sample_cadence_seconds"] is not None:
        cadence = _positive_float(payload["sample_cadence_seconds"], "sample_cadence_seconds")
    experts = _event_list(payload.get("expert_tags"), agent, predictions=False, cadence=None)
    predictions = _event_list(payload.get("predictions"), agent, predictions=True, cadence=cadence)
    if any(not _covered(e.interval, reviewed) for e in experts):
        raise ValidationError("Expert event extends outside reviewed intervals; extend coverage or correct annotation")
    # Predictions outside reviewed coverage cannot be scored; predictions crossing
    # a review boundary are listed as partial, not assumed false positives.
    relevant = [p for p in predictions if _exposure(p.interval, reviewed) > 0]
    matched = _max_cardinality_match(experts, relevant, threshold, min_overlap)
    used_experts = {i for i, _, _, _ in matched}
    used_predictions = {j for _, j, _, _ in matched}
    false_negatives = [e.ident for i, e in enumerate(experts) if i not in used_experts]
    false_positives = [p.ident for j, p in enumerate(relevant)
                       if j not in used_predictions and _covered(p.interval, reviewed)]
    partial_unmatched = [p.ident for j, p in enumerate(relevant)
                         if j not in used_predictions and not _covered(p.interval, reviewed)]
    excluded_unreviewed = [p.ident for p in predictions if _exposure(p.interval, reviewed) == 0]
    tp, fp, fn = len(matched), len(false_positives), len(false_negatives)
    # If any partial unpaired prediction remains, the FP count may be a lower bound.
    # Precision/F1 must not be presented as definitive in that situation.
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if (precision is not None and recall is not None and precision + recall > 0) else (0.0 if precision is not None and recall is not None else None)
    complete_fp = len(partial_unmatched) == 0
    expert_union = _merged([e.interval for e in experts])
    prediction_union = _clip_to_windows([p.interval for p in predictions], reviewed)
    covered_seconds = _union_overlap(expert_union, prediction_union)
    expert_seconds = sum(i.duration for i in expert_union)
    result = {
        "status": "evaluated" if complete_fp else "partial_boundary_predictions_review_required",
        "rule_version": RULE_VERSION,
        "scope": {"well": payload["well"], "section": payload["section"], "agent": agent,
                  "reviewed_seconds": sum(w.duration for w in reviewed),
                  "prediction_generation": payload["prediction_generation"]},
        "matching": {"method": rules["method"], "min_iou": threshold, "min_overlap_seconds": min_overlap},
        "event_counts": {"TP": tp, "FP": fp if complete_fp else None, "FN": fn,
                         "FP_lower_bound": fp if not complete_fp else None},
        "metrics": {"precision": precision if complete_fp else None,
                    "recall": recall, "f1": f1 if complete_fp else None,
                    "expert_time_covered_fraction": covered_seconds / expert_seconds if expert_seconds else None},
        "matches": [{"expert_id": experts[i].ident, "prediction_id": relevant[j].ident,
                     "overlap_seconds": round(ov, 6), "iou": round(iou, 8)}
                    for i, j, ov, iou in matched],
        "unmatched_expert_ids": false_negatives,
        "unmatched_prediction_ids": false_positives,
        "partial_boundary_prediction_ids": partial_unmatched,
        "excluded_unreviewed_prediction_ids": excluded_unreviewed,
        "warnings": (["Unmatched predictions cross review boundaries: precision, F1 and FP are not definitive. Extend reviewed coverage or adjudicate these events."]
                     if not complete_fp else []),
    }
    return result
