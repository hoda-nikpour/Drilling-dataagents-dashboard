from pathlib import Path

SYMPTOM = Path("agents/symptom_agents.py")
TEST = Path("tests/test_pspike_adjusted_production.py")

if not SYMPTOM.exists():
    raise SystemExit(f"Missing {SYMPTOM}. Run this script from the repository root.")

text = SYMPTOM.read_text()

# 1) Import adjusted-pressure detector.
import_block = """from agents.adjusted_pressure import (
    AdjustedPressureConfig,
    detect_adjusted_pressure_spikes,
)
"""

if "from agents.adjusted_pressure import" not in text:
    marker = "import pandas as pd\n"
    if marker not in text:
        raise SystemExit("Could not locate 'import pandas as pd'; no changes written.")
    text = text.replace(marker, marker + "\n" + import_block, 1)

# 2) Add production adjusted-pressure config fields.
if "pspike_adjusted_exponent" not in text:
    marker = "    pspike_min_interval_samples: int = 1\n"
    if marker not in text:
        raise SystemExit(
            "Could not locate pspike_min_interval_samples in SymptomConfig; no changes written."
        )

    extra_config = """    # Flow-normalised PSpike settings.
    # Production PSpike uses SPP / MFI**1.75 rather than raw SPP delta.
    pspike_adjusted_exponent: float = 1.75
    pspike_adjusted_robust_z_threshold: float = 4.0
    pspike_adjusted_min_relative_deviation: float = 0.05
    pspike_adjusted_min_mfi: float = 1.0
    pspike_adjusted_min_consecutive: int = 2
    pspike_adjusted_min_periods: int = 10
"""
    text = text.replace(marker, marker + extra_config, 1)

# 3) Replace build_pspike_agent using function boundaries.
start = text.find("def build_pspike_agent(")
end = text.find("def build_overpull_agent(", start)

if start < 0 or end < 0:
    raise SystemExit(
        "Could not locate build_pspike_agent/build_overpull_agent boundaries; no changes written."
    )

