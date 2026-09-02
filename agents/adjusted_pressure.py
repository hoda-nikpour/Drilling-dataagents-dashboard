"""Flow-normalised standpipe-pressure anomaly detector.

Implements the review recommendation:

    adjusted_pressure = SPP / MFI ** 1.75

The detector works on deviations from a robust rolling baseline of the adjusted
signal.  Raw-SPP diagnostics are calculated alongside it so the dashboard can
compare the old and new approaches during validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdjustedPressureConfig:
    exponent: float = 1.75
    baseline_window: int = 120
    min_periods: int = 30
    robust_z_threshold: float = 4.0
    min_relative_deviation: float = 0.05
    min_mfi: float = 1.0
    min_consecutive: int = 2
    epsilon: float = 1e-12

    def __post_init__(self) -> None:
        if self.exponent <= 0:
            raise ValueError("exponent must be > 0")
        if self.baseline_window < 3:
            raise ValueError("baseline_window must be >= 3")
        if not 1 <= self.min_periods <= self.baseline_window:
            raise ValueError("min_periods must be between 1 and baseline_window")
        if self.robust_z_threshold <= 0:
            raise ValueError("robust_z_threshold must be > 0")
        if self.min_relative_deviation < 0:
            raise ValueError("min_relative_deviation must be >= 0")
        if self.min_mfi < 0:
            raise ValueError("min_mfi must be >= 0")
        if self.min_consecutive < 1:
            raise ValueError("min_consecutive must be >= 1")


def _rolling_mad(signal: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Rolling median absolute deviation, using only prior samples."""
    previous = signal.shift(1)

    def mad(values: np.ndarray) -> float:
        values = values[np.isfinite(values)]
        if values.size == 0:
            return np.nan
        med = np.median(values)
        return float(np.median(np.abs(values - med)))

    return previous.rolling(window=window, min_periods=min_periods).apply(mad, raw=True)


