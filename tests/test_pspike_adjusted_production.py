import numpy as np
import pandas as pd

from agents.symptom_agents import SymptomConfig, build_pspike_agent


def _inputs(spp, mfi):
    n = len(spp)
    idx = pd.RangeIndex(n)

    df = pd.DataFrame(
        {
            "SPP": spp,
            "MFI": mfi,
            "WOB": np.full(n, 10.0),
            "RPMB": np.full(n, 120.0),
            "Mud Motor On": np.zeros(n),
        },
        index=idx,
    )

    column_map = {
        "SPP": "SPP",
        "MFI": "MFI",
        "WOB": "WOB",
        "RPMB": "RPMB",
        "Mud Motor On": "Mud Motor On",
    }

    activity_labels = pd.Series("Drilling", index=idx)

    activity_features = pd.DataFrame(
        {
            "stable_flow": True,
            "stable_rpm": True,
            "stable_wob": True,
        },
        index=idx,
    )

    return df, column_map, activity_features, activity_labels


def test_pspike_does_not_fire_for_flow_driven_spp_ramp():
    n = 90
    mfi = np.linspace(450.0, 800.0, n)
    spp = 0.02 * np.power(mfi, 1.75)

    df, cmap, features, labels = _inputs(spp, mfi)

    out, intervals = build_pspike_agent(
        df=df,
        column_map=cmap,
        cfg=SymptomConfig(),
        activity_features=features,
        activity_labels=labels,
    )

    assert out["spp_delta"].abs().max() > 0
    assert not out["combined_mask"].any()
    assert intervals == []


def test_pspike_detects_real_pressure_rise_at_constant_mfi():
    n = 90
    mfi = np.full(n, 600.0)
    spp = np.full(n, 0.02 * (600.0 ** 1.75), dtype=float)
    spp[55:60] *= 1.30

    df, cmap, features, labels = _inputs(spp, mfi)

    out, intervals = build_pspike_agent(
        df=df,
        column_map=cmap,
        cfg=SymptomConfig(),
        activity_features=features,
        activity_labels=labels,
    )

    assert out.loc[55:59, "adjusted_pressure_spike"].any()
    assert out.loc[55:59, "combined_mask"].any()
    assert len(intervals) >= 1


def test_raw_spp_delta_is_diagnostic_not_event_gate():
    n = 90
    mfi = np.full(n, 500.0)
    mfi[45:] = 800.0
    spp = 0.02 * np.power(mfi, 1.75)

    df, cmap, features, labels = _inputs(spp, mfi)

    out, intervals = build_pspike_agent(
        df=df,
        column_map=cmap,
        cfg=SymptomConfig(),
        activity_features=features,
        activity_labels=labels,
    )

    assert out["spp_delta"].max() > 0
    assert not out["adjusted_pressure_spike"].any()
    assert not out["combined_mask"].any()
    assert intervals == []
