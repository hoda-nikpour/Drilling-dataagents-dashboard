import numpy as np
import pandas as pd

from config import LOGICAL_PARAMETER_RANGES


def _normalize_with_range(
    series: pd.Series,
    label: str,
    parameter_ranges: dict[str, tuple[float, float]] | None = None,
):
    s = pd.to_numeric(series, errors="coerce")
    s_valid = s.dropna()

    if s_valid.empty:
        return s * np.nan, np.nan, np.nan

    range_lookup = parameter_ranges or LOGICAL_PARAMETER_RANGES
    range_min, range_max = range_lookup.get(
        label,
        (float(s_valid.min()), float(s_valid.max())),
    )

    if np.isclose(range_min, range_max):
        return pd.Series(np.full(len(s), 0.5), index=s.index), range_min, range_max

    s_clipped = s.clip(lower=range_min, upper=range_max)
    s_norm = (s_clipped - range_min) / (range_max - range_min)

    return s_norm, range_min, range_max