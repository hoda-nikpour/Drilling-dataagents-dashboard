import numpy as np
import pandas as pd

from agents.adjusted_pressure import AdjustedPressureConfig, detect_adjusted_pressure_spikes


def _cfg():
    return AdjustedPressureConfig(
        exponent=1.75,
        baseline_window=30,
        min_periods=15,
        robust_z_threshold=4.0,
        min_relative_deviation=0.05,
        min_mfi=1.0,
        min_consecutive=2,
    )


def test_gradual_flow_change_does_not_trigger_adjusted_pressure():
    # Physics-like synthetic example: SPP changes only because MFI changes.
    # Therefore SPP / MFI^1.75 is constant and should not be an anomaly.
    n = 120
    mfi = np.linspace(500.0, 800.0, n)
    spp = 0.02 * np.power(mfi, 1.75)
    df = pd.DataFrame({"SPP": spp, "MFI": mfi})

    out = detect_adjusted_pressure_spikes(df, spp_col="SPP", mfi_col="MFI", config=_cfg())
    assert int(out["pressure_spike"].sum()) == 0


def test_true_pressure_deviation_is_detected_after_flow_normalisation():
    n = 120
    mfi = np.full(n, 600.0)
    spp = 0.02 * np.power(mfi, 1.75)
    spp = spp.astype(float)
    spp[70:75] *= 1.30  # genuine 30% pressure increase not explained by MFI
    df = pd.DataFrame({"SPP": spp, "MFI": mfi})

    out = detect_adjusted_pressure_spikes(df, spp_col="SPP", mfi_col="MFI", config=_cfg())
    assert out.loc[70:74, "pressure_spike"].all()
    assert int(out["pressure_spike"].sum()) >= 5


def test_pump_off_samples_are_not_detected():
    n = 80
    mfi = np.full(n, 600.0)
    spp = 0.02 * np.power(mfi, 1.75)
    mfi[50:55] = 0.0
    spp[50:55] = 5000.0
    df = pd.DataFrame({"SPP": spp, "MFI": mfi})

    out = detect_adjusted_pressure_spikes(df, spp_col="SPP", mfi_col="MFI", config=_cfg())
    assert not out.loc[50:54, "pressure_spike"].any()
    assert not out.loc[50:54, "pressure_valid_for_detection"].any()
