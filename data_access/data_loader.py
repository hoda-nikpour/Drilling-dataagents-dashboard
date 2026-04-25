import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
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


@st.cache_data(show_spinner="Loading well data …")
def load_sections_for_columns(
    well: str,
    sections: tuple[str, ...],
    requested_columns: tuple[str, ...],
) -> pd.DataFrame:
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

        needed = [time_col] + OPTIONAL_META_COLUMNS + list(requested_columns)
        cols = [c for c in needed if c in schema_cols]

        try:
            part = pd.read_parquet(path, columns=cols, engine="pyarrow")
        except Exception as e:
            st.warning(f"Could not read {path.name}: {e}")
            continue

        if time_col != "TIME":
            part = part.rename(columns={time_col: "TIME"})

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
            df = pd.read_parquet(path, engine="pyarrow")
        except Exception:
            continue

        for col in df.columns:
            if col in excluded or col in discovered:
                continue

            series = df[col]

            if pd.api.types.is_numeric_dtype(series):
                discovered.add(col)
                continue

            sample = pd.to_numeric(series.dropna().head(200), errors="coerce")
            if not sample.empty and sample.notna().any():
                discovered.add(col)

    return sorted(discovered)