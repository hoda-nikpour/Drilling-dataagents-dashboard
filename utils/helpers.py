import numpy as np
import pandas as pd

from config import (
    BASE_MARKER_SIZE,
    ZOOM_MARKER_SIZE,
)


def get_display_mode(marker_display: str = "Lines only") -> tuple[str, float]:
    if marker_display == "Small dots":
        return "lines+markers", BASE_MARKER_SIZE

    if marker_display == "Larger dots":
        return "lines+markers", ZOOM_MARKER_SIZE

    return "lines", BASE_MARKER_SIZE


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
