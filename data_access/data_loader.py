import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.types as pat
import streamlit as st

from config import DATA_DIR


TIME_CANDIDATES = ["TIME", "date_time", "datetime", "Time", "time"]
OPTIONAL_META_COLUMNS = ["_section_in", "DEPT"]


@st.cache_data(show_spinner="Loading catalog …")
def load_catalog() -> dict:
    path = DATA_DIR / "catalog.json"
    if not path.exists():
        return {"sections": []}

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_schema_columns(path: Path) -> list[str]:
    try:
        return pq.read_schema(path).names
    except Exception:
        return []


def _detect_time_column(existing_columns: list[str]) -> str | None:
    for candidate in TIME_CANDIDATES:
        if candidate in existing_columns:
            return candidate
    return None


def _normalize_time_bound(value):
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def _filter_by_time_column(df: pd.DataFrame, time_start=None, time_end=None) -> pd.DataFrame:
    if df.empty or "TIME" not in df.columns:
        return df

    if time_start is None and time_end is None:
        return df

    t = pd.to_datetime(df["TIME"], errors="coerce")
    mask = pd.Series(True, index=df.index)

    if time_start is not None:
        mask &= t >= pd.Timestamp(time_start)

    if time_end is not None:
        mask &= t <= pd.Timestamp(time_end)

    return df.loc[mask].copy()



def _timestamp_for_compare(value):
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts
    except Exception:
        return None


def _stats_overlap_window(stats, time_start=None, time_end=None) -> bool:
    """
    Use parquet row-group min/max statistics when they are available.
    If statistics cannot be parsed, return True so the row group is read and
    filtered in pandas. This keeps correctness above aggressive skipping.
    """
    if stats is None or not getattr(stats, "has_min_max", False):
        return True

    try:
        rg_min = pd.Timestamp(stats.min)
        rg_max = pd.Timestamp(stats.max)
    except Exception:
        return True

    if pd.isna(rg_min) or pd.isna(rg_max):
        return True

    start_ts = _timestamp_for_compare(time_start)
    end_ts = _timestamp_for_compare(time_end)

    if start_ts is not None and rg_max < start_ts:
        return False
    if end_ts is not None and rg_min > end_ts:
        return False

    return True


def _read_window_by_row_groups(
    path: Path,
    columns: list[str],
    time_col: str,
    time_start=None,
    time_end=None,
) -> pd.DataFrame:
    """
    Robust fallback for windowed loading.

    It does NOT load the whole section into one dataframe. It reads parquet
    row groups one by one, filters each row group by TIME in pandas, and keeps
    only matching rows. If row-group statistics are available, non-overlapping
    row groups are skipped.
    """
    frames = []

    try:
        pf = pq.ParquetFile(path)
    except Exception:
        return pd.DataFrame()

    schema_names = pf.schema_arrow.names
    safe_columns = [c for c in columns if c in schema_names]
    if time_col not in safe_columns and time_col in schema_names:
        safe_columns = [time_col] + safe_columns

    try:
        time_col_idx = schema_names.index(time_col)
    except ValueError:
        time_col_idx = None

    for rg_idx in range(pf.num_row_groups):
        if time_col_idx is not None:
            try:
                stats = pf.metadata.row_group(rg_idx).column(time_col_idx).statistics
                if not _stats_overlap_window(stats, time_start=time_start, time_end=time_end):
                    continue
            except Exception:
                pass

        try:
            table = pf.read_row_group(rg_idx, columns=safe_columns)
            part = table.to_pandas()
        except Exception:
            continue

        if time_col != "TIME" and time_col in part.columns:
            part = part.rename(columns={time_col: "TIME"})

        part = _filter_by_time_column(part, time_start=time_start, time_end=time_end)
        if not part.empty:
            frames.append(part)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True, sort=False)


@st.cache_data(show_spinner="Loading available time range …")
def load_section_time_index(
    well: str,
    sections: tuple[str, ...],
) -> pd.DataFrame:
    """
    Load only TIME for the selected section(s). This is lightweight and lets the
    dashboard build 12-hour windows before loading any curve columns.
    """
    frames = []

    for sec in sections:
        key = f"{well}_{str(sec).replace('.', '_')}in"
        path = DATA_DIR / f"{key}.parquet"

        if not path.exists():
            st.warning(f"Parquet not found: {path.name}")
            continue

        schema_cols = _read_schema_columns(path)
        if not schema_cols:
            st.warning(f"Could not inspect schema for {path.name}")
            continue

        time_col = _detect_time_column(schema_cols)
        if not time_col:
            st.warning(f"No supported time column found in {path.name}")
            continue

        try:
            part = pd.read_parquet(path, columns=[time_col], engine="pyarrow")
        except Exception as e:
            st.warning(f"Could not read time column from {path.name}: {e}")
            continue

        if time_col != "TIME":
            part = part.rename(columns={time_col: "TIME"})

        part["_section_in"] = float(sec)
        frames.append(part)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["TIME"] = pd.to_datetime(merged["TIME"], errors="coerce")
    merged = merged.dropna(subset=["TIME"])
    merged.sort_values("TIME", inplace=True)
    merged.set_index("TIME", inplace=True)

    if "_section_in" in merged.columns:
        merged["_section_in"] = pd.to_numeric(
            merged["_section_in"], errors="coerce"
        ).astype("float32")

    return merged


