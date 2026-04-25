import numpy as np
import pandas as pd

from config import (
    BASE_MARKER_SIZE,
    MAX_POINTS_PER_TRACE,
    MAX_POINTS_PER_TRACE_ZOOM,
    ZOOM_MARKER_SIZE,
)


def get_display_mode(zoom_percent: float) -> tuple[str, float]:
    """
    Keep markers visible at all times.

    Important note:
    Plotly zooming inside the chart does not automatically update Streamlit state,
    so the marker size must remain usable even without a sidebar time-range change.
    """
    if zoom_percent < 20:
        return "lines+markers", BASE_MARKER_SIZE
    if zoom_percent < 60:
        return "lines+markers", max(BASE_MARKER_SIZE, 4.0)
    return "lines+markers", ZOOM_MARKER_SIZE


def get_target_points(zoom_percent: float) -> int:
    """
    Keep enough points so direct chart zoom remains informative.
    """
    if zoom_percent < 20:
        return MAX_POINTS_PER_TRACE
    return MAX_POINTS_PER_TRACE_ZOOM


def downsample_xy(x_series: pd.Series, y_series: pd.Series, n_max: int):
    n = len(x_series)
    if n <= n_max:
        return x_series, y_series

    step = max(1, n // n_max)
    idx = x_series.index[::step]
    return x_series.loc[idx], y_series.loc[idx]


def compute_section_ranges(df: pd.DataFrame, selected_sections: list[str]) -> list[dict]:
    if "_section_in" not in df.columns:
        return []

    ranges = []
    for sec in sorted(selected_sections, key=float):
        mask = df["_section_in"] == float(sec)
        idx = df.index[mask]
        if len(idx) == 0:
            continue

        ranges.append(
            {
                "label": f'{sec}"',
                "t_min": idx.min(),
                "t_max": idx.max(),
            }
        )

    ranges.sort(key=lambda r: r["t_min"])
    return ranges


def normalize_series(s: pd.Series):
    s = pd.to_numeric(s, errors="coerce")
    s_valid = s.dropna()

    if s_valid.empty:
        return s * np.nan, np.nan, np.nan

    s_min = float(s_valid.min())
    s_max = float(s_valid.max())

    if np.isclose(s_min, s_max):
        return pd.Series(np.full(len(s), 0.5), index=s.index), s_min, s_max

    return (s - s_min) / (s_max - s_min), s_min, s_max


def format_number(value: float) -> str:
    if pd.isna(value):
        return "NA"
    return f"{value:.1f}"


def axis_annotation_y(param_idx: int) -> float:
    return -0.09 - (param_idx * 0.05)