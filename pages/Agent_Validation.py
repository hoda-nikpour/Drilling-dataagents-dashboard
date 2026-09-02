import pandas as pd
import streamlit as st

from ui.agent_quality_panel import render_agent_quality_panel


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Agent Validation",
    page_icon="🧪",
    layout="wide",
)


# ============================================================
# PAGE HEADER
# ============================================================

st.title("Agent Validation")

st.caption(
    "Development and validation tools for activity-state transitions, "
    "activity backdating, flow-normalised standpipe pressure, and "
    "agent performance evaluation."
)


# ============================================================
# GET CURRENT DASHBOARD DATA
# ============================================================

df = st.session_state.get("agent_validation_df")

context = st.session_state.get(
    "agent_validation_context",
    {},
)


# ============================================================
# NO DATA AVAILABLE
# ============================================================

if df is None or not isinstance(df, pd.DataFrame) or df.empty:

    st.warning(
        "No drilling data is currently available for validation."
    )

    st.info(
        "First open the main dashboard, choose a well and section, "
        "and allow the drilling data to load. Then return to this "
        "Agent Validation page."
    )

    st.stop()


# ============================================================
# CURRENT DATA CONTEXT
# ============================================================

well = context.get("well")
sections = context.get("sections", [])

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Loaded rows",
        f"{len(df):,}",
    )

with col2:
    st.metric(
        "Well",
        str(well) if well is not None else "Unknown",
    )

with col3:
    if sections:
        section_text = ", ".join(str(section) for section in sections)
    else:
        section_text = "Unknown"

    st.metric(
        "Section",
        section_text,
    )


st.divider()


# ============================================================
# BOSS-FEEDBACK AGENT VALIDATION
# ============================================================

boss_improved_df, boss_pressure_events = render_agent_quality_panel(df)


# ============================================================
# KEEP RESULTS AVAILABLE TO OTHER PAGES
# ============================================================

st.session_state["boss_improved_df"] = boss_improved_df
st.session_state["boss_pressure_events"] = boss_pressure_events