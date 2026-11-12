"""Observed-time gap handling for the live viewer; never a final-scoring claim.

The display threshold is ten times the median positive native interval per
section. No samples are synthesized, resampled or removed. Final validation
continues to require independently confirmed cadence and gap inputs.
"""
from dataclasses import asdict, is_dataclass

import numpy as np
import pandas as pd

from agents.activity_agents import build_activity_summary
from services.offline_gap_segments import restart_warmup_samples

LIVE_GAP_POLICY = 'native_median_times_10_with_restart_warmup_v1'

def _sections(values, count):
    if values is None:
        return np.full(count, '', dtype=object)
    return np.array([str(x) for x in values], dtype=object)

def build_live_gap_plan(index, activity_ui, symptom_ui, sections=None):
    times = pd.DatetimeIndex(index)
    if times.hasnans or not times.is_monotonic_increasing:
        raise ValueError('Live timestamps must be valid and sorted')
    labels = _sections(sections, len(times))
    if len(labels) != len(times):
        raise ValueError('Section labels and timestamps are not aligned')
    configs = [asdict(ui['config']) if is_dataclass(ui.get('config')) else {} for ui in (activity_ui, symptom_ui)]
    warmup = restart_warmup_samples(*configs)
    # Parquet-backed datetime indices may use microseconds rather than ns.
    # Subtraction + total_seconds preserves the index's actual time unit.
    seconds = np.asarray((times[1:] - times[:-1]).total_seconds())
    same_section = labels[1:] == labels[:-1]
    policies = {}
    for section in dict.fromkeys(labels):
        positive = seconds[(seconds > 0) & same_section & (labels[1:] == section)]
        cadence = float(np.median(positive)) if len(positive) else None
        policies[section] = {'cadence_seconds': cadence,
                             'max_gap_seconds': 10 * cadence if cadence is not None else None}
    breaks = [0]
    for i, delta in enumerate(seconds, start=1):
        threshold = policies[labels[i]]['max_gap_seconds']
        if labels[i] != labels[i-1] or (threshold is not None and delta > threshold):
            breaks.append(i)
    breaks.append(len(times))
    segments = []
    seen_sections = set()
    for a, z in zip(breaks[:-1], breaks[1:]):
        if a == z:
            continue
        section = labels[a]
        excluded = min(warmup, z-a) if section in seen_sections else 0
        seen_sections.add(section)
        cadence = policies[section]['cadence_seconds']
        end = times[z-1] + pd.Timedelta(seconds=cadence or 0)
        segments.append({'section': section, 'start': str(times[a]), 'last_sample': str(times[z-1]),
                         'end': str(end), 'sample_count': z-a, 'warmup_rows_excluded': excluded,
                         'trusted_start': str(times[a+excluded]) if excluded < z-a else None})
    return {'policy': LIVE_GAP_POLICY, 'policies': policies, 'segments': segments,
            'restart_warmup_samples': warmup, 'cadence_verified_for_final_validation': False}

def gap_break_positions(index, *, sections=None, plan=None):
    times = pd.DatetimeIndex(index)
    labels = _sections(sections, len(times))
    if plan is None:
        plan = build_live_gap_plan(times, {}, {}, labels)
    out = []
    for i in range(1, len(times)):
        policy = plan['policies'].get(labels[i], {})
        threshold = policy.get('max_gap_seconds')
        if labels[i] != labels[i-1] or (threshold is not None and (times[i]-times[i-1]).total_seconds() > threshold):
            out.append(i-1)
    return out

