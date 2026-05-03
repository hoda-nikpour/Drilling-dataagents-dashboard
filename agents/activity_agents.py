from dataclasses import dataclass

import pandas as pd

from agents.activity_support import (
    enforce_min_duration,
    fill_short_false_gaps,
    intervals_from_label_series,
    rolling_mean,
    stable_within_band,
)


@dataclass(frozen=True)
class ActivityConfig:
    short_window: int = 10
    medium_window: int = 100
    min_interval_samples: int = 6
    gap_fill_samples: int = 2

    pump_on_threshold: float = 100.0
    rpm_on_threshold: float = 10.0
    rpm_zero_threshold: float = 1.0
    rpm_low_threshold: float = 30.0

    wob_zero_band: float = 0.5

    # VT document:
    # Drilling:
    # - MDEA increases > 1 cm/time step
    # - BITD - MDEA < 5 cm
    # - WOB > 0.1 ton, but simplified drilling allows WOB >= 0
    wob_drilling_min: float = 0.1

    drilling_depth_step_min: float = 0.01
    drilling_depth_gap_max: float = 0.05

    # VT document:
    # Reaming:
    # - MFI > 100 lpm
    # - RPM > 10 rpm
    # - WOB = 0
    # - DBTM/time is changing slowly
    reaming_flow_min: float = 100.0
    reaming_rpm_min: float = 10.0
    reaming_depth_step_max: float = 0.30  # Assumption: "slowly" is not numerically defined in the VT document.

    # VT document:
    # Tripping:
    # - MFI < 1000 lpm
    # - RPM = 0
    # - WOB = 0
    # - DBTM/time step is changing
    # - Two time steps can be zero, but not four.
    tripping_flow_max: float = 1000.0
    tripping_rpm_max: float = 1.0
    tripping_max_consecutive_static_samples: int = 3

    # VT document:
    # Conditioning:
    # - Pump is on
    # - Pipe may be still or turning slowly
    # - No pipe reciprocations
    # - Bit close to bottom: WellDepth - BitDepth < 100 m
    conditioning_depth_gap_max: float = 100.0

    # VT document:
    # MakingCnx:
    # - Bit Depth - Hole Depth <= 10 m = constant
    # - BPOS move more than 2 m
    # - HKL = Dead Weight
    connection_depth_gap_max: float = 10.0
    connection_depth_constant_band: float = 0.05  # Assumption: "constant" needs a numerical tolerance.
    connection_block_travel_threshold: float = 2.0

    # If exact dead weight is unknown, the code falls back to "stable HKL".
    # If you later know the dead-weight value, set hkl_dead_weight_value.
    hkl_dead_weight_value: float | None = None
    hkl_dead_weight_tolerance: float = 3.0
    hkl_dead_weight_stability_band: float = 3.0

    movement_threshold: float = 0.3

    # BPOS direction convention.
    # Default keeps your current assumption:
    #   bpos_delta > 0  => pipe/block moving up
    #   bpos_delta < 0  => pipe/block moving down
    #
    # If your real data is reversed, set bpos_up_sign = -1.
    bpos_up_sign: int = 1

    flow_stability_band: float = 80.0
    rpm_stability_band: float = 8.0
    wob_stability_band: float = 0.8


REQUIRED_ACTIVITY_INPUTS = [
    "Bit Depth",
    "Well Depth",
    "BPOS",
    "HKL",
    "MFI",
    "RPMB",
    "WOB",
]


