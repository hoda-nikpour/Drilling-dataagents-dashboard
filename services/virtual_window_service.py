from __future__ import annotations

import pandas as pd


def dataframe_to_track_payload(
    df: pd.DataFrame,
    *,
    track_params_real: list[list[str]],
    track_param_labels: list[list[str]],
    parameter_units: dict[str, str] | None = None,
) -> dict:
    """
    Convert the currently loaded raw buffer into a compact JSON payload.

    No downsampling is applied. Every loaded timestamp/value is sent to the
    React component.
    """
    parameter_units = parameter_units or {}

    if df is None or df.empty:
        return {"tracks": [], "time_start": None, "time_end": None}

    idx_text = [pd.Timestamp(t).strftime("%Y-%m-%d %H:%M:%S") for t in df.index]

    tracks = []
    for track_idx, raw_cols in enumerate(track_params_real[:3], start=1):
        labels = track_param_labels[track_idx - 1] if track_idx - 1 < len(track_param_labels) else raw_cols
        curves = []

        for col_idx, raw_col in enumerate(raw_cols):
            if raw_col not in df.columns:
                continue

            label = labels[col_idx] if col_idx < len(labels) else raw_col
            s = pd.to_numeric(df[raw_col], errors="coerce")

            values = []
            for v in s:
                if pd.isna(v):
                    values.append(None)
                else:
                    values.append(float(v))

            curves.append(
                {
                    "label": str(label),
                    "raw_col": str(raw_col),
                    "unit": parameter_units.get(str(label), ""),
                    "x": values,
                    "y": idx_text,
                }
            )

        tracks.append({"track": track_idx, "curves": curves})

    return {
        "tracks": tracks,
        "time_start": idx_text[0] if idx_text else None,
        "time_end": idx_text[-1] if idx_text else None,
        "sample_count": len(idx_text),
    }
