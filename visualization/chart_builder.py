import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import (
    ACTIVITY_COLOR_MAP,
    AGENT_TRACK_XRANGE,
    LOGICAL_PARAMETER_RANGES,
    N_TRACKS,
    PARAMETER_CATALOG,
    SYMPTOM_COLOR_MAP,
)
from utils.helpers import downsample_xy, format_number, get_display_mode, get_target_points

TAG_X = 0.24
OVERLAP_X = 0.50
AGENT_X = 0.76


def add_section_boundaries(fig: go.Figure, section_ranges: list[dict], t_min_view, t_max_view):
    if not section_ranges or t_min_view is None or t_max_view is None:
        return

    total_ns = float((t_max_view - t_min_view).value)
    if total_ns <= 0:
        return

    def to_paper_y(t):
        frac = float((t - t_min_view).value) / total_ns
        return 1.0 - max(0.0, min(1.0, frac))

    for i, sr in enumerate(section_ranges):
        if i > 0:
            y_line = to_paper_y(sr["t_min"])
            if 0.01 < y_line < 0.99:
                fig.add_shape(
                    type="line",
                    x0=0,
                    x1=1,
                    xref="paper",
                    y0=y_line,
                    y1=y_line,
                    yref="paper",
                    line=dict(dash="dash", color="rgba(70,70,70,0.30)", width=1),
                )

        mid = sr["t_min"] + (sr["t_max"] - sr["t_min"]) / 2
        y_mid = max(0.02, min(0.98, to_paper_y(mid)))

        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.006,
            y=y_mid,
            text=sr["label"],
            textangle=-90,
            showarrow=False,
            font=dict(size=9, color="#333"),
            bgcolor="rgba(255,255,255,0.65)",
            borderpad=2,
            xanchor="center",
            yanchor="middle",
        )


def _normalize_with_range(
    series: pd.Series,
    label: str,
    parameter_ranges: dict[str, tuple[float, float]] | None = None,
):
    s = pd.to_numeric(series, errors="coerce")
    s_valid = s.dropna()
    if s_valid.empty:
        return s * np.nan, np.nan, np.nan

    range_lookup = parameter_ranges or LOGICAL_PARAMETER_RANGES
    range_min, range_max = range_lookup.get(
        label,
        (float(s_valid.min()), float(s_valid.max())),
    )

    if np.isclose(range_min, range_max):
        return pd.Series(np.full(len(s), 0.5), index=s.index), range_min, range_max

    s_clipped = s.clip(lower=range_min, upper=range_max)
    s_norm = (s_clipped - range_min) / (range_max - range_min)
    return s_norm, range_min, range_max


def _agent_line_width(severity: str) -> int:
    return {"Low": 2, "Medium": 4, "High": 7}.get(severity, 4)


def _activity_line_width(label: str) -> int:
    return 5 if label in {"Drilling", "Reaming", "TrippingIn", "TrippingOut"} else 4


def _interval_overlap(a_start, a_end, b_start, b_end):
    start = max(pd.Timestamp(a_start), pd.Timestamp(b_start))
    end = min(pd.Timestamp(a_end), pd.Timestamp(b_end))
    if start < end:
        return start, end
    return None


def _compute_overlap_intervals(tag_intervals: list[dict], agent_intervals: list[dict]) -> list[dict]:
    overlaps = []

    for tag in tag_intervals:
        for agent in agent_intervals:
            ov = _interval_overlap(tag["start"], tag["end"], agent["start"], agent["end"])
            if ov is not None:
                overlaps.append(
                    {
                        "start": ov[0],
                        "end": ov[1],
                        "tag_label": tag.get("label", ""),
                        "agent_label": agent.get("label", ""),
                    }
                )

    return overlaps


def _build_dual_time_ticks(t_min_view, t_max_view, n_ticks: int = 12):
    if t_min_view is None or t_max_view is None:
        return None, None

    vals = pd.date_range(start=t_min_view, end=t_max_view, periods=n_ticks)
    texts = [
        f"{ts.strftime('%d-%b-%y')}&nbsp;&nbsp;&nbsp;{ts.strftime('%H:%M:%S')}"
        for ts in vals
    ]
    return vals, texts


def _add_vertical_interval_line(
    fig: go.Figure,
    x_pos: float,
    start_time,
    end_time,
    color: str,
    width: int,
    row: int,
    col: int,
    hover_text: str | None = None,
):
    if pd.Timestamp(end_time) < pd.Timestamp(start_time):
        return

    y_vals = pd.date_range(pd.Timestamp(start_time), pd.Timestamp(end_time), periods=20)
    x_vals = np.full(len(y_vals), x_pos)

    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines",
            line=dict(color=color, width=width),
            showlegend=False,
            hovertemplate=(hover_text or "") + "<extra></extra>",
        ),
        row=row,
        col=col,
    )


