from dataclasses import dataclass

import pandas as pd

from agents.activity_support import fill_short_false_gaps, stable_within_band
from agents.symptom_support import (
    first_crossing_intervals,
    mask_to_intervals,
    rolling_baseline,
    rolling_reference_mean,
    rolling_reference_min,
    rolling_reference_std,
)


@dataclass(frozen=True)
class SymptomConfig:
    open_hole_length_threshold_1: float = 500.0
    open_hole_length_threshold_2: float = 750.0
    casing_depth: float | None = None

    # TRQSpike settings
    # trq_baseline_window is kept for backward compatibility with existing UI code.
    trq_baseline_window: int = 60
    trq_mean_long_window: int = 60
    trq_start_low_window: int = 7
    trq_spike_ratio_level_1: float = 1.25
    trq_spike_ratio_level_2: float = 1.40
    trq_spike_zscore_min: float = 2.9
    trq_spike_start_low_ratio: float = 1.05
    trq_spike_extreme_ratio: float = 1.80
    trq_min_baseline: float = 0.1

    # TRQErratic settings
    trq_erratic_mean_long_window: int = 100
    trq_erratic_ratio_level_1: float = 1.10
    trq_erratic_min_cycles: int = 3
    trq_erratic_high_cycles: int = 20
    trq_erratic_rpm_stability_band: float = 8.0

    pspike_baseline_window: int = 20
    pspike_threshold_normal: float = 5.0
    pspike_threshold_motor_on: float = 7.0
    pspike_gap_fill_samples: int = 2
    pspike_min_interval_samples: int = 1
    pspike_flow_delta_max: float = 50.0  # AI made assumption on this part: VT says Δq must be very small, but gives no number.
    pspike_rpm_delta_max: float = 3.0  # AI made assumption on this part.
    pspike_wob_delta_max: float = 0.5  # AI made assumption on this part.
    pspike_spp_stability_band: float = 3.0  # AI made assumption on this part.
    pspike_motor_wob_threshold: float = 0.5  # AI made assumption on this part when no Mud Motor On signal is available.

    overpull_baseline_window: int = 20
    overpull_threshold: float = 6.0
    overpull_gap_fill_samples: int = 2
    overpull_min_interval_samples: int = 1

    tookweight_baseline_window: int = 20
    tookweight_threshold: float = 6.0
    tookweight_gap_fill_samples: int = 2
    tookweight_min_interval_samples: int = 1

    hoisting_velocity_min: float = 0.15
    hoisting_velocity_max: float = 1.5

    require_stable_flow_for_pspike: bool = True
    require_stable_rpm_for_pspike: bool = True
    require_stable_wob_for_pspike: bool = True


REQUIRED_SYMPTOM_INPUTS = [
    "Bit Depth",
    "Well Depth",
    "Casing Depth",
    "MFI",
    "RPMB",
    "SPP",
    "TRQ",
    "WOB",
    "HKL",
    "Mud Motor On",
]


