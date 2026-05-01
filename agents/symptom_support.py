import pandas as pd


def rolling_baseline(series: pd.Series, window: int) -> pd.Series:
    """
    Causal rolling median baseline using current and past values only.
    """
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1, center=False).median()


def rolling_past_mean(series: pd.Series, window: int) -> pd.Series:
    """
    Causal rolling mean using current and past values only.
    """
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1, center=False).mean()


def rolling_past_median(series: pd.Series, window: int) -> pd.Series:
    """
    Causal rolling median using current and past values only.
    """
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1, center=False).median()


def rolling_std(series: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1, center=False).std()


def relative_change(series: pd.Series, baseline: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    b = pd.to_numeric(baseline, errors="coerce")
    return (s - b) / b.replace(0.0, pd.NA)


def spike_above_baseline(series: pd.Series, baseline: pd.Series, threshold: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    b = pd.to_numeric(baseline, errors="coerce")
    return (s - b) > threshold


def spike_below_baseline(series: pd.Series, baseline: pd.Series, threshold: float) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    b = pd.to_numeric(baseline, errors="coerce")
    return (b - s) > threshold


def mask_to_intervals(mask: pd.Series, label: str, min_samples: int = 1, severity: str | None = None) -> list[dict]:
    mask = mask.fillna(False).astype(bool)
    intervals = []
    start = None
    count = 0

    for ts, flag in mask.items():
        if flag and start is None:
            start = ts
            count = 1
        elif flag and start is not None:
            count += 1
        elif not flag and start is not None:
            if count >= min_samples:
                prev_ts = mask.index[mask.index.get_loc(ts) - 1]
                intervals.append(
                    {
                        "label": label,
                        "start": start,
                        "end": prev_ts,
                        "severity": severity,
                        "source": "symptom_agent",
                    }
                )
            start = None
            count = 0

    if start is not None and count >= min_samples:
        intervals.append(
            {
                "label": label,
                "start": start,
                "end": mask.index[-1],
                "severity": severity,
                "source": "symptom_agent",
            }
        )

    return intervals


def first_crossing_intervals(mask: pd.Series, label: str, severity: str | None = None) -> list[dict]:
    """
    Return one timestamp interval each time a mask crosses from False to True.

    Used for OpenHoleLength because the VT document says it is sufficient to
    report the symptom the first time a severity level appears.
    """
    if mask.empty:
        return []

    mask = mask.fillna(False).astype(bool)
    previous = mask.shift(1, fill_value=False)
    crossings = mask & ~previous

    intervals = []
    for ts, flag in crossings.items():
        if flag:
            intervals.append(
                {
                    "label": label,
                    "start": ts,
                    "end": ts,
                    "severity": severity,
                    "source": "symptom_agent",
                }
            )

    return intervals

def rolling_reference_mean(series: pd.Series, window: int) -> pd.Series:
    """
    Causal reference mean using previous values only.

    The current point is excluded so the spike itself does not raise its own baseline.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window=window, min_periods=1, center=False).mean().shift(1)


def rolling_reference_std(series: pd.Series, window: int) -> pd.Series:
    """
    Causal reference standard deviation using previous values only.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window=window, min_periods=2, center=False).std().shift(1)


def rolling_reference_min(series: pd.Series, window: int) -> pd.Series:
    """
    Causal reference minimum using previous values only.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window=window, min_periods=1, center=False).min().shift(1)