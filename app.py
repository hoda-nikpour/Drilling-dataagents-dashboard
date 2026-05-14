import pandas as pd
import streamlit as st

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS
from services.data_quality import build_time_cadence_df

from config import (
    CLEANING_RULES,
    DEFAULT_MARKER_DISPLAY,
    GLOBAL_PARAMETER_ALIASES,
    PARAMETER_CATALOG,
    SECTION_CLEANING_RULES,
    SECTION_PARAMETER_ALIASES,
    TRACK_COLOR_PALETTE,
    WELL_CLEANING_RULES,
    WELL_PARAMETER_ALIASES,
)

from services.data_cleaning import (
    apply_cleaning_layer,
    build_context_cleaning_rules,
)

from data_access.data_loader import (
    get_available_numeric_columns,
    load_catalog,
    load_sections_for_columns,
)

from services.dashboard_service import (
    build_context_parameter_aliases,
    build_label_to_column_map,
    build_mapping_diagnostic_df,
    build_parameter_catalog_df,
    build_requested_columns,
    build_sections_by_well,
    flatten_selected_params,
    make_context_key,
    run_activity_agent,
    run_symptom_agent,
)

from ui.layout import (
    render_chart,
    render_dashboard_header,
    render_result_tables,
    render_review_caption,
)

from ui.sidebar import (
    apply_loaded_dashboard_state_early,
    apply_visual_tag_from_query_params,
    build_activity_validation_df,
    build_agent_cfg_from_controls,
    build_boss_symptom_presentation_df,
    build_boss_symptom_presentation_excel,
    build_manual_review_df,
    build_professional_symptom_review_df,
    build_trq_spike_evaluation_df,
    render_agent_controls,
    render_agent_review_outputs,
    render_parameter_range_controls,
    render_review_loader_before_well_selector,
    render_time_filter,
    render_track_parameter_selector,
    render_well_section_selector,
)

from ui.styles import apply_global_styles


# -----------------------------------------------------------------------------
# Track 4 Symptom-Agent visual fallback
# -----------------------------------------------------------------------------
# Activity Agent can always draw Track 4 from its final activity label series.
# Symptom Agent does not have one common final label series; each symptom has
# different masks/features. If strict symptom intervals are empty, this fallback
# builds visual-only intervals from the same raw/cleaned curves so the Track 4
# Agent lane still shows suspicious regions for review. This does not change the
# official agent intervals used by Excel/table evaluation.