def _pick_series(df: pd.DataFrame, column_map: dict[str, str], logical_name: str) -> pd.Series:
    col = column_map.get(logical_name)
    if col is None or col not in df.columns:
        return pd.Series(index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def _series_from_config_or_column(
    df: pd.DataFrame,
    column_map: dict[str, str],
    logical_name: str,
    fallback_value: float | None,
) -> pd.Series:
    series = _pick_series(df, column_map, logical_name)
    if series.notna().any():
        return series

    if fallback_value is not None:
        return pd.Series(float(fallback_value), index=df.index, dtype="float64")

    return series


def _hoisting_velocity_from_bpos(activity_features: pd.DataFrame, index: pd.Index) -> pd.Series:
    if "bpos" not in activity_features.columns:
        return pd.Series(float("nan"), index=index, dtype="float64")

    bpos = pd.to_numeric(activity_features["bpos"], errors="coerce")
    if isinstance(index, pd.DatetimeIndex):
        seconds = pd.Series(index=index, data=index).diff().dt.total_seconds()
        seconds = seconds.replace(0.0, pd.NA)
        return (bpos.diff().abs() / seconds).fillna(0.0)

    return bpos.diff().abs().fillna(0.0)


def build_open_hole_length_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    well_depth = _pick_series(df, column_map, "Well Depth")
    casing_depth = _series_from_config_or_column(
        df=df,
        column_map=column_map,
        logical_name="Casing Depth",
        fallback_value=cfg.casing_depth,
    )

    open_hole_length = (well_depth - casing_depth).clip(lower=0.0)
    out["well_depth"] = well_depth
    out["casing_depth"] = casing_depth
    out["open_hole_length"] = open_hole_length

    lvl1_mask = open_hole_length > cfg.open_hole_length_threshold_1
    lvl2_mask = open_hole_length > cfg.open_hole_length_threshold_2

    lvl1_intervals = first_crossing_intervals(
        mask=lvl1_mask & ~lvl2_mask,
        label="OpenHoleLength",
        severity="Low",
    )
    lvl2_intervals = first_crossing_intervals(
        mask=lvl2_mask,
        label="OpenHoleLength",
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


def build_trq_spike_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_labels: pd.Series | None = None,
    activity_features: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    trq = _pick_series(df, column_map, "TRQ")
    rpm = _pick_series(df, column_map, "RPMB")

    window = getattr(cfg, "trq_mean_long_window", cfg.trq_baseline_window)

    trq_mean_long = rolling_reference_mean(trq, window).clip(lower=cfg.trq_min_baseline)
    trq_std_long = rolling_reference_std(trq, window).fillna(0.0)
    trq_min_previous_7 = rolling_reference_min(trq, cfg.trq_start_low_window)

    trq_ratio = trq / trq_mean_long
    trq_zscore = (trq - trq_mean_long) / trq_std_long.replace(0.0, pd.NA)

    out["trq"] = trq
    out["rpm"] = rpm
    out["trq_mean_long"] = trq_mean_long
    out["trq_std_long"] = trq_std_long
    out["trq_ratio"] = trq_ratio
    out["trq_zscore"] = trq_zscore
    out["trq_min_previous_7"] = trq_min_previous_7

    rpm_on = rpm > 0

    rpm_stable = pd.Series(True, index=df.index)
    if activity_features is not None and "stable_rpm" in activity_features.columns:
        rpm_stable = activity_features["stable_rpm"]

    context_mask = rpm_on & rpm_stable

    if activity_labels is not None and not activity_labels.empty:
        context_mask &= activity_labels.isin(["Drilling", "Reaming"])

    started_low = trq_min_previous_7 < (cfg.trq_spike_start_low_ratio * trq_mean_long)

    normal_spike_shape = (
        (trq_zscore > cfg.trq_spike_zscore_min)
        & started_low
    )

    extreme_spike = trq_ratio > cfg.trq_spike_extreme_ratio

    spike_gate = normal_spike_shape | extreme_spike

    lvl1_mask = (
        context_mask
        & spike_gate
        & (trq_ratio > cfg.trq_spike_ratio_level_1)
        & (trq_ratio <= cfg.trq_spike_ratio_level_2)
    )

    lvl2_mask = (
        context_mask
        & spike_gate
        & (trq_ratio > cfg.trq_spike_ratio_level_2)
    )

    lvl1_intervals = mask_to_intervals(
        mask=lvl1_mask,
        label="TRQSpike",
        min_samples=1,
        severity="Low",
    )

    lvl2_intervals = mask_to_intervals(
        mask=lvl2_mask,
        label="TRQSpike",
        min_samples=1,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


def build_trq_erratic_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    trq = _pick_series(df, column_map, "TRQ")
    rpm = _pick_series(df, column_map, "RPMB")

    mean_long = rolling_reference_mean(trq, cfg.trq_erratic_mean_long_window).clip(
        lower=cfg.trq_min_baseline
    )

    deviation = trq - mean_long

    sign = deviation.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    sign_change = (sign != sign.shift(1)) & sign.ne(0) & sign.shift(1).ne(0)

    cycle_count = sign_change.astype(int).rolling(
        window=cfg.trq_erratic_mean_long_window,
        min_periods=1,
        center=False,
    ).sum()

    trq_ratio = trq.abs() / mean_long.abs().replace(0.0, pd.NA)

    rpm_stable = stable_within_band(
        rpm,
        cfg.short_window if hasattr(cfg, "short_window") else 10,
        cfg.trq_erratic_rpm_stability_band,
    )

    if "stable_rpm" in activity_features.columns:
        rpm_stable &= activity_features["stable_rpm"]

    context_mask = activity_labels.isin(["Drilling", "Reaming"])

    lvl1_mask = (
        context_mask
        & rpm_stable
        & (trq_ratio > cfg.trq_erratic_ratio_level_1)
        & (cycle_count >= cfg.trq_erratic_min_cycles)
        & (cycle_count < cfg.trq_erratic_high_cycles)
    )

    lvl2_mask = (
        context_mask
        & rpm_stable
        & (trq_ratio > cfg.trq_erratic_ratio_level_1)
        & (cycle_count >= cfg.trq_erratic_high_cycles)
    )

    out["trq"] = trq
    out["rpm"] = rpm
    out["trq_mean_long"] = mean_long
    out["trq_deviation"] = deviation
    out["trq_ratio"] = trq_ratio
    out["trq_sign_change"] = sign_change
    out["trq_cycle_count"] = cycle_count
    out["rpm_stable"] = rpm_stable

    lvl1_intervals = mask_to_intervals(
        mask=lvl1_mask,
        label="TRQErratic",
        min_samples=cfg.trq_erratic_min_cycles,
        severity="Low",
    )

    lvl2_intervals = mask_to_intervals(
        mask=lvl2_mask,
        label="TRQErratic",
        min_samples=1,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


def build_pspike_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    spp = _pick_series(df, column_map, "SPP")
    wob = _pick_series(df, column_map, "WOB")
    rpm = _pick_series(df, column_map, "RPMB")
    mfi = _pick_series(df, column_map, "MFI")
    mud_motor_signal = _pick_series(df, column_map, "Mud Motor On")

    spp_baseline = rolling_baseline(spp, cfg.pspike_baseline_window)
    spp_delta = spp - spp_baseline

    out["spp"] = spp
    out["spp_baseline"] = spp_baseline
    out["spp_delta"] = spp_delta
    out["wob"] = wob
    out["rpm"] = rpm
    out["mfi"] = mfi

    context_mask = activity_labels.isin(["Drilling", "Reaming"])

    stable_mask = pd.Series(True, index=df.index)

    if cfg.require_stable_flow_for_pspike:
        stable_mask &= mfi.diff().abs().fillna(0.0) <= cfg.pspike_flow_delta_max
        if "stable_flow" in activity_features.columns:
            stable_mask &= activity_features["stable_flow"]

    if cfg.require_stable_rpm_for_pspike:
        stable_mask &= rpm.diff().abs().fillna(0.0) <= cfg.pspike_rpm_delta_max
        if "stable_rpm" in activity_features.columns:
            stable_mask &= activity_features["stable_rpm"]

    if cfg.require_stable_wob_for_pspike:
        stable_mask &= wob.diff().abs().fillna(0.0) <= cfg.pspike_wob_delta_max
        if "stable_wob" in activity_features.columns:
            stable_mask &= activity_features["stable_wob"]

    spp_stable_before_spike = stable_within_band(
        spp.shift(1),
        cfg.pspike_baseline_window,
        cfg.pspike_spp_stability_band,
    )

    if mud_motor_signal.notna().any():
        mud_motor_on = mud_motor_signal.fillna(0.0) > 0.0
    else:
        # AI made assumption on this part: fallback uses WOB as a proxy when a Mud Motor On signal is unavailable.
        mud_motor_on = wob > cfg.pspike_motor_wob_threshold

    normal_mask = (
        context_mask
        & stable_mask
        & spp_stable_before_spike
        & ~mud_motor_on
        & (spp_delta > cfg.pspike_threshold_normal)
    )

    motor_mask = (
        context_mask
        & stable_mask
        & spp_stable_before_spike
        & mud_motor_on
        & (spp_delta > cfg.pspike_threshold_motor_on)
    )

    combined_mask = fill_short_false_gaps(
        normal_mask | motor_mask,
        cfg.pspike_gap_fill_samples,
    )

    lvl1_intervals = mask_to_intervals(
        mask=combined_mask & normal_mask,
        label="PSpike",
        min_samples=cfg.pspike_min_interval_samples,
        severity="Medium",
    )

    lvl2_intervals = mask_to_intervals(
        mask=combined_mask & motor_mask,
        label="PSpike",
        min_samples=cfg.pspike_min_interval_samples,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


def build_overpull_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    hkl = _pick_series(df, column_map, "HKL")
    baseline = rolling_baseline(hkl, cfg.overpull_baseline_window)
    delta = hkl - baseline

    out["hkl"] = hkl
    out["hkl_baseline"] = baseline
    out["hkl_delta"] = delta

    context_mask = activity_labels.eq("TrippingOut")
    move_mask = (
        activity_features["pipe_moving_up"]
        if "pipe_moving_up" in activity_features.columns
        else pd.Series(False, index=df.index)
    )

    hoisting_velocity = _hoisting_velocity_from_bpos(activity_features, df.index)
    velocity_ok = hoisting_velocity.between(
        cfg.hoisting_velocity_min,
        cfg.hoisting_velocity_max,
        inclusive="both",
    )

    combined_mask = fill_short_false_gaps(
        context_mask & move_mask & velocity_ok & (delta > cfg.overpull_threshold),
        cfg.overpull_gap_fill_samples,
    )

    intervals = mask_to_intervals(
        mask=combined_mask,
        label="OverPull",
        min_samples=cfg.overpull_min_interval_samples,
        severity="High",
    )

    return out, intervals


def build_tookweight_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    hkl = _pick_series(df, column_map, "HKL")
    baseline = rolling_baseline(hkl, cfg.tookweight_baseline_window)
    delta = baseline - hkl

    out["hkl"] = hkl
    out["hkl_baseline"] = baseline
    out["hkl_drop"] = delta

    context_mask = activity_labels.eq("TrippingIn")
    move_mask = (
        activity_features["pipe_moving_down"]
        if "pipe_moving_down" in activity_features.columns
        else pd.Series(False, index=df.index)
    )

    hoisting_velocity = _hoisting_velocity_from_bpos(activity_features, df.index)
    velocity_ok = hoisting_velocity.between(
        cfg.hoisting_velocity_min,
        cfg.hoisting_velocity_max,
        inclusive="both",
    )

    combined_mask = fill_short_false_gaps(
        context_mask & move_mask & velocity_ok & (delta > cfg.tookweight_threshold),
        cfg.tookweight_gap_fill_samples,
    )

    intervals = mask_to_intervals(
        mask=combined_mask,
        label="TookWeight",
        min_samples=cfg.tookweight_min_interval_samples,
        severity="High",
    )

    return out, intervals


def build_selected_symptom_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    symptom_name: str,
    symptom_cfg: SymptomConfig,
    activity_features: pd.DataFrame,
    activity_labels: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    if symptom_name == "OpenHoleLength":
        return build_open_hole_length_agent(df, column_map, symptom_cfg)

    if symptom_name == "TRQSpike":
        return build_trq_spike_agent(
            df=df,
            column_map=column_map,
            cfg=symptom_cfg,
            activity_labels=activity_labels,
            activity_features=activity_features,
        )

    if symptom_name == "TRQErratic":
        return build_trq_erratic_agent(
            df=df,
            column_map=column_map,
            cfg=symptom_cfg,
            activity_features=activity_features,
            activity_labels=activity_labels,
        )

    if symptom_name == "PSpike":
        return build_pspike_agent(
            df=df,
            column_map=column_map,
            cfg=symptom_cfg,
            activity_features=activity_features,
            activity_labels=activity_labels,
        )

    if symptom_name == "OverPull":
        return build_overpull_agent(
            df=df,
            column_map=column_map,
            cfg=symptom_cfg,
            activity_features=activity_features,
            activity_labels=activity_labels,
        )

    if symptom_name == "TookWeight":
        return build_tookweight_agent(
            df=df,
            column_map=column_map,
            cfg=symptom_cfg,
            activity_features=activity_features,
            activity_labels=activity_labels,
        )

    return pd.DataFrame(index=df.index), []