@st.cache_data(show_spinner="Loading selected 12-hour window data …", max_entries=2)
def load_sections_for_columns(
    well: str,
    sections: tuple[str, ...],
    requested_columns: tuple[str, ...],
    time_start=None,
    time_end=None,
) -> pd.DataFrame:
    """
    Load only requested columns and only the selected 12-hour time window.

    No downsampling is performed.

    This version first tries PyArrow predicate pushdown. If the parquet TIME
    column has a dtype that makes predicate pushdown return empty rows even
    though the timestamp index shows data exists, it falls back to row-group
    scanning. The fallback reads one row group at a time and filters by TIME in
    pandas, so it avoids building the full section dataframe in memory.
    """
    frames = []
    start_bound = _normalize_time_bound(time_start)
    end_bound = _normalize_time_bound(time_end)

    for sec in sections:
        key = f"{well}_{str(sec).replace('.', '_')}in"
        path = DATA_DIR / f"{key}.parquet"

        if not path.exists():
            st.warning(f"Parquet not found: {path.name}")
            continue

        schema_cols = _read_schema_columns(path)
        if not schema_cols:
            st.warning(f"Could not inspect schema for {path.name}")
            continue

        time_col = _detect_time_column(schema_cols)
        if not time_col:
            st.warning(f"No supported time column found in {path.name}")
            continue

        needed = [time_col] + OPTIONAL_META_COLUMNS + list(requested_columns)
        cols = [c for c in needed if c in schema_cols]

        filters = []
        if start_bound is not None:
            filters.append((time_col, ">=", start_bound))
        if end_bound is not None:
            filters.append((time_col, "<=", end_bound))

        part = pd.DataFrame()

        # Fast path: let pyarrow use predicate pushdown when it works.
        try:
            if filters:
                part = pd.read_parquet(
                    path,
                    columns=cols,
                    engine="pyarrow",
                    filters=filters,
                )
            else:
                part = pd.read_parquet(path, columns=cols, engine="pyarrow")
        except Exception:
            part = pd.DataFrame()

        if time_col != "TIME" and not part.empty and time_col in part.columns:
            part = part.rename(columns={time_col: "TIME"})

        if not part.empty:
            part = _filter_by_time_column(part, time_start=start_bound, time_end=end_bound)

        # Robust path: if predicate pushdown returned no rows, scan row groups
        # one at a time and filter in pandas. This fixes TIME dtype mismatches
        # without loading the complete section into one dataframe.
        if part.empty and (start_bound is not None or end_bound is not None):
            part = _read_window_by_row_groups(
                path=path,
                columns=cols,
                time_col=time_col,
                time_start=start_bound,
                time_end=end_bound,
            )

        if part.empty:
            continue

        if "_section_in" not in part.columns:
            part["_section_in"] = float(sec)

        frames.append(part)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged.replace(-999.25, np.nan, inplace=True)

    merged["TIME"] = pd.to_datetime(merged["TIME"], errors="coerce")
    merged = merged.dropna(subset=["TIME"])
    merged.sort_values("TIME", inplace=True)
    merged.set_index("TIME", inplace=True)

    for col in merged.columns:
        if col in {"_section_in", "DEPT"}:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").astype("float32")
            continue

        if merged[col].dtype == object:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        elif pd.api.types.is_integer_dtype(merged[col]) or pd.api.types.is_float_dtype(merged[col]):
            merged[col] = merged[col].astype("float32")

    return merged

@st.cache_data(show_spinner=False)
def get_available_numeric_columns(
    well: str,
    sections: tuple[str, ...],
) -> list[str]:
    if not sections:
        return []

    excluded = {"TIME", "Time", "date_time", "datetime", "time", "_section_in"}
    discovered = set()

    for sec in sections:
        key = f"{well}_{str(sec).replace('.', '_')}in"
        path = DATA_DIR / f"{key}.parquet"

        if not path.exists():
            continue

        try:
            schema = pq.read_schema(path)
        except Exception:
            continue

        for field in schema:
            col = field.name
            if col in excluded or col in discovered:
                continue

            if pat.is_integer(field.type) or pat.is_floating(field.type):
                discovered.add(col)
                continue

            # Some numeric channels may be stored as strings. Inspect only a
            # small row-group sample, not the full column.
            try:
                pf = pq.ParquetFile(path)
                if pf.num_row_groups <= 0:
                    continue
                sample_table = pf.read_row_group(0, columns=[col]).slice(0, 500)
                sample_series = sample_table.to_pandas()[col]
            except Exception:
                continue

            sample = pd.to_numeric(sample_series.dropna(), errors="coerce")
            if not sample.empty and sample.notna().any():
                discovered.add(col)

    return sorted(discovered)