def _compute_activity_lane_summary(activity_intervals: list[dict]) -> list[dict]:
    if not activity_intervals:
        return []

    rows = []
    for item in activity_intervals:
        duration_hours = (
            pd.Timestamp(item["end"]) - pd.Timestamp(item["start"])
        ).total_seconds() / 3600.0

        rows.append(
            {
                "label": item["label"],
                "duration_hours": max(duration_hours, 0.0),
            }
        )

    df = pd.DataFrame(rows)
    summary = (
        df.groupby("label", dropna=False)
        .agg(
            count=("label", "size"),
            duration_hours=("duration_hours", "sum"),
        )
        .reset_index()
        .sort_values(["count", "duration_hours"], ascending=[False, False])
    )

    return summary.to_dict("records")


def _add_activity_summary_annotations(fig: go.Figure, activity_intervals: list[dict]):
    summary_rows = _compute_activity_lane_summary(activity_intervals)
    if not summary_rows:
        return

    summary_rows = summary_rows[:6]
    y_start = 0.97
    y_step = 0.055

    fig.add_annotation(
        xref="x4",
        yref="paper",
        x=0.50,
        y=0.995,
        text="<b>Activity Summary</b>",
        showarrow=False,
        font=dict(size=10, color="#333"),
    )

    for i, row in enumerate(summary_rows):
        y = y_start - i * y_step
        label = row["label"]
        count = row["count"]
        duration_hours = row["duration_hours"]
        color = ACTIVITY_COLOR_MAP.get(label, "rgba(149, 165, 166, 0.88)")

        fig.add_annotation(
            xref="x4",
            yref="paper",
            x=0.50,
            y=y,
            text=(
                f"<span style='color:{color}'><b>{label}</b></span>"
                f" &nbsp;|&nbsp; n={count}"
                f" &nbsp;|&nbsp; {duration_hours:.2f} h"
            ),
            showarrow=False,
            font=dict(size=9, color="#444"),
            align="center",
        )


def add_reference_line(fig: go.Figure, reference_time):
    fig.add_shape(
        type="line",
        x0=0,
        x1=1,
        xref="paper",
        y0=reference_time,
        y1=reference_time,
        yref="y",
        line=dict(color="rgba(255,0,0,0.55)", width=2),
    )