def _robust_baseline_and_z(
    signal: pd.Series,
    *,
    window: int,
    min_periods: int,
    epsilon: float,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return baseline, robust sigma, deviation and robust z-score.

    The current sample is excluded from the rolling statistics to avoid a spike
    contaminating its own baseline.
    """
    previous = signal.shift(1)
    baseline = previous.rolling(window=window, min_periods=min_periods).median()
    mad = _rolling_mad(signal, window, min_periods)
    robust_sigma = 1.4826 * mad

    # If MAD is unavailable, fall back to historical standard deviation.  If MAD
    # is *validly zero* (a truly stable baseline), keep an epsilon scale rather
    # than letting the anomaly inflate its own scale through the fallback std.
    # The separate relative-deviation threshold prevents tiny numerical changes
    # from becoming events in this zero-noise case.
    fallback_std = previous.rolling(window=window, min_periods=min_periods).std(ddof=0)
    scale = robust_sigma.copy()
    scale = scale.where(scale.notna(), fallback_std)
    scale = scale.where(scale > epsilon, epsilon)

    deviation = signal - baseline
    z = deviation / scale
    return baseline, scale, deviation, z


def _keep_confirmed_runs(mask: pd.Series, min_consecutive: int) -> pd.Series:
    """Keep complete True runs only when their length reaches min_consecutive.

    This intentionally back-fills the beginning of a confirmed run.  That matches
    the retrospective philosophy requested for the agents: once future samples
    confirm an event, its start is recorded at the first anomalous sample.
    """
    clean = mask.fillna(False).astype(bool)
    if min_consecutive <= 1 or clean.empty:
        return clean
    group = clean.ne(clean.shift(fill_value=False)).cumsum()
    run_lengths = clean.groupby(group).transform("sum")
    return clean & (run_lengths >= min_consecutive)


def detect_adjusted_pressure_spikes(
    df: pd.DataFrame,
    *,
    spp_col: str,
    mfi_col: str,
    config: AdjustedPressureConfig | None = None,
) -> pd.DataFrame:
    """Calculate adjusted pressure and detect positive deviations.

    Returns a copy of ``df`` with diagnostics:
      - adjusted_pressure
      - adjusted_pressure_baseline
      - adjusted_pressure_deviation
      - adjusted_pressure_relative_deviation
      - adjusted_pressure_robust_z
      - pressure_spike_candidate
      - pressure_spike
      - raw_spp_baseline / raw_spp_robust_z (A/B comparison only)
    """
    cfg = config or AdjustedPressureConfig()
    missing = [c for c in (spp_col, mfi_col) if c not in df.columns]
    if missing:
        raise KeyError(f"Missing pressure columns: {missing}")

    out = df.copy()
    spp = pd.to_numeric(out[spp_col], errors="coerce")
    mfi = pd.to_numeric(out[mfi_col], errors="coerce")

    pump_on = mfi >= cfg.min_mfi
    valid = pump_on & spp.notna() & mfi.notna() & (mfi > 0)

    adjusted = pd.Series(np.nan, index=out.index, dtype=float)
    adjusted.loc[valid] = spp.loc[valid] / np.power(mfi.loc[valid], cfg.exponent)
    out["adjusted_pressure"] = adjusted
    out["pressure_valid_for_detection"] = valid

    baseline, scale, deviation, robust_z = _robust_baseline_and_z(
        adjusted,
        window=cfg.baseline_window,
        min_periods=cfg.min_periods,
        epsilon=cfg.epsilon,
    )
    rel_dev = deviation / baseline.abs().where(baseline.abs() > cfg.epsilon)

    out["adjusted_pressure_baseline"] = baseline
    out["adjusted_pressure_scale"] = scale
    out["adjusted_pressure_deviation"] = deviation
    out["adjusted_pressure_relative_deviation"] = rel_dev
    out["adjusted_pressure_robust_z"] = robust_z

    candidate = (
        valid
        & baseline.notna()
        & (robust_z >= cfg.robust_z_threshold)
        & (rel_dev >= cfg.min_relative_deviation)
    )
    out["pressure_spike_candidate"] = candidate.fillna(False)
    out["pressure_spike"] = _keep_confirmed_runs(candidate, cfg.min_consecutive)

    # Raw SPP comparison.  Do not use this as the new event output; it is kept so
    # the dashboard can show whether normalisation removes flow-driven false alarms.
    raw_base, raw_scale, raw_dev, raw_z = _robust_baseline_and_z(
        spp.where(valid),
        window=cfg.baseline_window,
        min_periods=cfg.min_periods,
        epsilon=cfg.epsilon,
    )
    out["raw_spp_baseline"] = raw_base
    out["raw_spp_scale"] = raw_scale
    out["raw_spp_deviation"] = raw_dev
    out["raw_spp_robust_z"] = raw_z
    out["raw_spp_spike_candidate"] = (
        valid & raw_base.notna() & (raw_z >= cfg.robust_z_threshold)
    ).fillna(False)

    return out


def pressure_event_table(
    df: pd.DataFrame,
    *,
    event_col: str = "pressure_spike",
    timestamp_col: str | None = None,
    spp_col: str | None = None,
    mfi_col: str | None = None,
) -> pd.DataFrame:
    """Collapse sample-level spike flags into an event table."""
    if event_col not in df.columns:
        raise KeyError(f"{event_col!r} is not present in dataframe")

    mask = df[event_col].fillna(False).astype(bool)
    if not mask.any():
        cols = ["event_id", "start_index", "end_index", "n_samples", "peak_adjusted_z"]
        if timestamp_col:
            cols += ["start_time", "end_time"]
        if spp_col:
            cols += ["peak_spp"]
        if mfi_col:
            cols += ["mfi_at_peak_z"]
        return pd.DataFrame(columns=cols)

    groups = mask.ne(mask.shift(fill_value=False)).cumsum()
    rows: list[dict[str, object]] = []
    event_id = 0

    for _, segment in df.loc[mask].groupby(groups[mask]):
        event_id += 1
        z = pd.to_numeric(segment.get("adjusted_pressure_robust_z"), errors="coerce")
        peak_label = z.idxmax() if z.notna().any() else segment.index[0]
        row: dict[str, object] = {
            "event_id": event_id,
            "start_index": segment.index[0],
            "end_index": segment.index[-1],
            "n_samples": len(segment),
            "peak_adjusted_z": float(z.max()) if z.notna().any() else np.nan,
        }
        if timestamp_col and timestamp_col in segment.columns:
            row["start_time"] = segment.iloc[0][timestamp_col]
            row["end_time"] = segment.iloc[-1][timestamp_col]
        if spp_col and spp_col in segment.columns:
            row["peak_spp"] = float(pd.to_numeric(segment[spp_col], errors="coerce").max())
        if mfi_col and mfi_col in segment.columns:
            row["mfi_at_peak_z"] = float(pd.to_numeric(df.loc[peak_label, mfi_col], errors="coerce"))
        rows.append(row)

    return pd.DataFrame(rows)
