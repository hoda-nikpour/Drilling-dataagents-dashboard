import csv
import io
import json
import uuid
from datetime import timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from agents.activity_agents import ActivityConfig
from agents.activity_support import interval_overlap, overlap_ratio
from agents.symptom_agents import SymptomConfig
from config import (
    DEFAULT_MARKER_DISPLAY,
    MARKER_DISPLAY_OPTIONS,
    MAX_PARAMS_PER_TRACK,
    PARAMETER_CATALOG,
    PARAMETER_DISPLAY_NAMES,
)


ACCEPTANCE_THRESHOLD_PERCENT = 95.0
ACTIVITY_VALIDATION_MIN_OVERLAP_PERCENT = 50.0


def _interval_overlap(a_start, a_end, b_start, b_end):
    return interval_overlap(a_start, a_end, b_start, b_end)


def _build_tag_status_rows(tag_intervals: list[dict], agent_intervals: list[dict]) -> list[dict]:
    rows = []

    for tag in tag_intervals:
        matched = False
        overlap_start = None
        overlap_end = None

        for agent in agent_intervals:
            ov = _interval_overlap(tag["start"], tag["end"], agent["start"], agent["end"])
            if ov is not None:
                matched = True
                overlap_start, overlap_end = ov
                break

        rows.append(
            {
                "label": tag["label"],
                "start": tag["start"],
                "end": tag["end"],
                "status": "Matched" if matched else "Unmatched",
                "overlap_start": overlap_start,
                "overlap_end": overlap_end,
            }
        )

    return rows


def _build_summary(tag_intervals: list[dict], agent_intervals: list[dict]) -> dict:
    tag_status_rows = _build_tag_status_rows(tag_intervals, agent_intervals)
    overlap_count = sum(1 for row in tag_status_rows if row["status"] == "Matched")
    tag_count = len(tag_intervals)
    agent_count = len(agent_intervals)

    score_percent = (overlap_count / tag_count) * 100.0 if tag_count > 0 else 0.0
    accepted = score_percent >= ACCEPTANCE_THRESHOLD_PERCENT

    return {
        "tag_count": tag_count,
        "agent_count": agent_count,
        "overlap_count": overlap_count,
        "score_percent": score_percent,
        "acceptance_threshold_percent": ACCEPTANCE_THRESHOLD_PERCENT,
        "accepted": accepted,
        "tag_status_rows": tag_status_rows,
    }


def _build_activity_validation_rows(
    manual_activity_tags: list[dict],
    activity_intervals: list[dict],
    min_overlap_percent: float = ACTIVITY_VALIDATION_MIN_OVERLAP_PERCENT,
) -> list[dict]:
    rows = []
    min_overlap_ratio = min_overlap_percent / 100.0

    for tag in manual_activity_tags:
        best_overlap_ratio = 0.0
        best_overlap_start = None
        best_overlap_end = None
        matched_label = None
        matched = False

        for activity in activity_intervals:
            if activity.get("label") != tag.get("label"):
                continue

            ratio = overlap_ratio(
                reference_start=tag["start"],
                reference_end=tag["end"],
                candidate_start=activity["start"],
                candidate_end=activity["end"],
            )

            if ratio > best_overlap_ratio:
                best_overlap_ratio = ratio
                ov = _interval_overlap(tag["start"], tag["end"], activity["start"], activity["end"])
                if ov is not None:
                    best_overlap_start, best_overlap_end = ov
                matched_label = activity.get("label")

        if best_overlap_ratio >= min_overlap_ratio:
            matched = True

        rows.append(
            {
                "label": tag["label"],
                "start": tag["start"],
                "end": tag["end"],
                "status": "Matched" if matched else "Unmatched",
                "matched_activity": matched_label,
                "overlap_start": best_overlap_start,
                "overlap_end": best_overlap_end,
                "overlap_percent": best_overlap_ratio * 100.0,
            }
        )

    return rows


def _build_activity_validation_summary(
    manual_activity_tags: list[dict],
    activity_intervals: list[dict],
    min_overlap_percent: float = ACTIVITY_VALIDATION_MIN_OVERLAP_PERCENT,
) -> dict:
    rows = _build_activity_validation_rows(
        manual_activity_tags=manual_activity_tags,
        activity_intervals=activity_intervals,
        min_overlap_percent=min_overlap_percent,
    )
    matched_count = sum(1 for row in rows if row["status"] == "Matched")
    tag_count = len(manual_activity_tags)
    score_percent = (matched_count / tag_count * 100.0) if tag_count > 0 else 0.0

    return {
        "tag_count": tag_count,
        "matched_count": matched_count,
        "score_percent": score_percent,
        "min_overlap_percent": min_overlap_percent,
        "rows": rows,
    }


def _json_safe_text(value):
    """
    Convert values to JSON-safe text.
    Handles datetime/Timestamp/NaT/None safely.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        if isinstance(value, (pd.Timestamp,)):
            return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    try:
        ts = pd.Timestamp(value)
        if not pd.isna(ts):
            return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return str(value)

def _json_safe_value(value):
    """
    Convert Streamlit session_state values into JSON-safe values.
    Handles datetime, Timestamp, tuples, lists, dicts, and simple scalars.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    try:
        if hasattr(value, "strftime"):
            return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    if isinstance(value, tuple):
        return [_json_safe_value(x) for x in value]

    if isinstance(value, list):
        return [_json_safe_value(x) for x in value]

    if isinstance(value, dict):
        return {str(k): _json_safe_value(v) for k, v in value.items()}

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)




def _normalize_track_param_labels_for_save(value) -> list[list[str]]:
    """Return exactly three JSON-safe track parameter lists."""
    out: list[list[str]] = []

    if isinstance(value, dict):
        value = [
            value.get("track1", []),
            value.get("track2", []),
            value.get("track3", []),
        ]

    if not isinstance(value, list):
        value = []

    for i in range(3):
        item = value[i] if i < len(value) else []
        if isinstance(item, (list, tuple)):
            out.append([str(x) for x in item if str(x).strip()])
        elif isinstance(item, str) and item.strip():
            out.append([item.strip()])
        else:
            out.append([])

    return out


def _get_saved_track_param_labels(context_key: str) -> list[list[str]]:
    """Prefer the app's non-widget saved track selection, then widget keys."""
    for key in (
        f"saved_track_param_labels_{context_key}",
        f"plot_track_param_labels_{context_key}",
    ):
        tracks = _normalize_track_param_labels_for_save(st.session_state.get(key))
        if any(tracks):
            return tracks

    tracks = _normalize_track_param_labels_for_save([
        st.session_state.get(f"track_params_1_{context_key}", []),
        st.session_state.get(f"track_params_2_{context_key}", []),
        st.session_state.get(f"track_params_3_{context_key}", []),
    ])
    return tracks


def _sanitize_dashboard_session_filename(value: str, fallback: str = "dashboard_session") -> str:
    """Return a safe .json filename chosen by the user."""
    text = str(value or "").strip()
    if not text:
        text = fallback

    # Remove an existing extension first, then sanitize the base name.
    if text.lower().endswith(".json"):
        text = text[:-5]

    safe = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_", "."}:
            safe.append(ch)
        elif ch.isspace():
            safe.append("_")

    name = "".join(safe).strip("._-") or fallback
    return f"{name}.json"

def _build_full_dashboard_state(context_key: str) -> dict:
    """
    Save all small dashboard/session values for this selected well/section context.

    This intentionally saves the widget keys themselves. That makes restore robust:
    when the JSON is loaded, the exact same Streamlit widget keys are put back into
    st.session_state before the widgets are created.

    Important:
    Internal keys beginning with "_" are never saved. Those keys are app-control
    flags, not dashboard settings, and saving them can cause restore/rerun loops.
    """
    ignored_fragments = [
        "download_",
        "upload",
        "FormSubmitter",
        "_undo_",
        "use_current_window_as_tag_",
    ]

    state = {}

    for key, value in st.session_state.items():
        key = str(key)

        if _is_non_restorable_widget_key(key):
            continue

        if any(fragment in key for fragment in ignored_fragments):
            continue

        keep = (
            key == "selected_well"
            or key.startswith("selected_sections_")
            or key.endswith(f"_{context_key}")
            or f"_{context_key}_" in key
        )

        if not keep:
            continue

        try:
            state[key] = _json_safe_value(value)
        except Exception:
            pass

    return state

def _is_early_dashboard_key(key: str, context_key: str) -> bool:
    """
    These widgets are created before render_agent_controls().
    They must only be restored by apply_loaded_dashboard_state_early(),
    not later inside _apply_loaded_review_to_state().
    """
    early_prefixes = [
        "track_params_",
        "max_override_",
        "curve_source_",
        "window_index_",
    ]

    if not key.endswith(f"_{context_key}") and f"_{context_key}_" not in key:
        return False

    return any(key.startswith(prefix) for prefix in early_prefixes)


def _is_non_restorable_widget_key(key: str) -> bool:
    """
    Streamlit button-like widgets cannot be restored by assigning values into
    st.session_state before the widget is created.

    Saved JSON files from older versions may contain these one-click keys because
    they match the context suffix. Restoring them causes:
    StreamlitValueAssignmentNotAllowedError.

    Keep these keys out of both future saved sessions and loaded sessions.
    """
    key = str(key)

    blocked_exact_prefixes = [
        "use_current_window_as_tag_",
    ]

    blocked_fragments = [
        "download_",
        "upload",
        "FormSubmitter",
    ]

    if key.startswith("_"):
        return True

    if any(key.startswith(prefix) for prefix in blocked_exact_prefixes):
        return True

    if any(fragment in key for fragment in blocked_fragments):
        return True

    return False

def _restore_full_dashboard_state(uploaded_data: dict, context_key: str, t_min=None, t_max=None):
    """
    Restore saved widget/session values from JSON.

    Important:
    Early widgets such as track_params, curve_source, and exact_time fields
    are restored before those widgets are created by apply_loaded_dashboard_state_early().
    This function runs later, so it must skip those early keys.
    """
    dashboard_state = uploaded_data.get("dashboard_state", {}) or {}
    widget_state = dashboard_state.get("widget_state", {}) or {}

    min_ts = pd.Timestamp(t_min) if t_min is not None else None
    max_ts = pd.Timestamp(t_max) if t_max is not None else None

    def _maybe_datetime(value):
        try:
            ts = pd.Timestamp(value)
            if pd.isna(ts):
                return value

            if min_ts is not None and max_ts is not None:
                ts = _clamp_timestamp(ts, min_ts, max_ts)

            return ts.to_pydatetime()
        except Exception:
            return value

    def _safe_set(key: str, value):
        """
        Streamlit raises if a widget key is modified after the widget exists.
        If that happens, skip it instead of crashing the dashboard.
        """
        try:
            st.session_state[key] = value
        except Exception:
            pass

    for key, value in widget_state.items():
        key = str(key)

        # Critical:
        # Old saved JSON files may contain internal restore flags, pending payloads,
        # and button-like widget keys. Restoring those causes either rerun loops or
        # StreamlitValueAssignmentNotAllowedError when the button is created.
        if _is_non_restorable_widget_key(key):
            continue

        # Critical fix:
        # These keys have already been handled before their widgets were created.
        # Do not restore them again here.
        if _is_early_dashboard_key(key, context_key):
            continue

        if key.startswith("agent_interval_") and isinstance(value, list) and len(value) == 2:
            start_ts = _maybe_datetime(value[0])
            end_ts = _maybe_datetime(value[1])

            try:
                if pd.Timestamp(end_ts) > pd.Timestamp(start_ts):
                    _safe_set(key, (start_ts, end_ts))
            except Exception:
                pass

            continue

        if key.startswith("reference_time_"):
            _safe_set(key, _maybe_datetime(value))
            continue

        if (
            key.startswith("tag_start_")
            or key.startswith("tag_end_")
            or key.startswith("activity_tag_start_")
            or key.startswith("activity_tag_end_")
        ):
            parsed = _parse_uploaded_datetime(value)
            if not pd.isna(parsed):
                if min_ts is not None and max_ts is not None:
                    parsed = _clamp_timestamp(parsed, min_ts, max_ts)
                _safe_set(key, _format_datetime_text(parsed))
            else:
                _safe_set(key, str(value))
            continue

        _safe_set(key, value)

def _build_export_payload(
    tag_intervals: list[dict],
    agent_intervals: list[dict],
    summary: dict,
    manual_activity_tags: list[dict] | None = None,
    activity_validation_summary: dict | None = None,
    selected_well: str | None = None,
    selected_sections: tuple[str, ...] | list[str] | None = None,
    context_key: str | None = None,
) -> tuple[str, str]:
    manual_activity_tags = manual_activity_tags or []
    activity_validation_summary = activity_validation_summary or {}

    saved_track_param_labels = _get_saved_track_param_labels(context_key) if context_key else [[], [], []]

    widget_state = _build_full_dashboard_state(context_key=context_key)
    if context_key and any(saved_track_param_labels):
        widget_state[f"saved_track_param_labels_{context_key}"] = saved_track_param_labels
        widget_state[f"plot_track_param_labels_{context_key}"] = saved_track_param_labels
        for idx in range(3):
            widget_state[f"track_params_{idx + 1}_{context_key}"] = saved_track_param_labels[idx]

    dashboard_state = {
        "schema_version": 2,
        "save_type": "full_dashboard_restore",
        "plot_track_param_labels": saved_track_param_labels,
        "widget_state": widget_state,
    }

    # Keep manual sidebar tags and chart-drawn tags explicit in the saved JSON.
    # Track 4 receives both through tag_intervals, but restore needs to know which
    # ones came from the browser-drawn tagger path.
    visual_key = f"visual_tag_intervals_{context_key}" if context_key else ""
    drawn_tag_intervals = []
    if visual_key:
        for idx, item in enumerate(st.session_state.get(visual_key, []) or [], start=1):
            normalized = _normalize_restored_visual_tag(
                item,
                fallback_label=f"Drawn Tag {idx}",
            )
            if normalized:
                drawn_tag_intervals.append(normalized)

    if not drawn_tag_intervals:
        drawn_tag_intervals = [
            x for x in tag_intervals
            if isinstance(x, dict) and str(x.get("source", "")).lower() == "chart_drag"
        ]

    manual_tagger_intervals = [
        x for x in tag_intervals
        if not (isinstance(x, dict) and str(x.get("source", "")).lower() == "chart_drag")
    ]

    payload = {
        "dashboard_context": {
            "selected_well": selected_well,
            "selected_sections": [str(x) for x in (selected_sections or [])],
            "context_key": context_key,
        },
        "dashboard_state": dashboard_state,
        "plot_track_param_labels": saved_track_param_labels,
        "manual_tagger_intervals": [
            {
                "label": str(x.get("label", "")),
                "start": _json_safe_text(x.get("start")),
                "end": _json_safe_text(x.get("end")),
                "source": x.get("source", "manual"),
            }
            for x in manual_tagger_intervals
        ],
        "drawn_tag_intervals": [
            {
                "label": str(x.get("label", "")),
                "start": _json_safe_text(x.get("start")),
                "end": _json_safe_text(x.get("end")),
                "source": "chart_drag",
            }
            for x in drawn_tag_intervals
        ],
        "tag_intervals": [
            {
                "label": str(x.get("label", "")),
                "start": _json_safe_text(x.get("start")),
                "end": _json_safe_text(x.get("end")),
                "source": x.get("source", "manual"),
            }
            for x in tag_intervals
        ],
        "agent_intervals": [
            {
                "label": str(x.get("label", "")),
                "start": _json_safe_text(x.get("start")),
                "end": _json_safe_text(x.get("end")),
                "severity": x.get("severity"),
                "source": x.get("source"),
            }
            for x in agent_intervals
        ],
        "manual_activity_tags": [
            {
                "label": str(x.get("label", "")),
                "start": _json_safe_text(x.get("start")),
                "end": _json_safe_text(x.get("end")),
            }
            for x in manual_activity_tags
        ],
        "summary": {
            "tag_count": int(summary.get("tag_count", 0)),
            "agent_count": int(summary.get("agent_count", 0)),
            "overlap_count": int(summary.get("overlap_count", 0)),
            "score_percent": round(float(summary.get("score_percent", 0.0)), 1),
            "acceptance_threshold_percent": float(
                summary.get("acceptance_threshold_percent", ACCEPTANCE_THRESHOLD_PERCENT)
            ),
            "accepted": bool(summary.get("accepted", False)),
        },
        "activity_validation_summary": {
            "tag_count": int(activity_validation_summary.get("tag_count", 0)),
            "matched_count": int(activity_validation_summary.get("matched_count", 0)),
            "score_percent": round(
                float(activity_validation_summary.get("score_percent", 0.0)),
                1,
            ),
            "min_overlap_percent": float(
                activity_validation_summary.get(
                    "min_overlap_percent",
                    ACTIVITY_VALIDATION_MIN_OVERLAP_PERCENT,
                )
            ),
        },
    }

    json_text = json.dumps(payload, indent=2)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "label", "start", "end", "severity", "source"])

    for item in tag_intervals:
        writer.writerow(
            [
                "tag",
                item.get("label", ""),
                _json_safe_text(item.get("start")),
                _json_safe_text(item.get("end")),
                "",
                item.get("source", "manual"),
            ]
        )

    for item in agent_intervals:
        writer.writerow(
            [
                "agent",
                item.get("label", ""),
                _json_safe_text(item.get("start")),
                _json_safe_text(item.get("end")),
                item.get("severity", ""),
                item.get("source", ""),
            ]
        )

    for item in manual_activity_tags:
        writer.writerow(
            [
                "activity_tag",
                item.get("label", ""),
                _json_safe_text(item.get("start")),
                _json_safe_text(item.get("end")),
                "",
                "manual_activity_validation",
            ]
        )

    return json_text, output.getvalue()

