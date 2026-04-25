from dataclasses import dataclass

import pandas as pd

from agents.activity_support import (
    enforce_min_duration,
    fill_short_false_gaps,
    intervals_from_label_series,
    rolling_mean,
    rolling_median,
    stable_within_band,
)


@dataclass(frozen=True)
class ActivityConfig:
    short_window: int = 5
    medium_window: int = 15
    min_interval_samples: int = 6
    gap_fill_samples: int = 2

    pump_on_threshold: float = 100.0
    rpm_on_threshold: float = 10.0
    rpm_low_threshold: float = 30.0
    wob_zero_band: float = 0.5
    wob_drilling_min: float = 1.0
    rop_min: float = 0.5

    near_bottom_threshold: float = 5.0
    bit_on_bottom_threshold: float = 1.0

    movement_threshold: float = 0.3
    connection_block_travel_threshold: float = 2.0

    flow_stability_band: float = 80.0
    rpm_stability_band: float = 8.0
    wob_stability_band: float = 0.8

    trip_flow_max: float = 100.0
    trip_rpm_max: float = 5.0


REQUIRED_ACTIVITY_INPUTS = [
    "Bit Depth",
    "Well Depth",
    "BPOS",
    "HKL",
    "MFI",
    "RPMB",
    "ROP",
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
    rop = _pick_series(df, column_map, "ROP")
    wob = None

    wob_source = None
    if "WOB" in column_map:
        wob_source = _pick_series(df, column_map, "WOB")
    elif "HKL" in column_map:
        # Fallback placeholder when WOB is unavailable.
        wob_source = pd.Series(0.0, index=df.index)

    wob = pd.to_numeric(wob_source, errors="coerce").fillna(0.0)

    out["bit_depth"] = bit_depth
    out["well_depth"] = well_depth
    out["bpos"] = bpos
    out["hkl"] = hkl
    out["mfi"] = mfi
    out["rpm"] = rpm
    out["rop"] = rop
    out["wob"] = wob

    out["mfi_med"] = rolling_median(mfi, cfg.short_window)
    out["rpm_med"] = rolling_median(rpm, cfg.short_window)
    out["rop_med"] = rolling_median(rop, cfg.short_window)
    out["wob_med"] = rolling_median(wob, cfg.short_window)
    out["bpos_smooth"] = rolling_mean(bpos, cfg.short_window)

    out["pump_on"] = out["mfi_med"] > cfg.pump_on_threshold
    out["rpm_on"] = out["rpm_med"] > cfg.rpm_on_threshold
    out["rpm_low_or_off"] = out["rpm_med"] <= cfg.rpm_low_threshold
    out["trip_rpm_off"] = out["rpm_med"] <= cfg.trip_rpm_max
    out["trip_flow_low"] = out["mfi_med"] <= cfg.trip_flow_max

    depth_gap = (out["well_depth"] - out["bit_depth"]).abs()
    out["near_bottom"] = depth_gap <= cfg.near_bottom_threshold
    out["bit_on_bottom"] = depth_gap <= cfg.bit_on_bottom_threshold

    bpos_delta = out["bpos_smooth"] - out["bpos_smooth"].shift(cfg.short_window)
    out["pipe_moving_up"] = bpos_delta > cfg.movement_threshold
    out["pipe_moving_down"] = bpos_delta < -cfg.movement_threshold
    out["pipe_moving"] = out["pipe_moving_up"] | out["pipe_moving_down"]

    out["block_motion_window"] = (
        out["bpos"].rolling(cfg.medium_window, min_periods=1).max()
        - out["bpos"].rolling(cfg.medium_window, min_periods=1).min()
    )
    out["block_moving"] = out["block_motion_window"] > cfg.movement_threshold

    out["drilling_ahead"] = out["rop_med"] > cfg.rop_min

    out["stable_flow"] = stable_within_band(out["mfi_med"], cfg.medium_window, cfg.flow_stability_band)
    out["stable_rpm"] = stable_within_band(out["rpm_med"], cfg.medium_window, cfg.rpm_stability_band)
    out["stable_wob"] = stable_within_band(out["wob_med"], cfg.medium_window, cfg.wob_stability_band)

    return out


def classify_activities(
    df: pd.DataFrame,
    column_map: dict[str, str],
    cfg: ActivityConfig,
) -> tuple[pd.Series, pd.DataFrame, list[dict]]:
    features = build_activity_features(df=df, column_map=column_map, cfg=cfg)

    making_connection = (
        ~features["pump_on"]
        & ~features["rpm_on"]
        & features["near_bottom"]
        & (features["block_motion_window"] >= cfg.connection_block_travel_threshold)
        & ~features["drilling_ahead"]
        & (features["wob_med"].abs() <= cfg.wob_zero_band)
    )

    drilling = (
        features["pump_on"]
        & features["rpm_on"]
        & features["bit_on_bottom"]
        & (features["wob_med"] > cfg.wob_drilling_min)
        & features["drilling_ahead"]
    )

    reaming = (
        features["pump_on"]
        & features["rpm_on"]
        & (features["wob_med"].abs() <= cfg.wob_zero_band)
        & features["pipe_moving"]
        & ~features["drilling_ahead"]
    )

    tripping_in = (
        features["trip_flow_low"]
        & features["trip_rpm_off"]
        & (features["wob_med"].abs() <= cfg.wob_zero_band)
        & features["pipe_moving_down"]
        & ~features["bit_on_bottom"]
    )

    tripping_out = (
        features["trip_flow_low"]
        & features["trip_rpm_off"]
        & (features["wob_med"].abs() <= cfg.wob_zero_band)
        & features["pipe_moving_up"]
        & ~features["bit_on_bottom"]
    )

    conditioning = (
        features["pump_on"]
        & features["near_bottom"]
        & ~features["drilling_ahead"]
        & ~features["pipe_moving"]
        & features["rpm_low_or_off"]
    )

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