def run_live_agents(*, df, label_to_column, activity_ui, symptom_ui, run_activity,
                    resolve_activity, run_symptom, gap_plan=None):
    """Reset rolling/temporal state at physical gaps, keeping uncertain output out.

    A plan based on the full lightweight time index also preserves the warm-up
    exclusion when the loaded buffer starts partway through a restarted segment.
    """
    section_labels = df['_section_in'] if '_section_in' in df else None
    plan = gap_plan or build_live_gap_plan(df.index, activity_ui, symptom_ui, section_labels)
    cuts = [0] + [i+1 for i in gap_break_positions(df.index, sections=section_labels, plan=plan)] + [len(df)]
    section_names = _sections(section_labels, len(df))
    activity_parts, symptom_parts, coverage, uncertain = [], [], [], []
    for a, z in zip(cuts[:-1], cuts[1:]):
        if a == z:
            continue
        part = df.iloc[a:z].copy()
        activity = run_activity(df=part, label_to_column=label_to_column, activity_ui=activity_ui)
        if activity_ui.get('enabled') and not activity.get('labels', pd.Series(dtype=object)).empty:
            activity = resolve_activity(df=part, activity_cfg=activity)
        symptom = run_symptom(df=part, label_to_column=label_to_column, symptom_ui=symptom_ui,
                              activity_ui=activity_ui, activity_cfg=activity)
        candidates = [s for s in plan['segments'] if s['section'] == section_names[a]
                      and pd.Timestamp(s['start']) <= part.index[0] <= pd.Timestamp(s['last_sample'])]
        if len(candidates) != 1:
            raise ValueError('Live buffer does not match its section gap plan')
        segment = candidates[0]
        trusted = pd.Timestamp(segment['trusted_start']) if segment['trusted_start'] is not None else None
        # A freshly loaded buffer also has no history before its first row.
        # Do not certify a partially warmed restart just because the full-index
        # plan's cutoff is earlier than this particular buffer's cutoff.
        if part.index[0] > pd.Timestamp(segment['start']):
            local_warmup = plan['restart_warmup_samples']
            trusted = max(trusted, part.index[local_warmup]) if trusted is not None and len(part) > local_warmup else None
        cadence = plan['policies'][section_names[a]]['cadence_seconds'] or 0
        end = min(pd.Timestamp(segment['end']), part.index[-1] + pd.Timedelta(seconds=cadence))
        start = max(part.index[0], trusted) if trusted is not None else end
        if start < end:
            coverage.append({'start':str(start),'end':str(end)})
        for result, kind in ((activity, 'activity'), (symptom, 'symptom')):
            accepted = []
            for item in result.get('intervals', []):
                row = dict(item)
                left, right = pd.Timestamp(row['start']), pd.Timestamp(row['end'])
                if trusted is None or right < start:
                    continue
                if left < start:
                    if kind == 'symptom':
                        uncertain.append(dict(row, exclusion_reason='crosses_restart_warmup',
                            coverage_exclusion_end=str(right + pd.Timedelta(seconds=cadence))))
                        continue
                    row['start'] = start
                accepted.append(row)
            result = dict(result, intervals=accepted)
            if kind == 'activity':
                labels = result.get('labels')
                if isinstance(labels, pd.Series) and len(labels) == len(part):
                    labels = labels.copy()
                    labels.iloc[np.asarray(part.index < start)] = pd.NA
                    result['labels'] = labels
                activity_parts.append(result)
            else:
                symptom_parts.append(result)
    def combine(parts, kind):
        result = dict(parts[0]) if parts else {}
        result['intervals'] = [item for part in parts for item in part.get('intervals', [])]
        result['intervals'].sort(key=lambda item: pd.Timestamp(item['start']))
        for key in ('labels', 'labels_raw', 'features'):
            values = [p[key] for p in parts if isinstance(p.get(key), (pd.Series,pd.DataFrame))]
            if values:
                result[key] = pd.concat(values)
        if kind == 'activity' and isinstance(result.get('labels'), pd.Series):
            result['summary_df'] = build_activity_summary(result['labels'])
        reliable = list(coverage)
        if kind == 'symptom':
            # Dropping a warm-up-crossing event must not turn its remaining tail
            # into a certified absence / false Miss in the live comparison.
            for row in uncertain:
                left, right = pd.Timestamp(row['start']), pd.Timestamp(row['coverage_exclusion_end'])
                remaining = []
                for item in reliable:
                    a, z = pd.Timestamp(item['start']), pd.Timestamp(item['end'])
                    if right <= a or left >= z:
                        remaining.append(item)
                    else:
                        if a < left:
                            remaining.append({'start':str(a), 'end':str(left)})
                        if right < z:
                            remaining.append({'start':str(right), 'end':str(z)})
                reliable = remaining
        result.update(prediction_coverage=reliable, live_gap_policy=plan['policy'],
                      uncertified_intervals=uncertain)
        return result
    return combine(activity_parts, 'activity'), combine(symptom_parts, 'symptom')
