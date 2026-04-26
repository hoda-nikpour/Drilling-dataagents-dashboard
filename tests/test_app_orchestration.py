import pandas as pd

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS
from config import PARAMETER_ALIASES, PARAMETER_CATALOG, TRACK_COLOR_PALETTE
from services.dashboard_service import (
    build_available_param_labels,
    build_label_to_column_map,
    build_parameter_catalog_df,
    build_requested_columns,
    build_sections_by_well,
    empty_activity_result,
    empty_symptom_result,
    flatten_selected_params,
    make_context_key,
    prepare_track_plot_inputs,
)


def test_full_dashboard_preparation_path_works():
    catalog = {
        "sections": [
            {"well": "WELL_A", "section_in": 8.5},
            {"well": "WELL_A", "section_in": 12.25},
            {"well": "WELL_B", "section_in": 17.5},
        ]
    }

    sections_by_well = build_sections_by_well(catalog)

    assert sections_by_well == {
        "WELL_A": ["8.5", "12.25"],
        "WELL_B": ["17.5"],
    }

    selected_well = "WELL_A"
    selected_sections = tuple(sorted(["12.25", "8.5"], key=float))

    context_key = make_context_key(selected_well, selected_sections)

    assert context_key == "WELL_A__8.5_12.25"

    discovered_columns = [
        "BDTI",
        "GS_DMEA",
        "GS_BPOS",
        "GS_HKLD",
        "GS_MFI",
        "RPMB",
        "ROP",
        "WOB",
        "GS_SPPA",
        "GS_TQA",
        "UNUSED_COLUMN",
    ]

    label_to_column = build_label_to_column_map(
        discovered_params=discovered_columns,
        parameter_aliases=PARAMETER_ALIASES,
    )

    assert label_to_column["Bit Depth"] == "BDTI"
    assert label_to_column["Well Depth"] == "GS_DMEA"
    assert label_to_column["BPOS"] == "GS_BPOS"
    assert label_to_column["HKL"] == "GS_HKLD"
    assert label_to_column["MFI"] == "GS_MFI"
    assert label_to_column["RPMB"] == "RPMB"
    assert label_to_column["ROP"] == "ROP"
    assert label_to_column["WOB"] == "WOB"
    assert label_to_column["SPP"] == "GS_SPPA"
    assert label_to_column["TRQ"] == "GS_TQA"

    available_param_labels = build_available_param_labels(label_to_column)

    assert "Bit Depth" in available_param_labels
    assert "Well Depth" in available_param_labels
    assert "WOB" in available_param_labels
    assert "UNUSED_COLUMN" not in available_param_labels

    track_param_labels = [
        ["Bit Depth", "WOB"],
        ["MFI", "RPMB"],
        ["SPP", "TRQ"],
    ]

    selected_labels = flatten_selected_params(track_param_labels)

    assert selected_labels == ["Bit Depth", "WOB", "MFI", "RPMB", "SPP", "TRQ"]

    required_activity_labels = [
        label for label in REQUIRED_ACTIVITY_INPUTS if label in label_to_column
    ]
    required_symptom_labels = [
        label for label in REQUIRED_SYMPTOM_INPUTS if label in label_to_column
    ]

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    # Selected plot columns are included.
    assert "BDTI" in requested_columns
    assert "WOB" in requested_columns
    assert "GS_MFI" in requested_columns
    assert "RPMB" in requested_columns
    assert "GS_SPPA" in requested_columns
    assert "GS_TQA" in requested_columns

    # Activity-required raw columns are included.
    assert "GS_DMEA" in requested_columns
    assert "GS_BPOS" in requested_columns
    assert "GS_HKLD" in requested_columns

    # ROP is no longer required by the VT-style activity logic.
    assert "ROP" not in requested_columns

    # No duplicate raw columns.
    assert len(requested_columns) == len(set(requested_columns))

    track_colors = [
        TRACK_COLOR_PALETTE[: len(track)]
        for track in track_param_labels
    ]

    track_params_real, final_track_labels, final_track_colors = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert track_params_real == [
        ["BDTI", "WOB"],
        ["GS_MFI", "RPMB"],
        ["GS_SPPA", "GS_TQA"],
        [],
    ]

    assert final_track_labels == [
        ["Bit Depth", "WOB"],
        ["MFI", "RPMB"],
        ["SPP", "TRQ"],
        [],
    ]

    assert len(final_track_colors) == 4
    assert final_track_colors[-1] == []


