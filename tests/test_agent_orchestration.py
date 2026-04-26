import pandas as pd

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from services.dashboard_service import run_activity_agent, run_symptom_agent
from ui.sidebar import build_agent_cfg_from_controls


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


def _make_background_activity_df():
    index = pd.date_range("2026-01-01 00:00:00", periods=20, freq="min")
    depth = [1000.0 + i * 0.02 for i in range(20)]

    return pd.DataFrame(
        {
            "BDTI": depth,
            "DMEA": depth,
            "DepthCsg": [400.0] * 20,
            "BPOS": [10.0] * 20,
            "HKL": [120.0] * 20,
            "MFI": [500.0] * 20,
            "RPMB": [80.0] * 20,
            "WOB": [8.0] * 20,
            "SPP": [100.0] * 20,
            "TRQ": [10.0] * 20,
        },
        index=index,
    )


def test_activity_agent_intervals_can_be_used_as_track_4_agent_lane():
    controls = {
        "agent_source": "Activity agent",
        "tag_intervals": [],
        "manual_agent_intervals": [],
        "activity_ui": {
            "enabled": True,
            "selected_activity": "Drilling",
            "config": ActivityConfig(),
            "manual_activity_tags": [],
        },
        "symptom_ui": {
            "enabled": False,
            "selected_symptom": "OpenHoleLength",
            "config": SymptomConfig(),
        },
        "show_reference_line": False,
        "reference_time": None,
        "chart_height": 950,
        "review_mode": "Standard review",
    }

    activity_cfg = {
        "intervals": [
            {
                "label": "Drilling",
                "start": pd.Timestamp("2026-01-01 00:00:00"),
                "end": pd.Timestamp("2026-01-01 01:00:00"),
                "severity": None,
                "source": "activity_agent",
            },
            {
                "label": "Reaming",
                "start": pd.Timestamp("2026-01-01 02:00:00"),
                "end": pd.Timestamp("2026-01-01 03:00:00"),
                "severity": None,
                "source": "activity_agent",
            },
        ],
        "selected_activity": "Drilling",
        "summary_df": pd.DataFrame(),
        "labels": pd.Series(dtype="object"),
        "features": pd.DataFrame(),
    }

    symptom_cfg = {
        "intervals": [],
        "selected_symptom": "OpenHoleLength",
        "features": pd.DataFrame(),
    }

    agent_cfg = build_agent_cfg_from_controls(
        controls=controls,
        activity_cfg=activity_cfg,
        symptom_cfg=symptom_cfg,
    )

    assert len(agent_cfg["agent_intervals"]) == 1
    assert agent_cfg["agent_intervals"][0]["label"] == "Drilling"
    assert agent_cfg["agent_intervals"][0]["source"] == "activity_agent"


def test_symptom_agent_intervals_can_be_used_as_track_4_agent_lane():
    controls = {
        "agent_source": "Symptom agent",
        "tag_intervals": [],
        "manual_agent_intervals": [],
        "activity_ui": {
            "enabled": True,
            "selected_activity": "MakingConnection",
            "config": ActivityConfig(),
            "manual_activity_tags": [],
        },
        "symptom_ui": {
            "enabled": True,
            "selected_symptom": "PSpike",
            "config": SymptomConfig(),
        },
        "show_reference_line": False,
        "reference_time": None,
        "chart_height": 950,
        "review_mode": "Standard review",
    }

    activity_cfg = {
        "intervals": [
            {
                "label": "Drilling",
                "start": pd.Timestamp("2026-01-01 00:00:00"),
                "end": pd.Timestamp("2026-01-01 01:00:00"),
                "severity": None,
                "source": "activity_agent",
            }
        ],
        "selected_activity": "MakingConnection",
        "summary_df": pd.DataFrame(),
        "labels": pd.Series(dtype="object"),
        "features": pd.DataFrame(),
    }

    symptom_cfg = {
        "intervals": [
            {
                "label": "PSpike",
                "start": pd.Timestamp("2026-01-01 00:10:00"),
                "end": pd.Timestamp("2026-01-01 00:12:00"),
                "severity": "High",
                "source": "symptom_agent",
            }
        ],
        "selected_symptom": "PSpike",
        "features": pd.DataFrame(),
    }

    agent_cfg = build_agent_cfg_from_controls(
        controls=controls,
        activity_cfg=activity_cfg,
        symptom_cfg=symptom_cfg,
    )

    assert len(agent_cfg["agent_intervals"]) == 1
    assert agent_cfg["agent_intervals"][0]["label"] == "PSpike"
    assert agent_cfg["agent_intervals"][0]["source"] == "symptom_agent"


def test_symptom_agent_can_use_background_activity_agent_result():
    df = _make_background_activity_df()
    label_to_column = _make_column_map()

    activity_ui = {
        "enabled": True,
        "selected_activity": "MakingConnection",
        "config": ActivityConfig(min_interval_samples=2),
        "manual_activity_tags": [],
    }

    activity_cfg = run_activity_agent(
        df=df,
        label_to_column=label_to_column,
        activity_ui=activity_ui,
    )

    symptom_ui = {
        "enabled": True,
        "selected_symptom": "OpenHoleLength",
        "config": SymptomConfig(
            open_hole_length_threshold_1=500.0,
            open_hole_length_threshold_2=750.0,
        ),
    }

    symptom_cfg = run_symptom_agent(
        df=df,
        label_to_column=label_to_column,
        symptom_ui=symptom_ui,
        activity_ui=activity_ui,
        activity_cfg=activity_cfg,
    )

    assert not activity_cfg["labels"].empty
    assert not activity_cfg["features"].empty

    assert symptom_cfg["selected_symptom"] == "OpenHoleLength"
    assert len(symptom_cfg["intervals"]) > 0
    assert symptom_cfg["intervals"][0]["label"] == "OpenHoleLength"
    assert symptom_cfg["intervals"][0]["source"] == "symptom_agent"