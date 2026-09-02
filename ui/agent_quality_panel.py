"""Optional Streamlit panel for manually exercising the boss-feedback improvements.

Usage from app.py after your drilling dataframe has been loaded::

    from ui.agent_quality_panel import render_agent_quality_panel
    improved_df, pressure_events = render_agent_quality_panel(df)

The panel lets you select the actual column names, so it does not depend on a
particular WITS/WITSML mnemonic convention.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from agents.activity_temporal import (
    TemporalActivityConfig,
    resolve_activity_temporally,
    transition_table,
)
from agents.adjusted_pressure import (
    AdjustedPressureConfig,
    detect_adjusted_pressure_spikes,
    pressure_event_table,
)
from services.agent_validation import activity_metrics, binary_metrics


def _guess_column(columns: list[str], aliases: tuple[str, ...]) -> int:
    lower = [str(c).lower() for c in columns]
    for alias in aliases:
        for i, col in enumerate(lower):
            if alias == col or alias in col:
                return i
    return 0


def render_agent_quality_panel(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Render a self-contained manual evaluation panel.

    Returns
    -------
    improved_df, pressure_events
        The dataframe includes resolved activity and adjusted-pressure diagnostics.
    """
    if df.empty:
        st.info("No data available for agent evaluation.")
        return df.copy(), pd.DataFrame()

    st.header("Agent improvements / validation")
    st.caption(
        "Implements temporal activity states + backdating, flow-normalised SPP, "
        "and labelled confusion-matrix validation."
    )

    columns = [str(c) for c in df.columns]

    with st.expander("1) Activity state model and backdating", expanded=True):
        raw_activity_col = st.selectbox(
            "Instantaneous activity column from the existing agent",
            columns,
            index=_guess_column(columns, ("activity", "activity_raw", "activity_code")),
            key="quality_raw_activity_col",
        )
        c1, c2, c3 = st.columns(3)
        confirm_samples = c1.number_input("Likely transition confirmation", 1, 100, 3)
        override_samples = c2.number_input(
            "Unusual transition confirmation", int(confirm_samples), 500, max(8, int(confirm_samples))
        )
        max_backdate = c3.number_input("Max backdate samples", 1, 1000, 30)

        act_cfg = TemporalActivityConfig(
            confirm_samples=int(confirm_samples),
            override_confirm_samples=int(override_samples),
            max_backdate_samples=int(max_backdate),
        )
        improved = resolve_activity_temporally(
            df,
            raw_activity_col=raw_activity_col,
            config=act_cfg,
        )

        changed = int((improved[raw_activity_col].astype(str) != improved["activity_resolved"]).sum())
        provisional = int(improved["activity_is_provisional"].sum())
        m1, m2 = st.columns(2)
        m1.metric("Rows reconsidered/reclassified", changed)
        m2.metric("Rows still provisional", provisional)
        st.dataframe(transition_table(), use_container_width=True, hide_index=True)

        truth_activity_candidates = ["(none)"] + columns
        truth_activity = st.selectbox(
            "Optional labelled/ground-truth activity column",
            truth_activity_candidates,
            index=0,
            key="quality_truth_activity",
        )
        if truth_activity != "(none)":
            summary, cm, per_class = activity_metrics(
                improved[truth_activity], improved["activity_resolved"]
            )
            st.write("Activity summary", summary)
            st.write("Activity confusion matrix")
            st.dataframe(cm, use_container_width=True)
            st.write("Per-activity metrics")
            st.dataframe(per_class, use_container_width=True, hide_index=True)

    with st.expander("2) Adjusted-pressure spike agent", expanded=True):
        spp_col = st.selectbox(
            "Standpipe pressure (SPP) column",
            columns,
            index=_guess_column(columns, ("spp", "standpipe", "stand pipe")),
            key="quality_spp_col",
        )
        mfi_col = st.selectbox(
            "Mud flow-in (MFI) column",
            columns,
            index=_guess_column(columns, ("mfi", "flow in", "flowin", "mud flow")),
            key="quality_mfi_col",
        )
        timestamp_options = ["(index)"] + columns
        timestamp_col = st.selectbox(
            "Timestamp column (for event table)",
            timestamp_options,
            key="quality_timestamp_col",
        )

        p1, p2, p3, p4 = st.columns(4)
        exponent = p1.number_input("MFI exponent", 0.1, 4.0, 1.75, 0.05)
        window = p2.number_input("Baseline window", 10, 10000, 120)
        z_threshold = p3.number_input("Robust z threshold", 1.0, 20.0, 4.0, 0.25)
        min_mfi = p4.number_input("Minimum MFI (pump-on)", 0.0, 100000.0, 1.0)

        p5, p6 = st.columns(2)
        min_relative_dev = p5.number_input(
            "Minimum relative adjusted-pressure rise",
            0.0,
            2.0,
            0.05,
            0.01,
            help="0.05 = 5% above robust adjusted-pressure baseline.",
        )
        min_consecutive = p6.number_input("Minimum consecutive anomaly samples", 1, 100, 2)
        min_periods = min(30, int(window))

        pressure_cfg = AdjustedPressureConfig(
            exponent=float(exponent),
            baseline_window=int(window),
            min_periods=int(min_periods),
            robust_z_threshold=float(z_threshold),
            min_relative_deviation=float(min_relative_dev),
            min_mfi=float(min_mfi),
            min_consecutive=int(min_consecutive),
        )
        improved = detect_adjusted_pressure_spikes(
            improved,
            spp_col=spp_col,
            mfi_col=mfi_col,
            config=pressure_cfg,
        )
        events = pressure_event_table(
            improved,
            timestamp_col=None if timestamp_col == "(index)" else timestamp_col,
            spp_col=spp_col,
            mfi_col=mfi_col,
        )

        a, b, c = st.columns(3)
        a.metric("Adjusted-pressure events", len(events))
        b.metric("Adjusted candidate samples", int(improved["pressure_spike_candidate"].sum()))
        c.metric("Raw-SPP candidate samples (comparison)", int(improved["raw_spp_spike_candidate"].sum()))

        st.line_chart(improved[["adjusted_pressure", "adjusted_pressure_baseline"]])
        st.dataframe(events, use_container_width=True, hide_index=True)

        truth_pressure_candidates = ["(none)"] + columns
        truth_pressure = st.selectbox(
            "Optional labelled/ground-truth pressure-event column",
            truth_pressure_candidates,
            index=0,
            key="quality_truth_pressure",
        )
        if truth_pressure != "(none)":
            metrics = binary_metrics(improved[truth_pressure], improved["pressure_spike"])
            st.json(metrics.as_dict())

    with st.expander("3) Export improved rows", expanded=False):
        st.dataframe(
            improved[
                [
                    raw_activity_col,
                    "activity_resolved",
                    "activity_transition_status",
                    spp_col,
                    mfi_col,
                    "adjusted_pressure",
                    "adjusted_pressure_robust_z",
                    "pressure_spike",
                ]
            ].tail(500),
            use_container_width=True,
        )

    return improved, events


