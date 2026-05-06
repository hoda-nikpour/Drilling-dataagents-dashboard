import pandas as pd


def build_time_cadence_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Diagnose the real timestamp spacing in the loaded dataframe.

    This helps distinguish:
    - real low-frequency source data
    - visual compression/downsampling in the dashboard
    """
    columns = [
        "Scope",
        "Samples",
        "Start",
        "End",
        "Duration hours",
        "Median step sec",
        "P90 step sec",
        "P95 step sec",
        "Max step sec",
        "Gaps > 30 sec",
        "Gaps > 60 sec",
        "Duplicate timestamps",
        "Status",
    ]

    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return pd.DataFrame(columns=columns)

    def _one(scope: str, part: pd.DataFrame) -> dict:
        idx = pd.Series(part.index).sort_values()

        duplicate_count = int(idx.duplicated().sum())

        if len(idx) <= 1:
            return {
                "Scope": scope,
                "Samples": len(idx),
                "Start": idx.min() if len(idx) else pd.NaT,
                "End": idx.max() if len(idx) else pd.NaT,
                "Duration hours": 0.0,
                "Median step sec": pd.NA,
                "P90 step sec": pd.NA,
                "P95 step sec": pd.NA,
                "Max step sec": pd.NA,
                "Gaps > 30 sec": 0,
                "Gaps > 60 sec": 0,
                "Duplicate timestamps": duplicate_count,
                "Status": "Too few samples",
            }

        step_sec = idx.diff().dt.total_seconds().dropna()
        duration_hours = (idx.max() - idx.min()).total_seconds() / 3600.0

        median_step = float(step_sec.median())
        p90_step = float(step_sec.quantile(0.90))
        p95_step = float(step_sec.quantile(0.95))
        max_step = float(step_sec.max())

        gaps_30 = int((step_sec > 30.0).sum())
        gaps_60 = int((step_sec > 60.0).sum())

        if median_step <= 10.0:
            status = "High-frequency data"
        elif median_step <= 30.0:
            status = "Moderate-frequency data"
        else:
            status = "Low-frequency / minute-range data"

        if gaps_60 > 0:
            status += "; has large gaps"

        return {
            "Scope": scope,
            "Samples": int(len(idx)),
            "Start": idx.min(),
            "End": idx.max(),
            "Duration hours": round(duration_hours, 3),
            "Median step sec": round(median_step, 3),
            "P90 step sec": round(p90_step, 3),
            "P95 step sec": round(p95_step, 3),
            "Max step sec": round(max_step, 3),
            "Gaps > 30 sec": gaps_30,
            "Gaps > 60 sec": gaps_60,
            "Duplicate timestamps": duplicate_count,
            "Status": status,
        }

    rows = [_one("All selected data", df)]

    if "_section_in" in df.columns:
        for section, part in df.groupby("_section_in", dropna=False):
            rows.append(_one(f'Section {section}"', part))

    return pd.DataFrame(rows, columns=columns)