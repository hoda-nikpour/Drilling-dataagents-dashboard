import plotly.graph_objects as go

from config import PARAMETER_CATALOG
from utils.helpers import format_number


def _add_track_scale_guides(fig: go.Figure, track_idx: int):
    axis_name = "x domain" if track_idx == 0 else f"x{track_idx + 1} domain"

    for xpos in [0.0, 0.5, 1.0]:
        fig.add_shape(
            type="line",
            xref=axis_name,
            yref="paper",
            x0=xpos,
            x1=xpos,
            y0=0,
            y1=1,
            line=dict(color="rgba(120,120,120,0.10)", width=1, dash="dot"),
        )


def _add_scale_row(
    fig: go.Figure,
    track_idx: int,
    param_idx: int,
    label: str,
    color: str,
    x_min: float,
    x_max: float,
):
    axis_name = "x domain" if track_idx == 0 else f"x{track_idx + 1} domain"

    row_height = 0.06
    y_center = -0.10 - (param_idx * row_height)
    y0 = y_center - 0.022
    y1 = y_center + 0.022

    unit = PARAMETER_CATALOG.get(label, {}).get("unit", "")
    title_text = f"{label}{' (' + unit + ')' if unit else ''}"

    fig.add_shape(
        type="rect",
        xref=axis_name,
        yref="paper",
        x0=0.01,
        x1=0.99,
        y0=y0,
        y1=y1,
        line=dict(color="rgba(90,90,90,0.45)", width=1),
        fillcolor="rgba(245,245,245,0.85)",
        layer="below",
    )

    fig.add_shape(
        type="line",
        xref=axis_name,
        yref="paper",
        x0=0.17,
        x1=0.17,
        y0=y0,
        y1=y1,
        line=dict(color="rgba(120,120,120,0.35)", width=1),
        layer="below",
    )

    fig.add_shape(
        type="line",
        xref=axis_name,
        yref="paper",
        x0=0.83,
        x1=0.83,
        y0=y0,
        y1=y1,
        line=dict(color="rgba(120,120,120,0.35)", width=1),
        layer="below",
    )

    fig.add_shape(
        type="line",
        xref=axis_name,
        yref="paper",
        x0=0.50,
        x1=0.50,
        y0=y0,
        y1=y1,
        line=dict(color="rgba(160,160,160,0.18)", width=1, dash="dot"),
        layer="below",
    )

    fig.add_annotation(
        xref=axis_name,
        yref="paper",
        x=0.09,
        y=y_center,
        text=f"<span style='color:{color}; font-size:11px'><b>{format_number(x_min)}</b></span>",
        showarrow=False,
        xanchor="center",
        yanchor="middle",
        align="center",
    )

    fig.add_annotation(
        xref=axis_name,
        yref="paper",
        x=0.50,
        y=y_center,
        text=f"<span style='color:{color}; font-size:13px'><b>{title_text}</b></span>",
        showarrow=False,
        xanchor="center",
        yanchor="middle",
        align="center",
    )

    fig.add_annotation(
        xref=axis_name,
        yref="paper",
        x=0.91,
        y=y_center,
        text=f"<span style='color:{color}; font-size:11px'><b>{format_number(x_max)}</b></span>",
        showarrow=False,
        xanchor="center",
        yanchor="middle",
        align="center",
    )


def _add_track_selected_params_summary(
    fig: go.Figure,
    track_idx: int,
    labels: list[str],
    colors: list[str],
):
    axis_name = "x domain" if track_idx == 0 else f"x{track_idx + 1} domain"

    if not labels:
        summary_text = "<span style='color:#888; font-size:10px'>No parameters selected</span>"
    else:
        pieces = []
        for label, color in zip(labels, colors):
            pieces.append(f"<span style='color:{color}; font-size:10px'>{label}</span>")
        summary_text = " &nbsp;&nbsp;•&nbsp;&nbsp; ".join(pieces)

    fig.add_annotation(
        xref=axis_name,
        yref="paper",
        x=0.5,
        y=-0.31,
        text=summary_text,
        showarrow=False,
        xanchor="center",
        font=dict(size=10, color="#666"),
    )