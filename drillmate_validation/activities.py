"""Time-weighted validation for exhaustive, mutually exclusive activity timelines.

Expert and automatic activity timelines must each cover all reviewed intervals,
with exactly one label at each instant. Never infer untagged time as negatives.
"""
from __future__ import annotations

from .events import (_interval, _merged, _covered, _intersection, ValidationError)


def _timeline(raw, name, classes, reviewed):
    if not isinstance(raw, list):
        raise ValidationError(f"{name} must be a list")
    segments = []
    seen_ids = set()
    for obj in raw:
        if not isinstance(obj, dict):
            raise ValidationError(f"{name} includes a non-object")
        ident, label = obj.get("id"), obj.get("activity")
        if not isinstance(ident, str) or not ident.strip() or ident in seen_ids:
            raise ValidationError(f"{name} needs unique nonempty stable ids")
        seen_ids.add(ident)
        if label not in classes:
            raise ValidationError(f"{name} label {label!r} is not in activity_labels")
        interval = _interval(obj)
        if not _covered(interval, reviewed):
            raise ValidationError(f"{name} interval {ident!r} outside reviewed intervals; clip during normalization")
        segments.append((interval, label))
    segments.sort(key=lambda x: (x[0].start, x[0].end))
    if any(segments[i][0].end > segments[i+1][0].start for i in range(len(segments)-1)):
        raise ValidationError(f"{name} contains overlapping labels")
    # Every review period must be completely labeled. Unknown or ambiguous
    # stretches must be excluded from reviewed_intervals rather than invented
    # as a normal activity class.
    coverage = _merged([s[0] for s in segments])
    if (len(coverage) != len(reviewed) or
            any(abs(a.start-b.start) > 1e-6 or abs(a.end-b.end) > 1e-6
                for a, b in zip(coverage, reviewed))):
        raise ValidationError(f"{name} does not completely cover reviewed time")
    return segments


def evaluate_activities(payload):
    """Duration-weighted confusion and class metrics for exhaustive activity labels."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValidationError("schema_version must equal 1")
    if payload.get("agent_kind") != "activity":
        raise ValidationError("activity validator requires agent_kind='activity'")
    if not isinstance(payload.get("well"), str) or not payload["well"].strip():
        raise ValidationError("well must be a nonempty string")
    if not isinstance(payload.get("section"), str) or not payload["section"].strip():
        raise ValidationError("section must be a nonempty string")
    if payload.get("predictions_complete") is not True:
        raise ValidationError("Not evaluable: predictions_complete must be explicitly true")
    if payload.get("prediction_generation") not in {"continuous", "state_preserving_windows"}:
        raise ValidationError("Not evaluable: verified prediction_generation required")
    if not isinstance(payload.get("reviewed_intervals"), list) or not payload["reviewed_intervals"]:
        raise ValidationError("Not evaluable: reviewed_intervals required")
    if not isinstance(payload.get("prediction_coverage"), list) or not payload["prediction_coverage"]:
        raise ValidationError("Not evaluable: prediction_coverage required")
    reviewed = _merged([_interval(i) for i in payload["reviewed_intervals"]])
    coverage = _merged([_interval(i) for i in payload["prediction_coverage"]])
    if any(not _covered(w, coverage) for w in reviewed):
        raise ValidationError("Not evaluable: prediction coverage incomplete")
    classes = payload.get("activity_labels")
    if (not isinstance(classes, list) or not classes or
        any(not isinstance(c, str) or not c.strip() for c in classes) or
        len(set(classes)) != len(classes)):
        raise ValidationError("activity_labels must be nonempty, unique strings")
    expert = _timeline(payload.get("expert_activities"), "expert_activities", classes, reviewed)
    predicted = _timeline(payload.get("predicted_activities"), "predicted_activities", classes, reviewed)
    cm = {actual: {pred: 0.0 for pred in classes} for actual in classes}
    i = j = 0
    while i < len(expert) and j < len(predicted):
        a, a_name = expert[i]
        b, b_name = predicted[j]
        cm[a_name][b_name] += _intersection(a, b)
        if a.end <= b.end:
            i += 1
        if b.end <= a.end:
            j += 1
    duration = sum(w.duration for w in reviewed)
    diagonal = sum(cm[label][label] for label in classes)
    per_label = {}
    for c in classes:
        tp = cm[c][c]
        expert_seconds = sum(cm[c].values())
        pred_seconds = sum(cm[row][c] for row in classes)
        p = tp / pred_seconds if pred_seconds else None
        r = tp / expert_seconds if expert_seconds else None
        f1 = (2*p*r/(p+r)) if p is not None and r is not None and (p+r) else (0.0 if p is not None and r is not None else None)
        per_label[c] = {"expert_seconds": expert_seconds, "predicted_seconds": pred_seconds,
                        "matched_seconds": tp, "precision": p, "recall": r, "f1": f1}
    return {"status": "evaluated", "rule_version": "activity-duration-v1.0",
            "scope": {"well": payload["well"], "section": payload["section"],
                      "reviewed_seconds": duration},
            "accuracy": diagonal / duration if duration else None,
            "confusion_seconds": cm, "per_activity": per_label,
            "note": "Duration-weighted agreement, not distinct-event detection; requires exhaustive expert labels."}
