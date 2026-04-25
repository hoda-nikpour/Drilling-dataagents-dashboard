import pandas as pd

from agents.activity_agents import ActivityConfig, classify_activities
from agents.symptom_agents import SymptomConfig, build_open_hole_length_agent, build_selected_symptom_agent


def _make_basic_df():
    index = pd.date_range("2024-01-01", periods=20, freq="min")

    return pd.DataFrame(
        {
            "BDTI": [1000.0] * 20,
            "DMEA": [1600.0] * 20,
            "BPOS": [10.0] * 20,
            "HKL": [120.0] * 20,
            "MFI": [500.0] * 20,
            "RPMB": [80.0] * 20,
            "ROP": [10.0] * 20,
            "WOB": [8.0] * 20,
            "SPP": [100.0] * 20,
            "TRQ": [10.0] * 20,
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
        "SPP": "SPP",
        "TRQ": "TRQ",
    }


def test_open_hole_length_agent_does_not_create_interval_below_high_threshold():
    df = _make_basic_df()
    column_map = _make_column_map()
    cfg = SymptomConfig(
        open_hole_length_threshold_1=500.0,
        open_hole_length_threshold_2=750.0,
    )

    features, intervals = build_open_hole_length_agent(df, column_map, cfg)

    assert "open_hole_length" in features.columns
    assert len(intervals) > 0
    assert features["open_hole_length"].iloc[0] == 600.0


def test_open_hole_length_agent_creates_interval_when_above_threshold():
    df = _make_basic_df()
    column_map = _make_column_map()
    cfg = SymptomConfig(
        open_hole_length_threshold_1=300.0,
        open_hole_length_threshold_2=500.0,
    )

    features, intervals = build_open_hole_length_agent(df, column_map, cfg)

    assert not features.empty
    assert len(intervals) > 0
    assert intervals[0]["label"] == "OpenHoleLength"


def test_selected_symptom_agent_runs_for_open_hole_length():
    df = _make_basic_df()
    column_map = _make_column_map()

    activity_labels, activity_features, _ = classify_activities(
        df=df,
        column_map=column_map,
        cfg=ActivityConfig(min_interval_samples=2),
    )

    symptom_features, symptom_intervals = build_selected_symptom_agent(
        df=df,
        column_map=column_map,
        symptom_name="OpenHoleLength",
        symptom_cfg=SymptomConfig(
            open_hole_length_threshold_1=300.0,
            open_hole_length_threshold_2=500.0,
        ),
        activity_features=activity_features,
        activity_labels=activity_labels,
    )

    assert not symptom_features.empty
    assert isinstance(symptom_intervals, list)