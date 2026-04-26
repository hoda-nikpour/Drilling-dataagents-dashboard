import pandas as pd

from agents.activity_support import (
    enforce_min_duration,
    fill_short_false_gaps,
    intervals_from_label_series,
    interval_overlap,
    overlap_ratio,
    rolling_mean,
    stable_within_band,
)


def test_rolling_mean_is_past_looking_not_centered():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    series = pd.Series([1, 1, 100, 1, 1], index=index)

    result = rolling_mean(series, window=3)

    assert result.iloc[0] == 1
    assert result.iloc[1] == 1
    assert result.iloc[2] == 34
    assert result.iloc[1] != 34


def test_interval_overlap_returns_overlap():
    a_start = pd.Timestamp("2024-01-01 00:00:00")
    a_end = pd.Timestamp("2024-01-01 01:00:00")
    b_start = pd.Timestamp("2024-01-01 00:30:00")
    b_end = pd.Timestamp("2024-01-01 02:00:00")

    assert interval_overlap(a_start, a_end, b_start, b_end) == (b_start, a_end)


def test_interval_overlap_returns_none_when_no_overlap():
    a_start = pd.Timestamp("2024-01-01 00:00:00")
    a_end = pd.Timestamp("2024-01-01 01:00:00")
    b_start = pd.Timestamp("2024-01-01 02:00:00")
    b_end = pd.Timestamp("2024-01-01 03:00:00")

    assert interval_overlap(a_start, a_end, b_start, b_end) is None


def test_overlap_ratio_half_overlap():
    ratio = overlap_ratio(
        reference_start=pd.Timestamp("2024-01-01 00:00:00"),
        reference_end=pd.Timestamp("2024-01-01 01:00:00"),
        candidate_start=pd.Timestamp("2024-01-01 00:30:00"),
        candidate_end=pd.Timestamp("2024-01-01 01:30:00"),
    )

    assert ratio == 0.5


def test_fill_short_false_gaps():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    mask = pd.Series([True, True, False, True, True], index=index)

    result = fill_short_false_gaps(mask, max_gap=1)

    assert result.tolist() == [True, True, True, True, True]


def test_enforce_min_duration_replaces_short_runs():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    labels = pd.Series(["Drilling", "Drilling", "Other", "Drilling", "Drilling"], index=index)

    result = enforce_min_duration(labels, min_samples=2)

    assert result.tolist() == ["Drilling", "Drilling", "Drilling", "Drilling", "Drilling"]


def test_intervals_from_label_series():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    labels = pd.Series(["Drilling", "Drilling", "Other", "Other", "Reaming"], index=index)

    intervals = intervals_from_label_series(labels, min_samples=1)

    assert len(intervals) == 3
    assert intervals[0]["label"] == "Drilling"
    assert intervals[0]["start"] == index[0]
    assert intervals[0]["end"] == index[1]


def test_stable_within_band():
    index = pd.date_range("2024-01-01", periods=5, freq="min")
    series = pd.Series([10, 11, 10.5, 10.2, 10.8], index=index)

    stable = stable_within_band(series, window=3, band=2.0)

    assert stable.all()