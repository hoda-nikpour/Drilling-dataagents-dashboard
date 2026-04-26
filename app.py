import pandas as pd
import streamlit as st

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS
from config import DEFAULT_MARKER_DISPLAY, PARAMETER_ALIASES, PARAMETER_CATALOG, TRACK_COLOR_PALETTE
from data_access.data_loader import (
    get_available_numeric_columns,
    load_catalog,
    load_sections_for_columns,
)
from services.dashboard_service import (
    build_label_to_column_map,
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


st.set_page_config(layout="wide", initial_sidebar_state="expanded")
apply_global_styles()


def main():
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
    label_to_column = build_label_to_column_map(
        discovered_params=discovered_params,
        parameter_aliases=PARAMETER_ALIASES,
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
            use_container_width=True,
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

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    df = load_sections_for_columns(
        well=selected_well,
        sections=selected_sections,
        requested_columns=tuple(requested_columns),
    )

    if df.empty:
        st.error("No data loaded. Check the parquet files in the data folder.")
        st.stop()

    time_range, zoom_percent = render_time_filter(df, context_key)

    # Keep the initial chart style fixed.
    # Users can still switch style using the Plotly buttons above the chart.
    marker_display = DEFAULT_MARKER_DISPLAY
        
    # Create sidebar containers in the visual order we want.
    # Track 4 will appear before the agent settings, even though the
    # agent settings are read first internally.
    df = df.loc[pd.Timestamp(time_range[0]) : pd.Timestamp(time_range[1])]
    if df.empty:
        st.warning("No data available in the selected time range.")
        st.stop()
        
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
        label_to_column=label_to_column,
        activity_ui=activity_ui,
    )

    if activity_ui["enabled"] and not activity_cfg["labels"].empty:
        df["activity"] = activity_cfg["labels"]

    symptom_cfg = run_symptom_agent(
        df=df,
        label_to_column=label_to_column,
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

    section_ranges = compute_section_ranges(df, list(selected_sections))

    track_colors = [TRACK_COLOR_PALETTE[: len(params)] for params in track_param_labels]

    track_params_real = [
        [label_to_column[label] for label in track if label in label_to_column]
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
)

    chart_key = f"multi_track_chart_{context_key}"
    render_chart(fig, chart_key)


if __name__ == "__main__":
    main()