def _series_from_logical(df: pd.DataFrame, label_to_column: dict[str, str], logical_name: str) -> pd.Series:
    col = label_to_column.get(logical_name)
    if col is None or col not in df.columns:
        return pd.Series(index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def _visual_interval_end(index, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.Timestamp:
    start_ts = pd.Timestamp(start_ts)
    end_ts = pd.Timestamp(end_ts)

    if end_ts > start_ts:
        return end_ts

    try:
        loc = index.get_loc(start_ts)
        if isinstance(loc, slice):
            loc = loc.start
        if isinstance(loc, (list, tuple)):
            loc = loc[0]
        if hasattr(loc, "__len__") and not isinstance(loc, (str, bytes)):
            loc = int(list(loc)[0])
        loc = int(loc)
        if loc + 1 < len(index):
            next_ts = pd.Timestamp(index[loc + 1])
            if next_ts > start_ts:
                return next_ts
        if loc > 0:
            prev_ts = pd.Timestamp(index[loc - 1])
            step = start_ts - prev_ts
            if step.total_seconds() > 0:
                return start_ts + step
    except Exception:
        pass

    return start_ts + pd.Timedelta(seconds=30)


def _mask_to_visual_intervals(mask: pd.Series, label: str, severity: str = "Medium", max_intervals: int = 250) -> list[dict]:
    if mask is None or mask.empty:
        return []

    mask = mask.fillna(False).astype(bool)
    intervals: list[dict] = []
    start = None
    last_true = None
    count = 0

    for ts, flag in mask.items():
        ts = pd.Timestamp(ts)
        if flag:
            if start is None:
                start = ts
                count = 1
            else:
                count += 1
            last_true = ts
            continue

        if start is not None:
            end = _visual_interval_end(mask.index, start, pd.Timestamp(last_true))
            intervals.append(
                {
                    "label": label,
                    "start": start,
                    "end": end,
                    "severity": severity,
                    "source": "symptom_agent",
                    "visual_source": "app_raw_curve_visual_fallback",
                    "samples": int(count),
                }
            )
            if len(intervals) >= max_intervals:
                return intervals
            start = None
            last_true = None
            count = 0

    if start is not None:
        end = _visual_interval_end(mask.index, start, pd.Timestamp(last_true))
        intervals.append(
            {
                "label": label,
                "start": start,
                "end": end,
                "severity": severity,
                "source": "symptom_agent",
                "visual_source": "app_raw_curve_visual_fallback",
                "samples": int(count),
            }
        )

    return intervals[:max_intervals]


def _top_fraction_mask(values: pd.Series, fraction: float = 0.02, min_value: float | None = None) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    valid = values.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if valid.empty:
        return pd.Series(False, index=values.index)

    q = max(0.0, min(1.0, 1.0 - float(fraction)))
    threshold = float(valid.quantile(q))
    if min_value is not None:
        threshold = max(threshold, float(min_value))

    return values.ge(threshold).fillna(False)


def _rebuild_track4_summary(tag_intervals: list[dict], agent_intervals: list[dict]) -> dict:
    matched = 0
    for tag in tag_intervals or []:
        try:
            tag_start = pd.Timestamp(tag.get("start"))
            tag_end = pd.Timestamp(tag.get("end"))
        except Exception:
            continue

        has_overlap = False
        for hit in agent_intervals or []:
            try:
                hit_start = pd.Timestamp(hit.get("start"))
                hit_end = pd.Timestamp(hit.get("end"))
            except Exception:
                continue
            if max(tag_start, hit_start) < min(tag_end, hit_end):
                has_overlap = True
                break
        matched += int(has_overlap)

    tag_count = len(tag_intervals or [])
    agent_count = len(agent_intervals or [])
    score_percent = (matched / tag_count * 100.0) if tag_count else 0.0
    return {
        "tag_count": tag_count,
        "agent_count": agent_count,
        "overlap_count": matched,
        "score_percent": score_percent,
        "acceptance_threshold_percent": 95.0,
        "accepted": score_percent >= 95.0,
        "tag_status_rows": [],
    }


def build_raw_curve_symptom_track4_intervals(
    df: pd.DataFrame,
    label_to_column: dict[str, str],
    symptom_cfg: dict,
) -> list[dict]:
    """
    Last-resort Track 4 visual fallback for Symptom Agent.

    This uses raw/cleaned curves directly when symptom_cfg['intervals'] and
    symptom_cfg['features'] did not produce visible intervals. It is intentionally
    visual-only and does not alter the official evaluation tables.
    """
    if df is None or df.empty or not symptom_cfg:
        return []

    selected = symptom_cfg.get("selected_symptom", "") or "Symptom"
    cfg = symptom_cfg.get("config")

    if selected in {"TRQErratic", "TRQSpike"}:
        trq = _series_from_logical(df, label_to_column, "TRQ")
        if trq.dropna().empty:
            return []

        if selected == "TRQErratic":
            window = int(getattr(cfg, "trq_erratic_mean_long_window", 100))
            ratio_threshold = float(getattr(cfg, "trq_erratic_ratio_level_1", 1.10))
            min_cycles = int(getattr(cfg, "trq_erratic_min_cycles", 3))
            mean_long = trq.abs().rolling(window=window, min_periods=1, center=False).mean().shift(1)
            ratio = trq.abs() / mean_long.replace(0.0, pd.NA)
            deviation = trq - trq.rolling(window=window, min_periods=1, center=False).mean().shift(1)
            sign = deviation.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
            sign_change = (sign != sign.shift(1)) & sign.ne(0) & sign.shift(1).ne(0)
            cycles = sign_change.astype(int).rolling(window=window, min_periods=1, center=False).sum()

            mask = (ratio.gt(ratio_threshold) & cycles.ge(min_cycles)).fillna(False)
            if not mask.any():
                mask = _top_fraction_mask(ratio, fraction=0.025, min_value=min(1.02, ratio_threshold))
            return _mask_to_visual_intervals(mask, selected, severity="Medium")

        window = int(getattr(cfg, "trq_mean_long_window", getattr(cfg, "trq_baseline_window", 60)))
        ratio_threshold = float(getattr(cfg, "trq_spike_ratio_level_1", 1.25))
        mean_long = trq.rolling(window=window, min_periods=1, center=False).mean().shift(1)
        ratio = trq / mean_long.replace(0.0, pd.NA)
        mask = ratio.gt(ratio_threshold).fillna(False)
        if not mask.any():
            mask = _top_fraction_mask(ratio, fraction=0.02, min_value=min(1.05, ratio_threshold))
        return _mask_to_visual_intervals(mask, selected, severity="Medium")

    if selected == "PSpike":
        spp = _series_from_logical(df, label_to_column, "SPP")
        if spp.dropna().empty:
            return []
        window = int(getattr(cfg, "pspike_baseline_window", 20))
        threshold = float(getattr(cfg, "pspike_threshold_normal", 5.0))
        baseline = spp.rolling(window=window, min_periods=1, center=False).median().shift(1)
        delta = spp - baseline
        mask = delta.gt(threshold).fillna(False)
        if not mask.any():
            mask = _top_fraction_mask(delta, fraction=0.02)
        return _mask_to_visual_intervals(mask, selected, severity="Medium")

    if selected == "OverPull":
        hkl = _series_from_logical(df, label_to_column, "HKL")
        if hkl.dropna().empty:
            return []
        window = int(getattr(cfg, "overpull_baseline_window", 20))
        threshold = float(getattr(cfg, "overpull_threshold", 6.0))
        baseline = hkl.rolling(window=window, min_periods=1, center=False).median().shift(1)
        delta = hkl - baseline
        mask = delta.gt(threshold).fillna(False)
        if not mask.any():
            mask = _top_fraction_mask(delta, fraction=0.02)
        return _mask_to_visual_intervals(mask, selected, severity="High")

    if selected == "TookWeight":
        hkl = _series_from_logical(df, label_to_column, "HKL")
        if hkl.dropna().empty:
            return []
        window = int(getattr(cfg, "tookweight_baseline_window", 20))
        threshold = float(getattr(cfg, "tookweight_threshold", 6.0))
        baseline = hkl.rolling(window=window, min_periods=1, center=False).median().shift(1)
        drop = baseline - hkl
        mask = drop.gt(threshold).fillna(False)
        if not mask.any():
            mask = _top_fraction_mask(drop, fraction=0.02)
        return _mask_to_visual_intervals(mask, selected, severity="High")

    if selected == "OpenHoleLength":
        well_depth = _series_from_logical(df, label_to_column, "Well Depth")
        casing = _series_from_logical(df, label_to_column, "Casing Depth")
        if well_depth.dropna().empty:
            return []
        if casing.dropna().empty:
            fallback = getattr(cfg, "casing_depth", None)
            if fallback is None:
                return []
            casing = pd.Series(float(fallback), index=df.index)
        threshold = float(getattr(cfg, "open_hole_length_threshold_1", 500.0))
        open_hole = (well_depth - casing).clip(lower=0.0)
        mask = open_hole.gt(threshold).fillna(False)
        return _mask_to_visual_intervals(mask, selected, severity="Low")

    return []
from utils.helpers import compute_section_ranges, get_target_points
from visualization.chart_builder import create_multi_track_chart

from services.undo_service import (
    begin_undo_tracking,
    commit_undo_tracking,
    render_undo_controls,
)


st.set_page_config(layout="wide", initial_sidebar_state="expanded")
apply_global_styles()


def main():
    begin_undo_tracking()

    catalog = load_catalog()
    if not catalog["sections"]:
        st.error("data/catalog.json not found or empty.")
        st.stop()

    sections_by_well = build_sections_by_well(catalog)

    loaded_review_payload = render_review_loader_before_well_selector()

    selected_well, selected_sections = render_well_section_selector(sections_by_well)
    
    if not selected_sections:
        st.warning("Please select at least one section from the sidebar.")
        st.stop()

    selected_sections = tuple(sorted(selected_sections, key=float))
    context_key = make_context_key(selected_well, selected_sections)

    if loaded_review_payload is not None:
        restore_done_key = f"_loaded_review_restored_done_{context_key}"
        pending_payload_key = f"_pending_loaded_review_payload_{context_key}"

        if not st.session_state.get(restore_done_key, False):
            st.session_state[pending_payload_key] = loaded_review_payload

            apply_loaded_dashboard_state_early(
                uploaded_data=loaded_review_payload,
                context_key=context_key,
            )
    
    discovered_params = get_available_numeric_columns(selected_well, selected_sections)

    context_parameter_aliases = build_context_parameter_aliases(
        selected_well=selected_well,
        selected_sections=selected_sections,
        global_aliases=GLOBAL_PARAMETER_ALIASES,
        well_aliases=WELL_PARAMETER_ALIASES,
        section_aliases=SECTION_PARAMETER_ALIASES,
    )

    label_to_column = build_label_to_column_map(
        discovered_params=discovered_params,
        parameter_aliases=context_parameter_aliases,
    )

    required_activity_labels = [
        label for label in REQUIRED_ACTIVITY_INPUTS if label in label_to_column
    ]

    required_symptom_labels = [
        label for label in REQUIRED_SYMPTOM_INPUTS if label in label_to_column
    ]

    available_param_labels = list(dict.fromkeys(list(label_to_column.keys())))

    if not available_param_labels:
        st.error(
            "None of the requested drilling parameters were found for the selected well/sections. "
            f"Found numeric columns: {', '.join(discovered_params[:30])}"
        )
        st.stop()

    with st.expander("Parameter catalog for review", expanded=False):
        st.dataframe(
            build_parameter_catalog_df(
                label_to_column=label_to_column,
                parameter_catalog=PARAMETER_CATALOG,
            ),
            width="stretch",
        )

    track_param_labels = render_track_parameter_selector(
        available_param_labels=available_param_labels,
        context_key=context_key,
    )

    selected_labels = flatten_selected_params(track_param_labels)

    if not selected_labels:
        st.info("Select parameters from the sidebar to display plots.")
        st.stop()

    parameter_ranges = render_parameter_range_controls(
        selected_labels=selected_labels,
        context_key=context_key,
    )

    with st.sidebar:
        st.subheader("Curve Source")
        curve_source = st.radio(
            "Values shown in Tracks 1–3",
            options=["Raw values", "Cleaned values"],
            index=0,
            key=f"curve_source_{context_key}",
            help=(
                "Raw values preserve the original sensor data. "
                "Cleaned values apply the dashboard cleaning rules. "
                "Agents always use cleaned values."
            ),
        )

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    # Also load all mapped columns so the diagnostic table can check them.
    # Without this, parameters like ROP may appear as "Missing raw column"
    # simply because they were not selected for plotting and not required by agents.
    diagnostic_columns = list(label_to_column.values())

    requested_columns = list(
        dict.fromkeys(requested_columns + diagnostic_columns)
    )

    df = load_sections_for_columns(
        well=selected_well,
        sections=selected_sections,
        requested_columns=tuple(requested_columns),
    )

    if df.empty:
        st.error("No data loaded. Check the parquet files in the data folder.")
        st.stop()

    with st.expander("Time sampling diagnostics — raw loaded data", expanded=False):
        st.caption(
            "This table shows the real timestamp spacing in the loaded data. "
            "Use it to check whether the source data is seconds-sampled or minute-sampled."
        )

        cadence_df = build_time_cadence_df(df)
        st.dataframe(cadence_df, width="stretch")

        if not cadence_df.empty:
            median_steps = pd.to_numeric(cadence_df["Median step sec"], errors="coerce")
            worst_median_step = median_steps.max()

            if pd.notna(worst_median_step) and worst_median_step > 30.0:
                st.warning(
                    "The selected data appears to be low-frequency or minute-range sampled. "
                    "Fast symptoms such as TRQErratic may not be detectable from this data."
                )
            else:
                st.success(
                    "The selected data is not minute-range sampled based on the median timestamp step. "
                    "If the chart still looks sparse, it is probably a plotting scale/downsampling issue."
                )

    context_cleaning_rules = build_context_cleaning_rules(
        selected_well=selected_well,
        selected_sections=selected_sections,
        global_rules=CLEANING_RULES,
        well_rules=WELL_CLEANING_RULES,
        section_rules=SECTION_CLEANING_RULES,
    )

    df, clean_label_to_column, cleaning_summary_df = apply_cleaning_layer(
        df=df,
        label_to_column=label_to_column,
        cleaning_rules=context_cleaning_rules,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
    )

    with st.expander("Parameter mapping diagnostics", expanded=False):
        st.caption(
            "This table checks whether each logical dashboard parameter is connected "
            "to the expected raw mnemonic and whether its values look physically reasonable."
        )

        mapping_diagnostic_df = build_mapping_diagnostic_df(
            df=df,
            label_to_column=label_to_column,
            parameter_catalog=PARAMETER_CATALOG,
        )

        st.dataframe(mapping_diagnostic_df, width="stretch")

        bad_rows = mapping_diagnostic_df[
            mapping_diagnostic_df["Status"].astype(str).ne("OK")
        ]

        if not bad_rows.empty:
            st.warning(
                "Some curves contain values outside the expected display/diagnostic range. "
                "This does not automatically mean wrong mapping. It may indicate sensor zero drift, "
                "unit mismatch, outliers, or valid high-range operation. Check both this table "
                "and the Data cleaning diagnostics table."
            )

        with st.expander("Data cleaning diagnostics", expanded=False):
            st.caption(
                "Raw data is preserved. The dashboard creates cleaned columns for agent logic. "
                "Small negative zero-drift values can be corrected to 0. Extreme impossible values become NaN."
            )

            if cleaning_summary_df.empty:
                st.info("No cleaning summary is available.")
            else:
                st.dataframe(cleaning_summary_df, width="stretch")

                changed_rows = cleaning_summary_df[
                    (
                        cleaning_summary_df["Zero drift corrected"]
                        .fillna(0)
                        .astype(int)
                        > 0
                    )
                    | (
                        cleaning_summary_df["Below hard min invalid"]
                        .fillna(0)
                        .astype(int)
                        > 0
                    )
                    | (
                        cleaning_summary_df["Above hard max invalid"]
                        .fillna(0)
                        .astype(int)
                        > 0
                    )
                    | (
                        cleaning_summary_df["Infinite invalid"]
                        .fillna(0)
                        .astype(int)
                        > 0
                    )
                ]

                if not changed_rows.empty:
                    st.warning(
                        "Some raw values were corrected or marked invalid for agent use. "
                        "The original raw columns are still preserved for visual review."
                    )

    time_range, zoom_percent = render_time_filter(df, context_key)

    # Keep the initial chart style fixed.
    # Users can still switch style using the Plotly buttons above the chart.
    marker_display = DEFAULT_MARKER_DISPLAY

    if time_range is None:
        st.warning("No valid time range is available.")
        st.stop()

    df = df.loc[pd.Timestamp(time_range[0]) : pd.Timestamp(time_range[1])].copy()

    if df.empty:
        st.warning("No data available in the selected time range.")
        st.stop()

    with st.expander("Time sampling diagnostics — selected time window", expanded=False):
        selected_cadence_df = build_time_cadence_df(df)
        st.dataframe(selected_cadence_df, width="stretch")

        chart_point_limit = get_target_points(zoom_percent)

        st.caption(
            f"Selected window contains {len(df):,} raw rows. "
            f"Current chart target is about {chart_point_limit:,} points per curve."
        )

        if len(df) > chart_point_limit:
            approx_step = max(1, len(df) // chart_point_limit)
            st.warning(
                f"The chart is visually downsampled because the selected window has more rows "
                f"than the plotting target. Roughly every {approx_step}th row may be shown per curve. "
                "Use a shorter precise time window to inspect second-by-second drilling behavior. "
                "The activity/symptom agents still run on the filtered dataframe, not on the displayed points."
            )


    # Apply visual tags created by chart dragging before Track 4 widgets render.
    # The chart JavaScript writes visual_tag_* query parameters after the user
    # drags in Tagging mode. This converts them into the normal Tagger lane state.
    apply_visual_tag_from_query_params(
        context_key=context_key,
        t_min=df.index.min(),
        t_max=df.index.max(),
        max_tags=50,
    )

    # Create sidebar containers in the visual order we want.
    # Track 4 will appear before the agent settings, even though the
    # agent settings are read first internally.
    review_controls_container = st.sidebar.container()

    agent_controls = render_agent_controls(
        df=df,
        context_key=context_key,
        parent=review_controls_container,
    )

    activity_ui = agent_controls["activity_ui"]
    symptom_ui = agent_controls["symptom_ui"]

    activity_cfg = run_activity_agent(
        df=df,
        label_to_column=clean_label_to_column,
        activity_ui=activity_ui,
    )

    if activity_ui["enabled"] and not activity_cfg["labels"].empty:
        df["activity"] = activity_cfg["labels"]

    symptom_cfg = run_symptom_agent(
        df=df,
        label_to_column=clean_label_to_column,
        symptom_ui=symptom_ui,
        activity_ui=activity_ui,
        activity_cfg=activity_cfg,
    )

    # This is visually placed above the agent settings because it is rendered
    # into review_controls_container, which was created first.
    agent_cfg = build_agent_cfg_from_controls(
        controls=agent_controls,
        activity_cfg=activity_cfg,
        symptom_cfg=symptom_cfg,
    )

    # Last-resort visual fallback for Symptom Agent Track 4.
    # If sidebar/official symptom intervals still produce nothing, build visual
    # intervals directly from the selected raw/cleaned curve using the same
    # interval-list drawing mechanism that already works for Activity Agent.
    if (
        agent_cfg.get("agent_source") == "Symptom agent"
        and not agent_cfg.get("agent_intervals", [])
    ):
        fallback_symptom_intervals = build_raw_curve_symptom_track4_intervals(
            df=df,
            label_to_column=clean_label_to_column,
            symptom_cfg=symptom_cfg,
        )

        if fallback_symptom_intervals:
            agent_cfg["agent_intervals"] = fallback_symptom_intervals
            agent_cfg["summary"] = _rebuild_track4_summary(
                tag_intervals=agent_cfg.get("tag_intervals", []),
                agent_intervals=fallback_symptom_intervals,
            )
            st.caption(
                f"Track 4 visual fallback: built {len(fallback_symptom_intervals)} "
                f"{symptom_cfg.get('selected_symptom', 'symptom')} intervals directly from the curve."
            )

    render_agent_review_outputs(
        agent_cfg=agent_cfg,
        context_key=context_key,
        parent=review_controls_container,
        selected_well=selected_well,
        selected_sections=selected_sections,
    )

    render_dashboard_header(
        selected_well=selected_well,
        selected_sections=selected_sections,
        review_mode=agent_cfg.get("review_mode", "Standard review"),
    )

    summary = agent_cfg.get("summary", {})
    render_review_caption(summary)

    activity_validation_df = build_activity_validation_df(
        agent_cfg.get("activity_validation_summary", {})
    )

    review_df = build_manual_review_df(summary)

    render_result_tables(
        activity_cfg=activity_cfg,
        symptom_cfg=symptom_cfg,
        activity_validation_df=activity_validation_df,
        review_df=review_df,
    )

    # Show the miss-reason table only for a fresh Symptom Agent review.
    # This prevents the table from carrying old agent results when the dashboard opens
    # or when the user is using Manual interval / Activity agent.
    show_symptom_miss_reason_table = (
        agent_cfg.get("agent_source") == "Symptom agent"
        and symptom_ui.get("enabled", False)
        and bool(agent_cfg.get("tag_intervals", []))
    )

    if show_symptom_miss_reason_table:
        professional_review_df = build_professional_symptom_review_df(
            tag_intervals=agent_cfg.get("tag_intervals", []),
            symptom_cfg=symptom_cfg,
            activity_cfg=activity_cfg,
            df_index=df.index,
        )

        boss_presentation_df = build_boss_symptom_presentation_df(
            tag_intervals=agent_cfg.get("tag_intervals", []),
            symptom_cfg=symptom_cfg,
            selected_well=selected_well,
            selected_sections=selected_sections,
        )

        boss_excel_bytes = build_boss_symptom_presentation_excel(
            boss_df=boss_presentation_df,
            professional_df=professional_review_df,
        )

        boss_table_key = (
            "boss_symptom_presentation_"
            f"{context_key}_"
            f"{agent_cfg.get('agent_source')}_"
            f"{symptom_cfg.get('selected_symptom', '')}_"
            f"{len(agent_cfg.get('tag_intervals', []))}_"
            f"{len(symptom_cfg.get('intervals', []))}_"
            f"{hash(str(agent_cfg.get('tag_intervals', [])))}_"
            f"{hash(str(symptom_cfg.get('intervals', [])))}"
        )

        with st.expander(
            "Presentation 1 — simple agent result summary",
            expanded=False,
        ):
            st.caption(
                "Boss-friendly summary. One selected symptom at a time. "
                "This table compares manual tag intervals against selected agent intervals."
            )

            st.markdown(
                f"**Symptom:** {symptom_cfg.get('selected_symptom', '')}  \n"
                f"**Well:** {selected_well}  \n"
                f"**Section:** {', '.join(f'{str(sec)} in' for sec in selected_sections)}"
            )

            st.dataframe(
                boss_presentation_df,
                width="stretch",
                key=boss_table_key,
            )

            st.download_button(
                "Download Presentation 1 Excel",
                data=boss_excel_bytes,
                file_name=(
                    f"agent_presentation_"
                    f"{selected_well}_"
                    f"{'_'.join(str(sec).replace('.', '_') for sec in selected_sections)}_"
                    f"{symptom_cfg.get('selected_symptom', '')}.xlsx"
                ),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"download_boss_presentation_excel_{boss_table_key}",
            )

        if not professional_review_df.empty:
            with st.expander(
                "Detailed evaluation table",
                expanded=False,
            ):
                st.caption(
                    "Detailed evaluation remains here and in the second Excel sheet. "
                    "Track 4 remains visually clean: Tagger, Overlap, Agent."
                )

                st.dataframe(
                    professional_review_df,
                    width="stretch",
                    key=f"detailed_{boss_table_key}",
                )

    if (
        agent_cfg.get("agent_source") == "Symptom agent"
        and symptom_cfg.get("selected_symptom") == "TRQSpike"
        and not symptom_cfg.get("features", pd.DataFrame()).empty
    ):
        trq_spike_eval_df = build_trq_spike_evaluation_df(symptom_cfg)

        with st.expander(
            "TRQSpike agent result for evaluation — Ratio and z-value",
            expanded=False,
        ):
            st.caption(
                "This table prints the TRQ Ratio and TRQ z-value used by the TRQSpike agent. "
                "Use it to evaluate whether the ratio and z-score thresholds should be adjusted. "
                "Prev. TRQ Std Dev means previous torque standard deviation."
            )

            st.dataframe(
                trq_spike_eval_df,
                width="stretch",
                key=f"trq_spike_eval_{context_key}_{len(trq_spike_eval_df)}",
            )

    if symptom_cfg and not symptom_cfg.get("features", pd.DataFrame()).empty:
        with st.expander("Selected symptom debug features", expanded=False):
            st.dataframe(
                symptom_cfg["features"].tail(1000),
                width="stretch",
            )

    section_ranges = compute_section_ranges(df, list(selected_sections))

    track_colors = [
        TRACK_COLOR_PALETTE[: len(params)]
        for params in track_param_labels
    ]

    plot_label_to_column = (
        clean_label_to_column
        if curve_source == "Cleaned values"
        else label_to_column
    )

    track_params_real = [
        [
            plot_label_to_column[label]
            for label in track
            if label in plot_label_to_column
        ]
        for track in track_param_labels
    ]

    track_params_real = track_params_real + [[]]
    track_param_labels = track_param_labels + [[]]
    track_colors = track_colors + [[]]

    fig = create_multi_track_chart(
        df=df,
        track_params=track_params_real,
        track_param_labels=track_param_labels,
        track_colors=track_colors,
        zoom_percent=zoom_percent,
        section_ranges=section_ranges,
        agent_cfg=agent_cfg,
        chart_height=agent_cfg.get("chart_height", 950),
        parameter_ranges=parameter_ranges,
        marker_display=marker_display,
        curve_source=curve_source,
    )

    chart_key = f"multi_track_chart_{context_key}"

    render_chart(
        fig,
        chart_key,
        visual_tag_context_key=context_key,
    )

    commit_undo_tracking()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        st.error("Dashboard crashed. Full Python traceback is shown below.")
        st.exception(e)

        print("\n\n========== DASHBOARD CRASH TRACEBACK ==========")
        print(traceback.format_exc())
        print("========== END DASHBOARD CRASH TRACEBACK ==========\n\n")

        raise
