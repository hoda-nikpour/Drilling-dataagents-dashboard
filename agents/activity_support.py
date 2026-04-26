import pandas as pd


def coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def rolling_median(series: pd.Series, window: int) -> pd.Series:
    """
    Causal rolling median.

    Important:
    This intentionally uses center=False so the agent only uses current and past values.
    The VT procedure says agents should not see future values.
    """
    return coerce_numeric(series).rolling(window=window, min_periods=1, center=False).median()


def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    """
    Causal rolling mean.

    Important:
    This intentionally uses center=False so the agent only uses current and past values.
    The VT procedure says agents should not see future values.
    """
    return coerce_numeric(series).rolling(window=window, min_periods=1, center=False).mean()


def rolling_abs_change(series: pd.Series, window: int) -> pd.Series:
    s = coerce_numeric(series)
    return s.diff().abs().rolling(window=window, min_periods=1, center=False).mean()


def stable_within_band(series: pd.Series, window: int, band: float) -> pd.Series:
    s = coerce_numeric(series)
    rolling_max = s.rolling(window=window, min_periods=1, center=False).max()
    rolling_min = s.rolling(window=window, min_periods=1, center=False).min()
    return (rolling_max - rolling_min) <= band


def directional_movement(series: pd.Series, window: int, threshold: float) -> pd.Series:
    s = coerce_numeric(series)
    delta = s - s.shift(window)
    direction = pd.Series("still", index=s.index, dtype="object")
    direction.loc[delta > threshold] = "up"
    direction.loc[delta < -threshold] = "down"
    return direction


def interval_overlap(a_start, a_end, b_start, b_end):
    start = max(pd.Timestamp(a_start), pd.Timestamp(b_start))
    end = min(pd.Timestamp(a_end), pd.Timestamp(b_end))
    if start < end:
        return start, end
    return None


def interval_duration_seconds(start, end) -> float:
    return max((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds(), 0.0)


def overlap_ratio(reference_start, reference_end, candidate_start, candidate_end) -> float:
    """
    Overlap ratio measured against the reference interval duration.
    Returns a value between 0.0 and 1.0.
    """
    reference_duration = interval_duration_seconds(reference_start, reference_end)
    if reference_duration <= 0:
        return 0.0

    ov = interval_overlap(reference_start, reference_end, candidate_start, candidate_end)
    if ov is None:
        return 0.0

    overlap_duration = interval_duration_seconds(ov[0], ov[1])
    return overlap_duration / reference_duration


def bool_to_intervals(mask: pd.Series, label: str, min_samples: int = 1, severity: str | None = None) -> list[dict]:
    if mask.empty:
        return []

    mask = mask.fillna(False).astype(bool)
    intervals: list[dict] = []
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
                        "source": "activity_agent",
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
                "source": "activity_agent",
            }
        )

    return intervals


def fill_short_false_gaps(mask: pd.Series, max_gap: int) -> pd.Series:
    mask = mask.fillna(False).astype(bool).copy()
    if max_gap <= 0 or mask.empty:
        return mask

    values = mask.to_numpy()
    n = len(values)
    i = 0

    while i < n:
        if values[i]:
            i += 1
            continue

        start = i
        while i < n and not values[i]:
            i += 1
        end = i - 1
        gap_len = end - start + 1

        left_true = start > 0 and values[start - 1]
        right_true = i < n and values[i]

        if left_true and right_true and gap_len <= max_gap:
            values[start : end + 1] = True

    return pd.Series(values, index=mask.index)


def enforce_min_duration(labels: pd.Series, min_samples: int) -> pd.Series:
    if labels.empty or min_samples <= 1:
        return labels

    labels = labels.astype("object").copy()
    values = labels.tolist()
    n = len(values)
    i = 0

    while i < n:
        current = values[i]
        j = i + 1
        while j < n and values[j] == current:
            j += 1

        run_len = j - i
        if run_len < min_samples:
            prev_label = values[i - 1] if i > 0 else None
            next_label = values[j] if j < n else None
            replacement = prev_label if prev_label not in (None, "Other") else next_label
            if replacement is None:
                replacement = "Other"
            for k in range(i, j):
                values[k] = replacement

        i = j

    return pd.Series(values, index=labels.index, dtype="object")


def intervals_from_label_series(labels: pd.Series, min_samples: int = 1) -> list[dict]:
    if labels.empty:
        return []

    labels = labels.fillna("Other").astype("object")
    intervals: list[dict] = []
    start_idx = 0

    for i in range(1, len(labels)):
        if labels.iloc[i] != labels.iloc[start_idx]:
            if (i - start_idx) >= min_samples:
                intervals.append(
                    {
                        "label": labels.iloc[start_idx],
                        "start": labels.index[start_idx],
                        "end": labels.index[i - 1],
                        "severity": None,
                        "source": "activity_agent",
                    }
                )
            start_idx = i

    if (len(labels) - start_idx) >= min_samples:
        intervals.append(
            {
                "label": labels.iloc[start_idx],
                "start": labels.index[start_idx],
                "end": labels.index[-1],
                "severity": None,
                "source": "activity_agent",
            }
        )

    return intervals