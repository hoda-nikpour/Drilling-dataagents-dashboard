import pandas as pd

from agents.activity_agents import ActivityConfig, build_activity_features, classify_activities


def _make_basic_drilling_df():
    index = pd.date_range("2024-01-01", periods=20, freq="min")

    return pd.DataFrame(
        {
            "BDTI": [1000 + i for i in range(20)],
            "DMEA": [1000 + i for i in range(20)],
            "BPOS": [10.0] * 20,
            "HKL": [120.0] * 20,
            "MFI": [500.0] * 20,
            "RPMB": [80.0] * 20,
            "ROP": [10.0] * 20,
            "WOB": [8.0] * 20,
        },
        index=index,
    )


def _make_column_map():
    return {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "BPOS": "BPOS",
        "HKL": "HKL",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "ROP": "ROP",
        "WOB": "WOB",
    }


def test_build_activity_features_contains_expected_columns():
    df = _make_basic_drilling_df()
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
        "rop",
        "wob",
        "pump_on",
        "rpm_on",
        "near_bottom",
        "bit_on_bottom",
        "drilling_ahead",
        "stable_flow",
        "stable_rpm",
        "stable_wob",
    }

    assert expected_columns.issubset(set(features.columns))


def test_classify_activities_detects_drilling():
    df = _make_basic_drilling_df()
    column_map = _make_column_map()
    cfg = ActivityConfig(min_interval_samples=2)

    labels, features, intervals = classify_activities(df, column_map, cfg)

    assert not labels.empty
    assert not features.empty
    assert "Drilling" in labels.unique()
    assert any(item["label"] == "Drilling" for item in intervals)