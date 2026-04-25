import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import ACTIVITY_COLOR_MAP, AGENT_TRACK_XRANGE, SYMPTOM_COLOR_MAP


TAG_X = 0.24
OVERLAP_X = 0.50
AGENT_X = 0.76


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


def _add_agent_track(fig: go.Figure, agent_cfg: dict, row: int, col: int):
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