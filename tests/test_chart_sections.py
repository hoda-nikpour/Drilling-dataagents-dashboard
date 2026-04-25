import pandas as pd
import plotly.graph_objects as go

from visualization.chart_sections import _add_reference_line, _add_section_boundaries


def test_add_reference_line_adds_one_shape():
    fig = go.Figure()
    reference_time = pd.Timestamp("2026-01-01 00:30:00")

    _add_reference_line(fig, reference_time)

    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].type == "line"
    assert fig.layout.shapes[0].xref == "paper"
    assert fig.layout.shapes[0].yref == "y"


def test_add_section_boundaries_does_not_crash_and_adds_shapes_and_annotations():
    fig = go.Figure()

    t0 = pd.Timestamp("2026-01-01 00:00:00")
    t1 = pd.Timestamp("2026-01-01 01:00:00")
    t2 = pd.Timestamp("2026-01-01 02:00:00")

    section_ranges = [
        {
            "label": '8.5"',
            "t_min": t0,
            "t_max": t1,
        },
        {
            "label": '12.25"',
            "t_min": t1,
            "t_max": t2,
        },
    ]

    _add_section_boundaries(
        fig=fig,
        section_ranges=section_ranges,
        t_min_view=t0,
        t_max_view=t2,
    )

    # One boundary line is expected between the two sections.
    assert len(fig.layout.shapes) >= 1

    # One annotation per section is expected.
    assert len(fig.layout.annotations) >= 2


def test_add_section_boundaries_handles_empty_inputs():
    fig = go.Figure()

    _add_section_boundaries(
        fig=fig,
        section_ranges=[],
        t_min_view=None,
        t_max_view=None,
    )

    assert len(fig.layout.shapes) == 0
    assert len(fig.layout.annotations) == 0