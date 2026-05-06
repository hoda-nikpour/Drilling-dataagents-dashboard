import pandas as pd
import streamlit as st

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS

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
    build_activity_validation_df,
    build_agent_cfg_from_controls,
    build_manual_review_df,
    build_symptom_miss_reason_df,
    build_trq_spike_evaluation_df,
    render_agent_controls,
    render_agent_review_outputs,
    render_parameter_range_controls,
    render_time_filter,
    render_track_parameter_selector,
    render_well_section_selector,
)

from ui.styles import apply_global_styles
from utils.helpers import compute_section_ranges
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
    selected_well, selected_sections = render_well_section_selector(sections_by_well)

    if not selected_sections:
        st.warning("Please select at least one section from the sidebar.")
        st.stop()

    selected_sections = tuple(sorted(selected_sections, key=float))
    context_key = make_context_key(selected_well, selected_sections)

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

    with st.expander("Parameter mapping diagnostics", expanded=True):
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

        with st.expander("Data cleaning diagnostics", expanded=True):
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

    render_agent_review_outputs(
        agent_cfg=agent_cfg,
        context_key=context_key,
        parent=review_controls_container,
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
        symptom_miss_reason_df = build_symptom_miss_reason_df(
            tag_intervals=agent_cfg.get("tag_intervals", []),
            symptom_cfg=symptom_cfg,
            activity_cfg=activity_cfg,
        )

        # This key changes whenever tags or symptom-agent results change.
        # Streamlit will fully remount the dataframe instead of reusing old cells.
        miss_reason_table_key = (
            "symptom_miss_reason_"
            f"{context_key}_"
            f"{agent_cfg.get('agent_source')}_"
            f"{symptom_cfg.get('selected_symptom', '')}_"
            f"{len(agent_cfg.get('tag_intervals', []))}_"
            f"{len(symptom_cfg.get('intervals', []))}_"
            f"{hash(str(agent_cfg.get('tag_intervals', [])))}_"
            f"{hash(str(symptom_cfg.get('intervals', [])))}"
        )

        if not symptom_miss_reason_df.empty:
            with st.expander(
                "Why selected symptom agent did or did not hit manual tags",
                expanded=True,
            ):
                st.dataframe(
                    symptom_miss_reason_df,
                    width="stretch",
                    key=miss_reason_table_key,
                )

    if (
        agent_cfg.get("agent_source") == "Symptom agent"
        and symptom_cfg.get("selected_symptom") == "TRQSpike"
        and not symptom_cfg.get("features", pd.DataFrame()).empty
    ):
        trq_spike_eval_df = build_trq_spike_evaluation_df(symptom_cfg)

        with st.expander(
            "TRQSpike agent result for evaluation — Ratio and z-value",
            expanded=True,
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

    render_chart(fig, chart_key)

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