def test_parameter_catalog_df_is_safe_for_available_labels():
    label_to_column = {
        "Bit Depth": "BDTI",
        "Well Depth": "GS_DMEA",
        "WOB": "WOB",
    }

    catalog_df = build_parameter_catalog_df(
        label_to_column=label_to_column,
        parameter_catalog=PARAMETER_CATALOG,
    )

    assert list(catalog_df.columns) == [
        "Parameter",
        "Raw mnemonic",
        "Meaning",
        "Unit",
        "Logical min",
        "Logical max",
    ]

    assert set(catalog_df["Parameter"]) == {"Bit Depth", "Well Depth", "WOB"}
    assert set(catalog_df["Raw mnemonic"]) == {"BDTI", "GS_DMEA", "WOB"}


def test_missing_and_empty_selections_behave_safely():
    discovered_columns = ["BDTI", "WOB"]

    label_to_column = build_label_to_column_map(
        discovered_params=discovered_columns,
        parameter_aliases=PARAMETER_ALIASES,
    )

    assert label_to_column == {
        "Bit Depth": "BDTI",
        "WOB": "WOB",
    }

    track_param_labels = [
        ["Bit Depth", "Missing Parameter"],
        [],
        ["WOB"],
    ]

    selected_labels = flatten_selected_params(track_param_labels)

    assert selected_labels == ["Bit Depth", "Missing Parameter", "WOB"]

    requested_columns = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=["Bit Depth", "Well Depth", "Missing Parameter"],
        required_symptom_labels=["WOB", "SPP", "Missing Parameter"],
        label_to_column=label_to_column,
    )

    assert requested_columns == ["BDTI", "WOB"]

    track_colors = [
        TRACK_COLOR_PALETTE[: len(track)]
        for track in track_param_labels
    ]

    track_params_real, final_track_labels, final_track_colors = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert track_params_real == [
        ["BDTI"],
        [],
        ["WOB"],
        [],
    ]

    # The labels are preserved for display, even if one missing label has no raw column.
    assert final_track_labels == [
        ["Bit Depth", "Missing Parameter"],
        [],
        ["WOB"],
        [],
    ]

    assert len(final_track_colors) == 4


def test_empty_catalog_and_empty_catalog_dataframe_are_safe():
    sections_by_well = build_sections_by_well({"sections": []})

    assert sections_by_well == {}

    catalog_df = build_parameter_catalog_df(
        label_to_column={},
        parameter_catalog=PARAMETER_CATALOG,
    )

    assert catalog_df.empty
    assert list(catalog_df.columns) == [
        "Parameter",
        "Raw mnemonic",
        "Meaning",
        "Unit",
        "Logical min",
        "Logical max",
    ]


def test_empty_agent_results_preserve_dataframe_index():
    index = pd.date_range("2026-01-01 00:00:00", periods=3, freq="min")
    df = pd.DataFrame({"BDTI": [1000.0, 1001.0, 1002.0]}, index=index)

    activity_result = empty_activity_result(df)

    assert activity_result["intervals"] == []
    assert activity_result["summary_df"].empty
    assert activity_result["labels"].empty
    assert activity_result["selected_activity"] == "All activities"
    assert activity_result["features"].index.equals(df.index)

    symptom_result = empty_symptom_result(df, selected_symptom="PSpike")

    assert symptom_result["intervals"] == []
    assert symptom_result["selected_symptom"] == "PSpike"
    assert symptom_result["features"].index.equals(df.index)