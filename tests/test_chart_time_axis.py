import pandas as pd

from visualization.chart_time_axis import _build_dual_time_ticks


def test_build_dual_time_ticks_returns_correct_tick_count_and_text_format():
    t_min = pd.Timestamp("2026-01-01 00:00:00")
    t_max = pd.Timestamp("2026-01-01 01:00:00")

    tickvals, ticktext = _build_dual_time_ticks(
        t_min_view=t_min,
        t_max_view=t_max,
        n_ticks=5,
    )

    assert len(tickvals) == 5
    assert len(ticktext) == 5

    assert tickvals[0] == t_min
    assert tickvals[-1] == t_max

    assert "01-Jan-26" in ticktext[0]
    assert "00:00:00" in ticktext[0]
    assert "&nbsp;" in ticktext[0]


def test_build_dual_time_ticks_returns_none_when_start_time_is_missing():
    tickvals, ticktext = _build_dual_time_ticks(
        t_min_view=None,
        t_max_view=pd.Timestamp("2026-01-01 01:00:00"),
        n_ticks=5,
    )

    assert tickvals is None
    assert ticktext is None


def test_build_dual_time_ticks_returns_none_when_end_time_is_missing():
    tickvals, ticktext = _build_dual_time_ticks(
        t_min_view=pd.Timestamp("2026-01-01 00:00:00"),
        t_max_view=None,
        n_ticks=5,
    )

    assert tickvals is None
    assert ticktext is None