from dataclasses import dataclass

import pandas as pd

from agents.activity_support import fill_short_false_gaps
from agents.symptom_support import mask_to_intervals, rolling_baseline


@dataclass(frozen=True)
class SymptomConfig:
    open_hole_length_threshold_1: float = 500.0
    open_hole_length_threshold_2: float = 750.0

    trq_baseline_window: int = 60
    trq_spike_ratio_level_1: float = 1.25
    trq_spike_ratio_level_2: float = 1.40
    trq_min_baseline: float = 0.1

    pspike_baseline_window: int = 20
    pspike_threshold_normal: float = 5.0
    pspike_threshold_motor_on: float = 7.0
    pspike_gap_fill_samples: int = 2
    pspike_min_interval_samples: int = 1

    overpull_baseline_window: int = 30
    overpull_threshold_1: float = 3.0
    overpull_threshold_2: float = 6.0
    overpull_gap_fill_samples: int = 2
    overpull_min_interval_samples: int = 1

    tookweight_baseline_window: int = 30
    tookweight_threshold_1: float = 3.0
    tookweight_threshold_2: float = 6.0
    tookweight_gap_fill_samples: int = 2
    tookweight_min_interval_samples: int = 1

    require_stable_flow_for_pspike: bool = True
    require_stable_rpm_for_pspike: bool = True
    require_stable_wob_for_pspike: bool = True


REQUIRED_SYMPTOM_INPUTS = [
    "Bit Depth",
    "Well Depth",
    "MFI",
    "RPMB",
    "SPP",
    "TRQ",
    "WOB",
    "HKL",
]


def _pick_series(df: pd.DataFrame, column_map: dict[str, str], logical_name: str) -> pd.Series:
    col = column_map.get(logical_name)
    if col is None or col not in df.columns:
        return pd.Series(index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def build_open_hole_length_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    well_depth = _pick_series(df, column_map, "Well Depth")
    bit_depth = _pick_series(df, column_map, "Bit Depth")

    open_hole_length = (well_depth - bit_depth).clip(lower=0.0)
    out["open_hole_length"] = open_hole_length

    lvl1_mask = open_hole_length > cfg.open_hole_length_threshold_1
    lvl2_mask = open_hole_length > cfg.open_hole_length_threshold_2

    lvl1_intervals = mask_to_intervals(
        mask=lvl1_mask & ~lvl2_mask,
        label="OpenHoleLength",
        min_samples=1,
        severity="Low",
    )
    lvl2_intervals = mask_to_intervals(
        mask=lvl2_mask,
        label="OpenHoleLength",
        min_samples=1,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


def build_trq_spike_agent(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: SymptomConfig,
    activity_labels: pd.Series | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    out = pd.DataFrame(index=df.index)

    trq = _pick_series(df, column_map, "TRQ")
    rpm = _pick_series(df, column_map, "RPMB")

    baseline = rolling_baseline(trq, cfg.trq_baseline_window).clip(lower=cfg.trq_min_baseline)

    out["trq"] = trq
    out["trq_baseline"] = baseline
    out["trq_ratio"] = trq / baseline

    base_mask = rpm > 0
    if activity_labels is not None and not activity_labels.empty:
        base_mask &= activity_labels.isin(["Drilling", "Reaming"])

    lvl1_mask = (
        base_mask
        & (out["trq_ratio"] > cfg.trq_spike_ratio_level_1)
        & (out["trq_ratio"] <= cfg.trq_spike_ratio_level_2)
    )
    lvl2_mask = base_mask & (out["trq_ratio"] > cfg.trq_spike_ratio_level_2)

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
    if cfg.require_stable_flow_for_pspike and "stable_flow" in activity_features.columns:
        stable_mask &= activity_features["stable_flow"]
    if cfg.require_stable_rpm_for_pspike and "stable_rpm" in activity_features.columns:
        stable_mask &= activity_features["stable_rpm"]
    if cfg.require_stable_wob_for_pspike and "stable_wob" in activity_features.columns:
        stable_mask &= activity_features["stable_wob"]

    mud_motor_on = wob > 0.5

    normal_mask = context_mask & stable_mask & ~mud_motor_on & (spp_delta > cfg.pspike_threshold_normal)
    motor_mask = context_mask & stable_mask & mud_motor_on & (spp_delta > cfg.pspike_threshold_motor_on)

    combined_mask = fill_short_false_gaps(normal_mask | motor_mask, cfg.pspike_gap_fill_samples)

    high_cutoff = max(cfg.pspike_threshold_motor_on, cfg.pspike_threshold_normal) * 2.0
    low_mask = combined_mask & ~(spp_delta > high_cutoff)
    high_mask = combined_mask & (spp_delta > high_cutoff)

    lvl1_intervals = mask_to_intervals(
        mask=low_mask & ~high_mask,
        label="PSpike",
        min_samples=cfg.pspike_min_interval_samples,
        severity="Medium",
    )
    lvl2_intervals = mask_to_intervals(
        mask=high_mask,
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

    combined_mask = fill_short_false_gaps(
        context_mask & move_mask & (delta > cfg.overpull_threshold_1),
        cfg.overpull_gap_fill_samples,
    )

    lvl1_mask = combined_mask & (delta > cfg.overpull_threshold_1) & (delta <= cfg.overpull_threshold_2)
    lvl2_mask = combined_mask & (delta > cfg.overpull_threshold_2)

    lvl1_intervals = mask_to_intervals(
        mask=lvl1_mask & ~lvl2_mask,
        label="OverPull",
        min_samples=cfg.overpull_min_interval_samples,
        severity="Medium",
    )
    lvl2_intervals = mask_to_intervals(
        mask=lvl2_mask,
        label="OverPull",
        min_samples=cfg.overpull_min_interval_samples,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


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
    delta = hkl - baseline

    out["hkl"] = hkl
    out["hkl_baseline"] = baseline
    out["hkl_delta"] = delta

    context_mask = activity_labels.eq("TrippingIn")
    move_mask = (
        activity_features["pipe_moving_down"]
        if "pipe_moving_down" in activity_features.columns
        else pd.Series(False, index=df.index)
    )

    combined_mask = fill_short_false_gaps(
        context_mask & move_mask & (delta > cfg.tookweight_threshold_1),
        cfg.tookweight_gap_fill_samples,
    )

    lvl1_mask = combined_mask & (delta > cfg.tookweight_threshold_1) & (delta <= cfg.tookweight_threshold_2)
    lvl2_mask = combined_mask & (delta > cfg.tookweight_threshold_2)

    lvl1_intervals = mask_to_intervals(
        mask=lvl1_mask & ~lvl2_mask,
        label="TookWeight",
        min_samples=cfg.tookweight_min_interval_samples,
        severity="Medium",
    )
    lvl2_intervals = mask_to_intervals(
        mask=lvl2_mask,
        label="TookWeight",
        min_samples=cfg.tookweight_min_interval_samples,
        severity="High",
    )

    return out, (lvl1_intervals + lvl2_intervals)


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