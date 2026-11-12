#!/usr/bin/env python3
"""Generate read-only, continuous predictions on user's local machine.

Usage: python3 tools/generate_full_section_predictions.py --job job.json --output predictions.json
Requires same Git checkout and identical Parquet files as the online job.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from data_access.data_loader import load_section_time_index, load_sections_for_columns
from drillmate_validation.events import ValidationError
from drillmate_validation.offline_prediction_exchange import (
    OFFLINE_MAX_ROWS, make_prediction_file, validate_job, section_path,
)
from services.data_cleaning import apply_cleaning_layer
from services.dashboard_service import run_activity_agent, run_symptom_agent
from services.offline_temporal import _apply_temporal_activity_resolution
from services.validation_continuous import (
    assert_full_section_loaded, calculate_continuous_predictions,
    normalize_predictions,
)
from services.offline_gap_segments import split_at_gaps
from services.offline_duplicate_rows import verified_offline_keep_mask


def generate(job: dict, *, data_root: Path = ROOT) -> dict:
    validate_job(job, root=data_root)
    if job['full_sample_count'] > OFFLINE_MAX_ROWS:
        raise ValidationError(f'Offline runner safety limit exceeded: {OFFLINE_MAX_ROWS:,} samples')
    well, section = job['well'], job['section']
    raw_expected = load_section_time_index(well, (section,)).index
    if len(raw_expected) > OFFLINE_MAX_ROWS:
        raise ValidationError('Offline safety limit exceeded; no downsampling allowed')
    # Verify duplicates from every *raw* Parquet measurement column, not just
    # the agent's selected curves.  Only the optional offline path deduplicates.
    keep = verified_offline_keep_mask(raw_expected, section_path(
        well, section, data_dir=Path(data_root) / 'data'))
    expected = raw_expected[keep]
    if len(expected) != job['full_sample_count']:
        raise ValidationError('Verified unique index row count differs from online job')
    slices, coverage, segments = split_at_gaps(expected,
        log_utc_offset=job['log_utc_offset'],
        cadence_seconds=job['cadence_seconds'], max_gap_seconds=job['max_gap_seconds'],
        restart_warmup_samples=job['gap_restart_warmup_samples'])
    df = load_sections_for_columns(
        well=well, sections=(section,), requested_columns=tuple(job['requested_columns']),
        time_start=None, time_end=None)
    # Check original one-to-one loader alignment BEFORE omitting provenance-only
    # duplicates; then use the SAME mask as the expected section index.
    # assert_full_section_loaded intentionally rejects duplicates; here we
    # verify exact RAW alignment before applying the independently checked mask.
    if not pd.DatetimeIndex(df.index).equals(pd.DatetimeIndex(raw_expected)):
        raise ValidationError('Raw index and loaded agent rows are not aligned')
    df = df.iloc[keep].copy()
    assert_full_section_loaded(expected, df.index, max_rows=OFFLINE_MAX_ROWS)
    df, mapped, _ = apply_cleaning_layer(
        df=df, label_to_column=job['label_to_column'],
        cleaning_rules=job['cleaning_rules'],
        required_activity_labels=job['required_activity_labels'],
        required_symptom_labels=job['required_symptom_labels'])
    assert_full_section_loaded(expected, df.index, max_rows=OFFLINE_MAX_ROWS)
    activity_ui = dict(job['activity_ui'])
    activity_ui['config'] = ActivityConfig(**activity_ui['config'])
    symptom_ui = dict(job['symptom_ui'])
    symptom_ui['config'] = SymptomConfig(**symptom_ui['config'])
    predictions = []
    for seg_no, part in enumerate(slices):
        # A new call on a new dataframe guarantees that all rolling windows,
        # lag features, temporal state and symptom history start fresh after a gap.
        segment = segments[seg_no]
        if segment['warmup_rows_excluded'] == segment['sample_count']:
            continue  # a short restarted segment has no certifiable output
        segment_df = df.iloc[part].copy()
        detected = calculate_continuous_predictions(
            full_df=segment_df, label_to_column=mapped,
            activity_ui=activity_ui, symptom_ui=symptom_ui,
            selected_agent=job['agent'], agent_kind=job['agent_kind'],
            run_activity=run_activity_agent,
            resolve_activity=_apply_temporal_activity_resolution,
            run_symptom=run_symptom_agent)
        normalized = normalize_predictions(detected, agent=job['agent'],
            log_utc_offset=job['log_utc_offset'], sample_cadence_seconds=job['cadence_seconds'],
            sample_index=segment_df.index)
        trusted_start = pd.Timestamp(segment_df.index[segment['warmup_rows_excluded']])
        # Respect UTC offset when the log index is timezone-naive.
        from services.validation_continuous import utc_iso
        trusted_start = pd.Timestamp(utc_iso(trusted_start, job['log_utc_offset']))
        segment_end = pd.Timestamp(utc_iso(
            segment_df.index[-1] + pd.Timedelta(seconds=job['cadence_seconds']),
            job['log_utc_offset']))
        for pred in normalized:
            pred_start = pd.Timestamp(pred['start'])
            pred_end = pd.Timestamp(pred['end'])
            # A short symptom may start during warm-up, then continue into
            # trustworthy time. Refuse a definitive report, rather than turning
            # its continuation into an invented event or false negative.
            if pred_end > segment_end:
                raise ValidationError(f'Prediction exceeds physical segment end in segment {seg_no}')
            if pred_start < trusted_start < pred_end and job['agent_kind'] == 'symptom':
                raise ValidationError(
                    f'Symptom event crosses warm-up boundary in segment {seg_no}; '
                    'review its boundary or revise the gap-restart policy before scoring.')
            if pred_end <= trusted_start:
                continue
            if pred_start < trusted_start:
                pred['start'] = trusted_start.isoformat()  # activity labels may be clipped
            pred['id'] = f'gap-segment-{seg_no:03d}-{pred["id"]}'
            predictions.append(pred)
    generation = 'continuous' if len(slices) == 1 else 'gap_reset_segments'
    return make_prediction_file(job, predictions, coverage, len(df.index),
        generation=generation, segments=segments)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path, help='Manifest downloaded from Streamlit')
    parser.add_argument('--output', required=True, type=Path, help='Output JSON to upload to Streamlit')
    args = parser.parse_args(argv)
    try:
        job = json.loads(args.job.read_text(encoding='utf-8'))
        result = generate(job)
        if args.output.resolve() == args.job.resolve():
            raise ValidationError('Do not overwrite the input job')
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    except (ValidationError, ValueError, OSError, TypeError) as exc:
        print(f'NOT EVALUABLE: {exc}', file=sys.stderr)
        return 2
    print(f'Success: {result["sample_count"]:,} samples; '
          f'{len(result["predictions"]):,} selected-agent intervals. '
          f'Saved {args.output}')
    print('These are automatic predictions only, NOT expert labels or a validation score.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