def _pick_series(df: pd.DataFrame, column_map: dict[str, str], logical_name: str) -> pd.Series:
    col = column_map.get(logical_name)
    if col is None or col not in df.columns:
        return pd.Series(index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def build_activity_features(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: ActivityConfig,
) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)

    bit_depth = _pick_series(df, column_map, "Bit Depth")
    well_depth = _pick_series(df, column_map, "Well Depth")
    bpos = _pick_series(df, column_map, "BPOS")
    hkl = _pick_series(df, column_map, "HKL")
    mfi = _pick_series(df, column_map, "MFI")
    rpm = _pick_series(df, column_map, "RPMB")

    if "WOB" in column_map:
        wob_source = _pick_series(df, column_map, "WOB")
    else:
        # Assumption:
        # If WOB is unavailable, use 0 so non-WOB activities can still run.
        wob_source = pd.Series(0.0, index=df.index)

    wob = pd.to_numeric(wob_source, errors="coerce").fillna(0.0)

    out["bit_depth"] = bit_depth
    out["well_depth"] = well_depth
    out["bpos"] = bpos
    out["hkl"] = hkl
    out["mfi"] = mfi
    out["rpm"] = rpm
    out["wob"] = wob

    # Causal smoothing: current and previous values only.
    out["mfi_med"] = rolling_mean(mfi, cfg.short_window)
    out["rpm_med"] = rolling_mean(rpm, cfg.short_window)
    out["wob_med"] = rolling_mean(wob, cfg.short_window)
    out["bpos_smooth"] = rolling_mean(bpos, cfg.short_window)
    out["hkl_med"] = rolling_mean(hkl, cfg.short_window)

    out["pump_on"] = out["mfi_med"] > cfg.pump_on_threshold
    out["rpm_on"] = out["rpm_med"] > cfg.rpm_on_threshold
    out["rpm_zero"] = out["rpm_med"] <= cfg.rpm_zero_threshold
    out["rpm_low_or_off"] = out["rpm_med"] <= cfg.rpm_low_threshold

    # Keep both signed and absolute depth gap.
    # Absolute gap is robust to raw-data sign conventions.
    # Signed gap is available for debugging and future stricter VT interpretation.
    out["depth_gap_signed"] = out["well_depth"] - out["bit_depth"]
    out["depth_gap"] = out["depth_gap_signed"].abs()

    out["bit_on_bottom_document"] = out["depth_gap"] <= cfg.drilling_depth_gap_max
    out["near_bottom_conditioning"] = out["depth_gap"] <= cfg.conditioning_depth_gap_max
    out["near_bottom_connection"] = out["depth_gap"] <= cfg.connection_depth_gap_max

    out["well_depth_delta"] = out["well_depth"].diff()
    out["bit_depth_delta"] = out["bit_depth"].diff()

    # Drilling uses Well Depth / hole depth increase.
    out["well_depth_increasing"] = out["well_depth_delta"] > cfg.drilling_depth_step_min

    # Reaming/tripping use Bit Depth / DBTM movement, not Well Depth movement.
    # This is the key correction from your previous version.
    out["bit_depth_changing_slowly"] = out["bit_depth_delta"].abs().between(
        cfg.drilling_depth_step_min,
        cfg.reaming_depth_step_max,
        inclusive="both",
    )

    # Kept for debugging/backward compatibility, but no longer used for Reaming.
    out["well_depth_changing_slowly"] = out["well_depth_delta"].abs().between(
        cfg.drilling_depth_step_min,
        cfg.reaming_depth_step_max,
        inclusive="both",
    )

    out["bit_depth_constant"] = (
        out["bit_depth_delta"].abs().fillna(0.0) <= cfg.connection_depth_constant_band
    )
    out["well_depth_constant"] = (
        out["well_depth_delta"].abs().fillna(0.0) <= cfg.connection_depth_constant_band
    )

    # BPOS movement and direction.
    raw_bpos_delta = out["bpos_smooth"] - out["bpos_smooth"].shift(cfg.short_window)
    out["bpos_delta"] = raw_bpos_delta

    bpos_up_sign = 1 if cfg.bpos_up_sign >= 0 else -1
    direction_adjusted_bpos_delta = raw_bpos_delta * bpos_up_sign
    out["bpos_direction_adjusted_delta"] = direction_adjusted_bpos_delta

    out["pipe_moving_up"] = direction_adjusted_bpos_delta > cfg.movement_threshold
    out["pipe_moving_down"] = direction_adjusted_bpos_delta < -cfg.movement_threshold
    out["pipe_moving"] = out["pipe_moving_up"] | out["pipe_moving_down"]

    out["block_motion_window"] = (
        out["bpos"].rolling(cfg.medium_window, min_periods=1, center=False).max()
        - out["bpos"].rolling(cfg.medium_window, min_periods=1, center=False).min()
    )
    out["block_moving"] = out["block_motion_window"] > cfg.movement_threshold

    out["hkl_motion_window"] = (
        out["hkl"].rolling(cfg.medium_window, min_periods=1, center=False).max()
        - out["hkl"].rolling(cfg.medium_window, min_periods=1, center=False).min()
    )

    # This means HKL is stable, not necessarily equal to true dead weight.
    out["hkl_dead_weight_stable"] = (
        out["hkl_motion_window"] <= cfg.hkl_dead_weight_stability_band
    )

    # If real dead weight is known, require HKL to be close to it.
    # If not known, this stays True and the connection rule uses stability only.
    if cfg.hkl_dead_weight_value is not None:
        out["hkl_close_to_dead_weight"] = (
            out["hkl_med"] - float(cfg.hkl_dead_weight_value)
        ).abs() <= cfg.hkl_dead_weight_tolerance
    else:
        out["hkl_close_to_dead_weight"] = pd.Series(True, index=df.index)

    out["hkl_dead_weight_ok"] = (
        out["hkl_dead_weight_stable"] & out["hkl_close_to_dead_weight"]
    )

    out["tripping_flow_low"] = out["mfi_med"] < cfg.tripping_flow_max
    out["tripping_rpm_zero"] = out["rpm_med"] <= cfg.tripping_rpm_max
    out["wob_zero"] = out["wob_med"].abs() <= cfg.wob_zero_band

    # VT tripping definition uses DBTM/time-step movement.
    # Therefore use Bit Depth movement plus BPOS movement, not Well Depth movement.
    any_bit_or_block_motion = (
        out["bit_depth_delta"].abs().fillna(0.0) > cfg.drilling_depth_step_min
    ) | out["pipe_moving"]

    static_run_count = (~any_bit_or_block_motion).astype(int).rolling(
        cfg.tripping_max_consecutive_static_samples + 1,
        min_periods=1,
        center=False,
    ).sum()

    out["tripping_static_run_count"] = static_run_count
    out["tripping_motion_valid"] = (
        static_run_count <= cfg.tripping_max_consecutive_static_samples
    )

    out["stable_flow"] = stable_within_band(
        out["mfi_med"],
        cfg.medium_window,
        cfg.flow_stability_band,
    )
    out["stable_rpm"] = stable_within_band(
        out["rpm_med"],
        cfg.medium_window,
        cfg.rpm_stability_band,
    )
    out["stable_wob"] = stable_within_band(
        out["wob_med"],
        cfg.medium_window,
        cfg.wob_stability_band,
    )

    return out