def add_agent_track(fig: go.Figure, agent_cfg: dict, row: int, col: int):
    tag_intervals = agent_cfg.get("tag_intervals", [])
    agent_intervals = agent_cfg.get("agent_intervals", [])
    overlap_intervals = _compute_overlap_intervals(tag_intervals, agent_intervals)

    for x_pos in [TAG_X, OVERLAP_X, AGENT_X]:
        fig.add_shape(
            type="line",
            xref="x4",
            yref="paper",
            x0=x_pos,
            x1=x_pos,
            y0=0,
            y1=1,
            line=dict(color="rgba(100,100,100,0.16)", width=1, dash="dot"),
        )

    for i, tag in enumerate(tag_intervals, start=1):
        label = tag.get("label", f"Tag {i}")
        hover_text = f"Tagger<br>{label}"
        _add_vertical_interval_line(
            fig=fig,
            x_pos=TAG_X,
            start_time=tag["start"],
            end_time=tag["end"],
            color="rgba(128, 0, 128, 0.85)",
            width=4,
            row=row,
            col=col,
            hover_text=hover_text,
        )

    for overlap in overlap_intervals:
        hover_text = (
            "Overlap<br>"
            f"Tag: {overlap.get('tag_label', '')}<br>"
            f"Agent: {overlap.get('agent_label', '')}"
        )
        _add_vertical_interval_line(
            fig=fig,
            x_pos=OVERLAP_X,
            start_time=overlap["start"],
            end_time=overlap["end"],
            color="rgba(60, 160, 90, 0.90)",
            width=5,
            row=row,
            col=col,
            hover_text=hover_text,
        )

    for i, agent in enumerate(agent_intervals, start=1):
        label = agent.get("label", f"Hit {i}")
        severity = agent.get("severity", "Medium")

        if agent.get("source") == "activity_agent":
            color = ACTIVITY_COLOR_MAP.get(label, "rgba(149, 165, 166, 0.88)")
            width = _activity_line_width(label)
            hover_text = f"Activity<br>{label}"
        elif agent.get("source") == "symptom_agent":
            color = SYMPTOM_COLOR_MAP.get(label, "rgba(220, 50, 47, 0.92)")
            width = _agent_line_width(severity)
            hover_text = f"Symptom<br>{label}<br>Severity: {severity}"
        else:
            color = "rgba(220, 50, 47, 0.92)"
            width = _agent_line_width(severity)
            hover_text = f"Agent hit<br>{label}<br>Severity: {severity}"

        _add_vertical_interval_line(
            fig=fig,
            x_pos=AGENT_X,
            start_time=agent["start"],
            end_time=agent["end"],
            color=color,
            width=width,
            row=row,
            col=col,
            hover_text=hover_text,
        )

    activity_intervals_only = [
        item for item in agent_intervals if item.get("source") == "activity_agent"
    ]
    _add_activity_summary_annotations(fig, activity_intervals_only)

    fig.add_annotation(
        xref="x4",
        yref="paper",
        x=TAG_X,
        y=1.03,
        text="<b>Tagger</b>",
        showarrow=False,
        font=dict(size=10, color="#6A0DAD"),
    )
    fig.add_annotation(
        xref="x4",
        yref="paper",
        x=OVERLAP_X,
        y=1.03,
        text="<b>Overlap</b>",
        showarrow=False,
        font=dict(size=10, color="#2E8B57"),
    )
    fig.add_annotation(
        xref="x4",
        yref="paper",
        x=AGENT_X,
        y=1.03,
        text="<b>Agent</b>",
        showarrow=False,
        font=dict(size=10, color="#C0392B"),
    )

    summary = agent_cfg.get("summary", {})
    accepted_text = "Accepted" if summary.get("accepted", False) else "Not accepted yet"
    summary_text = (
        f"Tags: {summary.get('tag_count', 0)}"
        f" &nbsp;|&nbsp; Hits: {summary.get('agent_count', 0)}"
        f" &nbsp;|&nbsp; Overlap: {summary.get('overlap_count', 0)} / {summary.get('tag_count', 0)}"
        f" &nbsp;|&nbsp; Score: {summary.get('score_percent', 0.0):.1f}%"
        f" &nbsp;|&nbsp; {accepted_text}"
    )
    fig.add_annotation(
        xref="x4",
        yref="paper",
        x=0.5,
        y=-0.09,
        text=summary_text,
        showarrow=False,
        font=dict(size=10, color="#444"),
    )

    fig.update_xaxes(
        row=row,
        col=col,
        range=list(AGENT_TRACK_XRANGE),
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        side="top",
        title_text="",
    )


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


def _add_track_selected_params_summary(fig: go.Figure, track_idx: int, labels: list[str], colors: list[str]):
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
) -> go.Figure:
    subplot_titles = ["Track 1", "Track 2", "Track 3", "Track 4"]

    fig = make_subplots(
        rows=1,
        cols=N_TRACKS,
        shared_yaxes=True,
        horizontal_spacing=0.02,
        subplot_titles=subplot_titles,
    )

    mode, marker_size = get_display_mode(zoom_percent)
    target_points = get_target_points(zoom_percent)

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

            x_norm_full, x_min, x_max = _normalize_with_range(raw_x_full, label, parameter_ranges)
            x_plot, y_plot = downsample_xy(x_norm_full, raw_y_full, target_points)

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
                        opacity=0.95,
                        line=dict(width=0.5, color="rgba(40,40,40,0.55)"),
                    ),
                    customdata=np.column_stack([raw_vals.values]),
                    hovertemplate=hovertemplate,
                ),
                row=1,
                col=track_idx + 1,
            )

            _add_scale_row(fig, track_idx, param_idx, label, color, x_min, x_max)

        _add_track_selected_params_summary(fig, track_idx, labels, colors)

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
        add_agent_track(fig, agent_cfg, row=1, col=4)

    if section_ranges and t_min_view is not None and t_max_view is not None:
        add_section_boundaries(fig, section_ranges, t_min_view, t_max_view)

    if agent_cfg and agent_cfg.get("show_reference_line") and agent_cfg.get("reference_time") is not None:
        add_reference_line(fig, agent_cfg["reference_time"])

    y_range = None
    if t_min_view is not None and t_max_view is not None:
        y_range = [t_max_view, t_min_view]

    tickvals, ticktext = _build_dual_time_ticks(t_min_view, t_max_view, n_ticks=12)

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
        margin=dict(l=120, r=20, t=75, b=320),
        hovermode="closest",
        plot_bgcolor="white",
        paper_bgcolor="white",
        uirevision="keep_zoom_state",
    )

    return fig