def _format_datetime_text(value) -> str:
    """
    Convert datetime-like values to the exact string format used by text_input.
    """
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _clamp_timestamp(value, min_value, max_value):
    """
    Clamp datetime-like value into the available dataframe time range.
    """
    ts = pd.Timestamp(value)
    min_ts = pd.Timestamp(min_value)
    max_ts = pd.Timestamp(max_value)

    if pd.isna(ts):
        return min_ts

    if ts < min_ts:
        return min_ts

    if ts > max_ts:
        return max_ts

    return ts


def _safe_slider_interval_state(
    key: str,
    min_value,
    max_value,
    default_start=None,
    default_end=None,
):
    """
    Repair a datetime range slider session_state value before creating st.slider.

    Streamlit crashes if an existing slider state is outside min_value/max_value.
    This function clamps stale uploaded/restored values before the widget is created.
    """
    min_ts = pd.Timestamp(min_value)
    max_ts = pd.Timestamp(max_value)

    if default_start is None:
        default_start = min_ts

    if default_end is None:
        default_end = max_ts

    default_start = _clamp_timestamp(default_start, min_ts, max_ts)
    default_end = _clamp_timestamp(default_end, min_ts, max_ts)

    if default_end <= default_start:
        default_start = min_ts
        default_end = max_ts

    current = st.session_state.get(key, (default_start.to_pydatetime(), default_end.to_pydatetime()))

    try:
        if isinstance(current, (list, tuple)) and len(current) == 2:
            start_ts = _clamp_timestamp(current[0], min_ts, max_ts)
            end_ts = _clamp_timestamp(current[1], min_ts, max_ts)
        else:
            start_ts = default_start
            end_ts = default_end
    except Exception:
        start_ts = default_start
        end_ts = default_end

    if end_ts <= start_ts:
        start_ts = min_ts
        end_ts = max_ts

    st.session_state[key] = (
        start_ts.to_pydatetime(),
        end_ts.to_pydatetime(),
    )

    return st.session_state[key]

def _parse_uploaded_datetime(value, fallback=None):
    """
    Safely parse datetime values from uploaded JSON.
    """
    try:
        parsed = pd.to_datetime(value, errors="raise")
        if pd.isna(parsed):
            raise ValueError("Parsed datetime is NaT")
        return parsed
    except Exception:
        if fallback is not None:
            return pd.Timestamp(fallback)
        return pd.NaT


def _safe_uploaded_label(value, fallback: str) -> str:
    """
    Make sure labels restored into text_input are always strings.
    """
    if value is None:
        return fallback

    text = str(value).strip()
    return text if text else fallback





def _normalize_section_tag(item: dict, fallback_label: str = "Saved Tag", t_min=None, t_max=None) -> dict | None:
    """
    Normalize any saved section-level tag without forcing it into the current
    12-hour window. These tags are stored by absolute timestamp and are later
    filtered for display only when they overlap the active window.
    """
    if not isinstance(item, dict):
        return None

    start_raw = (
        item.get("start")
        or item.get("Tag Start")
        or item.get("tag_start")
        or item.get("start_time")
    )
    end_raw = (
        item.get("end")
        or item.get("Tag End")
        or item.get("tag_end")
        or item.get("end_time")
    )

    start_ts = _parse_uploaded_datetime(start_raw)
    end_ts = _parse_uploaded_datetime(end_raw)

    if pd.isna(start_ts) or pd.isna(end_ts):
        return None

    if t_min is not None and t_max is not None:
        start_ts = _clamp_timestamp(start_ts, t_min, t_max)
        end_ts = _clamp_timestamp(end_ts, t_min, t_max)

    if pd.Timestamp(end_ts) <= pd.Timestamp(start_ts):
        return None

    label = (
        item.get("label")
        or item.get("Tag Label")
        or item.get("tag_label")
        or fallback_label
    )
    label = str(label).strip() or fallback_label

    source = str(item.get("source", "manual") or "manual").strip() or "manual"

    return {
        "label": label,
        "start": _format_datetime_text(start_ts),
        "end": _format_datetime_text(end_ts),
        "source": source,
    }

def _normalize_restored_visual_tag(item: dict, fallback_label: str = "Visual Tag", t_min=None, t_max=None) -> dict | None:
    """
    Normalize a saved or browser-created chart-drawn tag.

    This accepts several schemas so old saved dashboard JSON files can still be
    restored. The returned item uses the same shape as normal Track 4 tagger
    intervals: label/start/end/source.
    """
    if not isinstance(item, dict):
        return None

    start_raw = (
        item.get("start")
        or item.get("Tag Start")
        or item.get("tag_start")
        or item.get("start_time")
    )
    end_raw = (
        item.get("end")
        or item.get("Tag End")
        or item.get("tag_end")
        or item.get("end_time")
    )

    start_ts = _parse_uploaded_datetime(start_raw)
    end_ts = _parse_uploaded_datetime(end_raw)

    if pd.isna(start_ts) or pd.isna(end_ts):
        return None

    if t_min is not None and t_max is not None:
        start_ts = _clamp_timestamp(start_ts, t_min, t_max)
        end_ts = _clamp_timestamp(end_ts, t_min, t_max)

    if pd.Timestamp(end_ts) <= pd.Timestamp(start_ts):
        return None

    label = (
        item.get("label")
        or item.get("Tag Label")
        or item.get("tag_label")
        or fallback_label
    )
    label = str(label).strip() or fallback_label

    return {
        "label": label,
        "start": _format_datetime_text(start_ts),
        "end": _format_datetime_text(end_ts),
        "source": "chart_drag",
    }


def _visual_tag_identity(item: dict) -> tuple[str, str, str]:
    """Stable identity used to remove duplicate restored/drawn tags."""
    if not isinstance(item, dict):
        return ("", "", "")

    try:
        start = _format_datetime_text(item.get("start"))
    except Exception:
        start = str(item.get("start", ""))

    try:
        end = _format_datetime_text(item.get("end"))
    except Exception:
        end = str(item.get("end", ""))

    # Time is the important identity. Keep label in the tuple only as a fallback
    # when two intentionally separate tags have exactly the same interval.
    return (str(item.get("label", "")), start, end)


def _deduplicate_visual_tags(items: list[dict]) -> list[dict]:
    """Remove duplicate chart-drawn tags while preserving order."""
    seen = set()
    out: list[dict] = []

    for item in items or []:
        if not isinstance(item, dict):
            continue
        ident = _visual_tag_identity(item)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(item)

    return out


def _interval_overlaps_window(item: dict, t_min, t_max) -> bool:
    """Return True when a section-level tag overlaps the currently loaded window."""
    if not isinstance(item, dict):
        return False
    try:
        start = pd.Timestamp(item.get("start"))
        end = pd.Timestamp(item.get("end"))
        win_start = pd.Timestamp(t_min)
        win_end = pd.Timestamp(t_max)
    except Exception:
        return False
    if pd.isna(start) or pd.isna(end) or pd.isna(win_start) or pd.isna(win_end):
        return False
    if end <= start:
        return False
    return start < win_end and end > win_start


def _looks_like_chart_drag_tag(item: dict) -> bool:
    """
    Identify drawn tags inside older saved files.

    Some older JSON exports did not have a dedicated drawn_tag_intervals field,
    so this also recognizes labels such as Dragged Tag / Drawn Tag / Visual Tag.
    """
    if not isinstance(item, dict):
        return False

    source = str(item.get("source", "") or item.get("Tag Source", "")).strip().lower()
    label = str(item.get("label", "") or item.get("Tag Label", "")).strip().lower()

    if source in {"chart_drag", "visual", "visual_tag", "dragged", "browser_drag", "server_tagger"}:
        return True

    return (
        label.startswith("visual tag")
        or label.startswith("dragged tag")
        or label.startswith("drawn tag")
    )


def _extract_restorable_visual_tags(uploaded_data: dict, context_key: str, t_min=None, t_max=None) -> list[dict]:
    """
    Extract chart-drawn tags from new and old saved dashboard JSON files.

    The important bridge is: saved drawn tags must be restored into
    visual_tag_intervals_<context_key>. render_agent_controls() then adds them
    into tag_intervals, which is what Track 4 actually draws.
    """
    if not isinstance(uploaded_data, dict):
        return []

    candidates: list[dict] = []

    # New schema: dedicated drawn-tag rows.
    for idx, item in enumerate(uploaded_data.get("drawn_tag_intervals", []) or [], start=1):
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label=f"Drawn Tag {idx}",
            t_min=None,
            t_max=None,
        )
        if normalized:
            candidates.append(normalized)

    # Widget-state fallback: visual tags saved under their context-specific key.
    widget_state = (uploaded_data.get("dashboard_state", {}) or {}).get("widget_state", {}) or {}
    visual_key = f"visual_tag_intervals_{context_key}"
    for idx, item in enumerate(widget_state.get(visual_key, []) or [], start=1):
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label=f"Drawn Tag {idx}",
            t_min=None,
            t_max=None,
        )
        if normalized:
            candidates.append(normalized)

    # Compatibility: drawn tags may be mixed into tag_intervals.
    for idx, item in enumerate(uploaded_data.get("tag_intervals", []) or [], start=1):
        if not _looks_like_chart_drag_tag(item):
            continue
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label=f"Drawn Tag {idx}",
            t_min=None,
            t_max=None,
        )
        if normalized:
            candidates.append(normalized)

    # Last-resort compatibility: saved hit-results rows may contain tag times.
    for idx, item in enumerate(uploaded_data.get("hit_results", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        source = str(item.get("Tag Source", "") or item.get("source", "")).strip().lower()
        label = str(item.get("Tag Label", "") or item.get("label", "")).strip().lower()
        if source and source not in {"chart_drag", "visual", "visual_tag", "dragged", "browser_drag", "server_tagger"}:
            continue
        if not source and not (
            label.startswith("visual tag")
            or label.startswith("dragged tag")
            or label.startswith("drawn tag")
        ):
            continue
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label=f"Drawn Tag {idx}",
            t_min=None,
            t_max=None,
        )
        if normalized:
            candidates.append(normalized)

    return _deduplicate_visual_tags(candidates)


def apply_visual_tag_from_query_params(
    context_key: str,
    t_min,
    t_max,
    max_tags: int = 50,
):
    """
    Read chart-drawn tags from URL query params and store them in Streamlit
    session_state as visual_tag_intervals_<context_key>.

    This version supports two paths:
    1. visual_tags_payload: a JSON list sent by the chart's Save drawn tags button.
    2. visual_tag_start / visual_tag_end: backward-compatible single-tag path.

    Important stability fix:
    It does not call st.rerun() after clearing query params. The state is updated
    before render_agent_controls(), so the same run can continue and draw the tags.
    This avoids the browser freeze/rerun loop that happened when a tag was drawn.
    """
    params = st.query_params

    if params.get("visual_tag_context") != context_key:
        return

    nonce = str(params.get("visual_tag_nonce") or "")
    nonce_key = f"_last_visual_tag_nonce_{context_key}"
    if nonce and st.session_state.get(nonce_key) == nonce:
        try:
            st.query_params.clear()
        except Exception:
            pass
        return

    raw_items: list[dict] = []

    payload_text = params.get("visual_tags_payload")
    if payload_text:
        try:
            parsed = json.loads(payload_text)
            if isinstance(parsed, list):
                raw_items.extend([item for item in parsed if isinstance(item, dict)])
            elif isinstance(parsed, dict):
                raw_items.append(parsed)
        except Exception as e:
            st.warning(f"Could not read drawn-tag payload from chart: {e}")

    start_text = params.get("visual_tag_start")
    end_text = params.get("visual_tag_end")
    if start_text and end_text:
        raw_items.append(
            {
                "label": "Drawn Tag",
                "start": start_text,
                "end": end_text,
                "source": "chart_drag",
            }
        )

    if not raw_items:
        try:
            st.query_params.clear()
        except Exception:
            pass
        return

    visual_key = f"visual_tag_intervals_{context_key}"
    existing = st.session_state.get(visual_key, [])
    if not isinstance(existing, list):
        existing = []

    combined = []
    for item in existing:
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label="Drawn Tag",
            t_min=None,
            t_max=None,
        )
        if normalized:
            combined.append(normalized)

    next_index = len(combined) + 1
    for item in raw_items:
        normalized = _normalize_restored_visual_tag(
            item,
            fallback_label=f"Drawn Tag {next_index}",
            t_min=None,
            t_max=None,
        )
        if normalized:
            # Preserve a browser label such as Dragged Tag 1, but mark source safely.
            normalized["source"] = "chart_drag"
            combined.append(normalized)
            next_index += 1

    st.session_state[visual_key] = _deduplicate_visual_tags(combined)[-max_tags:]

    if nonce:
        st.session_state[nonce_key] = nonce

    try:
        st.query_params.clear()
    except Exception:
        pass



