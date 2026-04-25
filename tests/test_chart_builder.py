import pandas as pd
import plotly.graph_objects as go

from visualization.chart_builder import create_multi_track_chart


def make_sample_chart_df() -> pd.DataFrame:
    index = pd.date_range(
        start="2026-01-01 00:00:00",
        periods=20,
        freq="min",
    )

    return pd.DataFrame(
        {
            "BDTI": [1000 + i for i in range(20)],
            "DMEA": [1001 + i for i in range(20)],
            "WOB": [5 + (i % 3) for i in range(20)],
            "_section_in": [8.5] * 10 + [12.25] * 10,
        },
        index=index,
    )


def test_create_multi_track_chart_returns_plotly_figure():
    df = make_sample_chart_df()

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["BDTI"],
            ["DMEA"],
            ["WOB"],
            [],
        ],
        track_param_labels=[
            ["Bit Depth"],
            ["Well Depth"],
            ["WOB"],
            [],
        ],
        track_colors=[
            ["#8E44AD"],
            ["#3498DB"],
            ["#E74C3C"],
            [],
        ],
        zoom_percent=0.0,
        section_ranges=[],
        agent_cfg=None,
        chart_height=700,
        parameter_ranges={
            "Bit Depth": (0.0, 6000.0),
            "Well Depth": (0.0, 6000.0),
            "WOB": (-5.0, 60.0),
        },
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 3
    assert fig.layout.height == 700


def test_create_multi_track_chart_works_with_empty_track_4_agent_config():
    df = make_sample_chart_df()

    empty_agent_cfg = {
        "tag_intervals": [],
        "agent_intervals": [],
        "summary": {
            "tag_count": 0,
            "agent_count": 0,
            "overlap_count": 0,
            "score_percent": 0.0,
            "accepted": False,
        },
        "show_reference_line": False,
        "reference_time": None,
    }

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["BDTI"],
            ["DMEA"],
            ["WOB"],
            [],
        ],
        track_param_labels=[
            ["Bit Depth"],
            ["Well Depth"],
            ["WOB"],
            [],
        ],
        track_colors=[
            ["#8E44AD"],
            ["#3498DB"],
            ["#E74C3C"],
            [],
        ],
        zoom_percent=50.0,
        section_ranges=[],
        agent_cfg=empty_agent_cfg,
        chart_height=900,
        parameter_ranges={
            "Bit Depth": (0.0, 6000.0),
            "Well Depth": (0.0, 6000.0),
            "WOB": (-5.0, 60.0),
        },
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 3
    assert fig.layout.height == 900


def test_create_multi_track_chart_adds_section_boundaries():
    df = make_sample_chart_df()

    section_ranges = [
        {
            "label": '8.5"',
            "t_min": df.index[:10].min(),
            "t_max": df.index[:10].max(),
        },
        {
            "label": '12.25"',
            "t_min": df.index[10:].min(),
            "t_max": df.index[10:].max(),
        },
    ]

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["BDTI"],
            [],
            [],
            [],
        ],
        track_param_labels=[
            ["Bit Depth"],
            [],
            [],
            [],
        ],
        track_colors=[
            ["#8E44AD"],
            [],
            [],
            [],
        ],
        zoom_percent=0.0,
        section_ranges=section_ranges,
        agent_cfg=None,
        chart_height=700,
        parameter_ranges={
            "Bit Depth": (0.0, 6000.0),
        },
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.layout.annotations) >= 2
    assert len(fig.layout.shapes) >= 1


def test_create_multi_track_chart_adds_reference_line_when_enabled():
    df = make_sample_chart_df()

    reference_time = df.index[5]

    agent_cfg = {
        "tag_intervals": [],
        "agent_intervals": [],
        "summary": {
            "tag_count": 0,
            "agent_count": 0,
            "overlap_count": 0,
            "score_percent": 0.0,
            "accepted": False,
        },
        "show_reference_line": True,
        "reference_time": reference_time,
    }

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["BDTI"],
            [],
            [],
            [],
        ],
        track_param_labels=[
            ["Bit Depth"],
            [],
            [],
            [],
        ],
        track_colors=[
            ["#8E44AD"],
            [],
            [],
            [],
        ],
        zoom_percent=0.0,
        section_ranges=[],
        agent_cfg=agent_cfg,
        chart_height=700,
        parameter_ranges={
            "Bit Depth": (0.0, 6000.0),
        },
    )

    assert isinstance(fig, go.Figure)

    reference_shapes = [
        shape
        for shape in fig.layout.shapes
        if shape.type == "line"
        and shape.xref == "paper"
        and shape.yref == "y"
        and shape.y0 == reference_time
        and shape.y1 == reference_time
    ]

    assert len(reference_shapes) == 1