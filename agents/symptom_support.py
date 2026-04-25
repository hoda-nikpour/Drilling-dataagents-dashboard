import pandas as pd


def rolling_baseline(series: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1).median()


def rolling_std(series: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(window=window, min_periods=1).std()


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