new_function = """def build_pspike_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    # Production PSpike uses flow-normalised pressure:
    # adjusted_pressure = SPP / MFI ** 1.75
    # Raw SPP/spp_delta remain diagnostics only.

    out = pd.DataFrame(index=df.index)

    spp = _pick_series(df, column_map, "SPP")
    wob = _pick_series(df, column_map, "WOB")
    rpm = _pick_series(df, column_map, "RPMB")
    mfi = _pick_series(df, column_map, "MFI")
    mud_motor_signal = _pick_series(df, column_map, "Mud Motor On")

    # Legacy raw-SPP diagnostics only.
    spp_baseline = rolling_baseline(spp, cfg.pspike_baseline_window)
    spp_delta = spp - spp_baseline

    pressure_input = pd.DataFrame(
        {
            "__pspike_spp": spp,
            "__pspike_mfi": mfi,
        },
        index=df.index,
    )

    adjusted_window = max(3, int(cfg.pspike_baseline_window))
    requested_min_periods = int(
        getattr(cfg, "pspike_adjusted_min_periods", 10)
    )
    adjusted_min_periods = max(
        1,
        min(requested_min_periods, adjusted_window),
    )

    adjusted_cfg = AdjustedPressureConfig(
        exponent=float(getattr(cfg, "pspike_adjusted_exponent", 1.75)),
        baseline_window=adjusted_window,
        min_periods=adjusted_min_periods,
        robust_z_threshold=float(
            getattr(cfg, "pspike_adjusted_robust_z_threshold", 4.0)
        ),
        min_relative_deviation=float(
            getattr(cfg, "pspike_adjusted_min_relative_deviation", 0.05)
        ),
        min_mfi=float(
            getattr(cfg, "pspike_adjusted_min_mfi", 1.0)
        ),
        min_consecutive=max(
            1,
            int(getattr(cfg, "pspike_adjusted_min_consecutive", 2)),
        ),
    )

    pressure_diag = detect_adjusted_pressure_spikes(
        pressure_input,
        spp_col="__pspike_spp",
        mfi_col="__pspike_mfi",
        config=adjusted_cfg,
    )

    adjusted_spike = (
        pressure_diag["pressure_spike"]
        .reindex(df.index)
        .fillna(False)
        .astype(bool)
    )

    pressure_valid = (
        pressure_diag["pressure_valid_for_detection"]
        .reindex(df.index)
        .fillna(False)
        .astype(bool)
    )

    context_mask = (
        activity_labels.reindex(df.index)
        .isin(["Drilling", "Reaming"])
        .fillna(False)
    )

    # Flow stability is diagnostic only; it no longer gates PSpike.
    stable_flow_mask = pd.Series(True, index=df.index)
    if cfg.require_stable_flow_for_pspike:
        stable_flow_mask = (
            mfi.diff().abs().fillna(0.0) <= cfg.pspike_flow_delta_max
        )
        if "stable_flow" in activity_features.columns:
            stable_flow_mask &= (
                activity_features["stable_flow"]
                .reindex(df.index)
                .fillna(False)
            )

    stable_rpm_mask = pd.Series(True, index=df.index)
    if cfg.require_stable_rpm_for_pspike:
        stable_rpm_mask = (
            rpm.diff().abs().fillna(0.0) <= cfg.pspike_rpm_delta_max
        )
        if "stable_rpm" in activity_features.columns:
            stable_rpm_mask &= (
                activity_features["stable_rpm"]
                .reindex(df.index)
                .fillna(False)
            )

    stable_wob_mask = pd.Series(True, index=df.index)
    if cfg.require_stable_wob_for_pspike:
        stable_wob_mask = (
            wob.diff().abs().fillna(0.0) <= cfg.pspike_wob_delta_max
        )
        if "stable_wob" in activity_features.columns:
            stable_wob_mask &= (
                activity_features["stable_wob"]
                .reindex(df.index)
                .fillna(False)
            )

    # IMPORTANT: no stable_flow_mask here.
    stable_mask = stable_rpm_mask & stable_wob_mask

    # Raw-SPP stability remains diagnostic only.
    spp_stable_before_spike = stable_within_band(
        spp.shift(1),
        cfg.pspike_baseline_window,
        cfg.pspike_spp_stability_band,
    )

    if mud_motor_signal.notna().any():
        mud_motor_on = mud_motor_signal.fillna(0.0) > 0.0
    else:
        mud_motor_on = wob > cfg.pspike_motor_wob_threshold

    # FINAL production gate: adjusted pressure drives PSpike.
    raw_adjusted_event_mask = (
        adjusted_spike
        & pressure_valid
        & context_mask
        & stable_mask
    )

    combined_mask = fill_short_false_gaps(
        raw_adjusted_event_mask,
        cfg.pspike_gap_fill_samples,
    )

    # Never fill gaps outside valid operational context.
    combined_mask &= pressure_valid & context_mask & stable_mask

    normal_mask = combined_mask & ~mud_motor_on
    motor_mask = combined_mask & mud_motor_on

    # Existing diagnostics.
    out["spp"] = spp
    out["spp_baseline"] = spp_baseline
    out["spp_delta"] = spp_delta
    out["wob"] = wob
    out["rpm"] = rpm
    out["mfi"] = mfi
    out["mud_motor_signal"] = mud_motor_signal
    out["mud_motor_on"] = mud_motor_on

    # Adjusted-pressure diagnostics.
    adjusted_columns = [
        "adjusted_pressure",
        "pressure_valid_for_detection",
        "adjusted_pressure_baseline",
        "adjusted_pressure_scale",
        "adjusted_pressure_deviation",
        "adjusted_pressure_relative_deviation",
        "adjusted_pressure_robust_z",
        "pressure_spike_candidate",
        "pressure_spike",
        "raw_spp_baseline",
        "raw_spp_scale",
        "raw_spp_deviation",
        "raw_spp_robust_z",
        "raw_spp_spike_candidate",
    ]
    for col in adjusted_columns:
        if col in pressure_diag.columns:
            out[col] = pressure_diag[col].reindex(df.index)

    out["adjusted_pressure_spike"] = adjusted_spike
    out["pspike_event_gate"] = raw_adjusted_event_mask

    out["context_mask"] = context_mask
    out["stable_flow_mask"] = stable_flow_mask
    out["stable_rpm_mask"] = stable_rpm_mask
    out["stable_wob_mask"] = stable_wob_mask
    out["stable_mask"] = stable_mask
    out["spp_stable_before_spike"] = spp_stable_before_spike

    out["normal_mask"] = normal_mask
    out["motor_mask"] = motor_mask
    out["combined_mask"] = combined_mask

    lvl1_intervals = mask_to_intervals(
        mask=normal_mask,
        label="PSpike",
        min_samples=cfg.pspike_min_interval_samples,
        severity="Medium",
    )

    lvl2_intervals = mask_to_intervals(
        mask=motor_mask,
        label="PSpike",
        min_samples=cfg.pspike_min_interval_samples,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


"""

text = text[:start] + new_function + text[end:]
SYMPTOM.write_text(text)

# 4) Production regression tests.
test_text = """import numpy as np
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
"""

TEST.parent.mkdir(parents=True, exist_ok=True)
TEST.write_text(test_text)

print("SUCCESS")
print(f"Updated: {SYMPTOM}")
print(f"Created/updated: {TEST}")
print("Production PSpike now uses adjusted pressure = SPP / MFI**1.75.")
print("Raw SPP/spp_delta remain diagnostics only.")
