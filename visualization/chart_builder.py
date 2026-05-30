import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import N_TRACKS, PARAMETER_CATALOG
from utils.helpers import get_display_mode
from visualization.chart_agent_track import _add_agent_track
from visualization.chart_scale import (
    _add_scale_row,
    _add_track_scale_guides,
    _add_track_selected_params_summary,
)
from visualization.chart_sections import _add_reference_line, _add_section_boundaries
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
    curve_source: str = "Raw values",
) -> go.Figure:
    """
    Build the four-track mud logging chart.

    Important UI decision:
    - Plotly spike lines are disabled.
    - The single continuous cross-track hover/reference line is handled by
      ui/layout.py as one HTML overlay line.
    - This prevents the ugly separated spike lines inside each individual track.
    """

    subplot_titles = ["Track 1", "Track 2", "Track 3", "Track 4"]

    fig = make_subplots(
        rows=1,
        cols=N_TRACKS,
        shared_yaxes=True,
        horizontal_spacing=0.02,
        subplot_titles=subplot_titles,
    )

    mode, marker_size = get_display_mode(marker_display)
    parameter_trace_indices: list[int] = []

    t_min_view = df.index.min() if not df.empty else None
    t_max_view = df.index.max() if not df.empty else None

    # ------------------------------------------------------------
    # Tracks 1–3: drilling curves
    # ------------------------------------------------------------
    for track_idx in range(3):
        params = track_params[track_idx] if track_idx < len(track_params) else []
        labels = track_param_labels[track_idx] if track_idx < len(track_param_labels) else []
        colors = track_colors[track_idx] if track_idx < len(track_colors) else []

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

            # No downsampling: the dataframe has already been limited to the
            # active 12-hour window before plotting. Every loaded raw point is drawn.
            x_plot = x_norm_full
            y_plot = raw_y_full

            if x_plot.dropna().empty:
                continue

            raw_vals = raw_x_full.loc[x_plot.index]
            unit = PARAMETER_CATALOG.get(label, {}).get("unit", "")

            hovertemplate = (
                f"<b>{label}</b><br>"
                + "Value: %{customdata[0]:.1f}"
                + (f" {unit}" if unit else "")
                + "<br>"
                + "Time: %{y|%H:%M:%S}"
                + "<extra></extra>"
            )

            fig.add_trace(
                go.Scattergl(
                    x=x_plot.values,
                    y=y_plot.values,
                    mode=mode,
                    name=f"Track {track_idx + 1} - {label}",
                    showlegend=False,
                    meta={
                        "label": label,
                        "unit": unit,
                    },
                    line=dict(
                        color=color,
                        width=1.25,
                    ),
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
            gridcolor="rgba(120,120,120,0.24)",
            gridwidth=0.7,
            minor=dict(
                tick0=0,
                dtick=0.025,
                showgrid=True,
                gridcolor="rgba(150,150,150,0.11)",
                gridwidth=0.35,
            ),
            zeroline=False,
            showticklabels=False,
            side="top",
            tickmode="array",
            tickvals=[i / 20 for i in range(21)],
            fixedrange=False,
        )

    # ------------------------------------------------------------
    # Track 4: tagger / overlap / agent lane
    # ------------------------------------------------------------
    if agent_cfg:
        _add_agent_track(fig, agent_cfg, row=1, col=4)
    else:
        fig.update_xaxes(
            row=1,
            col=4,
            range=[0, 1],
            showgrid=True,
            gridcolor="rgba(120,120,120,0.24)",
            gridwidth=0.7,
            minor=dict(
                tick0=0,
                dtick=0.025,
                showgrid=True,
                gridcolor="rgba(150,150,150,0.11)",
                gridwidth=0.35,
            ),
            zeroline=False,
            showticklabels=False,
            side="top",
            title_text="",
            fixedrange=False,
        )

    # ------------------------------------------------------------
    # Section boundary overlays
    # ------------------------------------------------------------
    if section_ranges and t_min_view is not None and t_max_view is not None:
        _add_section_boundaries(fig, section_ranges, t_min_view, t_max_view)

    # ------------------------------------------------------------
    # Shared time axis
    # ------------------------------------------------------------
    y_range = None
    if t_min_view is not None and t_max_view is not None:
        # Newest time at the top, oldest at the bottom.
        y_range = [t_max_view, t_min_view]

    # More frequent left-side time labels.
    # Use automatic ticks, not fixed tickvals, so the tick labels update after chart zoom.
    # Roughly one label every 80–90 px, which is close to the requested 2–3 cm spacing.
    time_tick_count = max(12, min(30, int(chart_height / 85)))

    fig.update_yaxes(
        range=y_range,
        autorange=False if y_range else "reversed",
        showgrid=True,
        gridcolor="rgba(120,120,120,0.24)",
        gridwidth=0.7,
        minor=dict(
            dtick=15 * 60 * 1000,
            showgrid=True,
            gridcolor="rgba(150,150,150,0.11)",
            gridwidth=0.35,
        ),
        tickmode="auto",
        nticks=time_tick_count,
        tickformat="%d-%b-%y<br>%H:%M:%S",
        tickfont=dict(size=10, family="Courier New"),
        automargin=True,
        fixedrange=False,

        # Critical:
        # Do NOT use Plotly spikes.
        # Plotly creates one spike per subplot, which is exactly the separated-line
        # problem you are seeing.
        showspikes=False,
    )

    # Force all four subplot y-axes to stay synchronized.
    fig.update_yaxes(matches="y")

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
        margin=dict(l=145, r=20, t=145, b=165),

        # Keep normal point hover. The continuous horizontal line is not Plotly;
        # it is drawn once in layout.py as an HTML overlay.
        hovermode="closest",

        # Do not set spikedistance here.
        # Do not set hoverdistance here.
        # They are only useful for Plotly spikes, which are intentionally disabled.

        plot_bgcolor="white",
        paper_bgcolor="white",
        uirevision="keep_zoom_state",
    )

    # ------------------------------------------------------------
    # Curve display buttons
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Optional fixed manual reference line
    # This is different from the hover line. It is user-controlled from sidebar.
    # ------------------------------------------------------------
    if (
        agent_cfg
        and agent_cfg.get("show_reference_line")
        and agent_cfg.get("reference_time") is not None
    ):
        _add_reference_line(
            fig=fig,
            reference_time=agent_cfg["reference_time"],
        )

    return fig
