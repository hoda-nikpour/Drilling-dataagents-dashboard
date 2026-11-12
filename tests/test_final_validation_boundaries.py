"""Use actual detector interval builders to check irregular native timestamps."""
import inspect
import pandas as pd
import pytest

from agents.activity_support import intervals_from_label_series
from agents.symptom_support import mask_to_intervals
from drillmate_validation.dashboard_adapter import binary_activity_timelines
from drillmate_validation.events import ValidationError
from services.validation_continuous import normalize_predictions

def normalize(raw, **kwargs):
    # Also exercise the preserved pre-fix module: show its wrong numeric
    # boundary, rather than failing merely because the new argument is absent.
    if 'sample_index' not in inspect.signature(normalize_predictions).parameters:
        kwargs.pop('sample_index', None)
    return normalize_predictions(raw, **kwargs)

@pytest.mark.parametrize('builder', ['activity', 'symptom'])
@pytest.mark.parametrize('seconds', [[0, 2, 4], [0, 6, 10]])
def test_end_is_next_observed_sample_not_assumed_cadence(builder, seconds):
    index = pd.Timestamp('2026-01-01') + pd.to_timedelta(seconds, unit='s')
    if builder == 'activity':
        raw = intervals_from_label_series(pd.Series(['Drilling', 'Other', 'Other'], index=index))[:1]
    else:
        raw = mask_to_intervals(pd.Series([True, False, False], index=index), 'TRQSpike')
    got = normalize(raw, agent=raw[0]['label'], log_utc_offset='+00:00',
                                sample_cadence_seconds=4, sample_index=index)
    assert pd.Timestamp(got[0]['end']) == index[1].tz_localize('UTC')

def test_final_sample_uses_explicit_cadence():
    index = pd.date_range('2026-01-01', periods=3, freq='2s')
    got = normalize([{'start': index[-1], 'end': index[-1]}],
        agent='TRQSpike', log_utc_offset='+02:00', sample_cadence_seconds=4, sample_index=index)
    assert got[0]['end'] == '2025-12-31T22:00:08+00:00'

def test_non_sample_endpoint_refused():
    index = pd.date_range('2026-01-01', periods=3, freq='4s')
    with pytest.raises(ValidationError, match='sample'):
        normalize([{'start': index[0], 'end': index[0] + pd.Timedelta(seconds=1)}],
            agent='TRQSpike', log_utc_offset='+00:00', sample_cadence_seconds=4, sample_index=index)

def test_irregular_activity_prediction_agrees_with_known_expert_transition():
    index = pd.to_datetime(['2026-01-01 00:00:00', '2026-01-01 00:00:02', '2026-01-01 00:00:04'])
    raw = intervals_from_label_series(pd.Series(['Drilling', 'Other', 'Other'], index=index))[:1]
    predictions = normalize(raw, agent='Drilling', log_utc_offset='+00:00',
        sample_cadence_seconds=4, sample_index=index)
    review = [{'start': '2026-01-01T00:00:00+00:00', 'end': '2026-01-01T00:00:08+00:00'}]
    expert = [{'start': review[0]['start'], 'end': '2026-01-01T00:00:02+00:00'}]
    left, right = binary_activity_timelines(expert, predictions, review, agent='Drilling')
    assert [(x['activity'], x['start'], x['end']) for x in left] == [(x['activity'], x['start'], x['end']) for x in right]
