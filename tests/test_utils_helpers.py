import pandas as pd

from utils.helpers import (
    compute_section_ranges,
    downsample_xy,
    format_number,
    get_display_mode,
    get_target_points,
)


def test_downsample_xy_keeps_small_series_unchanged():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    x = pd.Series([1, 2, 3, 4, 5], index=index)
    y = pd.Series(index, index=index)

    x_out, y_out = downsample_xy(x, y, n_max=10)

    assert len(x_out) == 5
    assert len(y_out) == 5
    assert x_out.index.equals(x.index)


def test_compute_section_ranges():
    index = pd.date_range("2024-01-01", periods=6, freq="min")
    df = pd.DataFrame(
        {"_section_in": [8.5, 8.5, 8.5, 12.25, 12.25, 12.25]},
        index=index,
    )

    ranges = compute_section_ranges(df, ["8.5", "12.25"])

    assert len(ranges) == 2
    assert ranges[0]["label"] == '8.5"'
    assert ranges[1]["label"] == '12.25"'


def test_format_number_handles_nan():
    assert format_number(float("nan")) == "NA"


def test_get_display_mode_returns_lines_and_markers():
    mode, marker_size = get_display_mode(zoom_percent=0)

    assert mode == "lines+markers"
    assert marker_size >= 0


def test_get_target_points_increases_when_zoomed():
    low_zoom_points = get_target_points(zoom_percent=0)
    high_zoom_points = get_target_points(zoom_percent=50)

    assert high_zoom_points >= low_zoom_points