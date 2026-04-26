import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import N_TRACKS, PARAMETER_CATALOG
from utils.helpers import downsample_xy, get_display_mode, get_target_points
from visualization.chart_agent_track import _add_agent_track
from visualization.chart_scale import (
    _add_scale_row,
    _add_track_scale_guides,
    _add_track_selected_params_summary,
)
from visualization.chart_sections import _add_reference_line, _add_section_boundaries
from visualization.chart_time_axis import _build_dual_time_ticks
from visualization.chart_transform import _normalize_with_range


def create_multi_track_chart(
    df: pd.DataFrame,
    track_params: list[list[str]],
    track_param_labels: list[list[str]],
    track_colors: list[list[str]],
    zoom_percent: float,
    section_ranges: list[dict] | None = None,
    agent_cfg: dict | None = None,
    chart_height: int = 950,
    parameter_ranges: dict[str, tuple[float, float]] | None = None,
    marker_display: str = "Lines only",
) -> go.Figure:
    subplot_titles = ["Track 1", "Track 2", "Track 3", "Track 4"]

    fig = make_subplots(
        rows=1,
        cols=N_TRACKS,
        shared_yaxes=True,
        horizontal_spacing=0.02,
        subplot_titles=subplot_titles,
    )

    mode, marker_size = get_display_mode(marker_display)
    target_points = get_target_points(zoom_percent)
    parameter_trace_indices = []

    t_min_view = df.index.min() if not df.empty else None
    t_max_view = df.index.max() if not df.empty else None

    for track_idx in range(3):
        params = track_params[track_idx]
        labels = track_param_labels[track_idx]
        colors = track_colors[track_idx]

        _add_track_scale_guides(fig, track_idx)

        for param_idx, (col, label, color) in enumerate(zip(params, labels, colors)):
            if col not in df.columns:
                continue

            series = pd.to_numeric(df[col], errors="coerce")
            valid = series.notna()

            if not valid.any():
                continue

            raw_x_full = series.loc[valid]
            raw_y_full = pd.Series(raw_x_full.index, index=raw_x_full.index)

            x_norm_full, x_min, x_max = _normalize_with_range(
                series=raw_x_full,
                label=label,
                parameter_ranges=parameter_ranges,
            )

            x_plot, y_plot = downsample_xy(
                x_series=x_norm_full,
                y_series=raw_y_full,
                n_max=target_points,
            )

            if x_plot.dropna().empty:
                continue

            raw_vals = raw_x_full.loc[x_plot.index]
            unit = PARAMETER_CATALOG.get(label, {}).get("unit", "")

            hovertemplate = (
                f"<b>{label}</b><br>"
                + (f"Unit: {unit}<br>" if unit else "")
                + "Value: %{customdata[0]:.1f}<br>"
                + "Date: %{y|%Y-%m-%d}<br>"
                + "Time: %{y|%H:%M:%S}<extra></extra>"
            )

            fig.add_trace(
                go.Scattergl(
                    x=x_plot.values,
                    y=y_plot.values,
                    mode=mode,
                    name=f"Track {track_idx + 1} - {label}",
                    showlegend=False,
                    line=dict(color=color, width=1.25),
                    marker=dict(
                        size=marker_size,
                        color=color,
                        opacity=0.75,
                        line=dict(width=0),
                    ),
                    customdata=np.column_stack([raw_vals.values]),
                    hovertemplate=hovertemplate,
                ),
                row=1,
                col=track_idx + 1,
            )

            parameter_trace_indices.append(len(fig.data) - 1)

            _add_scale_row(
                fig=fig,
                track_idx=track_idx,
                param_idx=param_idx,
                label=label,
                color=color,
                x_min=x_min,
                x_max=x_max,
            )

        _add_track_selected_params_summary(
            fig=fig,
            track_idx=track_idx,
            labels=labels,
            colors=colors,
        )

        fig.update_xaxes(
            row=1,
            col=track_idx + 1,
            range=[0, 1],
            showgrid=True,
            gridcolor="rgba(140,140,140,0.20)",
            gridwidth=0.6,
            zeroline=False,
            showticklabels=False,
            side="top",
            tickmode="array",
            tickvals=[i / 20 for i in range(21)],
        )

    if agent_cfg:
        _add_agent_track(fig, agent_cfg, row=1, col=4)

    if section_ranges and t_min_view is not None and t_max_view is not None:
        _add_section_boundaries(fig, section_ranges, t_min_view, t_max_view)

    if agent_cfg and agent_cfg.get("show_reference_line") and agent_cfg.get("reference_time") is not None:
        _add_reference_line(fig, agent_cfg["reference_time"])

    y_range = None
    if t_min_view is not None and t_max_view is not None:
        y_range = [t_max_view, t_min_view]

    tickvals, ticktext = _build_dual_time_ticks(
        t_min_view=t_min_view,
        t_max_view=t_max_view,
        n_ticks=12,
    )

    fig.update_yaxes(
        range=y_range,
        autorange=False if y_range else "reversed",
        showgrid=True,
        gridcolor="rgba(140,140,140,0.20)",
        gridwidth=0.6,
        tickmode="array" if tickvals is not None else "auto",
        tickvals=tickvals,
        ticktext=ticktext,
        tickfont=dict(size=10, family="Courier New"),

        # Cursor-attached horizontal reference line.
        # This lets the reviewer see the same timestamp across all 4 tracks.
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(60,60,60,0.55)",
        spikethickness=1,
        spikedash="solid",
    )

    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=0.0,
        y=1.03,
        text="<b>Date</b>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>Time</b>",
        showarrow=False,
        xanchor="left",
        font=dict(size=10, color="#333"),
    )

    fig.update_layout(
        height=chart_height,
        margin=dict(l=120, r=20, t=145, b=320),

        # Keeps normal point hover, but also allows the horizontal spike line.
        hovermode="closest",

        # Helps Plotly keep spike lines responsive near the cursor.
        spikedistance=-1,
        hoverdistance=30,

        plot_bgcolor="white",
        paper_bgcolor="white",
        uirevision="keep_zoom_state",
    )

    if parameter_trace_indices:
        fig.update_layout(
            updatemenus=[
                dict(
                    type="buttons",
                    direction="right",
                    x=0.42,
                    y=1.075,
                    xanchor="center",
                    yanchor="top",
                    showactive=True,
                    bgcolor="rgba(245,245,245,0.95)",
                    bordercolor="rgba(160,160,160,0.6)",
                    borderwidth=1,
                    pad=dict(l=4, r=4, t=2, b=2),
                    buttons=[
                        dict(
                            label="Lines only",
                            method="restyle",
                            args=[
                                {
                                    "mode": "lines",
                                    "marker.size": 2.0,
                                    "marker.opacity": 0.0,
                                },
                                parameter_trace_indices,
                            ],
                        ),
                        dict(
                            label="Small dots",
                            method="restyle",
                            args=[
                                {
                                    "mode": "lines+markers",
                                    "marker.size": 2.0,
                                    "marker.opacity": 0.75,
                                    "marker.line.width": 0,
                                },
                                parameter_trace_indices,
                            ],
                        ),
                        dict(
                            label="Larger dots",
                            method="restyle",
                            args=[
                                {
                                    "mode": "lines+markers",
                                    "marker.size": 4.0,
                                    "marker.opacity": 0.75,
                                    "marker.line.width": 0,
                                },
                                parameter_trace_indices,
                            ],
                        ),
                    ],
                )
            ]
        )

    return fig