def _normalized_time_identity(start_value, end_value) -> tuple[str, str] | None:
    """Return normalized start/end text for comparing saved hit rows to saved tags."""
    try:
        start_ts = pd.Timestamp(start_value)
        end_ts = pd.Timestamp(end_value)
    except Exception:
        return None

    if pd.isna(start_ts) or pd.isna(end_ts) or end_ts <= start_ts:
        return None

    return (
        start_ts.strftime("%Y-%m-%d %H:%M:%S"),
        end_ts.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _filter_hit_result_rows_for_tags(hit_rows: list[dict], tag_intervals: list[dict]) -> list[dict]:
    """
    Keep only hit-result rows that correspond to saved drawn/tag intervals.

    This prevents old browser localStorage hit-history rows from being saved or
    restored when they are not present in the saved Track 4 tag set.
    """
    valid_tag_times = set()
    for tag in tag_intervals or []:
        if not isinstance(tag, dict):
            continue
        ident = _normalized_time_identity(tag.get("start"), tag.get("end"))
        if ident is not None:
            valid_tag_times.add(ident)

    if not valid_tag_times:
        return []

    filtered: list[dict] = []
    seen = set()

    for row in hit_rows or []:
        if not isinstance(row, dict):
            continue

        ident = _normalized_time_identity(row.get("tag_start"), row.get("tag_end"))
        if ident not in valid_tag_times:
            continue

        row_key = (
            str(row.get("well", "")),
            str(row.get("section", "")),
            str(row.get("tag_label", "")),
            ident[0],
            ident[1],
        )
        if row_key in seen:
            continue
        seen.add(row_key)
        filtered.append(row)

    filtered.sort(key=lambda r: str(r.get("tag_start", "")))
    return filtered

def _apply_loaded_review_to_state(
    uploaded_data: dict,
    context_key: str,
    t_min=None,
    t_max=None,
):
    """
    Load saved review JSON into Streamlit widget state.

    Rules:
    - text_input datetime keys receive strings.
    - slider interval keys receive tuple(datetime, datetime).
    - uploaded times are clamped to the current available data range when t_min/t_max are supplied.
    """

    min_ts = pd.Timestamp(t_min) if t_min is not None else None
    max_ts = pd.Timestamp(t_max) if t_max is not None else None

    # First restore the full dashboard widget state if this is a new full-save JSON.
    # Then the older tag/agent restore code below acts as backward compatibility.
    _restore_full_dashboard_state(
        uploaded_data=uploaded_data,
        context_key=context_key,
        t_min=t_min,
        t_max=t_max,
    )

    # Restore chart-drawn tags into the dedicated Streamlit state used by
    # render_agent_controls(). This is the missing bridge: the JSON may contain
    # drawn_tag_intervals, but Track 4 only visualizes tags that are included in
    # agent_cfg["tag_intervals"].
    restored_visual_tags = _extract_restorable_visual_tags(
        uploaded_data=uploaded_data,
        context_key=context_key,
        t_min=None,
        t_max=None,
    )

    section_level_tags = []
    saved_tag_candidates = []
    saved_tag_candidates.extend(uploaded_data.get("manual_tagger_intervals", []) or [])
    saved_tag_candidates.extend(uploaded_data.get("drawn_tag_intervals", []) or [])
    saved_tag_candidates.extend(uploaded_data.get("tag_intervals", []) or [])

    for idx, item in enumerate(saved_tag_candidates, start=1):
        normalized = _normalize_section_tag(item, fallback_label=f"Saved Tag {idx}")
        if normalized:
            section_level_tags.append(normalized)

    section_level_tags.extend(restored_visual_tags or [])

    if section_level_tags:
        st.session_state[f"visual_tag_intervals_{context_key}"] = _deduplicate_visual_tags(section_level_tags)

    # Restore browser Hit results from saved JSON, but keep only rows that
    # correspond to the saved Track 4 tags. Older saves/browser localStorage may
    # contain stale rows from tags that were already removed.
    saved_hit_results = uploaded_data.get("hit_results", []) or []
    if not saved_hit_results:
        saved_hit_results = (
            (uploaded_data.get("dashboard_state", {}) or {})
            .get("widget_state", {})
            .get(f"hit_result_history_{context_key}", [])
        )

    if isinstance(saved_hit_results, list):
        cleaned_hit_rows = _filter_hit_result_rows_for_tags(
            saved_hit_results,
            section_level_tags,
        )
        if cleaned_hit_rows:
            st.session_state[f"hit_result_history_{context_key}"] = cleaned_hit_rows
        else:
            st.session_state.pop(f"hit_result_history_{context_key}", None)

    def _maybe_clamp(ts):
        if pd.isna(ts):
            return ts
        if min_ts is not None and max_ts is not None:
            return _clamp_timestamp(ts, min_ts, max_ts)
        return pd.Timestamp(ts)

    def _valid_order(start_ts, end_ts):
        return not pd.isna(start_ts) and not pd.isna(end_ts) and pd.Timestamp(end_ts) > pd.Timestamp(start_ts)

    for i in range(1, 4):
        st.session_state[f"enable_tag_{i}_{context_key}"] = False
        st.session_state[f"enable_activity_tag_{i}_{context_key}"] = False

    st.session_state[f"enable_agent_1_{context_key}"] = False

    # ------------------------------------------------------------
    # Normal sidebar tagger lane: text_input start/end keys need strings.
    # Keep chart-drawn tags out of these three sidebar slots; drawn tags are
    # restored through visual_tag_intervals_<context_key> and drawn directly in
    # Track 4.
    # ------------------------------------------------------------
    # Keep restored manual/saved tags as section-level absolute timestamps in
    # visual_tag_intervals_<context_key>. Do not force them into the three sidebar
    # text boxes, because those boxes are bounded by the current 12-hour window.
    manual_tags_to_restore = []

    for i, tag in enumerate((manual_tags_to_restore or [])[:3], start=1):
        start_ts = _maybe_clamp(_parse_uploaded_datetime(tag.get("start")))
        end_ts = _maybe_clamp(_parse_uploaded_datetime(tag.get("end")))

        if not _valid_order(start_ts, end_ts):
            continue

        st.session_state[f"enable_tag_{i}_{context_key}"] = True
        st.session_state[f"tag_label_{i}_{context_key}"] = _safe_uploaded_label(
            tag.get("label"),
            f"Observation {i}",
        )

        st.session_state[f"tag_start_{i}_{context_key}"] = _format_datetime_text(start_ts)
        st.session_state[f"tag_end_{i}_{context_key}"] = _format_datetime_text(end_ts)

    # ------------------------------------------------------------
    # Manual activity validation tags: text_input start/end keys need strings.
    # ------------------------------------------------------------
    for i, tag in enumerate(uploaded_data.get("manual_activity_tags", [])[:3], start=1):
        start_ts = _maybe_clamp(_parse_uploaded_datetime(tag.get("start")))
        end_ts = _maybe_clamp(_parse_uploaded_datetime(tag.get("end")))

        if not _valid_order(start_ts, end_ts):
            continue

        st.session_state[f"enable_activity_tag_{i}_{context_key}"] = True
        st.session_state[f"activity_tag_label_{i}_{context_key}"] = _safe_uploaded_label(
            tag.get("label"),
            "Drilling",
        )

        st.session_state[f"activity_tag_start_{i}_{context_key}"] = _format_datetime_text(start_ts)
        st.session_state[f"activity_tag_end_{i}_{context_key}"] = _format_datetime_text(end_ts)

        old_interval_key = f"activity_tag_interval_{i}_{context_key}"
        if old_interval_key in st.session_state:
            try:
                del st.session_state[old_interval_key]
            except Exception:
                pass

    # ------------------------------------------------------------
    # Manual agent interval: slider interval key needs tuple(datetime, datetime).
    # Clamp it so Streamlit slider cannot crash.
    # ------------------------------------------------------------
    loaded_agents = uploaded_data.get("agent_intervals", [])

    if loaded_agents:
        agent = loaded_agents[0]

        start_ts = _maybe_clamp(_parse_uploaded_datetime(agent.get("start")))
        end_ts = _maybe_clamp(_parse_uploaded_datetime(agent.get("end")))

        if _valid_order(start_ts, end_ts):
            st.session_state[f"enable_agent_1_{context_key}"] = True
            st.session_state[f"agent_label_1_{context_key}"] = _safe_uploaded_label(
                agent.get("label"),
                "Hit 1",
            )
            st.session_state[f"agent_interval_1_{context_key}"] = (
                start_ts.to_pydatetime(),
                end_ts.to_pydatetime(),
            )

            severity = agent.get("severity", "Medium")
            if severity not in ["Low", "Medium", "High"]:
                severity = "Medium"

            st.session_state[f"agent_severity_1_{context_key}"] = severity

def render_review_loader_before_well_selector() -> dict | None:
    """
    Load a saved review JSON before well/section selection.

    This lets the app restore selected_well and selected_sections if the JSON
    contains dashboard_context.

    Important:
    The uploaded payload is returned only once after the forced rerun.
    Returning it on every rerun can repeatedly re-arm restore logic and create
    a Streamlit rerun loop.
    """
    with st.sidebar:
        st.subheader("Load Dashboard Session")

        uploaded_review = st.file_uploader(
            "Drag/drop saved dashboard here",
            type=["json"],
            key="review_upload_global_before_well",
        )

        if uploaded_review is None:
            return None

        loaded_review_flag_key = f"_loaded_global_review_once_{uploaded_review.name}"
        consumed_key = f"_loaded_global_review_consumed_{uploaded_review.name}"

        # After the initial upload-triggered rerun, return the payload exactly once.
        if st.session_state.get(loaded_review_flag_key, False):
            if not st.session_state.get(consumed_key, False):
                st.session_state[consumed_key] = True
                return st.session_state.get("_loaded_review_payload_global")

            return None

        try:
            uploaded_data = json.load(uploaded_review)

            st.session_state["_loaded_review_payload_global"] = uploaded_data
            st.session_state[loaded_review_flag_key] = True
            st.session_state[consumed_key] = False

            context = uploaded_data.get("dashboard_context", {})
            selected_well = context.get("selected_well")
            selected_sections = context.get("selected_sections", [])

            if selected_well:
                st.session_state["selected_well"] = selected_well

            if selected_well and selected_sections:
                st.session_state[f"selected_sections_{selected_well}"] = [
                    str(x) for x in selected_sections
                ]

            st.success("Saved review JSON loaded.")
            st.rerun()

        except Exception as e:
            st.error(f"Could not read saved review JSON: {e}")
            return None

        return None
    


def render_well_section_selector(sections_by_well: dict):
    with st.sidebar:
        st.subheader("Well")

        wells = sorted(sections_by_well.keys())

        saved_well = st.session_state.get("selected_well")
        if saved_well not in wells:
            saved_well = wells[0] if wells else None
            st.session_state["selected_well"] = saved_well

        selected_well = st.selectbox(
            "Select Well",
            options=wells,
            index=wells.index(saved_well) if saved_well in wells else 0,
            key="selected_well",
        )

        available_sections = sorted(sections_by_well.get(selected_well, []), key=float)

        section_key = f"selected_sections_{selected_well}"

        existing_sections = st.session_state.get(section_key, [])
        existing_sections = [
            str(sec)
            for sec in existing_sections
            if str(sec) in available_sections
        ]

        if existing_sections:
            st.session_state[section_key] = existing_sections

        st.subheader("Section")
        selected_sections = st.multiselect(
            "Select Section(s)",
            options=available_sections,
            default=existing_sections,
            format_func=lambda s: f'{s}"',
            key=section_key,
        )

    return selected_well, selected_sections




def _clear_plot_selection_for_window_change(context_key: str, plot_context_key: str):
    """
    When the user moves to another 12-hour window, remove the previous curve
    choices so the new window starts with no plotted parameters. This does not
    touch section-level tags or agent settings.
    """
    active_key = f"_active_plot_context_{context_key}"
    previous_plot_context = st.session_state.get(active_key)

    if previous_plot_context == plot_context_key:
        return

    prefixes_to_clear = (
        "track_params_",
        "max_override_",
        "curve_source_",
    )

    for key in list(st.session_state.keys()):
        key_text = str(key)
        if previous_plot_context and (
            key_text.endswith(f"_{previous_plot_context}")
            or f"_{previous_plot_context}_" in key_text
        ):
            if key_text.startswith(prefixes_to_clear):
                try:
                    del st.session_state[key]
                except Exception:
                    pass

    st.session_state[active_key] = plot_context_key


def _build_time_window_info(
    time_df: pd.DataFrame,
    context_key: str,
    window_hours: int = 12,
):
    """
    Shared fixed-window calculation.

    This does not render Previous/Next buttons. It only decides which 12-hour
    window is active and returns the same structure app.py already expects.
    """
    if time_df.empty or not isinstance(time_df.index, pd.DatetimeIndex):
        st.sidebar.warning("No time data found for the selected section.")
        return None

    t_min = pd.Timestamp(time_df.index.min())
    t_max = pd.Timestamp(time_df.index.max())

    if pd.isna(t_min) or pd.isna(t_max) or t_max <= t_min:
        st.sidebar.warning("No valid time range found for the selected section.")
        return None

    window_delta = pd.Timedelta(hours=int(window_hours))
    total_sec = max((t_max - t_min).total_seconds(), 1.0)
    n_windows = max(1, int(total_sec // window_delta.total_seconds()))
    if t_min + n_windows * window_delta < t_max:
        n_windows += 1

    index_key = f"window_index_{context_key}"
    if index_key not in st.session_state:
        st.session_state[index_key] = 0

    st.session_state[index_key] = max(
        0,
        min(int(st.session_state.get(index_key, 0)), n_windows - 1),
    )

    current_index = int(st.session_state[index_key])
    selected_start = t_min + current_index * window_delta
    selected_end = min(selected_start + window_delta, t_max)
    rows_in_window = len(time_df.loc[selected_start:selected_end])

    # Keep plot selections stable across windows. The active window still controls
    # which rows are loaded, but the sidebar parameter choices remain section-level.
    plot_context_key = context_key

    # Browser-only chart state is window-specific, but still unique to this
    # Streamlit session so old localStorage tags do not reappear as false hits.
    browser_session_key = "_browser_session_uuid"
    if browser_session_key not in st.session_state:
        st.session_state[browser_session_key] = uuid.uuid4().hex

    # Keep browser-drawn tags and Hit results shared across all 12-hour
    # windows of the current well/section during this Streamlit session.
    # Do NOT include the window index here. Including the window made the Hit
    # results table reset when browsing windows. A fresh dashboard start still
    # gets a new browser_session_uuid, so the table starts empty from scratch.
    st.session_state["_drag_tag_browser_session_token"] = (
        f"{st.session_state[browser_session_key]}_{context_key}"
    )

    return {
        "start": selected_start,
        "end": selected_end,
        "index": int(st.session_state[index_key]),
        "count": int(n_windows),
        "hours": int(window_hours),
        "plot_context_key": plot_context_key,
        "rows_in_window": int(rows_in_window),
        "index_key": index_key,
    }


def render_window_pager(
    time_df: pd.DataFrame,
    context_key: str,
    window_hours: int = 12,
):
    """
    Fixed 12-hour backend window browser.

    This function now renders only the compact window status in the sidebar.
    The Previous/Next controls are rendered below the chart by
    render_window_footer_controls(), so users can move to the next/previous
    window after they reach the end of the four tracks.
    """
    window_info = _build_time_window_info(
        time_df=time_df,
        context_key=context_key,
        window_hours=window_hours,
    )

    if window_info is None:
        return None

    with st.sidebar:
        st.subheader("Time Window")
        st.caption("Fixed 12-hour windows. Only the active window is loaded and plotted.")
        st.caption(
            f"Active window: {window_info['index'] + 1} / {window_info['count']}"
        )
        st.caption(
            f"{window_info['start'].strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{window_info['end'].strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{window_info['rows_in_window']:,} timestamps"
        )

    return window_info


def render_window_footer_controls(
    window_info: dict | None,
    context_key: str,
):
    """
    Render Previous/Next time-window controls below the chart.

    The backend behavior is unchanged:
    - only the active 12-hour window is loaded,
    - selected parameters stay section-level,
    - manual/chart-drawn tags and hit results remain section-level.
    """
    if not window_info:
        return

    current_index = int(window_info.get("index", 0))
    n_windows = int(window_info.get("count", 1))
    if n_windows <= 1:
        return

    st.markdown("---")
    st.markdown("#### Continue time-window review")

    st.caption(
        f"Current 12-hour window {current_index + 1} / {n_windows}: "
        f"{pd.Timestamp(window_info['start']).strftime('%Y-%m-%d %H:%M:%S')} → "
        f"{pd.Timestamp(window_info['end']).strftime('%Y-%m-%d %H:%M:%S')}"
    )

    col_prev, col_mid, col_next = st.columns([1.2, 2.2, 1.2])

    index_key = str(window_info.get("index_key") or f"window_index_{context_key}")

    with col_prev:
        if st.button(
            "← Previous 12-hour window",
            key=f"bottom_window_prev_{context_key}",
            disabled=current_index <= 0,
            use_container_width=True,
        ):
            st.session_state[index_key] = max(0, current_index - 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.rerun()

    with col_mid:
        st.markdown(
            f"""
            <div style="
                text-align:center;
                padding: 0.45rem 0.75rem;
                border: 1px solid #ddd;
                border-radius: 0.5rem;
                background: #fafafa;
                font-size: 0.92rem;
            ">
                Window {current_index + 1} of {n_windows}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_next:
        if st.button(
            "Next 12-hour window →",
            key=f"bottom_window_next_{context_key}",
            disabled=current_index >= n_windows - 1,
            use_container_width=True,
        ):
            st.session_state[index_key] = min(n_windows - 1, current_index + 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.rerun()

def render_track_parameter_selector(available_param_labels: list[str], context_key: str):
    with st.sidebar:
        st.subheader("Track Parameters (Tracks 1–3)")

        track_params = []
        for i in range(3):
            selected = st.multiselect(
                f"Track {i + 1} parameters (max {MAX_PARAMS_PER_TRACK})",
                options=available_param_labels,
                default=[],
                max_selections=MAX_PARAMS_PER_TRACK,
                key=f"track_params_{i + 1}_{context_key}",
                format_func=lambda p: PARAMETER_DISPLAY_NAMES.get(p, p),
            )
            track_params.append(selected)

    return track_params


def render_parameter_range_controls(selected_labels: list[str], context_key: str) -> dict[str, tuple[float, float]]:
    overrides = {}

    with st.sidebar:
        st.subheader("Parameter Scale Limits")
        st.caption("You can change the maximum value of the selected parameters here.")

        for label in selected_labels:
            meta = PARAMETER_CATALOG.get(label, {})
            logical_min = float(meta.get("logical_min", 0.0))
            logical_max = float(meta.get("logical_max", 100.0))
            unit = meta.get("unit", "")

            max_value = st.number_input(
                f"{label} max ({unit})" if unit else f"{label} max",
                min_value=float(logical_min),
                value=float(logical_max),
                step=max(1.0, logical_max / 20 if logical_max > 0 else 1.0),
                key=f"max_override_{label}_{context_key}",
            )
            overrides[label] = (logical_min, float(max_value))

    return overrides


def render_time_filter(df, context_key: str):
    """
    Precise second-level time filter.

    Behavior:
    - Text boxes show full data range by default.
    - User edits start/end time.
    - Pressing Enter in either text box reruns Streamlit.
    - The returned time_range immediately reflects the typed values.
    - No Apply button is needed.
    """

    def _format_dt(value) -> str:
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def _parse_dt(text: str):
        return pd.to_datetime(
            str(text).strip(),
            format="%Y-%m-%d %H:%M:%S",
            errors="raise",
        )

    with st.sidebar:
        st.subheader("Time Filter")

        if df.empty:
            st.warning("No data available for time filtering.")
            return None, 0.0

        default_start = pd.Timestamp(df.index.min())
        default_end = pd.Timestamp(df.index.max())

        exact_start_key = f"exact_time_start_{context_key}"
        exact_end_key = f"exact_time_end_{context_key}"
        data_signature_key = f"time_filter_data_signature_{context_key}"

        current_data_signature = (
            _format_dt(default_start),
            _format_dt(default_end),
            len(df),
        )

        previous_data_signature = st.session_state.get(data_signature_key)

        # Reset default text values when well/section/data range changes.
        # This must happen before the text_input widgets are created.
        if previous_data_signature != current_data_signature:
            st.session_state[data_signature_key] = current_data_signature

            # Do not overwrite a restored JSON time filter.
            if exact_start_key not in st.session_state:
                st.session_state[exact_start_key] = _format_dt(default_start)

            if exact_end_key not in st.session_state:
                st.session_state[exact_end_key] = _format_dt(default_end)
        # Repair missing or empty widget state before creating widgets.
        if not str(st.session_state.get(exact_start_key, "")).strip():
            st.session_state[exact_start_key] = _format_dt(default_start)

        if not str(st.session_state.get(exact_end_key, "")).strip():
            st.session_state[exact_end_key] = _format_dt(default_end)

        if st.button("Reset time filter", key=f"reset_time_{context_key}"):
            st.session_state[exact_start_key] = _format_dt(default_start)
            st.session_state[exact_end_key] = _format_dt(default_end)
            st.rerun()

        st.markdown("**Precise time window**")
        st.caption(
            "Type exact start and end times, then press Enter. "
            "Format: YYYY-MM-DD HH:mm:ss"
        )

        start_text = st.text_input(
            "Precise time window start",
            key=exact_start_key,
            help="Use format: YYYY-MM-DD HH:mm:ss, for example 2005-12-24 01:11:47",
        )

        end_text = st.text_input(
            "Precise time window end",
            key=exact_end_key,
            help="Use format: YYYY-MM-DD HH:mm:ss, for example 2005-12-24 01:16:39",
        )

        selected_start = default_start
        selected_end = default_end

        try:
            parsed_start = _parse_dt(start_text)
            parsed_end = _parse_dt(end_text)

            valid_time_window = True

            if parsed_start < default_start:
                st.warning(
                    f"Start time is before available data. Minimum is {_format_dt(default_start)}."
                )
                valid_time_window = False

            if parsed_end > default_end:
                st.warning(
                    f"End time is after available data. Maximum is {_format_dt(default_end)}."
                )
                valid_time_window = False

            if parsed_end <= parsed_start:
                st.warning("End time must be after start time.")
                valid_time_window = False

            if valid_time_window:
                selected_start = parsed_start
                selected_end = parsed_end

        except Exception:
            st.error(
                "Invalid time format. Use exactly: YYYY-MM-DD HH:mm:ss "
                "for example 2005-12-24 01:11:47"
            )

        time_range = (
            selected_start.to_pydatetime(),
            selected_end.to_pydatetime(),
        )

        total_sec = (default_end - default_start).total_seconds()
        selected_sec = (selected_end - selected_start).total_seconds()

        zoom_percent = 100.0 - (selected_sec / total_sec * 100.0) if total_sec > 0 else 0.0
        zoom_percent = max(0.0, min(100.0, zoom_percent))

        filtered_records = len(df.loc[selected_start:selected_end])

        #st.metric("Records in selected window", f"{filtered_records:,}")
        #st.metric("Zoom", f"{zoom_percent:.0f}%")

        # st.caption(
        #     f"Available range: {_format_dt(default_start)} → {_format_dt(default_end)}"
        # )

        # st.caption(
        #     f"Applied range: {_format_dt(selected_start)} → {_format_dt(selected_end)}"
        # )

    return time_range, zoom_percent

    

def render_plot_marker_controls(context_key: str) -> str:
    with st.sidebar:
        st.subheader("Plot Marker Display")

        marker_display = st.selectbox(
            "Default curve style",
            options=MARKER_DISPLAY_OPTIONS,
            index=MARKER_DISPLAY_OPTIONS.index(DEFAULT_MARKER_DISPLAY),
            key=f"marker_display_{context_key}",
            help=(
                "Use 'Lines only' for clean normal viewing. "
                "Use the buttons above the chart to switch dots on/off without changing the time filter."
            ),
        )

        st.caption(
            "Dots are independent of the sidebar time filter. "
            "Inside the chart, use the buttons above the plot to switch between clean lines and dotted lines."
        )

    return marker_display


def _default_activity_ui(enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "selected_activity": "MakingConnection",
        "config": ActivityConfig(),
        "manual_activity_tags": [],
    }


def _default_symptom_ui(enabled: bool = False) -> dict:
    return {
        "enabled": enabled,
        "selected_symptom": "TRQErratic",
        "config": SymptomConfig(),
    }

def _safe_datetime_input(
    label: str,
    key: str,
    default_value,
    min_value,
    max_value,
):
    """
    Text-based datetime input with seconds.

    Expected format:
    YYYY-MM-DD HH:mm:ss

    This version protects Streamlit text_input from bad session-state types.
    text_input requires its widget state to be a string.
    """

    def _format_dt(value) -> str:
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    default_ts = pd.Timestamp(default_value)
    min_ts = pd.Timestamp(min_value)
    max_ts = pd.Timestamp(max_value)

    current_value = st.session_state.get(key, default_ts)

    try:
        current_ts = pd.Timestamp(current_value)
    except Exception:
        current_ts = default_ts

    if current_ts < min_ts or current_ts > max_ts or pd.isna(current_ts):
        current_ts = default_ts

    default_text = _format_dt(current_ts)

    # Critical repair:
    # If this key already exists from old uploaded JSON logic as a datetime,
    # convert it to string before creating st.text_input.
    existing_value = st.session_state.get(key, default_text)

    if not isinstance(existing_value, str):
        try:
            st.session_state[key] = _format_dt(existing_value)
        except Exception:
            st.session_state[key] = default_text

    elif not existing_value.strip():
        st.session_state[key] = default_text

    text_value = st.text_input(
        label,
        value=default_text,
        key=key,
        help="Use format: YYYY-MM-DD HH:mm:ss, for example 2005-12-24 01:11:39",
    )

    try:
        parsed_value = pd.to_datetime(
            str(text_value).strip(),
            format="%Y-%m-%d %H:%M:%S",
            errors="raise",
        )
    except Exception:
        st.error(
            f"Invalid datetime for '{label}'. Please use format YYYY-MM-DD HH:mm:ss."
        )
        return current_ts.to_pydatetime()

    if parsed_value < min_ts:
        st.warning(f"{label} is before the available data range. Using minimum time.")
        return min_ts.to_pydatetime()

    if parsed_value > max_ts:
        st.warning(f"{label} is after the available data range. Using maximum time.")
        return max_ts.to_pydatetime()

    return parsed_value.to_pydatetime()

def render_manual_activity_validation_tags(
    context_key: str,
    t_min,
    t_max,
    duration_options: dict | None = None,
) -> list[dict]:
    """
    Manual activity validation tags.

    These use the same start/end datetime style as the normal Tagger lane:
    YYYY-MM-DD HH:mm:ss

    Removed:
    - Activity Tag x segment length
    - Activity Tag x center time
    """

    st.markdown("**Manual activity validation tags**")
    st.caption("Use these to validate the automatic Activity Agent intervals.")

    manual_activity_tags = []

    activity_options = [
        "MakingConnection",
        "Drilling",
        "Reaming",
        "TrippingIn",
        "TrippingOut",
        "Conditioning",
        "Circulating",
        "Other",
    ]

    for i in range(1, 4):
        enabled = st.checkbox(
            f"Enable Activity Tag {i}",
            value=False,
            key=f"enable_activity_tag_{i}_{context_key}",
        )

        if not enabled:
            continue

        activity_label = st.selectbox(
            f"Activity Tag {i} label",
            options=activity_options,
            index=1,
            key=f"activity_tag_label_{i}_{context_key}",
        )

        activity_tag_start = _safe_datetime_input(
            label=f"Activity Tag {i} start time — year / month / day / hour / minute / second",
            key=f"activity_tag_start_{i}_{context_key}",
            default_value=t_min,
            min_value=t_min,
            max_value=t_max,
        )

        activity_tag_end = _safe_datetime_input(
            label=f"Activity Tag {i} end time — year / month / day / hour / minute / second",
            key=f"activity_tag_end_{i}_{context_key}",
            default_value=min(t_max, t_min + timedelta(minutes=30)),
            min_value=t_min,
            max_value=t_max,
        )

        if pd.Timestamp(activity_tag_end) <= pd.Timestamp(activity_tag_start):
            st.warning(
                f"Activity Tag {i}: end time must be after start time. "
                "This activity validation tag is not added."
            )
            continue

        st.caption(f"Activity tag interval: {activity_tag_start} → {activity_tag_end}")

        manual_activity_tags.append(
            {
                "label": activity_label,
                "start": activity_tag_start,
                "end": activity_tag_end,
            }
        )

    return manual_activity_tags

def render_activity_agent_controls(context_key: str, df=None, parent=None):
    container = parent if parent is not None else st.sidebar

    with container:
        st.subheader("Activity Agent Settings")

        enabled = st.checkbox(
            "Enable automatic activity recognition",
            value=True,
            key=f"enable_activity_agent_{context_key}",
        )

        selected_activity = st.selectbox(
            "Activity shown in Track 4 agent lane",
            options=[
                "All activities",
                "MakingConnection",
                "Drilling",
                "Reaming",
                "TrippingIn",
                "TrippingOut",
                "Conditioning",
                "Circulating",
                "Other",
            ],
            index=1,
            key=f"selected_activity_lane_{context_key}",
        )

        manual_activity_tags = []

        if df is not None and not df.empty:
            t_min = df.index.min().to_pydatetime()
            t_max = df.index.max().to_pydatetime()

            manual_activity_tags = render_manual_activity_validation_tags(
                context_key=context_key,
                t_min=t_min,
                t_max=t_max,
            )
        else:
            st.warning("No data available for manual activity validation tags.")

        with st.expander("Activity thresholds — VT document definitions", expanded=False):
            short_window = st.number_input(
                "Short causal window (samples)",
                min_value=3,
                max_value=21,
                value=10,
                key=f"act_short_window_{context_key}",
            )
            medium_window = st.number_input(
                "Medium causal window (samples)",
                min_value=6,
                max_value=300,
                value=100,
                key=f"act_medium_window_{context_key}",
            )
            min_interval_samples = st.number_input(
                "Minimum interval length (samples)",
                min_value=2,
                max_value=30,
                value=6,
                key=f"act_min_interval_{context_key}",
            )
            gap_fill_samples = st.number_input(
                "Gap fill (samples)",
                min_value=0,
                max_value=10,
                value=2,
                key=f"act_gap_fill_{context_key}",
            )

            pump_on_threshold = st.number_input(
                "Pump on threshold (lpm)",
                value=100.0,
                key=f"act_pump_thr_{context_key}",
            )
            rpm_on_threshold = st.number_input(
                "RPM on threshold",
                value=10.0,
                key=f"act_rpm_thr_{context_key}",
            )
            rpm_zero_threshold = st.number_input(
                "RPM zero threshold",
                value=1.0,
                key=f"act_rpm_zero_thr_{context_key}",
            )
            rpm_low_threshold = st.number_input(
                "RPM low/slow threshold",
                value=30.0,
                key=f"act_rpm_low_thr_{context_key}",
            )

            wob_zero_band = st.number_input(
                "WOB zero band",
                value=0.5,
                key=f"act_wob_zero_{context_key}",
            )
            wob_drilling_min = st.number_input(
                "WOB drilling minimum",
                value=0.1,
                key=f"act_wob_drill_{context_key}",
            )

            drilling_depth_step_min = st.number_input(
                "Drilling: well depth increase per step (m)",
                value=0.01,
                format="%.4f",
                key=f"act_drill_depth_step_{context_key}",
            )
            drilling_depth_gap_max = st.number_input(
                "Drilling: BitDepth-WellDepth max gap (m)",
                value=0.05,
                format="%.4f",
                key=f"act_drill_gap_{context_key}",
            )

            reaming_flow_min = st.number_input(
                "Reaming: MFI minimum (lpm)",
                value=100.0,
                key=f"act_ream_flow_{context_key}",
            )
            reaming_rpm_min = st.number_input(
                "Reaming: RPM minimum",
                value=10.0,
                key=f"act_ream_rpm_{context_key}",
            )
            reaming_depth_step_max = st.number_input(
                "Reaming: max slow depth change per step (m)",
                value=0.30,
                key=f"act_ream_depth_step_max_{context_key}",
            )

            tripping_flow_max = st.number_input(
                "Tripping: MFI max (lpm)",
                value=1000.0,
                key=f"act_trip_flow_{context_key}",
            )
            tripping_rpm_max = st.number_input(
                "Tripping: RPM max",
                value=1.0,
                key=f"act_trip_rpm_{context_key}",
            )
            tripping_max_consecutive_static_samples = st.number_input(
                "Tripping: max consecutive no-motion samples",
                min_value=1,
                max_value=10,
                value=3,
                key=f"act_trip_static_{context_key}",
            )

            conditioning_depth_gap_max = st.number_input(
                "Conditioning: WellDepth-BitDepth max gap (m)",
                value=100.0,
                key=f"act_cond_gap_{context_key}",
            )

            connection_depth_gap_max = st.number_input(
                "MakingCnx: BitDepth-WellDepth max gap (m)",
                value=10.0,
                key=f"act_conn_gap_{context_key}",
            )
            connection_depth_constant_band = st.number_input(
                "MakingCnx: depth constant tolerance (m)",
                value=0.05,
                format="%.4f",
                key=f"act_conn_depth_const_{context_key}",
            )
            connection_block_travel_threshold = st.number_input(
                "MakingCnx: BPOS travel threshold (m)",
                value=2.0,
                key=f"act_conn_move_{context_key}",
            )
            hkl_dead_weight_stability_band = st.number_input(
                "MakingCnx: HKL dead-weight stability band",
                value=3.0,
                key=f"act_conn_hkl_stable_{context_key}",
            )

            movement_threshold = st.number_input(
                "BPOS movement threshold",
                value=0.3,
                key=f"act_move_thr_{context_key}",
            )

        cfg = ActivityConfig(
            short_window=int(short_window),
            medium_window=int(medium_window),
            min_interval_samples=int(min_interval_samples),
            gap_fill_samples=int(gap_fill_samples),
            pump_on_threshold=float(pump_on_threshold),
            rpm_on_threshold=float(rpm_on_threshold),
            rpm_zero_threshold=float(rpm_zero_threshold),
            rpm_low_threshold=float(rpm_low_threshold),
            wob_zero_band=float(wob_zero_band),
            wob_drilling_min=float(wob_drilling_min),
            drilling_depth_step_min=float(drilling_depth_step_min),
            drilling_depth_gap_max=float(drilling_depth_gap_max),
            reaming_flow_min=float(reaming_flow_min),
            reaming_rpm_min=float(reaming_rpm_min),
            reaming_depth_step_max=float(reaming_depth_step_max),
            tripping_flow_max=float(tripping_flow_max),
            tripping_rpm_max=float(tripping_rpm_max),
            tripping_max_consecutive_static_samples=int(tripping_max_consecutive_static_samples),
            conditioning_depth_gap_max=float(conditioning_depth_gap_max),
            connection_depth_gap_max=float(connection_depth_gap_max),
            connection_depth_constant_band=float(connection_depth_constant_band),
            connection_block_travel_threshold=float(connection_block_travel_threshold),
            hkl_dead_weight_stability_band=float(hkl_dead_weight_stability_band),
            movement_threshold=float(movement_threshold),
        )

    return {
        "enabled": enabled,
        "selected_activity": selected_activity,
        "config": cfg,
        "manual_activity_tags": manual_activity_tags,
    }

def render_symptom_agent_controls(context_key: str, parent=None):
    container = parent if parent is not None else st.sidebar

    with container:
        st.subheader("Symptom Agent Settings")

        enabled = st.checkbox(
            "Enable symptom agents",
            value=True,
            key=f"enable_symptom_agents_{context_key}",
        )

        symptom_options = ["OpenHoleLength", "TRQSpike", "TRQErratic", "PSpike", "OverPull", "TookWeight"]
        symptom_key = f"selected_symptom_lane_{context_key}"
        if st.session_state.get(symptom_key) not in symptom_options:
            st.session_state[symptom_key] = "TRQErratic"

        selected_symptom = st.selectbox(
            "Symptom shown in Track 4 agent lane",
            options=symptom_options,
            index=symptom_options.index(st.session_state.get(symptom_key, "TRQErratic")),
            key=symptom_key,
        )

        with st.expander("Symptom thresholds — VT document definitions", expanded=False):
            casing_depth_fallback = st.number_input(
                "OpenHoleLength casing depth fallback (m, 0 = use Casing Depth column only)",
                value=0.0,
                min_value=0.0,
                key=f"sym_ohl_casing_depth_{context_key}",
            )
            open_hole_length_threshold_1 = st.number_input(
                "OpenHoleLength severity 1 (m)",
                value=500.0,
                key=f"sym_ohl_1_{context_key}",
            )
            open_hole_length_threshold_2 = st.number_input(
                "OpenHoleLength severity 2 (m)",
                value=750.0,
                key=f"sym_ohl_2_{context_key}",
            )

            trq_baseline_window = st.number_input(
                "TRQSpike mean-long window (preceding samples)",
                min_value=10,
                max_value=300,
                value=60,
                key=f"sym_trq_window_{context_key}",
            )
            trq_spike_ratio_level_1 = st.number_input(
                "TRQSpike level 1 ratio",
                value=1.25,
                key=f"sym_trq_l1_{context_key}",
            )
            trq_spike_ratio_level_2 = st.number_input(
                "TRQSpike level 2 ratio",
                value=1.40,
                key=f"sym_trq_l2_{context_key}",
            )

            trq_spike_zscore_min = st.number_input(
                "TRQSpike minimum z-value",
                value=2.9,
                key=f"sym_trq_zscore_min_{context_key}",
                help="Minimum TRQ z-value required for normal TRQSpike detection.",
            )

            trq_spike_extreme_ratio = st.number_input(
                "TRQSpike extreme ratio",
                value=1.80,
                key=f"sym_trq_extreme_ratio_{context_key}",
                help="If TRQ ratio exceeds this value, the spike can pass even without the normal z-shape rule.",
            )

            trq_erratic_mean_long_window = st.number_input(
                "TRQErratic mean-long window",
                min_value=20,
                max_value=300,
                value=100,
                key=f"sym_trqerr_window_{context_key}",
            )

            trq_erratic_ratio_level_1 = st.number_input(
                "TRQErratic amplitude ratio",
                value=1.10,
                key=f"sym_trqerr_ratio_{context_key}",
            )

            trq_erratic_min_cycles = st.number_input(
                "TRQErratic minimum cycles",
                min_value=2,
                max_value=20,
                value=3,
                key=f"sym_trqerr_min_cycles_{context_key}",
            )

            trq_erratic_high_cycles = st.number_input(
                "TRQErratic high severity cycles",
                min_value=5,
                max_value=100,
                value=20,
                key=f"sym_trqerr_high_cycles_{context_key}",
            )

            pspike_baseline_window = st.number_input(
                "PSpike baseline window",
                min_value=5,
                max_value=100,
                value=20,
                key=f"sym_ps_window_{context_key}",
            )
            pspike_threshold_normal = st.number_input(
                "PSpike threshold normal",
                value=5.0,
                key=f"sym_ps_norm_{context_key}",
            )
            pspike_threshold_motor_on = st.number_input(
                "PSpike threshold motor-on",
                value=7.0,
                key=f"sym_ps_motor_{context_key}",
            )
            pspike_gap_fill_samples = st.number_input(
                "PSpike gap fill (samples)",
                min_value=0,
                max_value=10,
                value=2,
                key=f"sym_ps_gap_{context_key}",
            )
            pspike_flow_delta_max = st.number_input(
                "PSpike max ΔMFI",
                value=50.0,
                key=f"sym_ps_dmfi_{context_key}",
            )
            pspike_rpm_delta_max = st.number_input(
                "PSpike max ΔRPM",
                value=3.0,
                key=f"sym_ps_drpm_{context_key}",
            )
            pspike_wob_delta_max = st.number_input(
                "PSpike max ΔWOB",
                value=0.5,
                key=f"sym_ps_dwob_{context_key}",
            )

            overpull_baseline_window = st.number_input(
                "OverPull HKL baseline window",
                min_value=5,
                max_value=200,
                value=20,
                key=f"sym_op_window_{context_key}",
            )
            overpull_threshold = st.number_input(
                "OverPull HKL increase threshold",
                value=6.0,
                key=f"sym_op_thr_{context_key}",
            )
            overpull_gap_fill_samples = st.number_input(
                "OverPull gap fill",
                min_value=0,
                max_value=10,
                value=2,
                key=f"sym_op_gap_{context_key}",
            )

            tookweight_baseline_window = st.number_input(
                "TookWeight HKL baseline window",
                min_value=5,
                max_value=200,
                value=20,
                key=f"sym_tw_window_{context_key}",
            )
            tookweight_threshold = st.number_input(
                "TookWeight HKL drop threshold",
                value=6.0,
                key=f"sym_tw_thr_{context_key}",
            )
            tookweight_gap_fill_samples = st.number_input(
                "TookWeight gap fill",
                min_value=0,
                max_value=10,
                value=2,
                key=f"sym_tw_gap_{context_key}",
            )

            hoisting_velocity_min = st.number_input(
                "Min hoisting velocity",
                value=0.15,
                key=f"sym_hoist_min_{context_key}",
            )
            hoisting_velocity_max = st.number_input(
                "Max hoisting velocity",
                value=1.5,
                key=f"sym_hoist_max_{context_key}",
            )

        cfg = SymptomConfig(
            casing_depth=None if float(casing_depth_fallback) <= 0 else float(casing_depth_fallback),
            open_hole_length_threshold_1=float(open_hole_length_threshold_1),
            open_hole_length_threshold_2=float(open_hole_length_threshold_2),

            trq_baseline_window=int(trq_baseline_window),
            trq_mean_long_window=int(trq_baseline_window),
            trq_spike_ratio_level_1=float(trq_spike_ratio_level_1),
            trq_spike_ratio_level_2=float(trq_spike_ratio_level_2),
            trq_spike_zscore_min=float(trq_spike_zscore_min),
            trq_spike_extreme_ratio=float(trq_spike_extreme_ratio),

            pspike_baseline_window=int(pspike_baseline_window),
            pspike_threshold_normal=float(pspike_threshold_normal),
            pspike_threshold_motor_on=float(pspike_threshold_motor_on),
            pspike_gap_fill_samples=int(pspike_gap_fill_samples),
            pspike_flow_delta_max=float(pspike_flow_delta_max),
            pspike_rpm_delta_max=float(pspike_rpm_delta_max),
            pspike_wob_delta_max=float(pspike_wob_delta_max),

            overpull_baseline_window=int(overpull_baseline_window),
            overpull_threshold=float(overpull_threshold),
            overpull_gap_fill_samples=int(overpull_gap_fill_samples),

            tookweight_baseline_window=int(tookweight_baseline_window),
            tookweight_threshold=float(tookweight_threshold),
            tookweight_gap_fill_samples=int(tookweight_gap_fill_samples),

            hoisting_velocity_min=float(hoisting_velocity_min),
            hoisting_velocity_max=float(hoisting_velocity_max),

            trq_erratic_mean_long_window=int(trq_erratic_mean_long_window),
            trq_erratic_ratio_level_1=float(trq_erratic_ratio_level_1),
            trq_erratic_min_cycles=int(trq_erratic_min_cycles),
            trq_erratic_high_cycles=int(trq_erratic_high_cycles),
        )

    return {
        "enabled": enabled,
        "selected_symptom": selected_symptom,
        "config": cfg,
    }

def build_manual_review_df(summary: dict) -> pd.DataFrame:
    rows = summary.get("tag_status_rows", [])
    if not rows:
        return pd.DataFrame(columns=["Tag", "Start", "End", "Status", "Overlap Start", "Overlap End"])

    return pd.DataFrame(
        [
            {
                "Tag": row["label"],
                "Start": row["start"],
                "End": row["end"],
                "Status": row["status"],
                "Overlap Start": row["overlap_start"],
                "Overlap End": row["overlap_end"],
            }
            for row in rows
        ]
    )


def build_activity_validation_df(activity_validation_summary: dict) -> pd.DataFrame:
    rows = activity_validation_summary.get("rows", [])
    if not rows:
        return pd.DataFrame(
            columns=[
                "Activity Tag",
                "Start",
                "End",
                "Status",
                "Matched Activity",
                "Overlap %",
                "Overlap Start",
                "Overlap End",
            ]
        )

    return pd.DataFrame(
        [
            {
                "Activity Tag": row["label"],
                "Start": row["start"],
                "End": row["end"],
                "Status": row["status"],
                "Matched Activity": row["matched_activity"],
                "Overlap %": round(row.get("overlap_percent", 0.0), 1),
                "Overlap Start": row["overlap_start"],
                "Overlap End": row["overlap_end"],
            }
            for row in rows
        ]
    )

def build_symptom_miss_reason_df(
    tag_intervals: list[dict],
    symptom_cfg: dict,
    activity_cfg: dict,
) -> pd.DataFrame:
    """
    Explain why the selected symptom agent did or did not hit each manual tag.

    Covers:
    - OpenHoleLength
    - TRQSpike
    - TRQErratic
    - PSpike
    - OverPull
    - TookWeight
    """

    columns = [
        "Tag",
        "Tag Start",
        "Tag End",
        "Selected Agent",
        "Matched?",
        "Activity In Tag",
        "Main Blocking Reason",
        "Details",
    ]

    if not tag_intervals:
        return pd.DataFrame(columns=columns)

    selected_symptom = symptom_cfg.get("selected_symptom", "")
    symptom_features = symptom_cfg.get("features", pd.DataFrame())
    symptom_intervals = symptom_cfg.get("intervals", [])
    cfg = symptom_cfg.get("config", SymptomConfig())

    activity_labels = activity_cfg.get("labels", pd.Series(dtype="object"))

    def _count_true(df: pd.DataFrame, col: str) -> int:
        if col not in df.columns:
            return 0
        return int(df[col].fillna(False).astype(bool).sum())

    def _max_value(df: pd.DataFrame, col: str):
        if col not in df.columns:
            return pd.NA
        return df[col].max()

    def _min_value(df: pd.DataFrame, col: str):
        if col not in df.columns:
            return pd.NA
        return df[col].min()

    def _fmt(value, decimals: int = 3) -> str:
        if pd.isna(value):
            return "NaN"
        try:
            return f"{float(value):.{decimals}f}"
        except Exception:
            return str(value)

    def _activity_counts_text(activity_window: pd.Series) -> str:
        if activity_window is None or activity_window.empty:
            return "No activity samples inside tag"

        activity_counts = activity_window.value_counts(dropna=False)
        return ", ".join(
            [f"{str(label)}={int(count)}" for label, count in activity_counts.items()]
        )

    rows = []

    for tag in tag_intervals:
        tag_start = pd.Timestamp(tag["start"])
        tag_end = pd.Timestamp(tag["end"])
        tag_label = tag.get("label", "")

        matched = False
        for hit in symptom_intervals:
            ov = interval_overlap(tag_start, tag_end, hit["start"], hit["end"])
            if ov is not None:
                matched = True
                break

        activity_window = pd.Series(dtype="object")
        activity_counts_text = "No activity labels available"

        if activity_labels is not None and not activity_labels.empty:
            activity_window = activity_labels.loc[tag_start:tag_end]
            activity_counts_text = _activity_counts_text(activity_window)

        if matched:
            rows.append(
                {
                    "Tag": tag_label,
                    "Tag Start": tag_start,
                    "Tag End": tag_end,
                    "Selected Agent": selected_symptom,
                    "Matched?": "Yes",
                    "Activity In Tag": activity_counts_text,
                    "Main Blocking Reason": "Matched",
                    "Details": "The selected symptom agent created at least one interval overlapping this tag.",
                }
            )
            continue

        if symptom_features is None or symptom_features.empty:
            rows.append(
                {
                    "Tag": tag_label,
                    "Tag Start": tag_start,
                    "Tag End": tag_end,
                    "Selected Agent": selected_symptom,
                    "Matched?": "No",
                    "Activity In Tag": activity_counts_text,
                    "Main Blocking Reason": "No symptom features",
                    "Details": (
                        "The selected symptom agent did not produce debug features. "
                        "Check that the symptom agent is enabled and the required columns are available."
                    ),
                }
            )
            continue

        feature_window = symptom_features.loc[tag_start:tag_end]

        if feature_window.empty:
            rows.append(
                {
                    "Tag": tag_label,
                    "Tag Start": tag_start,
                    "Tag End": tag_end,
                    "Selected Agent": selected_symptom,
                    "Matched?": "No",
                    "Activity In Tag": activity_counts_text,
                    "Main Blocking Reason": "No data in tag window",
                    "Details": "No rows exist inside this tag window after the current time filter.",
                }
            )
            continue

        details = []
        main_reason = "Condition blocked"

        # ----------------------------------------------------
        # OpenHoleLength
        # ----------------------------------------------------
        if selected_symptom == "OpenHoleLength":
            max_ohl = _max_value(feature_window, "open_hole_length")
            max_well_depth = _max_value(feature_window, "well_depth")
            min_casing_depth = _min_value(feature_window, "casing_depth")
            lvl1_count = _count_true(feature_window, "open_hole_lvl1_mask")
            lvl2_count = _count_true(feature_window, "open_hole_lvl2_mask")

            if pd.isna(max_ohl):
                main_reason = "Missing OpenHoleLength inputs"
                details.append("Open-hole length could not be calculated. Check Well Depth and Casing Depth.")
            elif max_ohl <= cfg.open_hole_length_threshold_1:
                main_reason = "Open-hole length below threshold"
                details.append(
                    f"max open_hole_length={_fmt(max_ohl, 2)} m, "
                    f"required > {cfg.open_hole_length_threshold_1:.2f} m for Low severity."
                )
            else:
                main_reason = "Crossing/interval logic blocked"
                details.append(
                    f"Open-hole length exceeded a threshold in the tag window "
                    f"(Low samples={lvl1_count}, High samples={lvl2_count}), "
                    "but no first-crossing interval overlapped this tag. "
                    "This can happen if the first crossing happened before the tag start."
                )

            details.append(
                f"max well_depth={_fmt(max_well_depth, 2)} m; "
                f"min casing_depth={_fmt(min_casing_depth, 2)} m."
            )

        # ----------------------------------------------------
        # TRQSpike
        # ----------------------------------------------------
        elif selected_symptom == "TRQSpike":
            context_count = _count_true(feature_window, "context_mask")
            rpm_on_count = _count_true(feature_window, "rpm_on")
            rpm_stable_count = _count_true(feature_window, "rpm_stable")
            started_low_count = _count_true(feature_window, "started_low")
            spike_gate_count = _count_true(feature_window, "spike_gate")
            lvl1_count = _count_true(feature_window, "lvl1_mask")
            lvl2_count = _count_true(feature_window, "lvl2_mask")

            max_ratio = _max_value(feature_window, "trq_ratio")
            max_z = _max_value(feature_window, "trq_zscore")

            if context_count == 0:
                main_reason = "Activity/RPM context blocked"
                details.append(
                    "TRQSpike is only allowed when RPM is on, RPM is stable, "
                    "and Activity Agent says Drilling or Reaming."
                )
                details.append(f"rpm_on samples={rpm_on_count}; rpm_stable samples={rpm_stable_count}.")
            elif pd.isna(max_ratio) or max_ratio <= cfg.trq_spike_ratio_level_1:
                main_reason = "Torque ratio below threshold"
                details.append(
                    f"max trq_ratio={_fmt(max_ratio)}, "
                    f"required > {cfg.trq_spike_ratio_level_1:.2f}."
                )
            elif spike_gate_count == 0:
                main_reason = "Spike shape blocked"
                details.append(
                    f"max trq_zscore={_fmt(max_z)}, required > {cfg.trq_spike_zscore_min:.2f}; "
                    f"started_low samples={started_low_count}; "
                    f"extreme ratio threshold={cfg.trq_spike_extreme_ratio:.2f}."
                )
            elif lvl1_count == 0 and lvl2_count == 0:
                main_reason = "Severity mask blocked"
                details.append(
                    "Context and spike shape were possible, but no Low/High severity TRQSpike mask "
                    "formed inside the tag window."
                )
            else:
                main_reason = "Interval continuity/min-samples blocked"
                details.append(
                    f"TRQSpike mask samples existed in the tag window "
                    f"(Low={lvl1_count}, High={lvl2_count}), but no final interval overlapped the tag."
                )

            details.append(f"max trq_ratio={_fmt(max_ratio)}; max trq_zscore={_fmt(max_z)}.")

        # ----------------------------------------------------
        # TRQErratic
        # ----------------------------------------------------
        elif selected_symptom == "TRQErratic":
            context_count = _count_true(feature_window, "context_mask")
            rpm_stable_count = _count_true(feature_window, "rpm_stable")
            lvl1_count = _count_true(feature_window, "lvl1_mask")
            lvl2_count = _count_true(feature_window, "lvl2_mask")

            max_ratio = _max_value(feature_window, "trq_ratio")
            max_cycles = _max_value(feature_window, "trq_cycle_count")

            if context_count == 0:
                main_reason = "Activity context blocked"
                details.append("TRQErratic is only allowed during Drilling or Reaming.")
            elif rpm_stable_count == 0:
                main_reason = "RPM stability blocked"
                details.append("rpm_stable was never True inside the tag window.")
            elif pd.isna(max_ratio) or max_ratio <= cfg.trq_erratic_ratio_level_1:
                main_reason = "Torque amplitude below threshold"
                details.append(
                    f"max trq_ratio={_fmt(max_ratio)}, "
                    f"required > {cfg.trq_erratic_ratio_level_1:.2f}."
                )
            elif pd.isna(max_cycles) or max_cycles < cfg.trq_erratic_min_cycles:
                main_reason = "Not enough torque cycles"
                details.append(
                    f"max trq_cycle_count={_fmt(max_cycles, 0)}, "
                    f"required >= {cfg.trq_erratic_min_cycles}."
                )
            elif lvl1_count == 0 and lvl2_count == 0:
                main_reason = "Severity mask blocked"
                details.append(
                    "The main TRQErratic conditions were close, but no Low/High mask formed."
                )
            else:
                main_reason = "Interval continuity/min-samples blocked"
                details.append(
                    f"TRQErratic mask samples existed in the tag window "
                    f"(Low={lvl1_count}, High={lvl2_count}), but no final interval overlapped the tag."
                )

            details.append(
                f"max trq_ratio={_fmt(max_ratio)}; "
                f"max trq_cycle_count={_fmt(max_cycles, 0)}."
            )

        # ----------------------------------------------------
        # PSpike
        # ----------------------------------------------------
        elif selected_symptom == "PSpike":
            context_count = _count_true(feature_window, "context_mask")
            stable_flow_count = _count_true(feature_window, "stable_flow_mask")
            stable_rpm_count = _count_true(feature_window, "stable_rpm_mask")
            stable_wob_count = _count_true(feature_window, "stable_wob_mask")
            stable_count = _count_true(feature_window, "stable_mask")
            spp_stable_count = _count_true(feature_window, "spp_stable_before_spike")
            normal_count = _count_true(feature_window, "normal_mask")
            motor_count = _count_true(feature_window, "motor_mask")
            combined_count = _count_true(feature_window, "combined_mask")

            max_spp_delta = _max_value(feature_window, "spp_delta")
            motor_on_count = _count_true(feature_window, "mud_motor_on")

            if context_count == 0:
                main_reason = "Activity context blocked"
                details.append("PSpike is only allowed during Drilling or Reaming.")
            elif stable_count == 0:
                main_reason = "Stable drilling conditions blocked"
                details.append(
                    "PSpike requires stable MFI, RPM, and WOB before the pressure spike."
                )
                details.append(
                    f"stable_flow samples={stable_flow_count}; "
                    f"stable_rpm samples={stable_rpm_count}; "
                    f"stable_wob samples={stable_wob_count}."
                )
            elif spp_stable_count == 0:
                main_reason = "SPP baseline stability blocked"
                details.append(
                    "SPP was not stable enough before the spike. "
                    f"Required SPP stability band={cfg.pspike_spp_stability_band:.2f}."
                )
            elif pd.isna(max_spp_delta):
                main_reason = "SPP delta unavailable"
                details.append("spp_delta was NaN. Check SPP availability and baseline calculation.")
            elif normal_count == 0 and motor_count == 0:
                main_reason = "Pressure increase below threshold"
                details.append(
                    f"max spp_delta={_fmt(max_spp_delta, 2)}; "
                    f"normal threshold>{cfg.pspike_threshold_normal:.2f}; "
                    f"motor-on threshold>{cfg.pspike_threshold_motor_on:.2f}; "
                    f"motor_on samples={motor_on_count}."
                )
            elif combined_count == 0:
                main_reason = "Gap-fill/final mask blocked"
                details.append(
                    "Normal or motor-on PSpike condition appeared possible, but the combined final mask did not form."
                )
            else:
                main_reason = "Interval continuity/min-samples blocked"
                details.append(
                    f"PSpike final mask samples existed in the tag window "
                    f"(combined samples={combined_count}), but no final interval overlapped the tag."
                )

            details.append(f"max spp_delta={_fmt(max_spp_delta, 2)}.")

        # ----------------------------------------------------
        # OverPull
        # ----------------------------------------------------
        elif selected_symptom == "OverPull":
            context_count = _count_true(feature_window, "context_mask")
            move_count = _count_true(feature_window, "move_mask")
            velocity_count = _count_true(feature_window, "velocity_ok")
            raw_count = _count_true(feature_window, "raw_mask")
            combined_count = _count_true(feature_window, "combined_mask")

            max_hkl_delta = _max_value(feature_window, "hkl_delta")
            min_velocity = _min_value(feature_window, "hoisting_velocity")
            max_velocity = _max_value(feature_window, "hoisting_velocity")

            if context_count == 0:
                main_reason = "Activity context blocked"
                details.append("OverPull is only allowed during TrippingOut.")
            elif move_count == 0:
                main_reason = "Pipe movement blocked"
                details.append("OverPull requires pipe_moving_up=True.")
            elif velocity_count == 0:
                main_reason = "Hoisting velocity blocked"
                details.append(
                    f"Hoisting velocity must be between {cfg.hoisting_velocity_min:.2f} "
                    f"and {cfg.hoisting_velocity_max:.2f}."
                )
                details.append(
                    f"velocity range in tag={_fmt(min_velocity, 3)} to {_fmt(max_velocity, 3)}."
                )
            elif pd.isna(max_hkl_delta) or max_hkl_delta <= cfg.overpull_threshold:
                main_reason = "HKL increase below threshold"
                details.append(
                    f"max hkl_delta={_fmt(max_hkl_delta, 2)}, "
                    f"required > {cfg.overpull_threshold:.2f}."
                )
            elif raw_count == 0:
                main_reason = "Raw OverPull mask blocked"
                details.append(
                    "The individual conditions were close, but they did not become True at the same timestamp."
                )
            elif combined_count == 0:
                main_reason = "Gap-fill/final mask blocked"
                details.append("Raw OverPull appeared possible, but final combined mask did not form.")
            else:
                main_reason = "Interval continuity/min-samples blocked"
                details.append(
                    f"OverPull final mask samples existed in the tag window "
                    f"(combined samples={combined_count}), but no final interval overlapped the tag."
                )

            details.append(f"max hkl_delta={_fmt(max_hkl_delta, 2)}.")

        # ----------------------------------------------------
        # TookWeight
        # ----------------------------------------------------
        elif selected_symptom == "TookWeight":
            context_count = _count_true(feature_window, "context_mask")
            move_count = _count_true(feature_window, "move_mask")
            velocity_count = _count_true(feature_window, "velocity_ok")
            raw_count = _count_true(feature_window, "raw_mask")
            combined_count = _count_true(feature_window, "combined_mask")

            max_hkl_drop = _max_value(feature_window, "hkl_drop")
            min_velocity = _min_value(feature_window, "hoisting_velocity")
            max_velocity = _max_value(feature_window, "hoisting_velocity")

            if context_count == 0:
                main_reason = "Activity context blocked"
                details.append("TookWeight is only allowed during TrippingIn.")
            elif move_count == 0:
                main_reason = "Pipe movement blocked"
                details.append("TookWeight requires pipe_moving_down=True.")
            elif velocity_count == 0:
                main_reason = "Hoisting velocity blocked"
                details.append(
                    f"Hoisting velocity must be between {cfg.hoisting_velocity_min:.2f} "
                    f"and {cfg.hoisting_velocity_max:.2f}."
                )
                details.append(
                    f"velocity range in tag={_fmt(min_velocity, 3)} to {_fmt(max_velocity, 3)}."
                )
            elif pd.isna(max_hkl_drop) or max_hkl_drop <= cfg.tookweight_threshold:
                main_reason = "HKL drop below threshold"
                details.append(
                    f"max hkl_drop={_fmt(max_hkl_drop, 2)}, "
                    f"required > {cfg.tookweight_threshold:.2f}."
                )
            elif raw_count == 0:
                main_reason = "Raw TookWeight mask blocked"
                details.append(
                    "The individual conditions were close, but they did not become True at the same timestamp."
                )
            elif combined_count == 0:
                main_reason = "Gap-fill/final mask blocked"
                details.append("Raw TookWeight appeared possible, but final combined mask did not form.")
            else:
                main_reason = "Interval continuity/min-samples blocked"
                details.append(
                    f"TookWeight final mask samples existed in the tag window "
                    f"(combined samples={combined_count}), but no final interval overlapped the tag."
                )

            details.append(f"max hkl_drop={_fmt(max_hkl_drop, 2)}.")

        else:
            main_reason = "Unknown selected symptom"
            details.append(f"No miss-reason rules exist for selected symptom: {selected_symptom}.")

        rows.append(
            {
                "Tag": tag_label,
                "Tag Start": tag_start,
                "Tag End": tag_end,
                "Selected Agent": selected_symptom,
                "Matched?": "No",
                "Activity In Tag": activity_counts_text,
                "Main Blocking Reason": main_reason,
                "Details": " | ".join(details),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def build_symptom_hit_tag_comparison(
    tag_intervals: list[dict],
    symptom_cfg: dict,
    activity_cfg: dict,
    df_index=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    VT-style comparison of manual tags versus selected symptom-agent hits.

    Categories:
    - True Positive: manual tag overlaps an agent hit
    - False Negative: manual tag has no overlapping agent hit
    - False Positive: agent hit has no overlapping manual tag
    - True Negative: selected-window samples outside both tags and hits

    Important:
    A single long agent interval is allowed to match several manual tags.
    This is intentional for drilling review because one continuous symptom hit
    can cover several boss-defined tag intervals. The older one-to-one matching
    logic could incorrectly turn later tags into misses.

    Hit rate / recall:
    TP / (TP + FN)
    """

    selected_symptom = symptom_cfg.get("selected_symptom", "")
    symptom_features = symptom_cfg.get("features", pd.DataFrame())
    symptom_intervals = symptom_cfg.get("intervals", [])

    detail_columns = [
        "Category",
        "Selected Agent",
        "Tag",
        "Hit",
        "Severity",
        "Tag Start",
        "Tag End",
        "Hit Start",
        "Hit End",
        "Overlap Start",
        "Overlap End",
        "Overlap sec",
        "Max Ratio",
        "Max z-value",
        "Notes",
    ]

    summary_columns = ["Metric", "Value"]

    def _duration_sec(start, end) -> float:
        try:
            return max((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds(), 0.0)
        except Exception:
            return 0.0

    def _fmt_number(value, decimals: int = 3):
        if value is None or pd.isna(value):
            return pd.NA

        try:
            return round(float(value), decimals)
        except Exception:
            return pd.NA

    def _feature_stats(start, end) -> dict:
        stats = {
            "max_ratio": pd.NA,
            "max_z": pd.NA,
        }

        if symptom_features is None or symptom_features.empty:
            return stats

        try:
            window = symptom_features.loc[pd.Timestamp(start): pd.Timestamp(end)]
        except Exception:
            return stats

        if window.empty:
            return stats

        if "trq_ratio" in window.columns:
            stats["max_ratio"] = _fmt_number(
                pd.to_numeric(window["trq_ratio"], errors="coerce").max()
            )

        if "trq_zscore" in window.columns:
            stats["max_z"] = _fmt_number(
                pd.to_numeric(window["trq_zscore"], errors="coerce").max()
            )

        return stats

    rows = []

    # ------------------------------------------------------------
    # Match each manual tag to the best overlapping hit.
    # Do not consume the hit. One long hit may correctly cover several tags.
    # ------------------------------------------------------------
    for tag_i, tag in enumerate(tag_intervals):
        tag_start = pd.Timestamp(tag["start"])
        tag_end = pd.Timestamp(tag["end"])
        tag_label = str(tag.get("label", f"Tag {tag_i + 1}"))

        best_hit = None
        best_overlap = None
        best_overlap_sec = 0.0

        for hit in symptom_intervals:
            ov = interval_overlap(
                tag_start,
                tag_end,
                hit["start"],
                hit["end"],
            )

            if ov is None:
                continue

            ov_sec = _duration_sec(ov[0], ov[1])

            if ov_sec > best_overlap_sec:
                best_hit = hit
                best_overlap = ov
                best_overlap_sec = ov_sec

        if best_hit is not None:
            stats = _feature_stats(tag_start, tag_end)

            rows.append(
                {
                    "Category": "True Positive",
                    "Selected Agent": selected_symptom,
                    "Tag": tag_label,
                    "Hit": best_hit.get("label", selected_symptom),
                    "Severity": best_hit.get("severity", ""),
                    "Tag Start": tag_start,
                    "Tag End": tag_end,
                    "Hit Start": pd.Timestamp(best_hit["start"]),
                    "Hit End": pd.Timestamp(best_hit["end"]),
                    "Overlap Start": best_overlap[0],
                    "Overlap End": best_overlap[1],
                    "Overlap sec": round(best_overlap_sec, 3),
                    "Max Ratio": stats["max_ratio"],
                    "Max z-value": stats["max_z"],
                    "Notes": "Manual tag overlaps selected symptom-agent hit.",
                }
            )
        else:
            stats = _feature_stats(tag_start, tag_end)

            rows.append(
                {
                    "Category": "False Negative",
                    "Selected Agent": selected_symptom,
                    "Tag": tag_label,
                    "Hit": "",
                    "Severity": "",
                    "Tag Start": tag_start,
                    "Tag End": tag_end,
                    "Hit Start": pd.NaT,
                    "Hit End": pd.NaT,
                    "Overlap Start": pd.NaT,
                    "Overlap End": pd.NaT,
                    "Overlap sec": 0.0,
                    "Max Ratio": stats["max_ratio"],
                    "Max z-value": stats["max_z"],
                    "Notes": "Manual tag exists, but no selected symptom-agent hit overlaps it.",
                }
            )

    # ------------------------------------------------------------
    # Agent hits that overlap no manual tag are false positives.
    # ------------------------------------------------------------
    for hit in symptom_intervals:
        hit_start = pd.Timestamp(hit["start"])
        hit_end = pd.Timestamp(hit["end"])

        overlaps_any_tag = False

        for tag in tag_intervals:
            ov = interval_overlap(
                tag["start"],
                tag["end"],
                hit_start,
                hit_end,
            )

            if ov is not None:
                overlaps_any_tag = True
                break

        if overlaps_any_tag:
            continue

        stats = _feature_stats(hit_start, hit_end)

        rows.append(
            {
                "Category": "False Positive",
                "Selected Agent": selected_symptom,
                "Tag": "",
                "Hit": hit.get("label", selected_symptom),
                "Severity": hit.get("severity", ""),
                "Tag Start": pd.NaT,
                "Tag End": pd.NaT,
                "Hit Start": hit_start,
                "Hit End": hit_end,
                "Overlap Start": pd.NaT,
                "Overlap End": pd.NaT,
                "Overlap sec": 0.0,
                "Max Ratio": stats["max_ratio"],
                "Max z-value": stats["max_z"],
                "Notes": "Selected symptom-agent hit exists, but no manual tag overlaps it.",
            }
        )

    true_negative_samples = 0

    if df_index is not None and len(df_index) > 0:
        idx = pd.DatetimeIndex(df_index)

        tag_mask = pd.Series(False, index=idx)
        hit_mask = pd.Series(False, index=idx)

        for tag in tag_intervals:
            tag_mask.loc[
                (idx >= pd.Timestamp(tag["start"]))
                & (idx <= pd.Timestamp(tag["end"]))
            ] = True

        for hit in symptom_intervals:
            hit_mask.loc[
                (idx >= pd.Timestamp(hit["start"]))
                & (idx <= pd.Timestamp(hit["end"]))
            ] = True

        true_negative_samples = int((~tag_mask & ~hit_mask).sum())

        if true_negative_samples > 0:
            rows.append(
                {
                    "Category": "True Negative",
                    "Selected Agent": selected_symptom,
                    "Tag": "",
                    "Hit": "",
                    "Severity": "",
                    "Tag Start": pd.NaT,
                    "Tag End": pd.NaT,
                    "Hit Start": pd.NaT,
                    "Hit End": pd.NaT,
                    "Overlap Start": pd.NaT,
                    "Overlap End": pd.NaT,
                    "Overlap sec": pd.NA,
                    "Max Ratio": pd.NA,
                    "Max z-value": pd.NA,
                    "Notes": (
                        f"{true_negative_samples:,} selected-window samples are outside "
                        "both manual tags and selected symptom-agent hits."
                    ),
                }
            )

    detail_df = pd.DataFrame(rows, columns=detail_columns)

    tp = int((detail_df["Category"] == "True Positive").sum()) if not detail_df.empty else 0
    fn = int((detail_df["Category"] == "False Negative").sum()) if not detail_df.empty else 0
    fp = int((detail_df["Category"] == "False Positive").sum()) if not detail_df.empty else 0

    hit_rate = (tp / (tp + fn) * 100.0) if (tp + fn) > 0 else 0.0
    precision = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 0.0

    summary_rows = [
        {"Metric": "True Positives", "Value": tp},
        {"Metric": "False Negatives", "Value": fn},
        {"Metric": "False Positives", "Value": fp},
        {"Metric": "True Negative Samples", "Value": true_negative_samples},
        {"Metric": "Hit Rate / Recall %", "Value": round(hit_rate, 1)},
        {"Metric": "Precision %", "Value": round(precision, 1)},
    ]

    summary_df = pd.DataFrame(summary_rows, columns=summary_columns)

    return summary_df, detail_df

def build_professional_symptom_review_df(
    tag_intervals: list[dict],
    symptom_cfg: dict,
    activity_cfg: dict,
    df_index=None,
) -> pd.DataFrame:
    """
    Build one professional VT-style symptom review table.

    This merges:
    - summary metrics: TP, FN, FP, TN, hit rate, precision
    - detailed hit/tag comparison
    - selected details from the miss-reason table

    Output is one table suitable for dashboard review and export.
    """

    summary_df, comparison_df = build_symptom_hit_tag_comparison(
        tag_intervals=tag_intervals,
        symptom_cfg=symptom_cfg,
        activity_cfg=activity_cfg,
        df_index=df_index,
    )

    miss_reason_df = build_symptom_miss_reason_df(
        tag_intervals=tag_intervals,
        symptom_cfg=symptom_cfg,
        activity_cfg=activity_cfg,
    )

    selected_symptom = symptom_cfg.get("selected_symptom", "")

    columns = [
        "Review Result",
        "Selected Agent",
        "Manual Tag",
        "Agent Hit",
        "Severity",
        "Tag Start",
        "Tag End",
        "Hit Start",
        "Hit End",
        "Overlap Start",
        "Overlap End",
        "Overlap sec",
        "Overlap % of Tag",
        "Max Ratio",
        "Max z-value",
        "Activity In Tag",
        "Main Blocking Reason",
        "Details",
        "TP",
        "FN",
        "FP",
        "TN Samples",
        "Hit Rate / Recall %",
        "Precision %",
    ]

    if comparison_df.empty and summary_df.empty:
        return pd.DataFrame(columns=columns)

    def _metric_value(metric_name: str, default=0):
        if summary_df.empty:
            return default

        rows = summary_df[summary_df["Metric"].astype(str).eq(metric_name)]

        if rows.empty:
            return default

        return rows.iloc[0]["Value"]

    tp = _metric_value("True Positives", 0)
    fn = _metric_value("False Negatives", 0)
    fp = _metric_value("False Positives", 0)
    tn_samples = _metric_value("True Negative Samples", 0)
    hit_rate = _metric_value("Hit Rate / Recall %", 0.0)
    precision = _metric_value("Precision %", 0.0)

    def _safe_seconds(start, end) -> float:
        try:
            return max(
                (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds(),
                0.0,
            )
        except Exception:
            return 0.0
#to keep records
    def _safe_overlap_percent(row) -> object:
        if pd.isna(row.get("Tag Start")) or pd.isna(row.get("Tag End")):
            return pd.NA

        tag_seconds = _safe_seconds(row.get("Tag Start"), row.get("Tag End"))

        if tag_seconds <= 0:
            return pd.NA

        overlap_seconds = row.get("Overlap sec", 0.0)

        try:
            return round(float(overlap_seconds) / tag_seconds * 100.0, 1)
        except Exception:
            return pd.NA

    def _find_miss_reason(row) -> dict:
        if miss_reason_df.empty:
            return {
                "Activity In Tag": "",
                "Main Blocking Reason": "",
                "Details": row.get("Notes", ""),
            }

        tag = row.get("Tag", "")
        tag_start = row.get("Tag Start", pd.NaT)
        tag_end = row.get("Tag End", pd.NaT)

        if not tag or pd.isna(tag_start) or pd.isna(tag_end):
            return {
                "Activity In Tag": "",
                "Main Blocking Reason": "",
                "Details": row.get("Notes", ""),
            }

        candidates = miss_reason_df[
            miss_reason_df["Tag"].astype(str).eq(str(tag))
        ].copy()

        if candidates.empty:
            return {
                "Activity In Tag": "",
                "Main Blocking Reason": "",
                "Details": row.get("Notes", ""),
            }

        candidates["_start_diff"] = (
            pd.to_datetime(candidates["Tag Start"], errors="coerce")
            - pd.Timestamp(tag_start)
        ).abs()

        candidates["_end_diff"] = (
            pd.to_datetime(candidates["Tag End"], errors="coerce")
            - pd.Timestamp(tag_end)
        ).abs()

        candidates["_total_diff"] = candidates["_start_diff"] + candidates["_end_diff"]
        best = candidates.sort_values("_total_diff").iloc[0]

        return {
            "Activity In Tag": best.get("Activity In Tag", ""),
            "Main Blocking Reason": best.get("Main Blocking Reason", ""),
            "Details": best.get("Details", row.get("Notes", "")),
        }

    def _clean_result(category: str) -> str:
        if category == "True Positive":
            return "True Positive — tag hit"
        if category == "False Negative":
            return "False Negative — missed tag"
        if category == "False Positive":
            return "False Positive — extra hit"
        if category == "True Negative":
            return "True Negative — quiet background"
        return str(category)

    rows = []

    for _, row in comparison_df.iterrows():
        category = str(row.get("Category", ""))
        reason = _find_miss_reason(row)

        if category == "True Positive":
            main_reason = "Matched"
            details = (
                "Manual tag overlaps the selected symptom-agent hit. "
                f"{reason.get('Details', '')}"
            ).strip()
        elif category == "False Positive":
            main_reason = "Extra agent hit"
            details = row.get(
                "Notes",
                "Agent created a hit, but no manual tag overlaps it.",
            )
        elif category == "True Negative":
            main_reason = "No tag and no hit"
            details = row.get(
                "Notes",
                "Selected-window samples outside both manual tags and agent hits.",
            )
        else:
            main_reason = reason.get("Main Blocking Reason", "")
            details = reason.get("Details", row.get("Notes", ""))

        rows.append(
            {
                "Review Result": _clean_result(category),
                "Selected Agent": row.get("Selected Agent", selected_symptom),
                "Manual Tag": row.get("Tag", ""),
                "Agent Hit": row.get("Hit", ""),
                "Severity": row.get("Severity", ""),
                "Tag Start": row.get("Tag Start", pd.NaT),
                "Tag End": row.get("Tag End", pd.NaT),
                "Hit Start": row.get("Hit Start", pd.NaT),
                "Hit End": row.get("Hit End", pd.NaT),
                "Overlap Start": row.get("Overlap Start", pd.NaT),
                "Overlap End": row.get("Overlap End", pd.NaT),
                "Overlap sec": row.get("Overlap sec", pd.NA),
                "Overlap % of Tag": _safe_overlap_percent(row),
                "Max Ratio": row.get("Max Ratio", pd.NA),
                "Max z-value": row.get("Max z-value", pd.NA),
                "Activity In Tag": reason.get("Activity In Tag", ""),
                "Main Blocking Reason": main_reason,
                "Details": details,
                "TP": tp,
                "FN": fn,
                "FP": fp,
                "TN Samples": tn_samples,
                "Hit Rate / Recall %": hit_rate,
                "Precision %": precision,
            }
        )

    review_df = pd.DataFrame(rows, columns=columns)

    if review_df.empty:
        return review_df

    result_order = {
        "True Positive — tag hit": 1,
        "False Negative — missed tag": 2,
        "False Positive — extra hit": 3,
        "True Negative — quiet background": 4,
    }

    review_df["_sort_order"] = review_df["Review Result"].map(result_order).fillna(99)

    review_df = (
        review_df
        .sort_values(
            by=["_sort_order", "Tag Start", "Hit Start"],
            na_position="last",
        )
        .drop(columns=["_sort_order"])
        .reset_index(drop=True)
    )

    return review_df


def build_boss_symptom_presentation_df(
    tag_intervals: list[dict],
    symptom_cfg: dict,
    selected_well: str,
    selected_sections: tuple[str, ...] | list[str],
) -> pd.DataFrame:
    """
    Boss-friendly Presentation 1.

    One symptom/parameter at a time.
    Simple columns only:
    Tag Start | Tag End | Agent Start | Agent End | Result | Percent

    Important:
    A single long agent interval is allowed to match multiple manual tags.
    We do NOT consume/remove a hit after matching one tag. This avoids the
    previous problem where a real hit could become a miss only because another
    tag used the same agent interval first.
    """

    selected_symptom = symptom_cfg.get("selected_symptom", "")
    agent_intervals = symptom_cfg.get("intervals", [])

    section_label = ", ".join(f"{str(sec)} in" for sec in selected_sections)

    columns = [
        "Symptom",
        "Well",
        "Section",
        "Date",
        "Tag Start",
        "Tag End",
        "Agent Start",
        "Agent End",
        "Result",
        "Percent",
    ]

    def _duration_sec(start, end) -> float:
        try:
            return max((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds(), 0.0)
        except Exception:
            return 0.0

    def _time_text(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return pd.Timestamp(value).strftime("%H:%M:%S")

    def _date_text(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return pd.Timestamp(value).strftime("%d.%m.%Y")

    rows = []

    for tag_i, tag in enumerate(tag_intervals, start=1):
        tag_start = pd.Timestamp(tag["start"])
        tag_end = pd.Timestamp(tag["end"])
        tag_duration = _duration_sec(tag_start, tag_end)

        best_hit = None
        best_overlap = None
        best_overlap_sec = 0.0

        for hit in agent_intervals:
            ov = interval_overlap(
                tag_start,
                tag_end,
                hit["start"],
                hit["end"],
            )

            if ov is None:
                continue

            overlap_sec = _duration_sec(ov[0], ov[1])

            if overlap_sec > best_overlap_sec:
                best_hit = hit
                best_overlap = ov
                best_overlap_sec = overlap_sec

        percent = 0.0
        if tag_duration > 0:
            percent = best_overlap_sec / tag_duration * 100.0

        if best_hit is not None and best_overlap is not None:
            result = "Hit"
            agent_start = pd.Timestamp(best_hit["start"])
            agent_end = pd.Timestamp(best_hit["end"])
        else:
            result = "Miss"
            agent_start = pd.NaT
            agent_end = pd.NaT

        rows.append(
            {
                "Symptom": selected_symptom,
                "Well": selected_well,
                "Section": section_label,
                "Date": _date_text(tag_start),
                "Tag Start": _time_text(tag_start),
                "Tag End": _time_text(tag_end),
                "Agent Start": _time_text(agent_start),
                "Agent End": _time_text(agent_end),
                "Result": result,
                "Percent": f"{round(percent, 1)}% hit",
            }
        )

    # Add extra agent hits that do not overlap any tag.
    for hit in agent_intervals:
        hit_start = pd.Timestamp(hit["start"])
        hit_end = pd.Timestamp(hit["end"])

        overlaps_any_tag = False

        for tag in tag_intervals:
            ov = interval_overlap(
                tag["start"],
                tag["end"],
                hit_start,
                hit_end,
            )

            if ov is not None:
                overlaps_any_tag = True
                break

        if overlaps_any_tag:
            continue

        rows.append(
            {
                "Symptom": selected_symptom,
                "Well": selected_well,
                "Section": section_label,
                "Date": _date_text(hit_start),
                "Tag Start": "",
                "Tag End": "",
                "Agent Start": _time_text(hit_start),
                "Agent End": _time_text(hit_end),
                "Result": "Extra Agent Hit",
                "Percent": "",
            }
        )

    if not rows:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(rows, columns=columns)


def build_boss_symptom_presentation_excel(
    boss_df: pd.DataFrame,
    professional_df: pd.DataFrame | None = None,
) -> bytes:
    """
    Build Excel output with:
    Sheet 1: boss-friendly summary
    Sheet 2: detailed evaluation table
    """

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        boss_df.to_excel(
            writer,
            sheet_name="Presentation 1 Summary",
            index=False,
        )

        if professional_df is not None and not professional_df.empty:
            professional_df.to_excel(
                writer,
                sheet_name="Detailed Evaluation",
                index=False,
            )

    return output.getvalue()


def render_agent_controls(
    df,
    context_key: str,
    parent=None,
):
    container = parent if parent is not None else st.sidebar

    with container:
        st.subheader("Track 4 — Review and Agent Track")

        t_min = df.index.min().to_pydatetime()
        t_max = df.index.max().to_pydatetime()

        pending_payload_key = f"_pending_loaded_review_payload_{context_key}"

        if pending_payload_key in st.session_state:
            uploaded_data = st.session_state.pop(pending_payload_key)

            _apply_loaded_review_to_state(
                uploaded_data=uploaded_data,
                context_key=context_key,
                t_min=t_min,
                t_max=t_max,
            )

            st.session_state[f"_loaded_review_restored_done_{context_key}"] = True

            st.success("Saved review restored for this well/section.")

        review_mode_options = ["Stretched inspection", "Standard review"]
        review_mode_key = f"review_mode_{context_key}"
        if st.session_state.get(review_mode_key) not in review_mode_options:
            st.session_state[review_mode_key] = "Stretched inspection"

        review_mode = st.radio(
            "Review mode",
            options=review_mode_options,
            key=review_mode_key,
            horizontal=True,
            help=(
                "Stretched inspection gives a taller chart for detailed tagging. "
                "Standard review uses a more compact chart."
            ),
        )
        chart_height = 1400 if review_mode == "Stretched inspection" else 950

        show_reference_line = st.checkbox(
            "Show cross-track reference line",
            value=False,
            key=f"show_reference_line_{context_key}",
        )

        st.caption(
            "This adds a fixed horizontal line at one timestamp across Track 1, "
            "Track 2, Track 3, and Track 4. Use it to compare all curves and agent "
            "events at the same time."
        )

        reference_time = None
        if show_reference_line:
            reference_time = st.slider(
                "Reference time",
                min_value=t_min,
                max_value=t_max,
                value=t_min,
                format="YYYY-MM-DD HH:mm:ss",
                key=f"reference_time_{context_key}",
            )

        tag_intervals = []
        manual_agent_intervals = []

        # Safety cleanup: older versions had a button that could create a full
        # loaded-window tag automatically. Remove those stale default window tags
        # so the Hit results table starts empty until the user actually draws or
        # enables a real manual tag.
        for cleanup_i in range(1, 4):
            label_key = f"tag_label_{cleanup_i}_{context_key}"
            start_key = f"tag_start_{cleanup_i}_{context_key}"
            end_key = f"tag_end_{cleanup_i}_{context_key}"
            enable_key = f"enable_tag_{cleanup_i}_{context_key}"

            label_text = str(st.session_state.get(label_key, ""))
            start_text = str(st.session_state.get(start_key, ""))
            end_text = str(st.session_state.get(end_key, ""))

            # Remove stale/default full-window tags before any user action.
            # These are the cause of the false 12-hour Hit-results row.
            is_full_window_default_tag = (
                start_text == _format_datetime_text(t_min)
                and end_text == _format_datetime_text(t_max)
                and (
                    label_text.startswith("Window Tag")
                    or label_text.startswith("Observation")
                    or label_text.strip() == ""
                )
            )

            if is_full_window_default_tag:
                for cleanup_key in [enable_key, label_key, start_key, end_key]:
                    try:
                        del st.session_state[cleanup_key]
                    except Exception:
                        pass

        st.markdown("**Tagger lane**")
        st.caption(
            "Draw tags with the chart Tagging button, or enable a manual tag below. "
            "Saved tags remain section-level and only appear in windows they overlap."
        )

        st.caption(
            f"Current loaded window: {_format_datetime_text(t_min)} → {_format_datetime_text(t_max)}"
        )

        for i in range(1, 4):
            enabled = st.checkbox(
                f"Enable Tag {i}",
                value=False,
                key=f"enable_tag_{i}_{context_key}",
            )

            if enabled:
                label = st.text_input(
                    f"Tag {i} label",
                    value=f"Observation {i}",
                    key=f"tag_label_{i}_{context_key}",
                )

                tag_start = _safe_datetime_input(
                    label=f"Tag {i} start time — year / month / day / hour / minute / second",
                    key=f"tag_start_{i}_{context_key}",
                    default_value=t_min,
                    min_value=t_min,
                    max_value=t_max,
                )

                tag_end = _safe_datetime_input(
                    label=f"Tag {i} end time — year / month / day / hour / minute / second",
                    key=f"tag_end_{i}_{context_key}",
                    default_value=min(t_max, t_min + timedelta(minutes=30)),
                    min_value=t_min,
                    max_value=t_max,
                )

                if pd.Timestamp(tag_end) <= pd.Timestamp(tag_start):
                    st.warning(
                        f"Tag {i}: end time must be after start time. "
                        "This tag is not added to Track 4."
                    )
                    continue

                st.caption(f"Tag interval: {tag_start} → {tag_end}")

                tag_intervals.append(
                    {
                        "label": label.strip() or f"Observation {i}",
                        "start": tag_start,
                        "end": tag_end,
                    }
                )

        # Chart-drawn tags restored from JSON or received from the browser are
        # stored separately from the three sidebar Tagger slots. Add them to the
        # same tag_intervals list that Track 4 uses, so they are visualized as
        # real Tagger-lane intervals and included in the Hit results.
        visual_key = f"visual_tag_intervals_{context_key}"
        visual_items = st.session_state.get(visual_key, [])
        if isinstance(visual_items, list):
            cleaned_visual_items = []
            for visual_idx, visual_item in enumerate(visual_items, start=1):
                normalized_visual = _normalize_section_tag(
                    visual_item,
                    fallback_label=f"Drawn Tag {visual_idx}",
                )
                if normalized_visual is None:
                    continue
                cleaned_visual_items.append(normalized_visual)
                if _interval_overlaps_window(normalized_visual, t_min, t_max):
                    tag_intervals.append(normalized_visual)

            # Keep all saved/drawn tags as section-level absolute timestamps.
            # Do not clamp tags to the current 12-hour window.
            st.session_state[visual_key] = _deduplicate_visual_tags(cleaned_visual_items)

        st.markdown("**Agent lane**")

        agent_source_options = ["Manual interval", "Activity agent", "Symptom agent"]
        agent_source_key = f"agent_source_{context_key}"
        agent_source_default_key = f"_agent_source_default_fixed_{context_key}"

        # Streamlit keeps old widget values in session_state. If this app was opened
        # before the default changed, the radio can stay stuck on "Manual interval".
        # Force the new default once per well/section context, then let the user choose freely.
        if not st.session_state.get(agent_source_default_key, False):
            if st.session_state.get(agent_source_key) in (None, "Manual interval"):
                st.session_state[agent_source_key] = "Symptom agent"
            st.session_state[agent_source_default_key] = True

        if st.session_state.get(agent_source_key) not in agent_source_options:
            st.session_state[agent_source_key] = "Symptom agent"

        agent_source = st.radio(
            "Agent lane source",
            options=agent_source_options,
            key=agent_source_key,
        )

        activity_ui = _default_activity_ui(enabled=False)
        symptom_ui = _default_symptom_ui(enabled=False)

        if agent_source == "Manual interval":
            enabled = st.checkbox(
                "Enable Agent Hit",
                value=True,
                key=f"enable_agent_1_{context_key}",
            )

            if enabled:
                label = st.text_input(
                    "Agent Hit label",
                    value="Hit 1",
                    key=f"agent_label_1_{context_key}",
                )

                agent_interval_key = f"agent_interval_1_{context_key}"

                safe_agent_interval = _safe_slider_interval_state(
                    key=agent_interval_key,
                    min_value=t_min,
                    max_value=t_max,
                    default_start=t_min,
                    default_end=t_max,
                )

                interval = st.slider(
                    "Agent Hit interval",
                    min_value=t_min,
                    max_value=t_max,
                    value=safe_agent_interval,
                    format="YYYY-MM-DD HH:mm:ss",
                    key=agent_interval_key,
                )

                severity = st.selectbox(
                    "Agent Hit severity",
                    options=["Low", "Medium", "High"],
                    index=1,
                    key=f"agent_severity_1_{context_key}",
                )

                manual_agent_intervals.append(
                    {
                        "label": label.strip() or "Hit 1",
                        "start": interval[0],
                        "end": interval[1],
                        "severity": severity,
                        "source": "manual_agent",
                    }
                )

        elif agent_source == "Activity agent":
            activity_ui = render_activity_agent_controls(
                context_key=context_key,
                df=df,
                parent=container,
            )
            symptom_ui = _default_symptom_ui(enabled=False)

        elif agent_source == "Symptom agent":
            # Important:
            # Symptom agents need activity labels/features internally,
            # so Activity Agent runs in the background with default settings.
            activity_ui = _default_activity_ui(enabled=True)

            symptom_ui = render_symptom_agent_controls(
                context_key=context_key,
                parent=container,
            )

    return {
        "agent_source": agent_source,
        "tag_intervals": tag_intervals,
        "manual_agent_intervals": manual_agent_intervals,
        "activity_ui": activity_ui,
        "symptom_ui": symptom_ui,
        "show_reference_line": show_reference_line,
        "reference_time": reference_time,
        "chart_height": chart_height,
        "review_mode": review_mode,
    }

def build_agent_cfg_from_controls(
    controls: dict,
    activity_cfg: dict,
    symptom_cfg: dict,
) -> dict:
    agent_source = controls["agent_source"]
    tag_intervals = controls["tag_intervals"]
    manual_agent_intervals = controls["manual_agent_intervals"]

    auto_agent_intervals = []

    if agent_source == "Activity agent" and activity_cfg and activity_cfg.get("intervals"):
        selected_activity = activity_cfg.get("selected_activity", "All activities")

        if selected_activity == "All activities":
            auto_agent_intervals = activity_cfg["intervals"]
        else:
            auto_agent_intervals = [
                item
                for item in activity_cfg["intervals"]
                if item["label"] == selected_activity
            ]

    elif agent_source == "Symptom agent" and symptom_cfg and symptom_cfg.get("intervals"):
        auto_agent_intervals = symptom_cfg["intervals"]

    if agent_source == "Manual interval":
        agent_intervals = manual_agent_intervals
    else:
        agent_intervals = auto_agent_intervals

    activity_ui = controls.get("activity_ui", {})
    manual_activity_tags = activity_ui.get("manual_activity_tags", [])

    summary = _build_summary(tag_intervals, agent_intervals)

    activity_validation_summary = _build_activity_validation_summary(
        manual_activity_tags=manual_activity_tags,
        activity_intervals=activity_cfg.get("intervals", []) if activity_cfg else [],
    )

    return {
        "agent_source": agent_source,
        "tag_intervals": tag_intervals,
        "agent_intervals": agent_intervals,
        "summary": summary,
        "show_reference_line": controls["show_reference_line"],
        "reference_time": controls["reference_time"],
        "chart_height": controls["chart_height"],
        "review_mode": controls["review_mode"],
        "activity_cfg": activity_cfg or {},
        "symptom_cfg": symptom_cfg or {},
        "manual_activity_tags": manual_activity_tags,
        "activity_validation_summary": activity_validation_summary,
    }

def build_trq_spike_evaluation_df(symptom_cfg: dict) -> pd.DataFrame:
    """
    Build a readable TRQSpike evaluation table.

    This table is mainly for checking whether the TRQSpike thresholds are too
    strict or too loose. It prints the TRQ ratio and z-value requested for
    agent evaluation.
    """

    selected_symptom = symptom_cfg.get("selected_symptom", "")
    features = symptom_cfg.get("features", pd.DataFrame())
    cfg = symptom_cfg.get("config", SymptomConfig())

    columns = [
        "Time",
        "Current TRQ",
        "Prev. TRQ Mean",
        "Prev. TRQ Std Dev",
        "TRQ Ratio",
        "TRQ z-value",
        "RPM On",
        "RPM Stable",
        "Activity/RPM Context OK",
        "Started Low",
        "Normal Spike Shape",
        "Extreme Spike",
        "Spike Gate",
        "Low Mask",
        "High Mask",
        "Decision",
    ]

    if selected_symptom != "TRQSpike" or features is None or features.empty:
        return pd.DataFrame(columns=columns)

    df = features.copy()

    required_cols = [
        "trq",
        "trq_mean_long",
        "trq_std_long",
        "trq_ratio",
        "trq_zscore",
        "rpm_on",
        "rpm_stable",
        "context_mask",
        "started_low",
        "normal_spike_shape",
        "extreme_spike",
        "spike_gate",
        "lvl1_mask",
        "lvl2_mask",
    ]

    for col in required_cols:
        if col not in df.columns:
            df[col] = pd.NA

    # Keep rows that are useful for evaluation:
    # 1. agent hit rows,
    # 2. rows that passed context,
    # 3. rows where ratio is close to the level-1 threshold.
    near_threshold = pd.to_numeric(df["trq_ratio"], errors="coerce") >= (
        float(cfg.trq_spike_ratio_level_1) * 0.90
    )

    useful_rows = (
        df["lvl1_mask"].fillna(False).astype(bool)
        | df["lvl2_mask"].fillna(False).astype(bool)
        | df["context_mask"].fillna(False).astype(bool)
        | near_threshold.fillna(False)
    )

    eval_df = df.loc[useful_rows].copy()

    if eval_df.empty:
        eval_df = df.tail(200).copy()
    else:
        eval_df = eval_df.tail(1000).copy()

    def _decision(row):
        if bool(row.get("lvl2_mask", False)):
            return "High TRQSpike"
        if bool(row.get("lvl1_mask", False)):
            return "Low TRQSpike"
        if not bool(row.get("context_mask", False)):
            return "No hit: context blocked"
        if pd.isna(row.get("trq_ratio")) or row.get("trq_ratio") <= cfg.trq_spike_ratio_level_1:
            return "No hit: ratio below threshold"
        if not bool(row.get("spike_gate", False)):
            return "No hit: z-value / spike shape blocked"
        return "No hit"

    out = pd.DataFrame(
        {
            "Time": eval_df.index,
            "Current TRQ": pd.to_numeric(eval_df["trq"], errors="coerce").round(3),
            "Prev. TRQ Mean": pd.to_numeric(eval_df["trq_mean_long"], errors="coerce").round(3),
            "Prev. TRQ Std Dev": pd.to_numeric(eval_df["trq_std_long"], errors="coerce").round(3),
            "TRQ Ratio": pd.to_numeric(eval_df["trq_ratio"], errors="coerce").round(3),
            "TRQ z-value": pd.to_numeric(eval_df["trq_zscore"], errors="coerce").round(3),
            "RPM On": eval_df["rpm_on"],
            "RPM Stable": eval_df["rpm_stable"],
            "Activity/RPM Context OK": eval_df["context_mask"],
            "Started Low": eval_df["started_low"],
            "Normal Spike Shape": eval_df["normal_spike_shape"],
            "Extreme Spike": eval_df["extreme_spike"],
            "Spike Gate": eval_df["spike_gate"],
            "Low Mask": eval_df["lvl1_mask"],
            "High Mask": eval_df["lvl2_mask"],
            "Decision": eval_df.apply(_decision, axis=1),
        }
    )

    return out[columns].reset_index(drop=True)

def apply_loaded_dashboard_state_early(uploaded_data: dict | None, context_key: str):
    """
    Restore widget state that must exist before early sidebar widgets render:
    - track parameter selections
    - parameter max overrides
    - curve source
    - time filter text fields

    This prevents the app from stopping at 'Select parameters' after loading JSON.
    """
    if not uploaded_data:
        return

    dashboard_state = uploaded_data.get("dashboard_state", {}) or {}
    widget_state = dashboard_state.get("widget_state", {}) or {}

    if not widget_state:
        return

    saved_track_param_labels = _normalize_track_param_labels_for_save(
        uploaded_data.get("plot_track_param_labels")
        or dashboard_state.get("plot_track_param_labels")
        or widget_state.get(f"saved_track_param_labels_{context_key}")
        or widget_state.get(f"plot_track_param_labels_{context_key}")
    )

    if any(saved_track_param_labels):
        st.session_state[f"saved_track_param_labels_{context_key}"] = saved_track_param_labels
        st.session_state[f"plot_track_param_labels_{context_key}"] = saved_track_param_labels
        for idx in range(3):
            # This runs before render_track_parameter_selector(), so assigning
            # widget state here is safe and makes the restored plot selections
            # visible in the sidebar after upload.
            st.session_state[f"track_params_{idx + 1}_{context_key}"] = saved_track_param_labels[idx]

    early_prefixes = [
        "track_params_",
        "max_override_",
        "curve_source_",
        "window_index_",
        "saved_track_param_labels_",
        "plot_track_param_labels_",
    ]

    for key, value in widget_state.items():
        key = str(key)

        # Important:
        # Never restore internal app/session keys from saved JSON.
        # Old JSON files may contain _pending_loaded_review_payload_* or
        # _loaded_review_restored_done_* keys, which can cause rerun loops.
        if key.startswith("_"):
            continue

        if not key.endswith(f"_{context_key}") and f"_{context_key}_" not in key:
            continue

        if not any(key.startswith(prefix) for prefix in early_prefixes):
            continue

        # Do not let older JSON files with empty track_params overwrite the
        # explicit saved_track_param_labels restored above.
        if key.startswith("track_params_") and any(saved_track_param_labels):
            try:
                track_number = int(key.split("track_params_", 1)[1].split("_", 1)[0])
                if 1 <= track_number <= 3:
                    st.session_state[key] = saved_track_param_labels[track_number - 1]
                    continue
            except Exception:
                pass

        # Text inputs need strings.
        if key.startswith("exact_time_start_") or key.startswith("exact_time_end_"):
            st.session_state[key] = str(value)
        else:
            st.session_state[key] = value


def _render_dashboard_session_download_with_browser_tags(
    json_text: str,
    context_key: str,
    file_name: str,
):
    """
    Browser-side save button for full dashboard sessions.

    Why this exists:
    chart-drawn tags are created inside components.html / Plotly JavaScript first.
    A normal st.download_button is prepared on the Python side before the click,
    so it cannot see unsynced browser/localStorage tags at click time.

    This component reads the current browser-drawn tags from localStorage, injects
    them into the already-built JSON payload, and downloads the final JSON in the
    browser. Manual sidebar tags remain in the base JSON from Python.
    """
    base_json_text = json.dumps(json_text)
    context_json = json.dumps(str(context_key or ""))
    file_name_json = json.dumps(file_name)

    components.html(
        f"""
        <div style="font-family:Arial,sans-serif; margin: 0 0 8px 0;">
            <button id="save_dashboard_with_drawn_tags_btn" style="
                width: 100%;
                padding: 0.45rem 0.65rem;
                border: 1px solid rgba(49,51,63,0.25);
                border-radius: 0.35rem;
                background: rgb(255,255,255);
                color: rgb(49,51,63);
                cursor: pointer;
                font-size: 0.92rem;
                line-height: 1.4;
            ">
                Save Dashboard Session
            </button>
            <div id="save_dashboard_with_drawn_tags_status" style="
                font-size: 11px;
                color: #666;
                margin-top: 4px;
                line-height: 1.25;
            "></div>
        </div>

        <script>
        (function() {{
            const baseJsonText = {base_json_text};
            const contextKey = {context_json};
            const fileName = {file_name_json};
            const button = document.getElementById("save_dashboard_with_drawn_tags_btn");
            const status = document.getElementById("save_dashboard_with_drawn_tags_status");

            function parseDateMs(value) {{
                const d = new Date(value);
                return isNaN(d.getTime()) ? null : d.getTime();
            }}

            function normalizeTag(item, idx) {{
                if (!item || typeof item !== "object") return null;

                const start = item.start || item["Tag Start"] || item.tag_start || item.start_time || "";
                const end = item.end || item["Tag End"] || item.tag_end || item.end_time || "";

                if (!start || !end) return null;

                const startMs = parseDateMs(start);
                const endMs = parseDateMs(end);

                if (startMs === null || endMs === null || endMs <= startMs) return null;

                return {{
                    label: String(item.label || item["Tag Label"] || item.tag_label || ("Drawn Tag " + idx)),
                    start: String(start).replace("T", " ").slice(0, 19),
                    end: String(end).replace("T", " ").slice(0, 19),
                    source: "chart_drag"
                }};
            }}

            function identity(tag) {{
                return String(tag.label || "") + "|" + String(tag.start || "") + "|" + String(tag.end || "");
            }}

            function deduplicate(tags) {{
                const out = [];
                const seen = new Set();

                (Array.isArray(tags) ? tags : []).forEach(function(tag) {{
                    const normalized = normalizeTag(tag, out.length + 1);
                    if (!normalized) return;

                    const key = identity(normalized);
                    if (seen.has(key)) return;

                    seen.add(key);
                    out.push(normalized);
                }});

                return out;
            }}

            function readJsonList(key) {{
                try {{
                    const raw = window.localStorage.getItem(key);
                    if (!raw) return [];
                    const parsed = JSON.parse(raw);
                    return Array.isArray(parsed) ? parsed : [];
                }} catch (e) {{
                    return [];
                }}
            }}

            function readBrowserDrawnTags() {{
                if (!contextKey) return [];

                const latestKey = "hoda_client_visual_tags_latest_" + contextKey;
                let items = readJsonList(latestKey);

                // Fallback for dashboards opened before the latest-key fix:
                // collect all session-token-specific keys for this context.
                if (!items.length) {{
                    const prefix = "hoda_client_visual_tags_" + contextKey + "_";
                    try {{
                        for (let i = 0; i < window.localStorage.length; i++) {{
                            const key = window.localStorage.key(i);
                            if (!key || !key.startsWith(prefix)) continue;
                            if (key.includes("_redo_")) continue;
                            items = items.concat(readJsonList(key));
                        }}
                    }} catch (e) {{}}
                }}

                return deduplicate(items);
            }}

            function readBrowserHitResults() {{
                if (!contextKey) return [];
                const prefix = "hoda_hit_result_history_" + contextKey + "_";
                let rows = [];
                try {{
                    for (let i = 0; i < window.localStorage.length; i++) {{
                        const key = window.localStorage.key(i);
                        if (!key || !key.startsWith(prefix)) continue;
                        rows = rows.concat(readJsonList(key));
                    }}
                }} catch (e) {{}}

                const out = [];
                const seen = new Set();
                rows.forEach(function(row) {{
                    if (!row || typeof row !== "object") return;
                    const ident = [
                        row.well || "",
                        row.section || "",
                        row.tag_label || "",
                        row.tag_start || "",
                        row.tag_end || ""
                    ].join("|");
                    if (seen.has(ident)) return;
                    seen.add(ident);
                    out.push(row);
                }});
                out.sort(function(a, b) {{
                    return (parseDateMs(a && a.tag_start) || 0) - (parseDateMs(b && b.tag_start) || 0);
                }});
                return out;
            }}

            function mergePayloadWithDrawnTags(basePayload, browserDrawnTags, browserHitResults) {{
                const payload = basePayload && typeof basePayload === "object" ? basePayload : {{}};

                if (!payload.dashboard_context) payload.dashboard_context = {{}};
                if (!payload.dashboard_state) payload.dashboard_state = {{}};
                if (!payload.dashboard_state.widget_state) payload.dashboard_state.widget_state = {{}};

                const existingDrawn = deduplicate(payload.drawn_tag_intervals || []);
                const allDrawn = deduplicate(existingDrawn.concat(browserDrawnTags));

                payload.drawn_tag_intervals = allDrawn;
                payload.dashboard_state.widget_state["visual_tag_intervals_" + contextKey] = allDrawn;

                const existingHitResults = Array.isArray(payload.hit_results) ? payload.hit_results : [];
                const combinedHitResults = existingHitResults.concat(Array.isArray(browserHitResults) ? browserHitResults : []);

                // Critical: save hit-result rows only for the actual saved drawn tags.
                // Browser localStorage can contain stale rows from previous testing or
                // removed tags. Those rows must not enter the saved dashboard JSON.
                const validTagTimes = new Set();
                allDrawn.forEach(function(tag) {{
                    if (!tag || typeof tag !== "object") return;
                    const s = String(tag.start || "").replace("T", " ").slice(0, 19);
                    const e = String(tag.end || "").replace("T", " ").slice(0, 19);
                    if (s && e && s !== e) validTagTimes.add(s + "|" + e);
                }});

                const hitOut = [];
                const hitSeen = new Set();
                combinedHitResults.forEach(function(row) {{
                    if (!row || typeof row !== "object") return;
                    const tagStart = String(row.tag_start || "").replace("T", " ").slice(0, 19);
                    const tagEnd = String(row.tag_end || "").replace("T", " ").slice(0, 19);
                    if (!tagStart || !tagEnd || !validTagTimes.has(tagStart + "|" + tagEnd)) return;

                    const ident = [
                        row.well || "",
                        row.section || "",
                        row.tag_label || "",
                        tagStart,
                        tagEnd
                    ].join("|");
                    if (hitSeen.has(ident)) return;
                    hitSeen.add(ident);
                    row.tag_start = tagStart;
                    row.tag_end = tagEnd;
                    hitOut.push(row);
                }});
                payload.hit_results = hitOut;
                payload.dashboard_state.widget_state["hit_result_history_" + contextKey] = hitOut;

                const manual = Array.isArray(payload.manual_tagger_intervals)
                    ? payload.manual_tagger_intervals
                    : [];

                const nonDrawnExisting = (Array.isArray(payload.tag_intervals) ? payload.tag_intervals : [])
                    .filter(function(tag) {{
                        return String((tag && tag.source) || "").toLowerCase() !== "chart_drag";
                    }});

                // Prefer the explicit manual_tagger_intervals, but keep compatibility
                // with older payloads that only had tag_intervals.
                const manualBase = manual.length ? manual : nonDrawnExisting;
                payload.tag_intervals = deduplicate(manualBase.concat(allDrawn));

                if (!payload.summary) payload.summary = {{}};
                payload.summary.tag_count = payload.tag_intervals.length;

                return payload;
            }}

            function downloadText(text, name) {{
                const blob = new Blob([text], {{type: "application/json;charset=utf-8"}});
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = name || "dashboard_session.json";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }}

            function setStatus(message) {{
                if (status) status.textContent = message;
            }}

            function doSave() {{
                let basePayload = null;
                try {{
                    basePayload = JSON.parse(baseJsonText);
                }} catch (e) {{
                    alert("Could not prepare the saved dashboard JSON.");
                    return;
                }}

                const browserDrawnTags = readBrowserDrawnTags();
                const browserHitResults = readBrowserHitResults();
                const finalPayload = mergePayloadWithDrawnTags(basePayload, browserDrawnTags, browserHitResults);
                const finalText = JSON.stringify(finalPayload, null, 2);

                downloadText(finalText, fileName);

                if (browserDrawnTags.length) {{
                    setStatus("Saved with " + browserDrawnTags.length + " drawn tag(s) and " + browserHitResults.length + " hit-result row(s).");
                }} else {{
                    setStatus("Saved with " + browserHitResults.length + " hit-result row(s). No browser-drawn tags were found.");
                }}
            }}

            if (button) {{
                button.addEventListener("mouseenter", function() {{
                    button.style.borderColor = "rgba(49,51,63,0.45)";
                    button.style.background = "rgb(250,250,250)";
                }});
                button.addEventListener("mouseleave", function() {{
                    button.style.borderColor = "rgba(49,51,63,0.25)";
                    button.style.background = "rgb(255,255,255)";
                }});
                button.addEventListener("click", doSave);
            }}

            const initialCount = readBrowserDrawnTags().length;
            if (initialCount) {{
                setStatus("Ready to save with " + initialCount + " browser-drawn tag(s).");
            }} else {{
                setStatus("Ready to save.");
            }}
        }})();
        </script>
        """,
        height=68,
        scrolling=False,
    )

def render_agent_review_outputs(
    agent_cfg: dict,
    context_key: str,
    parent=None,
    selected_well: str | None = None,
    selected_sections: tuple[str, ...] | list[str] | None = None,
):
    container = parent if parent is not None else st.sidebar

    with container:
        summary = agent_cfg["summary"]
        manual_activity_tags = agent_cfg.get("manual_activity_tags", [])
        activity_validation_summary = agent_cfg.get("activity_validation_summary", {})

        score_text = f"{summary['score_percent']:.1f}%"
        threshold_text = f"{summary['acceptance_threshold_percent']:.0f}%"
        acceptance_text = "Accepted" if summary["accepted"] else "Not accepted yet"

        st.caption(
            f"Summary — Tags: {summary['tag_count']} | "
            f"Hits: {summary['agent_count']} | "
            f"Overlap: {summary['overlap_count']} / {summary['tag_count']}"
        )

        st.caption(
            f"Score: {score_text} | Acceptance threshold: {threshold_text} | "
            f"Status: {acceptance_text}"
        )

        if manual_activity_tags:
            st.caption(
                f"Activity validation — Manual tags: {activity_validation_summary['tag_count']} | "
                f"Matched: {activity_validation_summary['matched_count']} | "
                f"Score: {activity_validation_summary['score_percent']:.1f}% | "
                f"Min overlap: {activity_validation_summary['min_overlap_percent']:.0f}%"
            )

        status_rows = summary["tag_status_rows"]
        if status_rows:
            st.markdown("**Manual review status**")
            for row in status_rows:
                st.caption(f"{row['label']}: {row['status']}")

        json_text, csv_text = _build_export_payload(
            tag_intervals=agent_cfg["tag_intervals"],
            agent_intervals=agent_cfg["agent_intervals"],
            summary=summary,
            manual_activity_tags=manual_activity_tags,
            activity_validation_summary=activity_validation_summary,
            selected_well=selected_well,
            selected_sections=selected_sections,
            context_key=context_key,
        )

        default_json_name = f"tag_review_{context_key}"
        requested_json_name = st.text_input(
            "Dashboard session file name",
            value=default_json_name,
            key=f"dashboard_session_file_name_{context_key}",
            help="Choose the name of the saved dashboard .json file.",
        )

        safe_json_name = _sanitize_dashboard_session_filename(
            requested_json_name,
            fallback=default_json_name,
        )

        _render_dashboard_session_download_with_browser_tags(
            json_text=json_text,
            context_key=context_key,
            file_name=safe_json_name,
        )

        st.download_button(
            "Export tags/hits as CSV",
            data=csv_text,
            file_name=f"tag_review_{context_key}.csv",
            mime="text/csv",
            key=f"download_csv_{context_key}",
        )




