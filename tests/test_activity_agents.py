import pandas as pd

from agents.activity_agents import ActivityConfig, build_activity_features, classify_activities


def _make_column_map():
    return {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "BPOS": "BPOS",
        "HKL": "HKL",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "WOB": "WOB",
    }


def _make_drilling_df():
    index = pd.date_range("2024-01-01", periods=20, freq="min")
    depth = [1000 + i * 0.02 for i in range(20)]

    return pd.DataFrame(
        {
            "BDTI": depth,
            "DMEA": depth,
            "BPOS": [10.0] * 20,
            "HKL": [120.0] * 20,
            "MFI": [500.0] * 20,
            "RPMB": [80.0] * 20,
            "WOB": [8.0] * 20,
        },
        index=index,
    )


def test_build_activity_features_contains_expected_columns():
    df = _make_drilling_df()
    column_map = _make_column_map()
    cfg = ActivityConfig()

    features = build_activity_features(df, column_map, cfg)

    expected_columns = {
        "bit_depth",
        "well_depth",
        "bpos",
        "hkl",
        "mfi",
        "rpm",
        "wob",
        "pump_on",
        "rpm_on",
        "bit_on_bottom_document",
        "well_depth_increasing",
        "stable_flow",
        "stable_rpm",
        "stable_wob",
    }

    assert expected_columns.issubset(set(features.columns))


def test_drilling_detects_depth_increase_and_bit_on_bottom():
    df = _make_drilling_df()
    column_map = _make_column_map()
    cfg = ActivityConfig(min_interval_samples=2)

    labels, features, intervals = classify_activities(df, column_map, cfg)

    assert "Drilling" in labels.unique()
    assert any(item["label"] == "Drilling" for item in intervals)


def test_reaming_requires_flow_rpm_zero_wob_and_slow_depth_change():
    index = pd.date_range("2024-01-01", periods=20, freq="min")
    depth = [1000 + i * 0.05 for i in range(20)]

    df = pd.DataFrame(
        {
            "BDTI": depth,
            "DMEA": depth,
            "BPOS": [10.0] * 20,
            "HKL": [120.0] * 20,
            "MFI": [500.0] * 20,
            "RPMB": [80.0] * 20,
            "WOB": [0.0] * 20,
        },
        index=index,
    )

    labels, _, intervals = classify_activities(
        df=df,
        column_map=_make_column_map(),
        cfg=ActivityConfig(min_interval_samples=2),
    )

    assert "Reaming" in labels.unique()
    assert any(item["label"] == "Reaming" for item in intervals)


def test_tripping_allows_short_zero_depth_steps_but_not_long_stop():
    index = pd.date_range("2024-01-01", periods=12, freq="min")
    bpos = [30, 29, 28, 28, 27, 26, 26, 26, 26, 26, 25, 24]

    df = pd.DataFrame(
        {
            "BDTI": [1000.0] * 12,
            "DMEA": [1100.0] * 12,
            "BPOS": bpos,
            "HKL": [120.0] * 12,
            "MFI": [0.0] * 12,
            "RPMB": [0.0] * 12,
            "WOB": [0.0] * 12,
        },
        index=index,
    )

    cfg = ActivityConfig(
        short_window=1,
        min_interval_samples=2,
        movement_threshold=0.2,
        tripping_max_consecutive_static_samples=3,
    )

    labels, features, intervals = classify_activities(df, _make_column_map(), cfg)

    assert "TrippingIn" in labels.unique()
    assert any(item["label"] == "TrippingIn" for item in intervals)
    assert features["tripping_motion_valid"].iloc[9] is False or features["tripping_motion_valid"].iloc[9] == False