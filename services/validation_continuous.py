"""Read-only, continuous prediction generation for *final* validation.

Unlike the interactive window/table code, this computes from the section's
first sample to its last sample in a single run, preserving temporal state.
It does not modify or replace interactive predictions. The caller MUST make a
conservative resource decision before loading the full dataframe.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from math import isfinite
import re
from typing import Callable

import pandas as pd

from drillmate_validation.events import ValidationError


MAX_VALIDATION_ROWS = 300_000  # conservative default; never silently truncate


def fixed_utc_offset(text: str) -> timezone:
    """Require an explicitly acknowledged fixed timezone offset for naive logs."""
    if not isinstance(text, str) or not re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", text):
        raise ValidationError("Log timezone must be explicit, e.g. +00:00 or +02:00")
    sign = 1 if text[0] == "+" else -1
    hour, minute = int(text[1:3]), int(text[4:6])
    if hour == 14 and minute != 0:
        raise ValidationError("UTC offset cannot exceed 14:00")
    return timezone(sign * timedelta(hours=hour, minutes=minute))


def utc_iso(value, assumed_log_offset: str) -> str:
    """Parse timestamps; localize naive drilling times using explicit offset."""
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValidationError("Missing timestamp in validation interval")
    if ts.tzinfo is None:
        ts = ts.tz_localize(fixed_utc_offset(assumed_log_offset))
    return ts.tz_convert("UTC").isoformat()


def continuous_prediction_coverage(index, *, log_utc_offset: str,
                                   cadence_seconds: float,
                                   max_gap_seconds: float) -> list[dict]:
    """Prove which physical time spans are represented by sample timestamps.

    The last sample extends by the user-supplied sample cadence, while gaps
    longer than max_gap_seconds are excluded. We do NOT infer data in gaps.
    """
    fixed_utc_offset(log_utc_offset)
    if (not isfinite(float(cadence_seconds)) or not isfinite(float(max_gap_seconds))
            or not 0 < float(cadence_seconds) <= float(max_gap_seconds)):
        raise ValidationError("Require finite 0 < cadence_seconds <= max_gap_seconds")
    points = pd.DatetimeIndex(index)
    if (len(points) == 0 or points.hasnans or not points.is_monotonic_increasing
            or not points.is_unique):
        raise ValidationError("Continuous prediction time index must be nonempty, sorted, unique, and valid")
    unique = points
    groups = []
    start = prev = unique[0]
    for current in unique[1:]:
        elapsed = (current - prev).total_seconds()
        if elapsed > max_gap_seconds:
            groups.append({"start": utc_iso(start, log_utc_offset),
                           "end": utc_iso(prev + pd.Timedelta(seconds=cadence_seconds), log_utc_offset)})
            start = current
        prev = current
    groups.append({"start": utc_iso(start, log_utc_offset),
                   "end": utc_iso(prev + pd.Timedelta(seconds=cadence_seconds), log_utc_offset)})
    return groups


def assert_unbroken_prediction_state(coverage: list[dict]) -> None:
    """Fail closed when a continuous agent run would bridge missing-data gaps.

    The current activity state resolver does not reset itself at gaps. Until a
    verified gap-aware runner exists, predictions crossing such boundaries
    cannot be certified as section-wide validation ground truth.
    """
    if len(coverage) != 1:
        raise ValidationError(
            "Not evaluable: the section contains unobserved time gaps. "
            "Continuous agent state would cross these gaps; validate a contiguous "
            "section or implement and test gap-aware state resets first."
        )


def assert_full_section_loaded(expected_index, loaded_index, *, max_rows: int = MAX_VALIDATION_ROWS):
    """Guard before scoring: no subset, no reordered/missing sampled rows."""
    expected = pd.DatetimeIndex(expected_index)
    actual = pd.DatetimeIndex(loaded_index)
    if len(expected) > max_rows:
        raise ValidationError(
            f"Not evaluable in dashboard: {len(expected):,} rows exceed "
            f"the {max_rows:,}-row safety limit. Use an offline high-memory run."
        )
    if not expected.equals(actual):
        raise ValidationError("Loaded agent data does not match full section time index")
    if (not len(actual) or actual.hasnans or not actual.is_monotonic_increasing
            or not actual.is_unique):
        raise ValidationError("Invalid full-section index: timestamps must be sorted, unique and nonmissing")


def calculate_continuous_predictions(*, full_df: pd.DataFrame, label_to_column: dict,
                                     activity_ui: dict, symptom_ui: dict,
                                     selected_agent: str, agent_kind: str,
                                     run_activity: Callable, resolve_activity: Callable,
                                     run_symptom: Callable) -> list[dict]:
    """Call exact existing production agent functions ONCE, without window splits.

    Separate callback arguments let tests validate production call wiring without
    importing the Streamlit app (whose import executes page code).
    """
    if not selected_agent or agent_kind not in {"symptom", "activity"}:
        raise ValidationError("A selected agent and type are required")
    if activity_ui.get("enabled") is not True:
        raise ValidationError("Activity processing must be enabled")
    df = full_df.copy()
    activity_cfg = run_activity(df=df, label_to_column=label_to_column, activity_ui=activity_ui)
    if not isinstance(activity_cfg, dict) or not isinstance(activity_cfg.get("labels"), pd.Series) or activity_cfg["labels"].empty:
        raise ValidationError("Activity processing did not produce a complete label series")
    activity_cfg = resolve_activity(df=df, activity_cfg=activity_cfg)
    if not isinstance(activity_cfg, dict) or not isinstance(activity_cfg.get("labels"), pd.Series) or len(activity_cfg["labels"]) != len(df):
        raise ValidationError("Temporal activity resolution did not produce a full label series")
    if agent_kind == "symptom":
        if symptom_ui.get("enabled") is not True or symptom_ui.get("selected_symptom") != selected_agent:
            raise ValidationError("Selected symptom and configuration do not agree")
        calculated = run_symptom(df=df, label_to_column=label_to_column,
                                 symptom_ui=symptom_ui, activity_ui=activity_ui,
                                 activity_cfg=activity_cfg)
    else:
        if activity_ui.get("selected_activity") != selected_agent:
            raise ValidationError("Selected activity and configuration do not agree")
        calculated = activity_cfg
    if not isinstance(calculated, dict) or not isinstance(calculated.get("intervals"), list):
        raise ValidationError("Agent failed to return interval list")
    rows = [dict(x) for x in calculated["intervals"] if x.get("label") == selected_agent]
    for row in rows:
        if "start" not in row or "end" not in row:
            raise ValidationError("Agent returned an interval missing time boundaries")
    rows.sort(key=lambda x: pd.Timestamp(x["start"]))
    return rows


def normalize_predictions(raw_intervals: list[dict], *, agent: str, log_utc_offset: str,
                          sample_cadence_seconds: float | None = None) -> list[dict]:
    """Convert inclusive last-sample endpoints to half-open model intervals.

    The current production `mask_to_intervals()` and
    `intervals_from_label_series()` both set `end` to the *last detected
    sample*, not the timestamp immediately after the detected period. For
    validation ONLY, extend the end by the verified sample cadence. Original
    dashboard interval timestamps and exports are never modified.
    """
    normalized = []
    for i, item in enumerate(raw_intervals):
        start = utc_iso(item["start"], log_utc_offset)
        end = utc_iso(item["end"], log_utc_offset)
        if pd.Timestamp(end) < pd.Timestamp(start):
            raise ValidationError("Prediction end precedes start")
        if sample_cadence_seconds is not None:
            if not isfinite(float(sample_cadence_seconds)) or not 0 < float(sample_cadence_seconds):
                raise ValidationError("Verified finite positive sample cadence required")
            end = (pd.Timestamp(end) + pd.Timedelta(seconds=float(sample_cadence_seconds))).isoformat()
        normalized.append({"id": f"continuous-{i:08d}", "agent": agent,
                           "start": start, "end": end})
    return normalized
