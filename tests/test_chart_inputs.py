import pandas as pd

from services.dashboard_service import (
    build_available_param_labels,
    build_requested_columns,
    flatten_selected_params,
    prepare_track_plot_inputs,
)


def test_build_available_param_labels_preserves_service_order():
    label_to_column = {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "WOB": "SWOB",
        "ROP": "ROP",
    }

    result = build_available_param_labels(label_to_column)

    assert result == ["Bit Depth", "Well Depth", "WOB", "ROP"]


def test_flatten_selected_params_removes_duplicates_and_preserves_order():
    track_param_labels = [
        ["WOB", "ROP"],
        ["SPP", "WOB"],
        ["TRQ", "ROP"],
    ]

    result = flatten_selected_params(track_param_labels)

    assert result == ["WOB", "ROP", "SPP", "TRQ"]


def test_build_requested_columns_includes_selected_activity_and_symptom_columns_once():
    selected_labels = ["WOB", "ROP"]
    required_activity_labels = ["Bit Depth", "Well Depth", "BPOS", "WOB"]
    required_symptom_labels = ["WOB", "SPP", "TRQ"]

    label_to_column = {
        "WOB": "SWOB",
        "ROP": "ROP",
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "BPOS": "BPOS",
        "SPP": "SPPA",
        "TRQ": "TQA",
    }

    result = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    assert result == ["SWOB", "ROP", "BDTI", "DMEA", "BPOS", "SPPA", "TQA"]


def test_prepare_track_plot_inputs_maps_labels_to_real_columns_and_adds_track_4():
    track_param_labels = [
        ["WOB", "ROP"],
        ["SPP"],
        ["TRQ", "Missing Parameter"],
    ]

    label_to_column = {
        "WOB": "SWOB",
        "ROP": "ROP",
        "SPP": "SPPA",
        "TRQ": "TQA",
    }

    track_colors = [
        ["#8E44AD", "#3498DB"],
        ["#E74C3C"],
        ["#8E44AD", "#3498DB"],
    ]

    track_params_real, plot_labels, plot_colors = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert track_params_real == [
        ["SWOB", "ROP"],
        ["SPPA"],
        ["TQA"],
        [],
    ]

    assert plot_labels == [
        ["WOB", "ROP"],
        ["SPP"],
        ["TRQ", "Missing Parameter"],
        [],
    ]

    assert plot_colors == [
        ["#8E44AD", "#3498DB"],
        ["#E74C3C"],
        ["#8E44AD", "#3498DB"],
        [],
    ]


def test_prepare_track_plot_inputs_does_not_change_original_inputs():
    track_param_labels = [["WOB"], ["ROP"], []]
    label_to_column = {"WOB": "SWOB", "ROP": "ROP"}
    track_colors = [["#8E44AD"], ["#3498DB"], []]

    original_labels = [x.copy() for x in track_param_labels]
    original_colors = [x.copy() for x in track_colors]

    prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert track_param_labels == original_labels
    assert track_colors == original_colors


def test_chart_input_dataframe_columns_exist_after_mapping():
    df = pd.DataFrame(
        {
            "SWOB": [1.0, 2.0, 3.0],
            "ROP": [10.0, 11.0, 12.0],
            "SPPA": [100.0, 110.0, 120.0],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="min"),
    )

    track_param_labels = [["WOB", "ROP"], ["SPP"], []]
    label_to_column = {
        "WOB": "SWOB",
        "ROP": "ROP",
        "SPP": "SPPA",
    }
    track_colors = [["#8E44AD", "#3498DB"], ["#E74C3C"], []]

    track_params_real, _, _ = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    used_columns = [col for track in track_params_real for col in track]

    assert used_columns == ["SWOB", "ROP", "SPPA"]
    assert all(col in df.columns for col in used_columns)