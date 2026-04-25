import csv
import io
import json
from datetime import timedelta

import pandas as pd
import streamlit as st

from agents.activity_agents import ActivityConfig
from agents.activity_support import interval_overlap, overlap_ratio
from agents.symptom_agents import SymptomConfig
from config import MAX_PARAMS_PER_TRACK, PARAMETER_CATALOG, PARAMETER_DISPLAY_NAMES



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
        st.session_state[f"tag_interval_{i}_{context_key}"] = (
            pd.to_datetime(tag["start"]).to_pydatetime(),
            pd.to_datetime(tag["end"]).to_pydatetime(),
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
    with st.sidebar:
        st.subheader("Time Filter")

        t_min_all = df.index.min().to_pydatetime()
        t_max_all = df.index.max().to_pydatetime()

        default_value = (t_min_all, t_max_all)
        slider_key = f"time_range_{context_key}"

        if slider_key not in st.session_state:
            st.session_state[slider_key] = default_value

        if st.button("Reset time filter", key=f"reset_time_{context_key}"):
            st.session_state[slider_key] = default_value

        time_range = st.slider(
            "Select Time Range",
            min_value=t_min_all,
            max_value=t_max_all,
            value=st.session_state[slider_key],
            format="YYYY-MM-DD HH:mm",
            key=slider_key,
        )

        total_sec = (t_max_all - t_min_all).total_seconds()
        sel_sec = (time_range[1] - time_range[0]).total_seconds()
        zoom_percent = 100.0 - (sel_sec / total_sec * 100.0) if total_sec > 0 else 0.0

        st.metric("Records", f"{len(df):,}")
        st.metric("Zoom", f"{zoom_percent:.0f}%")
        st.caption("To reduce magnification, click 'Reset time filter' or widen the time range.")

    return time_range, zoom_percent


def render_activity_agent_controls(context_key: str):
    with st.sidebar:
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

        with st.expander("Activity thresholds", expanded=False):
            short_window = st.number_input(
                "Short window (samples)",
                min_value=3,
                max_value=21,
                value=5,
                key=f"act_short_window_{context_key}",
            )
            medium_window = st.number_input(
                "Medium window (samples)",
                min_value=6,
                max_value=60,
                value=15,
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

            pump_on_threshold = st.number_input("Pump on threshold (lpm)", value=100.0, key=f"act_pump_thr_{context_key}")
            rpm_on_threshold = st.number_input("RPM on threshold", value=10.0, key=f"act_rpm_thr_{context_key}")
            rpm_low_threshold = st.number_input("RPM low threshold", value=30.0, key=f"act_rpm_low_thr_{context_key}")
            trip_rpm_max = st.number_input("Trip RPM max", value=5.0, key=f"act_trip_rpm_{context_key}")
            trip_flow_max = st.number_input("Trip flow max (lpm)", value=100.0, key=f"act_trip_flow_{context_key}")

            wob_zero_band = st.number_input("WOB zero band", value=0.5, key=f"act_wob_zero_{context_key}")
            wob_drilling_min = st.number_input("WOB drilling minimum", value=1.0, key=f"act_wob_drill_{context_key}")
            rop_min = st.number_input("ROP drilling minimum (m/h)", value=0.5, key=f"act_rop_min_{context_key}")

            near_bottom_threshold = st.number_input("Near-bottom threshold (m)", value=5.0, key=f"act_near_bottom_{context_key}")
            bit_on_bottom_threshold = st.number_input("Bit-on-bottom threshold (m)", value=1.0, key=f"act_bottom_{context_key}")

            movement_threshold = st.number_input("Movement threshold", value=0.3, key=f"act_move_thr_{context_key}")
            connection_block_travel_threshold = st.number_input(
                "Connection block travel threshold",
                value=2.0,
                key=f"act_conn_move_{context_key}",
            )

        cfg = ActivityConfig(
            short_window=int(short_window),
            medium_window=int(medium_window),
            min_interval_samples=int(min_interval_samples),
            gap_fill_samples=int(gap_fill_samples),
            pump_on_threshold=float(pump_on_threshold),
            rpm_on_threshold=float(rpm_on_threshold),
            rpm_low_threshold=float(rpm_low_threshold),
            wob_zero_band=float(wob_zero_band),
            wob_drilling_min=float(wob_drilling_min),
            rop_min=float(rop_min),
            near_bottom_threshold=float(near_bottom_threshold),
            bit_on_bottom_threshold=float(bit_on_bottom_threshold),
            movement_threshold=float(movement_threshold),
            connection_block_travel_threshold=float(connection_block_travel_threshold),
            trip_flow_max=float(trip_flow_max),
            trip_rpm_max=float(trip_rpm_max),
        )

    return {
        "enabled": enabled,
        "selected_activity": selected_activity,
        "config": cfg,
    }


def render_symptom_agent_controls(context_key: str):
    with st.sidebar:
        st.subheader("Symptom Agent Settings")

        enabled = st.checkbox(
            "Enable symptom agents",
            value=True,
            key=f"enable_symptom_agents_{context_key}",
        )

        selected_symptom = st.selectbox(
            "Symptom shown in Track 4 agent lane",
            options=["OpenHoleLength", "TRQSpike", "PSpike", "OverPull", "TookWeight"],
            index=0,
            key=f"selected_symptom_lane_{context_key}",
        )

        with st.expander("Symptom thresholds", expanded=False):
            open_hole_length_threshold_1 = st.number_input(
                "OpenHoleLength threshold 1 (m)",
                value=500.0,
                key=f"sym_ohl_1_{context_key}",
            )
            open_hole_length_threshold_2 = st.number_input(
                "OpenHoleLength threshold 2 (m)",
                value=750.0,
                key=f"sym_ohl_2_{context_key}",
            )

            trq_baseline_window = st.number_input(
                "TRQ baseline window",
                min_value=10,
                max_value=300,
                value=60,
                key=f"sym_trq_window_{context_key}",
            )
            trq_spike_ratio_level_1 = st.number_input(
                "TRQ spike ratio level 1",
                value=1.25,
                key=f"sym_trq_l1_{context_key}",
            )
            trq_spike_ratio_level_2 = st.number_input(
                "TRQ spike ratio level 2",
                value=1.40,
                key=f"sym_trq_l2_{context_key}",
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

            overpull_baseline_window = st.number_input(
                "OverPull baseline window",
                min_value=5,
                max_value=200,
                value=30,
                key=f"sym_op_window_{context_key}",
            )
            overpull_threshold_1 = st.number_input(
                "OverPull threshold 1",
                value=3.0,
                key=f"sym_op_thr1_{context_key}",
            )
            overpull_threshold_2 = st.number_input(
                "OverPull threshold 2",
                value=6.0,
                key=f"sym_op_thr2_{context_key}",
            )
            overpull_gap_fill_samples = st.number_input(
                "OverPull gap fill",
                min_value=0,
                max_value=10,
                value=2,
                key=f"sym_op_gap_{context_key}",
            )

            tookweight_baseline_window = st.number_input(
                "TookWeight baseline window",
                min_value=5,
                max_value=200,
                value=30,
                key=f"sym_tw_window_{context_key}",
            )
            tookweight_threshold_1 = st.number_input(
                "TookWeight threshold 1",
                value=3.0,
                key=f"sym_tw_thr1_{context_key}",
            )
            tookweight_threshold_2 = st.number_input(
                "TookWeight threshold 2",
                value=6.0,
                key=f"sym_tw_thr2_{context_key}",
            )
            tookweight_gap_fill_samples = st.number_input(
                "TookWeight gap fill",
                min_value=0,
                max_value=10,
                value=2,
                key=f"sym_tw_gap_{context_key}",
            )

        cfg = SymptomConfig(
            open_hole_length_threshold_1=float(open_hole_length_threshold_1),
            open_hole_length_threshold_2=float(open_hole_length_threshold_2),
            trq_baseline_window=int(trq_baseline_window),
            trq_spike_ratio_level_1=float(trq_spike_ratio_level_1),
            trq_spike_ratio_level_2=float(trq_spike_ratio_level_2),
            pspike_baseline_window=int(pspike_baseline_window),
            pspike_threshold_normal=float(pspike_threshold_normal),
            pspike_threshold_motor_on=float(pspike_threshold_motor_on),
            pspike_gap_fill_samples=int(pspike_gap_fill_samples),
            overpull_baseline_window=int(overpull_baseline_window),
            overpull_threshold_1=float(overpull_threshold_1),
            overpull_threshold_2=float(overpull_threshold_2),
            overpull_gap_fill_samples=int(overpull_gap_fill_samples),
            tookweight_baseline_window=int(tookweight_baseline_window),
            tookweight_threshold_1=float(tookweight_threshold_1),
            tookweight_threshold_2=float(tookweight_threshold_2),
            tookweight_gap_fill_samples=int(tookweight_gap_fill_samples),
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


def render_agent_controls(
    df,
    context_key: str,
    activity_cfg: dict | None = None,
    symptom_cfg: dict | None = None,
):
    with st.sidebar:
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
        manual_activity_tags = []

        duration_options = {
            "5 min": timedelta(minutes=5),
            "15 min": timedelta(minutes=15),
            "30 min": timedelta(minutes=30),
            "1 hour": timedelta(hours=1),
            "3 hours": timedelta(hours=3),
            "Custom": None,
        }

        st.markdown("**Tagger lane**")
        st.caption("Use short or long time segments to mark deviation tags.")

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
                duration_choice = st.selectbox(
                    f"Tag {i} segment length",
                    options=list(duration_options.keys()),
                    index=2,
                    key=f"tag_duration_choice_{i}_{context_key}",
                )

                if duration_choice == "Custom":
                    interval = st.slider(
                        f"Tag {i} interval",
                        min_value=t_min,
                        max_value=t_max,
                        value=(t_min, t_max),
                        format="YYYY-MM-DD HH:mm",
                        key=f"tag_interval_{i}_{context_key}",
                    )
                else:
                    center_default = st.session_state.get(f"tag_center_{i}_{context_key}", t_min)
                    center_time = st.slider(
                        f"Tag {i} center time",
                        min_value=t_min,
                        max_value=t_max,
                        value=center_default,
                        format="YYYY-MM-DD HH:mm",
                        key=f"tag_center_{i}_{context_key}",
                    )
                    duration = duration_options[duration_choice]
                    half_duration = duration / 2
                    start = max(t_min, center_time - half_duration)
                    end = min(t_max, center_time + half_duration)
                    interval = (start, end)
                    st.caption(f"Segment: {start} → {end}")

                tag_intervals.append(
                    {
                        "label": label.strip() or f"Observation {i}",
                        "start": interval[0],
                        "end": interval[1],
                    }
                )

        st.markdown("**Manual activity validation tags**")
        st.caption("Use these to validate the automatic activity intervals.")

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
            if enabled:
                activity_label = st.selectbox(
                    f"Activity Tag {i} label",
                    options=activity_options,
                    index=1,
                    key=f"activity_tag_label_{i}_{context_key}",
                )

                duration_choice = st.selectbox(
                    f"Activity Tag {i} segment length",
                    options=list(duration_options.keys()),
                    index=2,
                    key=f"activity_tag_duration_choice_{i}_{context_key}",
                )

                if duration_choice == "Custom":
                    interval = st.slider(
                        f"Activity Tag {i} interval",
                        min_value=t_min,
                        max_value=t_max,
                        value=(t_min, t_max),
                        format="YYYY-MM-DD HH:mm",
                        key=f"activity_tag_interval_{i}_{context_key}",
                    )
                else:
                    center_default = st.session_state.get(f"activity_tag_center_{i}_{context_key}", t_min)
                    center_time = st.slider(
                        f"Activity Tag {i} center time",
                        min_value=t_min,
                        max_value=t_max,
                        value=center_default,
                        format="YYYY-MM-DD HH:mm",
                        key=f"activity_tag_center_{i}_{context_key}",
                    )
                    duration = duration_options[duration_choice]
                    half_duration = duration / 2
                    start = max(t_min, center_time - half_duration)
                    end = min(t_max, center_time + half_duration)
                    interval = (start, end)
                    st.caption(f"Activity segment: {start} → {end}")

                manual_activity_tags.append(
                    {
                        "label": activity_label,
                        "start": interval[0],
                        "end": interval[1],
                    }
                )

        st.markdown("**Agent lane**")
        agent_source = st.radio(
            "Agent lane source",
            options=["Activity agent", "Symptom agent", "Manual interval"],
            index=1,
            key=f"agent_source_{context_key}",
        )

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

        auto_agent_intervals = []
        if agent_source == "Activity agent" and activity_cfg and activity_cfg.get("intervals"):
            selected_activity = activity_cfg.get("selected_activity", "All activities")
            if selected_activity == "All activities":
                auto_agent_intervals = activity_cfg["intervals"]
            else:
                auto_agent_intervals = [
                    item for item in activity_cfg["intervals"] if item["label"] == selected_activity
                ]

        if agent_source == "Symptom agent" and symptom_cfg and symptom_cfg.get("intervals"):
            auto_agent_intervals = symptom_cfg["intervals"]

        agent_intervals = auto_agent_intervals if agent_source != "Manual interval" else manual_agent_intervals

        summary = _build_summary(tag_intervals, agent_intervals)

        activity_validation_summary = _build_activity_validation_summary(
            manual_activity_tags=manual_activity_tags,
            activity_intervals=activity_cfg.get("intervals", []) if activity_cfg else [],
        )

        score_text = f"{summary['score_percent']:.1f}%"
        threshold_text = f"{summary['acceptance_threshold_percent']:.0f}%"
        acceptance_text = "Accepted" if summary["accepted"] else "Not accepted yet"

        st.caption(
            f"Summary — Tags: {summary['tag_count']} | "
            f"Hits: {summary['agent_count']} | "
            f"Overlap: {summary['overlap_count']} / {summary['tag_count']}"
        )
        st.caption(
            f"Score: {score_text} | Acceptance threshold: {threshold_text} | Status: {acceptance_text}"
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
            tag_intervals=tag_intervals,
            agent_intervals=agent_intervals,
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

    return {
        "tag_intervals": tag_intervals,
        "agent_intervals": agent_intervals,
        "summary": summary,
        "show_reference_line": show_reference_line,
        "reference_time": reference_time,
        "chart_height": chart_height,
        "review_mode": review_mode,
        "activity_cfg": activity_cfg or {},
        "symptom_cfg": symptom_cfg or {},
        "manual_activity_tags": manual_activity_tags,
        "activity_validation_summary": activity_validation_summary,
    }