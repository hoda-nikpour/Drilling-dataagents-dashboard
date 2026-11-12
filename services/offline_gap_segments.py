"""Conservative offline prediction split at missing-data gaps.

Only the offline validation job uses this. Production agents and chart windows
remain unchanged. After each restart a deterministic history warm-up is NOT
certified as covered by predictions. The opening section begins normally.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd
from drillmate_validation.events import ValidationError
from services.validation_continuous import utc_iso, fixed_utc_offset

MIN_RESTART_WARMUP_SAMPLES = 256


def restart_warmup_samples(activity_cfg: dict, symptom_cfg: dict) -> int:
    """Conservative configuration-sensitive history exclusion after a reset.

    This is a screening rule for trustworthy coverage, not mathematical proof
    of perfect agent convergence. The rule/parameters are signed into the job.
    """
    history = 0
    for cfg in (activity_cfg, symptom_cfg):
        if not isinstance(cfg, dict):
            raise ValidationError('Agent configuration is needed for gap restart planning')
        for key, raw in cfg.items():
            if any(t in key for t in ('window', '_samples', '_periods')):
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw):
                    raise ValidationError(f'Invalid configured lookback: {key}')
                if raw < 0 or (key.endswith('window') and raw < 1):
                    raise ValidationError(f'Invalid configured lookback: {key}')
                history = max(history, int(raw) + (raw != int(raw)))
    # Includes temporal confirmation/backdating headroom; 3x rolling history.
    result = max(MIN_RESTART_WARMUP_SAMPLES, 3 * history + 64)
    if result > 50_000:
        raise ValidationError('Configured history exceeds supported restart warm-up; refuse offline prediction')
    return result


def split_at_gaps(index, *, cadence_seconds: float, max_gap_seconds: float,
                  log_utc_offset: str, restart_warmup_samples: int) -> tuple[list[slice], list[dict], list[dict]]:
    """Return processing slices, certifiable coverage and explicit gap metadata.

    A gap-separated segment is evaluated with a fresh agent state. Its first
    warm-up rows are excluded from coverage (except the original section start,
    which uses the same initialization as an unbroken full-section run).
    """
    fixed_utc_offset(log_utc_offset)
    if (not all(isfinite(float(x)) for x in (cadence_seconds, max_gap_seconds))
            or not 0 < float(cadence_seconds) <= float(max_gap_seconds)
            or float(max_gap_seconds) > 10 * float(cadence_seconds)):
        raise ValidationError('Invalid sampling cadence or maximum gap')
    if (isinstance(restart_warmup_samples, bool) or not isinstance(restart_warmup_samples, int)
            or restart_warmup_samples < MIN_RESTART_WARMUP_SAMPLES
            or restart_warmup_samples > 50_000):
        raise ValidationError('Invalid restart warm-up sample count')
    times = pd.DatetimeIndex(index)
    if len(times) == 0 or times.hasnans or not times.is_monotonic_increasing or not times.is_unique:
        raise ValidationError('Timestamp index must be nonempty, sorted, unique and valid')
    edges = [0]
    gaps = []
    for i in range(1, len(times)):
        delta = (times[i] - times[i-1]).total_seconds()
        if delta > max_gap_seconds:
            edges.append(i)
            gaps.append({'after': utc_iso(times[i-1], log_utc_offset),
                         'before': utc_iso(times[i], log_utc_offset),
                         'missing_seconds_between_samples': delta})
    edges.append(len(times))
    slices = [slice(a, b) for a, b in zip(edges[:-1], edges[1:])]
    coverage = []
    segments = []
    for segment_number, part in enumerate(slices):
        # Initial dataset start retains original algorithm initialization;
        # a new segment after a gap requires fresh warm-up.
        excluded = 0 if segment_number == 0 else min(part.stop - part.start, restart_warmup_samples)
        first = part.start + excluded
        segment = {
            'segment_number': segment_number,
            'first_sample': int(part.start), 'end_sample_exclusive': int(part.stop),
            'warmup_rows_excluded': int(excluded),
            'sample_count': int(part.stop-part.start),
        }
        segments.append(segment)
        if first < part.stop:
            coverage.append({'start': utc_iso(times[first], log_utc_offset),
                             'end': utc_iso(times[part.stop-1] + pd.Timedelta(seconds=cadence_seconds),log_utc_offset)})
    if not coverage:
        raise ValidationError('No certifiable prediction coverage remains after gap-reset warm-up')
    return slices, coverage, segments