def classify_activities(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: ActivityConfig,
) -> tuple[pd.Series, pd.DataFrame, list[dict]]:
    features = build_activity_features(df=df, column_map=column_map, cfg=cfg)

    drilling = (
        features["pump_on"]
        & features["rpm_on"]
        & features["well_depth_increasing"]
        & features["bit_on_bottom_document"]
        & (features["wob_med"] > cfg.wob_drilling_min)
    )

    # Corrected:
    # Reaming should use Bit Depth / DBTM movement, not Well Depth movement.
    reaming = (
        (features["mfi_med"] > cfg.reaming_flow_min)
        & (features["rpm_med"] > cfg.reaming_rpm_min)
        & features["wob_zero"]
        & features["bit_depth_changing_slowly"]
    )

    tripping_base = (
        features["tripping_flow_low"]
        & features["tripping_rpm_zero"]
        & features["wob_zero"]
        & features["tripping_motion_valid"]
        & features["pipe_moving"]
    )

    tripping_in = tripping_base & features["pipe_moving_down"]
    tripping_out = tripping_base & features["pipe_moving_up"]

    conditioning = (
        features["pump_on"]
        & features["near_bottom_conditioning"]
        & features["rpm_low_or_off"]
        & ~features["pipe_moving"]
    )

    making_connection = (
        ~features["pump_on"]
        & features["near_bottom_connection"]
        & features["bit_depth_constant"]
        & features["well_depth_constant"]
        & (features["block_motion_window"] >= cfg.connection_block_travel_threshold)
        & features["hkl_dead_weight_ok"]
    )

    # Circulating is not specified as fully as Drilling/Reaming/Tripping in the VT text.
    # This is a practical dashboard rule:
    # pump on, not drilling/reaming/conditioning, and no pipe movement.
    circulating = (
        features["pump_on"]
        & ~drilling
        & ~reaming
        & ~conditioning
        & ~features["pipe_moving"]
    )

    rule_masks = {
        "MakingConnection": fill_short_false_gaps(making_connection, cfg.gap_fill_samples),
        "Drilling": fill_short_false_gaps(drilling, cfg.gap_fill_samples),
        "Reaming": fill_short_false_gaps(reaming, cfg.gap_fill_samples),
        "TrippingIn": fill_short_false_gaps(tripping_in, cfg.gap_fill_samples),
        "TrippingOut": fill_short_false_gaps(tripping_out, cfg.gap_fill_samples),
        "Conditioning": fill_short_false_gaps(conditioning, cfg.gap_fill_samples),
        "Circulating": fill_short_false_gaps(circulating, cfg.gap_fill_samples),
    }

    labels = pd.Series("Other", index=df.index, dtype="object")

    # Priority matters when several rule masks are True at the same timestamp.
    priority = [
        "MakingConnection",
        "Drilling",
        "Reaming",
        "TrippingIn",
        "TrippingOut",
        "Conditioning",
        "Circulating",
    ]

    for name in priority:
        labels.loc[rule_masks[name]] = name

    labels = enforce_min_duration(labels, cfg.min_interval_samples)
    intervals = intervals_from_label_series(labels, min_samples=cfg.min_interval_samples)

    features["activity"] = labels

    for name, mask in rule_masks.items():
        features[f"is_{name.lower()}"] = mask

    return labels, features, intervals


def build_activity_summary(labels: pd.Series) -> pd.DataFrame:
    if labels.empty:
        return pd.DataFrame(columns=["Activity", "Samples", "Percent"])

    counts = labels.value_counts(dropna=False)
    total = float(counts.sum()) or 1.0

    summary = pd.DataFrame(
        {
            "Activity": counts.index.astype(str),
            "Samples": counts.values,
            "Percent": (counts.values / total) * 100.0,
        }
    )

    return summary.reset_index(drop=True)