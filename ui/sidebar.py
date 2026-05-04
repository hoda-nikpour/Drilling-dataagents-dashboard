import csv
import io
import json
from datetime import timedelta

import pandas as pd
import streamlit as st

from agents.activity_agents import ActivityConfig
from agents.activity_support import interval_overlap, overlap_ratio
from agents.symptom_agents import SymptomConfig
from config import (
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


def _build_export_payload(
    tag_intervals: list[dict],
    agent_intervals: list[dict],
    summary: dict,
    manual_activity_tags: list[dict] | None = None,
    activity_validation_summary: dict | None = None,
) -> tuple[str, str]:
    manual_activity_tags = manual_activity_tags or []
    activity_validation_summary = activity_validation_summary or {}

    payload = {
        "tag_intervals": [
            {
                "label": x["label"],
                "start": str(x["start"]),
                "end": str(x["end"]),
            }
            for x in tag_intervals
        ],
        "agent_intervals": [
            {
                "label": x["label"],
                "start": str(x["start"]),
                "end": str(x["end"]),
                "severity": x.get("severity"),
                "source": x.get("source"),
            }
            for x in agent_intervals
        ],
        "manual_activity_tags": [
            {
                "label": x["label"],
                "start": str(x["start"]),
                "end": str(x["end"]),
            }
            for x in manual_activity_tags
        ],
        "summary": {
            "tag_count": summary["tag_count"],
            "agent_count": summary["agent_count"],
            "overlap_count": summary["overlap_count"],
            "score_percent": round(summary["score_percent"], 1),
            "acceptance_threshold_percent": summary["acceptance_threshold_percent"],
            "accepted": summary["accepted"],
        },
        "activity_validation_summary": {
            "tag_count": activity_validation_summary.get("tag_count", 0),
            "matched_count": activity_validation_summary.get("matched_count", 0),
            "score_percent": round(activity_validation_summary.get("score_percent", 0.0), 1),
            "min_overlap_percent": activity_validation_summary.get(
                "min_overlap_percent",
                ACTIVITY_VALIDATION_MIN_OVERLAP_PERCENT,
            ),
        },
    }

    json_text = json.dumps(payload, indent=2)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "label", "start", "end", "severity", "source"])

    for item in tag_intervals:
        writer.writerow(["tag", item["label"], item["start"], item["end"], "", "manual"])

    for item in agent_intervals:
        writer.writerow(
            [
                "agent",
                item["label"],
                item["start"],
                item["end"],
                item.get("severity", ""),
                item.get("source", ""),
            ]
        )

    for item in manual_activity_tags:
        writer.writerow(
            [
                "activity_tag",
                item["label"],
                item["start"],
                item["end"],
                "",
                "manual_activity_validation",
            ]
        )

    return json_text, output.getvalue()


def _apply_loaded_review_to_state(uploaded_data: dict, context_key: str):
    for i in range(1, 4):
        st.session_state[f"enable_tag_{i}_{context_key}"] = False
        st.session_state[f"enable_activity_tag_{i}_{context_key}"] = False

    st.session_state[f"enable_agent_1_{context_key}"] = False

    for i, tag in enumerate(uploaded_data.get("tag_intervals", [])[:3], start=1):
        st.session_state[f"enable_tag_{i}_{context_key}"] = True
        st.session_state[f"tag_label_{i}_{context_key}"] = tag.get("label", f"Observation {i}")

        st.session_state[f"tag_start_{i}_{context_key}"] = (
            pd.to_datetime(tag["start"]).to_pydatetime()
        )
        st.session_state[f"tag_end_{i}_{context_key}"] = (
            pd.to_datetime(tag["end"]).to_pydatetime()
        )

    for i, tag in enumerate(uploaded_data.get("manual_activity_tags", [])[:3], start=1):
        st.session_state[f"enable_activity_tag_{i}_{context_key}"] = True
        st.session_state[f"activity_tag_label_{i}_{context_key}"] = tag.get("label", "Drilling")
        st.session_state[f"activity_tag_interval_{i}_{context_key}"] = (
            pd.to_datetime(tag["start"]).to_pydatetime(),
            pd.to_datetime(tag["end"]).to_pydatetime(),
        )

    loaded_agents = uploaded_data.get("agent_intervals", [])
    if loaded_agents:
        agent = loaded_agents[0]
        st.session_state[f"enable_agent_1_{context_key}"] = True
        st.session_state[f"agent_label_1_{context_key}"] = agent.get("label", "Hit 1")
        st.session_state[f"agent_interval_1_{context_key}"] = (
            pd.to_datetime(agent["start"]).to_pydatetime(),
            pd.to_datetime(agent["end"]).to_pydatetime(),
        )
        st.session_state[f"agent_severity_1_{context_key}"] = agent.get("severity", "Medium")


