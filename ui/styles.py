
import streamlit as st


import streamlit as st


def apply_global_styles():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 4.0rem;
            padding-bottom: 0;
        }

        .well-header {
            text-align: center;
            color: #1E3A5F;
            font-size: 1.4rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }

        .well-subheader {
            text-align: center;
            color: #555;
            font-size: 0.85rem;
            margin-bottom: 0rem;
        }

        /* Reserve real space above the chart for the Plotly modebar,
           so it no longer sits on top of the custom chart buttons. */
        div[data-testid="stPlotlyChart"] {
            position: relative;
            padding-top: 56px;
        }

        div[data-testid="stPlotlyChart"] .modebar-container {
            position: absolute !important;
            top: 4px !important;
            left: 0 !important;
            width: 100% !important;
            display: flex !important;
            justify-content: center !important;
            pointer-events: none !important;
            z-index: 1000 !important;
        }

        div[data-testid="stPlotlyChart"] .modebar {
            position: relative !important;
            left: auto !important;
            right: auto !important;
            top: 0 !important;
            opacity: 1 !important;
            visibility: visible !important;
            display: flex !important;
            background: #f3f3f3 !important;
            border: 1px solid #d0d0d0 !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            padding: 3px 6px !important;
            margin: 0 auto !important;
            pointer-events: auto !important;
        }

        div[data-testid="stPlotlyChart"] .modebar-group {
            background: transparent !important;
            border: none !important;
            padding-left: 2px !important;
            padding-right: 2px !important;
        }

        div[data-testid="stPlotlyChart"] a.modebar-btn {
            opacity: 1 !important;
        }

        div[data-testid="stPlotlyChart"] svg.icon {
            width: 18px !important;
            height: 18px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
