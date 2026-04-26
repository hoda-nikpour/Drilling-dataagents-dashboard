import pandas as pd

from agents.activity_agents import REQUIRED_ACTIVITY_INPUTS
from agents.symptom_agents import REQUIRED_SYMPTOM_INPUTS
from config import PARAMETER_ALIASES, PARAMETER_CATALOG
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


def test_build_sections_by_well_groups_sections_correctly():
    catalog = {
        "sections": [
            {"well": "C47", "section_in": 8.5},
            {"well": "C47", "section_in": 12.25},
            {"well": "F10", "section_in": 17.5},
        ]
    }

    result = build_sections_by_well(catalog)

    assert result == {
        "C47": ["8.5", "12.25"],
        "F10": ["17.5"],
    }


def test_flatten_selected_params_keeps_order_and_removes_duplicates():
    track_params = [
        ["Bit Depth", "WOB"],
        ["WOB", "RPMB"],
        ["SPP", "Bit Depth"],
    ]

    result = flatten_selected_params(track_params)

    assert result == ["Bit Depth", "WOB", "RPMB", "SPP"]


def test_build_label_to_column_map_finds_bit_depth_well_depth_and_wob():
    discovered_params = [
        "BDTI",
        "DMEA",
        "GS_DMEA",
        "DEPT",
        "DBTV",
        "WOB",
        "GS_WOB",
        "RPMB",
    ]

    result = build_label_to_column_map(
        discovered_params=discovered_params,
        parameter_aliases=PARAMETER_ALIASES,
    )

    assert result["Bit Depth"] == "BDTI"
    assert result["WOB"] in ["WOB", "GS_WOB"]

    assert "Well Depth" in result
    assert result["Well Depth"] in ["GS_DMEA", "DMEA", "DEPT", "DBTV"]


def test_build_available_param_labels_preserves_mapping_order():
    label_to_column = {
        "WOB": "WOB",
        "Bit Depth": "BDTI",
        "RPMB": "RPMB",
    }

    result = build_available_param_labels(label_to_column)

    assert result == ["WOB", "Bit Depth", "RPMB"]


def test_make_context_key_combines_well_and_sections():
    result = make_context_key("C47", ("8.5", "12.25"))

    assert result == "C47__8.5_12.25"


def test_build_parameter_catalog_df_returns_review_table():
    label_to_column = {
        "Bit Depth": "BDTI",
        "WOB": "WOB",
    }

    result = build_parameter_catalog_df(
        label_to_column=label_to_column,
        parameter_catalog=PARAMETER_CATALOG,
    )

    assert list(result.columns) == [
        "Parameter",
        "Raw mnemonic",
        "Meaning",
        "Unit",
        "Logical min",
        "Logical max",
    ]

    assert set(result["Parameter"]) == {"Bit Depth", "WOB"}
    assert set(result["Raw mnemonic"]) == {"BDTI", "WOB"}


def test_build_parameter_catalog_df_handles_empty_mapping():
    result = build_parameter_catalog_df(
        label_to_column={},
        parameter_catalog=PARAMETER_CATALOG,
    )

    assert result.empty
    assert list(result.columns) == [
        "Parameter",
        "Raw mnemonic",
        "Meaning",
        "Unit",
        "Logical min",
        "Logical max",
    ]


def test_build_requested_columns_includes_selected_activity_and_symptom_columns():
    label_to_column = {
        "Bit Depth": "BDTI",
        "Well Depth": "DMEA",
        "Casing Depth": "DepthCsg",
        "Mud Motor On": "MudMotorOn",
        "BPOS": "BPOS",
        "HKL": "HKL",
        "MFI": "MFI",
        "RPMB": "RPMB",
        "WOB": "WOB",
        "SPP": "SPP",
        "TRQ": "TRQ",
    }

    selected_labels = ["Bit Depth", "WOB"]

    required_activity_labels = [
        label for label in REQUIRED_ACTIVITY_INPUTS if label in label_to_column
    ]
    required_symptom_labels = [
        label for label in REQUIRED_SYMPTOM_INPUTS if label in label_to_column
    ]

    result = build_requested_columns(
        selected_labels=selected_labels,
        required_activity_labels=required_activity_labels,
        required_symptom_labels=required_symptom_labels,
        label_to_column=label_to_column,
    )

    assert "BDTI" in result
    assert "WOB" in result
    assert "DMEA" in result
    assert "BPOS" in result
    assert "HKL" in result
    assert "MFI" in result
    assert "RPMB" in result
    assert "SPP" in result
    assert "TRQ" in result
    assert "DepthCsg" in result
    assert "MudMotorOn" in result

    # ROP is no longer required by the VT-style activity logic.
    assert "ROP" not in result

    assert len(result) == len(set(result))


def test_empty_activity_result_has_expected_shape():
    index = pd.date_range("2026-01-01", periods=3, freq="min")
    df = pd.DataFrame(index=index)

    result = empty_activity_result(df)

    assert result["intervals"] == []
    assert result["summary_df"].empty
    assert result["labels"].empty
    assert result["selected_activity"] == "All activities"
    assert list(result["features"].index) == list(df.index)


def test_empty_symptom_result_has_expected_shape():
    index = pd.date_range("2026-01-01", periods=3, freq="min")
    df = pd.DataFrame(index=index)

    result = empty_symptom_result(df, selected_symptom="OpenHoleLength")

    assert result["intervals"] == []
    assert result["selected_symptom"] == "OpenHoleLength"
    assert list(result["features"].index) == list(df.index)


def test_prepare_track_plot_inputs_converts_labels_to_real_columns():
    track_param_labels = [
        ["Bit Depth", "WOB"],
        ["RPMB"],
        [],
    ]

    label_to_column = {
        "Bit Depth": "BDTI",
        "WOB": "WOB",
        "RPMB": "RPMB",
    }

    track_colors = [
        ["#111111", "#222222"],
        ["#333333"],
        [],
    ]

    real_params, labels_with_agent_track, colors_with_agent_track = prepare_track_plot_inputs(
        track_param_labels=track_param_labels,
        label_to_column=label_to_column,
        track_colors=track_colors,
    )

    assert real_params == [
        ["BDTI", "WOB"],
        ["RPMB"],
        [],
        [],
    ]

    assert labels_with_agent_track == [
        ["Bit Depth", "WOB"],
        ["RPMB"],
        [],
        [],
    ]

    assert colors_with_agent_track == [
        ["#111111", "#222222"],
        ["#333333"],
        [],
        [],
    ]