def render_well_section_selector(sections_by_well: dict):
    with st.sidebar:
        st.subheader("Well")
        selected_well = st.selectbox(
            "Select Well",
            options=sorted(sections_by_well.keys()),
            index=0,
            key="selected_well",
        )

        available_sections = sorted(sections_by_well.get(selected_well, []), key=float)

        st.subheader("Section")
        selected_sections = st.multiselect(
            "Select Section(s)",
            options=available_sections,
            default=[],
            format_func=lambda s: f'{s}"',
            key=f"selected_sections_{selected_well}",
        )

    return selected_well, selected_sections


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
            st.session_state[exact_start_key] = _format_dt(default_start)
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

        st.metric("Records in selected window", f"{filtered_records:,}")
        st.metric("Zoom", f"{zoom_percent:.0f}%")

        st.caption(
            f"Available range: {_format_dt(default_start)} → {_format_dt(default_end)}"
        )

        st.caption(
            f"Applied range: {_format_dt(selected_start)} → {_format_dt(selected_end)}"
        )

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
        "selected_symptom": "OpenHoleLength",
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

    Example:
    2005-12-24 01:11:39
    """
    current_value = st.session_state.get(key, default_value)

    try:
        current_value = pd.Timestamp(current_value)
    except Exception:
        current_value = pd.Timestamp(default_value)

    if (
        current_value < pd.Timestamp(min_value)
        or current_value > pd.Timestamp(max_value)
    ):
        current_value = pd.Timestamp(default_value)

    default_text = current_value.strftime("%Y-%m-%d %H:%M:%S")

    text_value = st.text_input(
        label,
        value=default_text,
        key=key,
        help="Use format: YYYY-MM-DD HH:mm:ss, for example 2005-12-24 01:11:39",
    )

    try:
        parsed_value = pd.to_datetime(text_value, format="%Y-%m-%d %H:%M:%S")
    except Exception:
        st.error(
            f"Invalid datetime for '{label}'. Please use format YYYY-MM-DD HH:mm:ss."
        )
        return current_value.to_pydatetime()

    if parsed_value < pd.Timestamp(min_value):
        st.warning(f"{label} is before the available data range. Using minimum time.")
        return pd.Timestamp(min_value).to_pydatetime()

    if parsed_value > pd.Timestamp(max_value):
        st.warning(f"{label} is after the available data range. Using maximum time.")
        return pd.Timestamp(max_value).to_pydatetime()

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

        selected_symptom = st.selectbox(
            "Symptom shown in Track 4 agent lane",
            options=["OpenHoleLength", "TRQSpike", "TRQErratic", "PSpike", "OverPull", "TookWeight"],
            index=0,
            key=f"selected_symptom_lane_{context_key}",
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

        review_mode = st.selectbox(
            "Review mode",
            options=["Standard review", "Stretched inspection"],
            index=1,
            key=f"review_mode_{context_key}",
        )
        chart_height = 950 if review_mode == "Standard review" else 1400

        uploaded_review = st.file_uploader(
            "Load saved review JSON",
            type=["json"],
            key=f"review_upload_{context_key}",
        )
        if uploaded_review is not None:
            try:
                uploaded_data = json.load(uploaded_review)
                _apply_loaded_review_to_state(uploaded_data, context_key)
                st.success("Saved review loaded into the controls.")
            except Exception:
                st.error("Could not read the uploaded review JSON.")

        show_reference_line = st.checkbox(
            "Show cross-track reference line",
            value=False,
            key=f"show_reference_line_{context_key}",
        )

        reference_time = None
        if show_reference_line:
            reference_time = st.slider(
                "Reference time",
                min_value=t_min,
                max_value=t_max,
                value=t_min,
                format="YYYY-MM-DD HH:mm",
                key=f"reference_time_{context_key}",
            )
        tag_intervals = []
        manual_agent_intervals = []

        st.markdown("**Tagger lane**")
        st.caption(
            "Use these fields to manually mark an observation interval. "
            "Choose the start and end time directly."
        )

        for i in range(1, 4):
            enabled = st.checkbox(
                f"Enable Tag {i}",
                value=(i == 1),
                key=f"enable_tag_{i}_{context_key}",
            )

            if enabled:
                label = st.text_input(
                    f"Tag {i} label",
                    value=f"Observation {i}",
                    key=f"tag_label_{i}_{context_key}",
                )

                tag_start = _safe_datetime_input(
                    label=f"Tag {i} start time — day / hour / minute",
                    key=f"tag_start_{i}_{context_key}",
                    default_value=t_min,
                    min_value=t_min,
                    max_value=t_max,
                )

                tag_end = _safe_datetime_input(
                    label=f"Tag {i} end time — day / hour / minute",
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

        

        st.markdown("**Agent lane**")

        agent_source = st.radio(
            "Agent lane source",
            options=["Manual interval", "Activity agent", "Symptom agent"],
            index=0,
            key=f"agent_source_{context_key}",
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

                interval = st.slider(
                    "Agent Hit interval",
                    min_value=t_min,
                    max_value=t_max,
                    value=(t_min, t_max),
                    format="YYYY-MM-DD HH:mm",
                    key=f"agent_interval_1_{context_key}",
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

def render_agent_review_outputs(
    agent_cfg: dict,
    context_key: str,
    parent=None,
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
        )

        st.download_button(
            "Export tags/hits as JSON",
            data=json_text,
            file_name=f"tag_review_{context_key}.json",
            mime="application/json",
            key=f"download_json_{context_key}",
        )

        st.download_button(
            "Export tags/hits as CSV",
            data=csv_text,
            file_name=f"tag_review_{context_key}.csv",
            mime="text/csv",
            key=f"download_csv_{context_key}",
        )