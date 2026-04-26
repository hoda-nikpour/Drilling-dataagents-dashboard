import pandas as pd

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from config import PARAMETER_ALIASES, TRACK_COLOR_PALETTE
from services.dashboard_controls import (
    apply_time_filter,
    build_time_filter_result,
    calculate_zoom_percent,
    get_default_time_range,
)
from services.dashboard_service import (
    build_label_to_column_map,
    build_requested_columns,
    flatten_selected_params,
    prepare_track_plot_inputs,
    run_activity_agent,
    run_symptom_agent,
)


def make_time_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01 00:00:00", periods=11, freq="1min")
    return pd.DataFrame(
        {
            "BDTI": range(11),
            "DMEA": range(100, 111),
            "BPOS": [10.0] * 11,
            "HKL": [100.0] * 11,
            "MFI": [0.0] * 11,
            "RPMB": [0.0] * 11,
            "ROP": [0.0] * 11,
            "WOB": [0.0] * 11,
            "SPP": [100.0] * 11,
            "TRQ": [5.0] * 11,
        },
        index=index,
    )


def test_default_time_range_uses_full_dataframe_index():
    df = make_time_df()

    default_range = get_default_time_range(df)

    assert default_range[0] == df.index.min().to_pydatetime()
    assert default_range[1] == df.index.max().to_pydatetime()


def test_apply_time_filter_slices_dataframe_correctly():
    df = make_time_df()
    start = pd.Timestamp("2024-01-01 00:03:00")
    end = pd.Timestamp("2024-01-01 00:06:00")

    filtered = apply_time_filter(df, (start, end))

    assert len(filtered) == 4
    assert filtered.index.min() == start
    assert filtered.index.max() == end


def test_calculate_zoom_percent_full_range_is_zero():
    df = make_time_df()

    zoom_percent = calculate_zoom_percent(
        t_min_all=df.index.min(),
        t_max_all=df.index.max(),
        selected_start=df.index.min(),
        selected_end=df.index.max(),
    )

    assert zoom_percent == 0.0


def test_calculate_zoom_percent_half_range_is_about_fifty():
    df = make_time_df()

    zoom_percent = calculate_zoom_percent(
        t_min_all=df.index.min(),
        t_max_all=df.index.max(),
        selected_start=df.index.min(),
        selected_end=df.index[5],
    )

    assert zoom_percent == 50.0


def test_build_time_filter_result_returns_filtered_df_and_zoom():
    df = make_time_df()
    time_range = (df.index[2], df.index[7])

    result = build_time_filter_result(df, time_range)

    assert len(result["df_filtered"]) == 6
    assert result["df_filtered"].index.min() == df.index[2]
    assert result["df_filtered"].index.max() == df.index[7]
    assert result["zoom_percent"] == 50.0
    assert result["time_range"] == time_range


def test_track_parameter_change_updates_selected_labels_requested_columns_and_plot_inputs():
    discovered_columns = [
        "BDTI",
        "DMEA",
        "WOB",
        "RPMB",
        "MFI",
        "BPOS",
        "HKL",
        "ROP",
        "SPP",
        "TRQ",
    ]

    label_to_column = build_label_to_column_map(
        discovered_params=discovered_columns,
        parameter_aliases=PARAMETER_ALIASES,
    )

    track_param_labels = [
        ["Bit Depth", "WOB"],
        ["RPMB"],
        [],
    ]

    selected_labels = flatten_selected_params(track_param_labels)

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=[
            "Bit Depth",
            "Well Depth",
            "BPOS",
            "HKL",
            "MFI",
            "RPMB",
            "ROP",
            "WOB",
        ],
        required_symptom_labels=[
            "Bit Depth",
            "Well Depth",
            "MFI",
            "RPMB",
            "SPP",
            "TRQ",
            "WOB",
            "HKL",
        ],
        label_to_column=label_to_column,
    )

    track_colors = [TRACK_COLOR_PALETTE[: len(track)] for track in track_param_labels]

    track_params_real, chart_labels, chart_colors = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert selected_labels == ["Bit Depth", "WOB", "RPMB"]

    assert "BDTI" in requested_columns
    assert "DMEA" in requested_columns
    assert "WOB" in requested_columns
    assert "RPMB" in requested_columns
    assert "MFI" in requested_columns
    assert "BPOS" in requested_columns
    assert "HKL" in requested_columns
    assert "ROP" in requested_columns
    assert "SPP" in requested_columns
    assert "TRQ" in requested_columns

    assert track_params_real == [["BDTI", "WOB"], ["RPMB"], [], []]
    assert chart_labels == [["Bit Depth", "WOB"], ["RPMB"], [], []]
    assert len(chart_colors) == 4


def test_activity_agent_disabled_returns_empty_safe_result():
    df = make_time_df()

    label_to_column = {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "BPOS": "BPOS",
        "HKL": "HKL",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "ROP": "ROP",
        "WOB": "WOB",
    }

    activity_ui = {
        "enabled": False,
        "selected_activity": "Drilling",
        "config": ActivityConfig(),
    }

    activity_result = run_activity_agent(
        df=df,
        label_to_column=label_to_column,
        activity_ui=activity_ui,
    )

    assert activity_result["intervals"] == []
    assert activity_result["summary_df"].empty
    assert activity_result["labels"].empty
    assert activity_result["selected_activity"] == "All activities"
    assert list(activity_result["features"].index) == list(df.index)


def test_symptom_agent_enabled_but_activity_disabled_returns_empty_safe_result():
    df = make_time_df()

    label_to_column = {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "SPP": "SPP",
        "TRQ": "TRQ",
        "WOB": "WOB",
        "HKL": "HKL",
    }

    activity_ui = {
        "enabled": False,
        "selected_activity": "Drilling",
        "config": ActivityConfig(),
    }

    activity_result = run_activity_agent(
        df=df,
        label_to_column=label_to_column,
        activity_ui=activity_ui,
    )

    symptom_ui = {
        "enabled": True,
        "selected_symptom": "PSpike",
        "config": SymptomConfig(),
    }

    symptom_result = run_symptom_agent(
        df=df,
        label_to_column=label_to_column,
        symptom_ui=symptom_ui,
        activity_ui=activity_ui,
        activity_cfg=activity_result,
    )

    assert symptom_result["intervals"] == []
    assert symptom_result["selected_symptom"] == "PSpike"
    assert list(symptom_result["features"].index) == list(df.index)