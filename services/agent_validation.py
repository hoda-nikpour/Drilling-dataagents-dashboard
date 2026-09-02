"""Regression metrics for drilling agents.

Provides sample-level TP/TN/FP/FN metrics for binary event agents and a multiclass
confusion matrix + per-class metrics for the activity agent.  These functions are
small on purpose so they can run both in pytest and inside Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BinaryMetrics:
    tp: int
    tn: int
    fp: int
    fn: int
    precision: float
    recall: float
    specificity: float
    f1: float
    accuracy: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _safe_div(n: float, d: float) -> float:
    return float(n / d) if d else 0.0

def _coerce_binary_value(value: object):
    """Convert common event labels safely to True/False."""
    if pd.isna(value):
        return pd.NA

    if isinstance(value, (bool, np.bool_)):
        return bool(value)

    if isinstance(value, (int, np.integer)):
        if value == 1:
            return True
        if value == 0:
            return False

    if isinstance(value, (float, np.floating)):
        if value == 1.0:
            return True
        if value == 0.0:
            return False

    text = str(value).strip().lower()

    true_values = {
        "true",
        "t",
        "yes",
        "y",
        "1",
        "event",
        "positive",
        "spike",
    }

    false_values = {
        "false",
        "f",
        "no",
        "n",
        "0",
        "no event",
        "negative",
        "normal",
    }

    if text in true_values:
        return True

    if text in false_values:
        return False

    raise ValueError(
        f"Cannot interpret binary label {value!r}. "
        "Use True/False, 1/0, Yes/No, Event/No Event, or similar supported labels."
    )

def binary_metrics(y_true: Sequence[object], y_pred: Sequence[object]) -> BinaryMetrics:
    """Compute TP/TN/FP/FN and derived metrics.

    Values are interpreted as booleans after missing rows are removed pairwise.
    """
    truth = pd.Series(y_true).reset_index(drop=True)
    pred = pd.Series(y_pred).reset_index(drop=True)
    if len(truth) != len(pred):
        raise ValueError("y_true and y_pred must have the same length")

    truth_binary = truth.map(_coerce_binary_value)
    pred_binary = pred.map(_coerce_binary_value)

    valid = truth_binary.notna() & pred_binary.notna()

    t = truth_binary[valid].astype(bool).to_numpy()
    p = pred_binary[valid].astype(bool).to_numpy()

    

    tp = int(np.sum(t & p))
    tn = int(np.sum(~t & ~p))
    fp = int(np.sum(~t & p))
    fn = int(np.sum(t & ~p))

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    accuracy = _safe_div(tp + tn, tp + tn + fp + fn)

    return BinaryMetrics(tp, tn, fp, fn, precision, recall, specificity, f1, accuracy)


def activity_confusion_matrix(
    y_true: Sequence[object],
    y_pred: Sequence[object],
    *,
    labels: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return a labelled multiclass confusion matrix (rows=true, columns=predicted)."""
    truth = pd.Series(y_true, dtype="object").reset_index(drop=True)
    pred = pd.Series(y_pred, dtype="object").reset_index(drop=True)
    if len(truth) != len(pred):
        raise ValueError("y_true and y_pred must have the same length")
    valid = truth.notna() & pred.notna()
    truth = truth[valid].astype(str)
    pred = pred[valid].astype(str)

    if labels is None:
        labels = sorted(set(truth.tolist()) | set(pred.tolist()))

    matrix = pd.DataFrame(0, index=list(labels), columns=list(labels), dtype=int)
    matrix.index.name = "true_activity"
    matrix.columns.name = "predicted_activity"

    for t, p in zip(truth, pred):
        if t not in matrix.index:
            matrix.loc[t] = 0
        if p not in matrix.columns:
            matrix[p] = 0
        matrix.loc[t, p] += 1
    return matrix


def activity_metrics(
    y_true: Sequence[object],
    y_pred: Sequence[object],
    *,
    labels: Sequence[str] | None = None,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """Return summary metrics, confusion matrix and per-class precision/recall/F1."""
    cm = activity_confusion_matrix(y_true, y_pred, labels=labels)
    total = int(cm.to_numpy().sum())
    correct = int(np.trace(cm.to_numpy())) if cm.shape[0] == cm.shape[1] else 0
    accuracy = _safe_div(correct, total)

    per_class_rows = []
    f1s = []
    recalls = []
    precisions = []
    for label in cm.index:
        tp = int(cm.loc[label, label]) if label in cm.columns else 0
        fn = int(cm.loc[label].sum() - tp)
        fp = int(cm[label].sum() - tp) if label in cm.columns else 0
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class_rows.append(
            {
                "activity": label,
                "support": int(cm.loc[label].sum()),
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    summary = {
        "accuracy": accuracy,
        "macro_precision": float(np.mean(precisions)) if precisions else 0.0,
        "macro_recall": float(np.mean(recalls)) if recalls else 0.0,
        "macro_f1": float(np.mean(f1s)) if f1s else 0.0,
        "n_samples": float(total),
    }
    return summary, cm, pd.DataFrame(per_class_rows)


def compare_binary_versions(
    *,
    y_true: Sequence[object],
    old_pred: Sequence[object],
    new_pred: Sequence[object],
    old_name: str = "old_agent",
    new_name: str = "new_agent",
) -> pd.DataFrame:
    """Side-by-side regression table for an old and a changed binary agent."""
    old = binary_metrics(y_true, old_pred).as_dict()
    new = binary_metrics(y_true, new_pred).as_dict()
    table = pd.DataFrame([old, new], index=[old_name, new_name])
    table["delta_f1_vs_old"] = table["f1"] - float(table.loc[old_name, "f1"])
    table["delta_fp_vs_old"] = table["fp"] - int(table.loc[old_name, "fp"])
    table["delta_fn_vs_old"] = table["fn"] - int(table.loc[old_name, "fn"])
    return table
