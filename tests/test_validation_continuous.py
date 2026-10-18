import unittest
import pandas as pd
from drillmate_validation.events import ValidationError
from services.validation_continuous import (
    assert_full_section_loaded, assert_unbroken_prediction_state,
    continuous_prediction_coverage, calculate_continuous_predictions,
    normalize_predictions, utc_iso,
)


class ContinuousValidationTests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range('2026-01-01', periods=5, freq='h')

    def test_coverage_does_not_bridge_gap(self):
        dates = pd.DatetimeIndex([self.idx[0], self.idx[1], self.idx[4]])
        rows = continuous_prediction_coverage(dates, log_utc_offset='+00:00', cadence_seconds=10, max_gap_seconds=3600)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]['end'].startswith('2026-01-01T01:00:10'))

    def test_strict_index_equality_and_resource_guard(self):
        assert_full_section_loaded(self.idx, self.idx)
        with self.assertRaises(ValidationError):
            assert_full_section_loaded(self.idx, self.idx[1:])
        with self.assertRaises(ValidationError):
            assert_full_section_loaded(self.idx, self.idx, max_rows=2)

    def test_large_time_gap_requires_gap_aware_state_reset(self):
        points = pd.DatetimeIndex([self.idx[0], self.idx[1], self.idx[4]])
        coverage = continuous_prediction_coverage(points, log_utc_offset='+00:00',
            cadence_seconds=10, max_gap_seconds=3600)
        with self.assertRaisesRegex(ValidationError, 'state'):
            assert_unbroken_prediction_state(coverage)
        assert_unbroken_prediction_state(coverage[:1])

    def test_duplicate_timestamps_fail_closed(self):
        duplicate = pd.DatetimeIndex([self.idx[0], self.idx[0], self.idx[1]])
        with self.assertRaisesRegex(ValidationError, 'unique'):
            assert_full_section_loaded(duplicate, duplicate)
        with self.assertRaisesRegex(ValidationError, 'unique'):
            continuous_prediction_coverage(duplicate, log_utc_offset='+00:00',
                                           cadence_seconds=1, max_gap_seconds=10)

    def test_nonfinite_cadence_and_gap_rejected(self):
        for cadence, gap in [(float('inf'), float('inf')), (1, float('inf')),
                             (float('nan'), 10), (1, float('nan'))]:
            with self.subTest(cadence=cadence, gap=gap):
                with self.assertRaises(ValidationError):
                    continuous_prediction_coverage(self.idx, log_utc_offset='+00:00',
                                                   cadence_seconds=cadence, max_gap_seconds=gap)
        with self.assertRaises(ValidationError):
            normalize_predictions([{'start': self.idx[0], 'end': self.idx[0]}],
                                  agent='TRQSpike', log_utc_offset='+00:00',
                                  sample_cadence_seconds=float('inf'))

    def test_timezone_is_explicit(self):
        self.assertEqual(utc_iso('2026-01-01 12:00:00', '+02:00'), '2026-01-01T10:00:00+00:00')
        with self.assertRaises(ValidationError):
            utc_iso('2026-01-01', 'UTC')

    def test_continuous_calls_temporal_once(self):
        calls = []
        labels = pd.Series(['Drilling']*5, index=self.idx)
        def activity(**kw):
            calls.append('activity')
            return {'labels': labels, 'intervals': []}
        def temporal(**kw):
            calls.append('temporal')
            return kw['activity_cfg']
        def symptom(**kw):
            calls.append('symptom')
            return {'intervals': [{'start':self.idx[1], 'end':self.idx[2], 'label':'TRQSpike'}]}
        actual = calculate_continuous_predictions(
            full_df=pd.DataFrame(index=self.idx), label_to_column={},
            activity_ui={'enabled': True}, symptom_ui={'enabled': True,'selected_symptom':'TRQSpike'},
            selected_agent='TRQSpike',agent_kind='symptom',run_activity=activity,
            resolve_activity=temporal,run_symptom=symptom)
        self.assertEqual(calls,['activity','temporal','symptom'])
        self.assertEqual(len(actual),1)

    def test_crossing_twelve_hour_boundary_is_processed_as_one_section(self):
        idx = pd.date_range('2026-01-01', periods=25, freq='h')
        df = pd.DataFrame(index=idx)
        labels = pd.Series(['Other']*25, index=idx)
        called = []
        def activity(**kw):
            return {'labels':labels, 'intervals':[]}
        def temporal(**kw):
            return kw['activity_cfg']
        def symptom(**kw):
            called.append(len(kw['df']))
            assert len(kw['df']) == 25
            return {'intervals':[{'label':'TRQSpike','start':idx[11], 'end':idx[13]}]}
        result = calculate_continuous_predictions(
            full_df=df, label_to_column={},
            activity_ui={'enabled': True},
            symptom_ui={'enabled': True,'selected_symptom':'TRQSpike'},
            selected_agent='TRQSpike',agent_kind='symptom',
            run_activity=activity,resolve_activity=temporal,run_symptom=symptom)
        self.assertEqual(called,[25])
        self.assertEqual((result[0]['start'],result[0]['end']), (idx[11],idx[13]))

    def test_zero_length_prediction_preserved(self):
        rows=normalize_predictions([{'start': self.idx[0], 'end': self.idx[0]}],agent='PSpike',log_utc_offset='+00:00')
        self.assertEqual(rows[0]['start'],rows[0]['end'])

    def test_last_detected_sample_is_inclusive_in_agent_output(self):
        rows = normalize_predictions([{'start': self.idx[0], 'end': self.idx[1]}],
            agent='TRQSpike', log_utc_offset='+00:00', sample_cadence_seconds=1.0)
        self.assertEqual(rows[0]['end'], '2026-01-01T01:00:01+00:00')

    def test_gap_safety_requires_known_cadence(self):
        with self.assertRaises(ValidationError):
            continuous_prediction_coverage(self.idx,log_utc_offset='+00:00',cadence_seconds=0,max_gap_seconds=10)

if __name__=='__main__': unittest.main()
