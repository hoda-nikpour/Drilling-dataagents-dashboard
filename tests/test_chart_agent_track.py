import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from visualization.chart_agent_track import (
    _activity_line_width,
    _add_agent_track,
    _add_vertical_interval_line,
    _agent_line_width,
    _compute_activity_lane_summary,
    _compute_overlap_intervals,
    _interval_overlap,
)


def test_agent_line_width_uses_expected_values():
    assert _agent_line_width("Low") == 2
    assert _agent_line_width("Medium") == 4
    assert _agent_line_width("High") == 7
    assert _agent_line_width("Unknown") == 4


def test_activity_line_width_uses_expected_values():
    assert _activity_line_width("Drilling") == 5
    assert _activity_line_width("Reaming") == 5
    assert _activity_line_width("TrippingIn") == 5
    assert _activity_line_width("TrippingOut") == 5
    assert _activity_line_width("Other") == 4


def test_interval_overlap_returns_overlap_when_intervals_intersect():
    overlap = _interval_overlap(
        pd.Timestamp("2026-01-01 00:00:00"),
        pd.Timestamp("2026-01-01 01:00:00"),
        pd.Timestamp("2026-01-01 00:30:00"),
        pd.Timestamp("2026-01-01 02:00:00"),
    )

    assert overlap == (
        pd.Timestamp("2026-01-01 00:30:00"),
        pd.Timestamp("2026-01-01 01:00:00"),
    )


def test_interval_overlap_returns_none_when_intervals_do_not_intersect():
    overlap = _interval_overlap(
        pd.Timestamp("2026-01-01 00:00:00"),
        pd.Timestamp("2026-01-01 01:00:00"),
        pd.Timestamp("2026-01-01 01:00:00"),
        pd.Timestamp("2026-01-01 02:00:00"),
    )

    assert overlap is None


def test_compute_overlap_intervals_builds_expected_overlap_rows():
    tag_intervals = [
        {
            "label": "Manual tag",
            "start": pd.Timestamp("2026-01-01 00:00:00"),
            "end": pd.Timestamp("2026-01-01 01:00:00"),
        }
    ]

    agent_intervals = [
        {
            "label": "Agent hit",
            "start": pd.Timestamp("2026-01-01 00:30:00"),
            "end": pd.Timestamp("2026-01-01 02:00:00"),
        }
    ]

    overlaps = _compute_overlap_intervals(tag_intervals, agent_intervals)

    assert len(overlaps) == 1
    assert overlaps[0]["start"] == pd.Timestamp("2026-01-01 00:30:00")
    assert overlaps[0]["end"] == pd.Timestamp("2026-01-01 01:00:00")
    assert overlaps[0]["tag_label"] == "Manual tag"
    assert overlaps[0]["agent_label"] == "Agent hit"


def test_compute_activity_lane_summary_counts_and_duration():
    activity_intervals = [
        {
            "label": "Drilling",
            "start": pd.Timestamp("2026-01-01 00:00:00"),
            "end": pd.Timestamp("2026-01-01 01:00:00"),
        },
        {
            "label": "Drilling",
            "start": pd.Timestamp("2026-01-01 02:00:00"),
            "end": pd.Timestamp("2026-01-01 03:30:00"),
        },
        {
            "label": "Reaming",
            "start": pd.Timestamp("2026-01-01 04:00:00"),
            "end": pd.Timestamp("2026-01-01 04:30:00"),
        },
    ]

    summary = _compute_activity_lane_summary(activity_intervals)

    drilling = next(row for row in summary if row["label"] == "Drilling")
    reaming = next(row for row in summary if row["label"] == "Reaming")

    assert drilling["count"] == 2
    assert drilling["duration_hours"] == 2.5
    assert reaming["count"] == 1
    assert reaming["duration_hours"] == 0.5


def test_add_vertical_interval_line_adds_one_trace():
    fig = make_subplots(rows=1, cols=1)

    _add_vertical_interval_line(
        fig=fig,
        x_pos=0.5,
        start_time=pd.Timestamp("2026-01-01 00:00:00"),
        end_time=pd.Timestamp("2026-01-01 01:00:00"),
        color="red",
        width=3,
        row=1,
        col=1,
        hover_text="Test interval",
    )

    assert len(fig.data) == 1
    assert fig.data[0].mode == "lines"


def test_add_vertical_interval_line_ignores_invalid_interval():
    fig = make_subplots(rows=1, cols=1)

    _add_vertical_interval_line(
        fig=fig,
        x_pos=0.5,
        start_time=pd.Timestamp("2026-01-01 02:00:00"),
        end_time=pd.Timestamp("2026-01-01 01:00:00"),
        color="red",
        width=3,
        row=1,
        col=1,
        hover_text="Invalid interval",
    )

    assert len(fig.data) == 0


def test_add_agent_track_adds_shapes_traces_and_annotations():
    fig = make_subplots(rows=1, cols=4, shared_yaxes=True)

    agent_cfg = {
        "tag_intervals": [
            {
                "label": "Manual tag",
                "start": pd.Timestamp("2026-01-01 00:00:00"),
                "end": pd.Timestamp("2026-01-01 01:00:00"),
            }
        ],
        "agent_intervals": [
            {
                "label": "Drilling",
                "start": pd.Timestamp("2026-01-01 00:30:00"),
                "end": pd.Timestamp("2026-01-01 02:00:00"),
                "severity": "Medium",
                "source": "activity_agent",
            }
        ],
        "summary": {
            "tag_count": 1,
            "agent_count": 1,
            "overlap_count": 1,
            "score_percent": 100.0,
            "accepted": True,
        },
    }

    _add_agent_track(fig, agent_cfg, row=1, col=4)

    assert len(fig.layout.shapes) >= 3
    assert len(fig.data) >= 3
    assert len(fig.layout.annotations) >= 4


def test_add_agent_track_works_with_empty_agent_config():
    fig = make_subplots(rows=1, cols=4, shared_yaxes=True)

    agent_cfg = {
        "tag_intervals": [],
        "agent_intervals": [],
        "summary": {},
    }

    _add_agent_track(fig, agent_cfg, row=1, col=4)

    assert len(fig.layout.shapes) >= 3
    assert len(fig.layout.annotations) >= 4