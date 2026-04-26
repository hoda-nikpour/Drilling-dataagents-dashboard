import pandas as pd

from agents.activity_agents import ActivityConfig, classify_activities
from agents.symptom_agents import (
    SymptomConfig,
    build_open_hole_length_agent,
    build_overpull_agent,
    build_pspike_agent,
    build_selected_symptom_agent,
    build_tookweight_agent,
)


def _make_column_map():
    return {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "Casing Depth": "DepthCsg",
        "BPOS": "BPOS",
        "HKL": "HKL",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "WOB": "WOB",
        "SPP": "SPP",
        "TRQ": "TRQ",
    }


def _make_basic_df():
    index = pd.date_range("2024-01-01", periods=30, freq="min")
    depth = [1000 + i * 0.02 for i in range(30)]

    return pd.DataFrame(
        {
            "BDTI": depth,
            "DMEA": depth,
            "DepthCsg": [400.0] * 30,
            "BPOS": [10.0] * 30,
            "HKL": [120.0] * 30,
            "MFI": [500.0] * 30,
            "RPMB": [80.0] * 30,
            "WOB": [8.0] * 30,
            "SPP": [100.0] * 30,
            "TRQ": [10.0] * 30,
        },
        index=index,
    )


def test_open_hole_length_uses_casing_depth_not_bit_depth():
    df = _make_basic_df()
    column_map = _make_column_map()
    cfg = SymptomConfig(
        open_hole_length_threshold_1=500.0,
        open_hole_length_threshold_2=750.0,
    )

    features, intervals = build_open_hole_length_agent(df, column_map, cfg)

    assert "open_hole_length" in features.columns
    assert features["open_hole_length"].iloc[0] == 600.0
    assert len(intervals) == 1
    assert intervals[0]["severity"] == "Low"


def test_open_hole_length_reports_first_crossing_only():
    df = _make_basic_df()
    column_map = _make_column_map()

    cfg = SymptomConfig(
        open_hole_length_threshold_1=500.0,
        open_hole_length_threshold_2=550.0,
    )

    _, intervals = build_open_hole_length_agent(df, column_map, cfg)

    assert len(intervals) == 1
    assert intervals[0]["severity"] == "High"


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
            open_hole_length_threshold_1=500.0,
            open_hole_length_threshold_2=750.0,
        ),
        activity_features=activity_features,
        activity_labels=activity_labels,
    )

    assert not symptom_features.empty
    assert isinstance(symptom_intervals, list)


def test_overpull_uses_one_level_six_bar_threshold():
    index = pd.date_range("2024-01-01", periods=30, freq="min")
    df = pd.DataFrame(
        {
            "HKL": [100.0] * 20 + [107.0] * 10,
        },
        index=index,
    )

    activity_features = pd.DataFrame(
        {
            "pipe_moving_up": [True] * 30,
            "bpos": [float(i) for i in range(30)],
        },
        index=index,
    )
    activity_labels = pd.Series(["TrippingOut"] * 30, index=index)

    features, intervals = build_overpull_agent(
        df=df,
        column_map={"HKL": "HKL"},
        cfg=SymptomConfig(
            overpull_baseline_window=20,
            overpull_threshold=6.0,
            hoisting_velocity_min=0.0,
            hoisting_velocity_max=10.0,
        ),
        activity_features=activity_features,
        activity_labels=activity_labels,
    )

    assert "hkl_delta" in features.columns
    assert len(intervals) > 0
    assert all(item["severity"] == "High" for item in intervals)


def test_tookweight_uses_one_level_six_bar_drop():
    index = pd.date_range("2024-01-01", periods=30, freq="min")
    df = pd.DataFrame(
        {
            "HKL": [100.0] * 20 + [93.0] * 10,
        },
        index=index,
    )

    activity_features = pd.DataFrame(
        {
            "pipe_moving_down": [True] * 30,
            "bpos": [float(30 - i) for i in range(30)],
        },
        index=index,
    )
    activity_labels = pd.Series(["TrippingIn"] * 30, index=index)

    features, intervals = build_tookweight_agent(
        df=df,
        column_map={"HKL": "HKL"},
        cfg=SymptomConfig(
            tookweight_baseline_window=20,
            tookweight_threshold=6.0,
            hoisting_velocity_min=0.0,
            hoisting_velocity_max=10.0,
        ),
        activity_features=activity_features,
        activity_labels=activity_labels,
    )

    assert "hkl_drop" in features.columns
    assert len(intervals) > 0
    assert all(item["severity"] == "High" for item in intervals)


def test_pspike_requires_stable_mfi_rpm_wob():
    index = pd.date_range("2024-01-01", periods=30, freq="min")
    spp = [100.0] * 20 + [108.0] * 10

    df = pd.DataFrame(
        {
            "SPP": spp,
            "WOB": [0.0] * 30,
            "RPMB": [80.0] * 30,
            "MFI": [500.0] * 30,
        },
        index=index,
    )

    activity_features = pd.DataFrame(
        {
            "stable_flow": [True] * 30,
            "stable_rpm": [True] * 30,
            "stable_wob": [True] * 30,
        },
        index=index,
    )
    activity_labels = pd.Series(["Reaming"] * 30, index=index)

    _, intervals = build_pspike_agent(
        df=df,
        column_map={
            "SPP": "SPP",
            "WOB": "WOB",
            "RPMB": "RPMB",
            "MFI": "MFI",
        },
        cfg=SymptomConfig(
            pspike_baseline_window=10,
            pspike_threshold_normal=5.0,
            pspike_threshold_motor_on=7.0,
            pspike_spp_stability_band=2.0,
        ),
        activity_features=activity_features,
        activity_labels=activity_labels,
    )

    assert len(intervals) > 0
    assert intervals[0]["label"] == "PSpike"