def render_agent_quality_panel_from_globals(namespace: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Find DataFrames already created by ``app.py`` and open the manual panel.

    This helper is intended for a low-risk first integration into an existing
    Streamlit dashboard whose main dataframe variable name is not known in
    advance.  Add this call near the END of ``app.py``::

        improved_df, pressure_events = render_agent_quality_panel_from_globals(globals())

    If several DataFrames exist, the dashboard shows a selector.  The original
    dataframe is not overwritten; the returned ``improved_df`` contains the
    new activity/pressure columns.
    """
    candidates: list[tuple[str, pd.DataFrame]] = []
    seen_ids: set[int] = set()

    def add_candidate(name: str, value: object) -> None:
        if isinstance(value, pd.DataFrame) and not value.empty and id(value) not in seen_ids:
            candidates.append((name, value))
            seen_ids.add(id(value))

    # First inspect top-level variables created by app.py.
    for name, value in namespace.items():
        if name.startswith("_"):
            continue
        add_candidate(name, value)

    # Many Streamlit dashboards keep the loaded data in session_state rather
    # than a top-level variable, so include those DataFrames automatically too.
    try:
        for key, value in st.session_state.items():
            add_candidate(f"st.session_state[{key!r}]", value)
    except Exception:
        # Session state may not be available in non-Streamlit test contexts.
        pass

    if not candidates:
        st.warning(
            "Boss-feedback panel could not find a non-empty pandas DataFrame in app.py. "
            "Move the render_agent_quality_panel_from_globals(globals()) call lower in "
            "app.py, after the drilling data has been loaded."
        )
        return pd.DataFrame(), pd.DataFrame()

    # Put larger frames first; these are more likely to be the drilling time series
    # than tiny summary/event tables.
    candidates.sort(key=lambda item: (len(item[1]), len(item[1].columns)), reverse=True)
    names = [name for name, _ in candidates]
    selected_name = st.selectbox(
        "Dashboard dataframe to evaluate",
        names,
        index=0,
        key="boss_feedback_dataframe_selector",
        help="Choose the main time-series dataframe loaded by your dashboard.",
    )
    selected_df = dict(candidates)[selected_name]
    st.caption(
        f"Using `{selected_name}`: {len(selected_df):,} rows × "
        f"{len(selected_df.columns):,} columns"
    )
    return render_agent_quality_panel(selected_df)
