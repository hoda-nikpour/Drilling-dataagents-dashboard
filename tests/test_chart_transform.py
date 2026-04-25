import numpy as np
import pandas as pd

from visualization.chart_transform import _normalize_with_range


def test_normalize_with_range_uses_given_parameter_range():
    series = pd.Series([0, 50, 100])
    normalized, x_min, x_max = _normalize_with_range(
        series=series,
        label="Test",
        parameter_ranges={"Test": (0, 100)},
    )

    assert x_min == 0
    assert x_max == 100
    assert normalized.tolist() == [0.0, 0.5, 1.0]


def test_normalize_with_range_clips_values_outside_range():
    series = pd.Series([-10, 50, 120])
    normalized, x_min, x_max = _normalize_with_range(
        series=series,
        label="Test",
        parameter_ranges={"Test": (0, 100)},
    )

    assert x_min == 0
    assert x_max == 100
    assert normalized.tolist() == [0.0, 0.5, 1.0]


def test_normalize_with_range_returns_half_when_range_is_flat():
    series = pd.Series([5, 5, 5])
    normalized, x_min, x_max = _normalize_with_range(
        series=series,
        label="Test",
        parameter_ranges={"Test": (5, 5)},
    )

    assert x_min == 5
    assert x_max == 5
    assert normalized.tolist() == [0.5, 0.5, 0.5]


def test_normalize_with_range_handles_empty_valid_series():
    series = pd.Series([np.nan, np.nan])
    normalized, x_min, x_max = _normalize_with_range(
        series=series,
        label="Test",
        parameter_ranges={"Test": (0, 100)},
    )

    assert pd.isna(x_min)
    assert pd.isna(x_max)
    assert normalized.isna().all()


def test_normalize_with_range_falls_back_to_data_min_max_for_unknown_label():
    series = pd.Series([10, 20, 30])
    normalized, x_min, x_max = _normalize_with_range(
        series=series,
        label="Unknown Parameter",
        parameter_ranges={},
    )

    assert x_min == 10
    assert x_max == 30
    assert normalized.tolist() == [0.0, 0.5, 1.0]