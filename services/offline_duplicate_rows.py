"""Verify and normalize redundant timestamps for optional offline validation only.

Never edits files or chooses between conflicting drilling measurements.  For each
repeated timestamp, compare *all raw Parquet fields*, ignoring only provenance
column ``_source_file``.  Time index and agent input use the same keep-first
mask.  Original source bytes remain covered by the offline manifest's SHA-256.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from drillmate_validation.events import ValidationError

# Fail closed on unexpectedly high duplicate rates or memory pressure.
MAX_REDUNDANT_ROWS = 10_000


def verified_offline_keep_mask(index, parquet_path: Path) -> list[bool]:
    """Return an in-memory keep-first mask only after raw-data verification.

    This function is deliberately *not* used by the normal chart/data loader.
    It reads full columns only from Parquet row groups containing repeated times,
    not the entire section at once. No candidate is removed on conflicting data.
    """
    times = pd.DatetimeIndex(index)
    if times.empty or times.hasnans or not times.is_monotonic_increasing:
        raise ValidationError('Offline time index must be sorted, nonempty and valid')
    keep = ~times.duplicated(keep='first')
    if bool(keep.all()):
        return keep.tolist()
    removed = int((~keep).sum())
    if removed > MAX_REDUNDANT_ROWS:
        raise ValidationError('Too many repeated timestamp rows for safe offline verification')

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValidationError('PyArrow is required to verify repeated Parquet timestamps') from exc
    try:
        pf = pq.ParquetFile(Path(parquet_path))
        if 'TIME' not in pf.schema_arrow.names:
            raise ValidationError('Duplicate verification requires a raw TIME column')
        duplicates = pd.DatetimeIndex(times[times.duplicated(keep=False)]).unique()
        # The raw parquet must have the exact same occurrence count for every
        # duplicate timestamp as the index loaded by the dashboard.
        expected_counts = pd.Series(times[times.isin(duplicates)]).value_counts(sort=False)
        collected = []
        for rg in range(pf.num_row_groups):
            raw_time = pf.read_row_group(rg, columns=['TIME']).column('TIME').to_pandas()
            raw_time = pd.to_datetime(raw_time, errors='raise')
            matching = raw_time.isin(duplicates)
            if not matching.any():
                continue
            raw = pf.read_row_group(rg).to_pandas()
            if len(raw) != len(raw_time):
                raise ValidationError('Parquet row-group TIME/data alignment differs')
            selected = raw.iloc[list(matching)].copy()
            collected.append(selected)
        if not collected:
            raise ValidationError('Duplicated TIME values absent from original Parquet')
        candidates = pd.concat(collected, ignore_index=True)
        candidates['TIME'] = pd.to_datetime(candidates['TIME'], errors='raise')
        actual_counts = candidates['TIME'].value_counts(sort=False)
        if (len(actual_counts) != len(expected_counts)
                or not actual_counts.sort_index().equals(expected_counts.sort_index())):
            raise ValidationError('Duplicate TIME multiplicities differ from raw Parquet')
        for stamp, group in candidates.groupby('TIME', sort=False):
            raw_measurements = group.drop(columns=['_source_file'], errors='ignore')
            first = raw_measurements.iloc[0]
            for pos in range(1, len(raw_measurements)):
                if not first.equals(raw_measurements.iloc[pos]):
                    raise ValidationError(
                        f'Conflicting raw drilling measurements at repeated TIME {stamp}; '
                        'no duplicate rows were removed')
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f'Unable to verify repeated Parquet measurements: {exc}') from exc
    return keep.tolist()


def verified_offline_unique_index(index, parquet_path: Path) -> pd.DatetimeIndex:
    times = pd.DatetimeIndex(index)
    return times[verified_offline_keep_mask(times, parquet_path)]
