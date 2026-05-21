import gc

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
    load_section_time_index,
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
    render_window_pager,
    render_track_parameter_selector,
    render_well_section_selector,
    apply_visual_tag_from_query_params,
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


def _build_fixed_time_windows_from_index(time_index, window_hours: int = 12) -> list[dict]:
    """
    Build the same fixed backend windows used by the sidebar pager.
    Only timestamps are used here; no curve data is loaded.
    """
    if time_index is None or len(time_index) == 0:
        return []

    t_min = pd.Timestamp(time_index.min())
    t_max = pd.Timestamp(time_index.max())

    if pd.isna(t_min) or pd.isna(t_max) or t_max <= t_min:
        return []

    window_delta = pd.Timedelta(hours=int(window_hours))
    total_sec = max((t_max - t_min).total_seconds(), 1.0)
    n_windows = max(1, int(total_sec // window_delta.total_seconds()))
    if t_min + n_windows * window_delta < t_max:
        n_windows += 1

    windows = []
    for idx in range(n_windows):
        start = t_min + idx * window_delta
        end = min(start + window_delta, t_max)
        if end > start:
            windows.append({"index": idx, "start": start, "end": end})

    return windows


@st.cache_data(show_spinner="Computing section-wide symptom intervals …", max_entries=4)
def build_section_wide_symptom_intervals(
    well: str,
    sections: tuple[str, ...],
    windows: tuple[tuple[str, str], ...],
    requested_columns: tuple[str, ...],
    label_to_column: dict,
    cleaning_rules: dict,
    required_activity_labels: tuple[str, ...],
    required_symptom_labels: tuple[str, ...],
    activity_enabled: bool,
    selected_activity: str,
    activity_config,
    symptom_enabled: bool,
    selected_symptom: str,
    symptom_config,
) -> list[dict]:
    """
    Compute selected symptom-agent intervals for the whole section without
    keeping the full section dataframe in memory.

    The function loops through the same 12-hour windows, loads one window,
    runs cleaning + activity + symptom agents, stores only interval rows, then
    deletes the dataframe before moving to the next window.
    """
    if not activity_enabled or not symptom_enabled or not windows:
        return []

    all_intervals: list[dict] = []

    activity_ui = {
        "enabled": bool(activity_enabled),
        "selected_activity": selected_activity,
        "config": activity_config,
    }
    symptom_ui = {
        "enabled": bool(symptom_enabled),
        "selected_symptom": selected_symptom,
        "config": symptom_config,
    }

    for win_idx, (start_text, end_text) in enumerate(windows, start=1):
        df_part = load_sections_for_columns(
            well=well,
            sections=sections,
            requested_columns=requested_columns,
            time_start=start_text,
            time_end=end_text,
        )

        if df_part.empty:
            continue

        df_part, clean_label_to_column_part, _ = apply_cleaning_layer(
            df=df_part,
            label_to_column=label_to_column,
            cleaning_rules=cleaning_rules,
            required_activity_labels=list(required_activity_labels),
            required_symptom_labels=list(required_symptom_labels),
        )

        activity_cfg_part = run_activity_agent(
            df=df_part,
            label_to_column=clean_label_to_column_part,
            activity_ui=activity_ui,
        )

        symptom_cfg_part = run_symptom_agent(
            df=df_part,
            label_to_column=clean_label_to_column_part,
            symptom_ui=symptom_ui,
            activity_ui=activity_ui,
            activity_cfg=activity_cfg_part,
        )

        for item in symptom_cfg_part.get("intervals", []) or []:
            row = dict(item)
            row["window"] = win_idx
            row["window_start"] = start_text
            row["window_end"] = end_text
            all_intervals.append(row)

        del df_part, activity_cfg_part, symptom_cfg_part
        gc.collect()

    all_intervals.sort(key=lambda x: pd.Timestamp(x.get("start")))
    return all_intervals



def _normalize_track_selection_payload(value) -> list[list[str]]:
    """Return exactly three track-selection lists from saved/session data."""
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


def _infer_track_params_from_loaded_payload(context_key: str, label_to_column: dict[str, str]) -> list[list[str]]:
    """
    Recover plot selections from an uploaded dashboard session.

    New saved sessions contain saved_track_param_labels_<context>. Older sessions
    may only contain track_params_* widget keys. The user's uploaded example has
    empty track_params but still has max_override_TRQ/RPMB keys, so we also use
    those raw mnemonics as a last-resort compatibility hint.
    """
    payload = st.session_state.get(f"_pending_loaded_review_payload_{context_key}")
    if not isinstance(payload, dict):
        return [[], [], []]

    widget_state = (payload.get("dashboard_state", {}) or {}).get("widget_state", {}) or {}

    candidates = [
        payload.get("plot_track_param_labels"),
        (payload.get("dashboard_state", {}) or {}).get("plot_track_param_labels"),
        widget_state.get(f"saved_track_param_labels_{context_key}"),
        widget_state.get(f"plot_track_param_labels_{context_key}"),
    ]

    for candidate in candidates:
        restored = _normalize_track_selection_payload(candidate)
        if any(restored):
            return restored

    restored = _normalize_track_selection_payload([
        widget_state.get(f"track_params_1_{context_key}", []),
        widget_state.get(f"track_params_2_{context_key}", []),
        widget_state.get(f"track_params_3_{context_key}", []),
    ])
    if any(restored):
        return restored

    # Last-resort compatibility for older saved sessions where the track widgets
    # were saved empty but parameter scale controls reveal what was plotted.
    raw_to_label = {str(raw): label for label, raw in (label_to_column or {}).items()}
    inferred_labels: list[str] = []
    suffix = f"_{context_key}"
    for key in widget_state:
        key = str(key)
        if not key.startswith("max_override_") or not key.endswith(suffix):
            continue
        raw_col = key[len("max_override_") : -len(suffix)]
        label = raw_to_label.get(raw_col)
        if label and label not in inferred_labels:
            inferred_labels.append(label)

    if inferred_labels:
        tracks = [[], [], []]
        for idx, label in enumerate(inferred_labels[:9]):
            tracks[min(idx, 2)].append(label)
        return tracks

    return [[], [], []]


def _remember_track_params_for_save(context_key: str, track_param_labels: list[list[str]]):
    """Store current plot selections under non-widget keys so JSON save/load is reliable."""
    safe_tracks = _normalize_track_selection_payload(track_param_labels)
    if any(safe_tracks):
        # These keys intentionally do not start with '_' so _build_full_dashboard_state()
        # saves them into the dashboard session JSON.
        st.session_state[f"saved_track_param_labels_{context_key}"] = safe_tracks
        st.session_state[f"plot_track_param_labels_{context_key}"] = safe_tracks


def _restore_track_params_after_window_change(
    track_param_labels,
    context_key: str,
    label_to_column: dict[str, str] | None = None,
):
    """
    Keep selected plot parameters when browsing 12-hour windows and after loading
    a saved dashboard session.

    Streamlit does not allow assigning to a widget key after that widget has
    already been instantiated in the same run. Therefore this helper returns the
    restored selections to the plotting pipeline and saves them under separate
    non-widget keys for future JSON export.
    """
    memory_key = f"_last_nonempty_track_params_{context_key}"
    changed_key = f"_window_changed_{context_key}"

    safe_tracks = _normalize_track_selection_payload(track_param_labels)
    has_selection = any(bool(track) for track in safe_tracks)

    if has_selection:
        st.session_state[memory_key] = [list(track) for track in safe_tracks]
        _remember_track_params_for_save(context_key, safe_tracks)
        st.session_state[changed_key] = False
        return safe_tracks

    remembered = st.session_state.get(memory_key)
    remembered_tracks = _normalize_track_selection_payload(remembered)
    if any(remembered_tracks):
        _remember_track_params_for_save(context_key, remembered_tracks)
        st.session_state[changed_key] = False
        return remembered_tracks

    loaded_tracks = _infer_track_params_from_loaded_payload(
        context_key=context_key,
        label_to_column=label_to_column or {},
    )
    if any(loaded_tracks):
        st.session_state[memory_key] = [list(track) for track in loaded_tracks]
        _remember_track_params_for_save(context_key, loaded_tracks)
        st.session_state[changed_key] = False
        return loaded_tracks

    st.session_state[changed_key] = False
    return safe_tracks



def _safe_html_id(value: str) -> str:
    """Return a browser-safe id fragment."""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def _render_scroll_to_chart_top_once(context_key: str):
    """
    After a 12-hour window navigation click, scroll the browser back to the
    top of the newly loaded plot.

    The scroll flag is set by the bottom Previous/Next buttons and consumed
    once here after the new Streamlit run has rendered the chart anchor.
    """
    flag_key = f"_scroll_to_chart_top_{context_key}"
    if not st.session_state.pop(flag_key, False):
        return

    anchor_id = f"chart_top_anchor_{_safe_html_id(context_key)}"
    components.html(
        f"""
        <script>
        (function() {{
            function scrollToChartTop() {{
                try {{
                    const parentDoc = window.parent.document;
                    const anchor = parentDoc.getElementById({anchor_id!r});
                    if (anchor) {{
                        anchor.scrollIntoView({{behavior: "smooth", block: "start"}});
                        return;
                    }}

                    const appView = parentDoc.querySelector('[data-testid="stAppViewContainer"]');
                    if (appView && appView.scrollTo) {{
                        appView.scrollTo({{top: 0, behavior: "smooth"}});
                        return;
                    }}
                }} catch (e) {{}}

                try {{
                    window.parent.scrollTo({{top: 0, behavior: "smooth"}});
                }} catch (e2) {{}}
            }}

            setTimeout(scrollToChartTop, 250);
            setTimeout(scrollToChartTop, 900);
        }})();
        </script>
        """,
        height=0,
    )


def render_bottom_window_navigation(window_info: dict, context_key: str):
    """
    Show Previous/Next controls directly below the four-track chart.

    The active data loading remains controlled by render_window_pager(), but
    these bottom buttons change the same window_index_<context_key> value.
    """
    if not window_info:
        return

    index_key = f"window_index_{context_key}"
    current_index = int(window_info.get("index", st.session_state.get(index_key, 0)))
    window_count = int(window_info.get("count", 1))
    start = pd.Timestamp(window_info.get("start"))
    end = pd.Timestamp(window_info.get("end"))

    st.markdown(
        """
        <style>
            div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) {
                margin-top: -0.25rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_prev, col_status, col_next = st.columns([1.2, 2.0, 1.2])

    with col_prev:
        if st.button(
            "⬅ Previous window",
            key=f"bottom_window_prev_{context_key}",
            disabled=current_index <= 0,
            width="stretch",
        ):
            st.session_state[index_key] = max(0, current_index - 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.session_state[f"_scroll_to_chart_top_{context_key}"] = True
            st.rerun()

    with col_status:
        st.markdown(
            f"<div style='text-align:center; color:#555; font-size:0.92rem; padding-top:0.45rem;'>"
            f"Window {current_index + 1} / {window_count}: "
            f"{start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_next:
        if st.button(
            "Next window ➡",
            key=f"bottom_window_next_{context_key}",
            disabled=current_index >= window_count - 1,
            width="stretch",
        ):
            st.session_state[index_key] = min(window_count - 1, current_index + 1)
            st.session_state[f"_window_changed_{context_key}"] = True
            st.session_state[f"_scroll_to_chart_top_{context_key}"] = True
            st.rerun()

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
        pending_payload_key = f"_pending_loaded_review_payload_{context_key}"

        # The loader returns a payload only once per uploaded-file content hash.
        # Therefore it is safe and more reliable to apply it whenever it is returned.
        # This avoids the old problem where _loaded_review_restored_done_<context>
        # blocked a newly uploaded file from being applied.
        st.session_state[pending_payload_key] = loaded_review_payload

        apply_loaded_dashboard_state_early(
            uploaded_data=loaded_review_payload,
            context_key=context_key,
        )

        # A saved dashboard file was uploaded for this context. This flag lets
        # the chart restore saved/browser zoom only for loaded sessions, while
        # a fresh app restart starts from the unzoomed/default view.
        st.session_state[f"_loaded_dashboard_active_{context_key}"] = True

    time_df = load_section_time_index(
        well=selected_well,
        sections=selected_sections,
    )

    window_info = render_window_pager(
        time_df=time_df,
        context_key=context_key,
        window_hours=12,
    )

    if window_info is None:
        st.warning("No valid 12-hour time window is available for the selected section.")
        st.stop()

    selected_time_window = (window_info["start"], window_info["end"])
    plot_context_key = window_info["plot_context_key"]
    zoom_percent = 100.0
    
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

    # Columns needed to compute data-agent intervals. This is intentionally
    # separate from plot/diagnostic columns so the section-wide interval table
    # can be built window-by-window without loading unnecessary plot columns.
    section_agent_requested_columns = build_requested_columns(
        selected_labels=[],
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

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

    # If a saved dashboard session was uploaded and its normal track_params
    # widget values were empty in the JSON, recover the plot selections before
    # the multiselect widgets are created. This makes restored parameters both
    # visible in the sidebar and available for plotting.
    restored_tracks_before_widget = _infer_track_params_from_loaded_payload(
        context_key=context_key,
        label_to_column=label_to_column,
    )
    if any(restored_tracks_before_widget):
        for idx in range(3):
            widget_key = f"track_params_{idx + 1}_{context_key}"
            current_value = st.session_state.get(widget_key, [])
            if not current_value:
                st.session_state[widget_key] = restored_tracks_before_widget[idx]
        _remember_track_params_for_save(context_key, restored_tracks_before_widget)

    # Keep parameter selections section-level, not window-level.
    # When the user moves to the next/previous 12-hour window, the same
    # previously selected parameters are plotted automatically for the new window.
    track_param_labels = render_track_parameter_selector(
        available_param_labels=available_param_labels,
        context_key=context_key,
    )

    track_param_labels = _restore_track_params_after_window_change(
        track_param_labels=track_param_labels,
        context_key=context_key,
        label_to_column=label_to_column,
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
        time_start=selected_time_window[0],
        time_end=selected_time_window[1],
    )

    if df.empty:
        st.error("No data loaded. Check the parquet files in the data folder.")
        st.stop()

    if st.session_state.get("_show_hidden_time_sampling_raw", False):
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

    if st.session_state.get("_show_hidden_parameter_mapping_diagnostics", False):
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
    
    # The dataframe has already been loaded only for the selected fixed 12-hour window.
    # No secondary time filter and no downsampling are used.
    marker_display = DEFAULT_MARKER_DISPLAY

    # Consume chart-drawn tag URL payloads before Track 4 controls and the Plotly
    # figure are built. Tags are stored as section-level absolute timestamps.
    apply_visual_tag_from_query_params(
        context_key=context_key,
        t_min=df.index.min(),
        t_max=df.index.max(),
    )

    if st.session_state.get("_show_hidden_time_sampling_window", False):
        with st.expander("Time sampling diagnostics — selected 12-hour window", expanded=False):
            selected_cadence_df = build_time_cadence_df(df)
            st.dataframe(selected_cadence_df, width="stretch")
    
            st.caption(
                f"Selected 12-hour window contains {len(df):,} raw rows. "
                "No dashboard downsampling is applied; every loaded point is plotted."
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

    # Build section-wide selected symptom intervals for the table only.
    # This does NOT change Track 4 and does NOT load/plot the whole section.
    # It loops over 12-hour windows, stores only interval rows, and releases
    # each temporary dataframe before moving to the next window.
    section_windows = _build_fixed_time_windows_from_index(
        time_df.index,
        window_hours=12,
    )
    section_window_tuple = tuple(
        (
            item["start"].strftime("%Y-%m-%d %H:%M:%S"),
            item["end"].strftime("%Y-%m-%d %H:%M:%S"),
        )
        for item in section_windows
    )

    section_wide_symptom_intervals = build_section_wide_symptom_intervals(
        well=selected_well,
        sections=selected_sections,
        windows=section_window_tuple,
        requested_columns=tuple(section_agent_requested_columns),
        label_to_column=label_to_column,
        cleaning_rules=context_cleaning_rules,
        required_activity_labels=tuple(required_activity_labels),
        required_symptom_labels=tuple(required_symptom_labels),
        activity_enabled=bool(activity_ui.get("enabled", False)),
        selected_activity=str(activity_ui.get("selected_activity", "All activities")),
        activity_config=activity_ui.get("config"),
        symptom_enabled=bool(symptom_ui.get("enabled", False)),
        selected_symptom=str(symptom_ui.get("selected_symptom", "")),
        symptom_config=symptom_ui.get("config"),
    )

    symptom_table_cfg = dict(symptom_cfg)
    symptom_table_cfg["intervals"] = section_wide_symptom_intervals
    symptom_table_cfg["interval_scope"] = "Full selected section, computed window-by-window"

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
        symptom_cfg=symptom_table_cfg,
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
        if st.session_state.get("_show_hidden_selected_symptom_debug", False):
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

    saved_hit_results = st.session_state.get(f"hit_result_history_{context_key}", [])

    chart_anchor_id = f"chart_top_anchor_{_safe_html_id(context_key)}"
    st.markdown(
        f'<div id="{chart_anchor_id}" style="scroll-margin-top: 0.75rem;"></div>',
        unsafe_allow_html=True,
    )

    render_chart(
        fig,
        chart_key,
        visual_tag_context_key=context_key,
        restore_saved_browser_zoom=False,
        current_window_start=selected_time_window[0],
        current_window_end=selected_time_window[1],
        saved_hit_results=saved_hit_results,
    )

    render_bottom_window_navigation(window_info=window_info, context_key=context_key)
    _render_scroll_to_chart_top_once(context_key)

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

