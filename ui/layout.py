import pandas as pd
import streamlit as st


def render_dashboard_header(
    selected_well: str,
    selected_sections: tuple[str, ...],
    review_mode: str,
):
    sections_label = "  ·  ".join(f'{s}"' for s in selected_sections)

    st.markdown(
        f'<div class="well-header">Well {selected_well}</div>'
        f'<div class="well-subheader">Mud Logging Dashboard &nbsp;|&nbsp; '
        f'Sections: {sections_label} &nbsp;|&nbsp; Review mode: {review_mode}</div>',
        unsafe_allow_html=True,
    )


def render_review_caption(summary: dict):
    accepted_text = "Accepted" if summary.get("accepted", False) else "Not accepted yet"

    st.caption(
        f"Review summary — Tags: {summary.get('tag_count', 0)} | "
        f"Hits: {summary.get('agent_count', 0)} | "
        f"Overlap: {summary.get('overlap_count', 0)} / {summary.get('tag_count', 0)} | "
        f"Score: {summary.get('score_percent', 0.0):.1f}% | "
        f"Status: {accepted_text}"
    )


def render_result_tables(
    activity_cfg: dict,
    symptom_cfg: dict,
    activity_validation_df: pd.DataFrame,
    review_df: pd.DataFrame,
):
    if not activity_cfg["summary_df"].empty:
        with st.expander("Activity summary", expanded=False):
            st.dataframe(activity_cfg["summary_df"], use_container_width=True)

    if symptom_cfg["intervals"]:
        symptom_rows = pd.DataFrame(symptom_cfg["intervals"])
        with st.expander("Symptom intervals", expanded=False):
            st.dataframe(symptom_rows, use_container_width=True)

    if not activity_validation_df.empty:
        with st.expander("Activity validation against manual tags", expanded=False):
            st.dataframe(activity_validation_df, use_container_width=True)

    if not review_df.empty:
        with st.expander("Manual hit review", expanded=False):
            st.dataframe(review_df, use_container_width=True)


def render_chart(fig, chart_key: str):
    st.caption(
        "Chart controls: use the toolbar above the chart or double-click inside the chart to reset zoom. "
        "Use 'Reset time filter' in the sidebar to restore the full selected time window."
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key=chart_key,
        config={
            "displaylogo": False,
            "displayModeBar": True,
            "scrollZoom": False,
            "doubleClick": "reset+autosize",
            "modeBarButtonsToRemove": [
            "lasso2d",
            "select2d",
        ],
        },
    )