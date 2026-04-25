import pandas as pd

try:
    from visualization.chart_builder import create_multi_track_chart
except ModuleNotFoundError:
    from tests.test_chart_builder import create_multi_track_chart


def _sample_chart_df():
    index = pd.date_range("2026-01-01 00:00:00", periods=20, freq="min")

    return pd.DataFrame(
        {
            "SWOB": range(20),
            "ROP": [10 + i * 0.5 for i in range(20)],
            "SPPA": [100 + i for i in range(20)],
            "_section_in": [8.5] * 10 + [12.25] * 10,
        },
        index=index,
    )


def test_create_multi_track_chart_runs_with_basic_inputs():
    df = _sample_chart_df()

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["SWOB", "ROP"],
            ["SPPA"],
            [],
            [],
        ],
        track_param_labels=[
            ["WOB", "ROP"],
            ["SPP"],
            [],
            [],
        ],
        track_colors=[
            ["#8E44AD", "#3498DB"],
            ["#E74C3C"],
            [],
            [],
        ],
        zoom_percent=50.0,
        section_ranges=[],
        agent_cfg={
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
        },
        chart_height=950,
        parameter_ranges={
            "WOB": (-5.0, 60.0),
            "ROP": (0.0, 200.0),
            "SPP": (0.0, 4000.0),
        },
    )

    assert fig is not None
    assert len(fig.data) >= 3
    assert fig.layout.height == 950


def test_create_multi_track_chart_runs_with_empty_agent_config():
    df = _sample_chart_df()

    fig = create_multi_track_chart(
        df=df,
        track_params=[
            ["SWOB"],
            [],
            [],
            [],
        ],
        track_param_labels=[
            ["WOB"],
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
        zoom_percent=10.0,
        section_ranges=[],
        agent_cfg=None,
        chart_height=950,
        parameter_ranges={"WOB": (-5.0, 60.0)},
    )

    assert fig is not None
    assert len(fig.data) >= 1