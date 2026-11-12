"""Gap-reset regression tests; no Streamlit or Parquet files required."""
import copy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import pandas as pd

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from drillmate_validation.events import ValidationError, evaluate_events, RULE_VERSION
from drillmate_validation.offline_prediction_exchange import make_job, verify_prediction_file
from services.offline_gap_segments import split_at_gaps, restart_warmup_samples
# This module's loader uses PyArrow in production; the test stubs only file IO.
# Keep these logic tests runnable in a minimal Python environment too.
import importlib.util
import sys
import types
if importlib.util.find_spec('pyarrow') is None:
    stub = types.ModuleType('data_access.data_loader')
    stub.load_section_time_index = lambda *args, **kwargs: None
    stub.load_sections_for_columns = lambda *args, **kwargs: None
    with patch.dict(sys.modules, {'data_access.data_loader':stub}):
        from tools.generate_full_section_predictions import generate
else:
    from tools.generate_full_section_predictions import generate
from tests.test_offline_prediction_exchange import OfflineExchangeTests


class GapSegmentTests(unittest.TestCase):
    def setUp(self):
        self.cadence = 1.0
        self.idx = pd.date_range('2026-01-01', periods=12, freq='s').append(
            pd.date_range('2026-01-01 00:01:00', periods=700, freq='s'))
        self.warmup = restart_warmup_samples(vars(ActivityConfig()), vars(SymptomConfig()))

    def _split(self):
        return split_at_gaps(self.idx, cadence_seconds=1,
            max_gap_seconds=2, log_utc_offset='+00:00', restart_warmup_samples=self.warmup)

    def test_coverage_excludes_gap_and_warmup(self):
        parts, coverage, seg = self._split()
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(coverage), 2)
        self.assertEqual(seg[1]['warmup_rows_excluded'], self.warmup)
        self.assertEqual(coverage[0]['end'], '2026-01-01T00:00:12+00:00')
        self.assertEqual(coverage[1]['start'], (pd.Timestamp('2026-01-01 00:01:00') + pd.Timedelta(seconds=self.warmup)).tz_localize('UTC').isoformat())
        self.assertGreater(pd.Timestamp(coverage[1]['start']), pd.Timestamp(coverage[0]['end']))

    def test_short_segment_is_excluded_not_mistaken_for_full_coverage(self):
        idx = pd.date_range('2026-01-01', periods=12, freq='s').append(
            pd.date_range('2026-01-01 00:01:00', periods=40, freq='s'))
        parts, coverage, seg=split_at_gaps(idx, cadence_seconds=1,max_gap_seconds=2,log_utc_offset='+00:00',restart_warmup_samples=self.warmup)
        self.assertEqual(len(coverage), 1)
        self.assertEqual(seg[1]['warmup_rows_excluded'], 40)

    def test_missing_gap_cannot_be_counted_as_reviewed(self):
        parts, coverage, seg=self._split()
        payload=dict(schema_version=1,well='W',section='12.25',agent='TRQSpike',agent_kind='symptom',
            prediction_generation='gap_reset_segments',predictions_complete=True,
            prediction_coverage=coverage, reviewed_intervals=[{'start':coverage[0]['start'],'end':coverage[1]['end']}],
            expert_tags=[],predictions=[],matching={'version':RULE_VERSION,'method':'iou_one_to_one','min_iou':0.5,'min_overlap_seconds':0})
        with self.assertRaisesRegex(ValidationError,'coverage'):
            evaluate_events(payload)
        payload['reviewed_intervals']=coverage
        self.assertEqual(evaluate_events(payload)['status'],'evaluated')

    def test_invalid_gap_policy_or_warmup(self):
        with self.assertRaises(ValidationError):
            split_at_gaps(self.idx,cadence_seconds=1,max_gap_seconds=2,log_utc_offset='+00:00',restart_warmup_samples=0)

    def test_excessively_permissive_gap_policy_refused(self):
        with self.assertRaisesRegex(ValidationError, 'Invalid sampling'):
            split_at_gaps(self.idx,cadence_seconds=4,max_gap_seconds=914,
                log_utc_offset='+00:00',restart_warmup_samples=self.warmup)

    def test_unknown_clock_not_silently_assumed_utc(self):
        with self.assertRaises(ValidationError):
            split_at_gaps(self.idx,cadence_seconds=1,max_gap_seconds=2,log_utc_offset='',restart_warmup_samples=self.warmup)

    def test_real_runner_pipeline_resets_at_gaps_and_upload_verifies(self):
        # Reuse the manifest-test fixture, including fingerprints and exact job shape.
        fixture=OfflineExchangeTests('test_valid_roundtrip')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.params.update(full_sample_count=len(self.idx),max_gap_seconds=2)
        job=make_job(**fixture.params)
        calls=[]
        def fake_prediction(**kw):
            ix=kw['full_df'].index
            calls.append(ix)
            if len(calls)==1:
                return [{'label':'TRQSpike','start':ix[2],'end':ix[3]}]
            return [{'label':'TRQSpike','start':ix[self.warmup+4],'end':ix[self.warmup+7]}]
        with patch.dict(generate.__globals__, {
            'load_section_time_index':lambda *a,**kw:SimpleNamespace(index=self.idx),
            'load_sections_for_columns':lambda *a,**kw:pd.DataFrame({'x':range(len(self.idx))},index=self.idx),
            'apply_cleaning_layer':lambda df,**kw:(df,{'TRQ':'x'},None),
            'calculate_continuous_predictions':fake_prediction}):
            result=generate(job,data_root=fixture.root)
        self.assertEqual(len(calls),2)
        self.assertEqual([len(x) for x in calls],[12,700])
        self.assertEqual(result['prediction_generation'],'gap_reset_segments')
        self.assertEqual(len(result['predictions']),2)
        self.assertEqual(len(result['prediction_coverage']),2)
        preds,cov=verify_prediction_file(result,expected_job=job,full_time_index=self.idx)
        self.assertEqual(len(preds),2)
        # Mismatched gap cutoffs invalidate the file independently of its digest.
        edited=copy.deepcopy(result)
        edited['prediction_coverage'][1]['start']=edited['prediction_coverage'][0]['start']
        from drillmate_validation.offline_prediction_exchange import digest
        edited['prediction_payload_sha256']=digest({k:v for k,v in edited.items() if k!='prediction_payload_sha256'})
        with self.assertRaisesRegex(ValidationError,'coverage'):
            verify_prediction_file(edited,expected_job=job,full_time_index=self.idx)

    def test_boundary_crossing_symptom_does_not_make_false_event(self):
        fixture=OfflineExchangeTests('test_valid_roundtrip')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.params.update(full_sample_count=len(self.idx),max_gap_seconds=2)
        job=make_job(**fixture.params)
        def fake_prediction(**kw):
            ix=kw['full_df'].index
            if len(ix)==12: return []
            return [{'label':'TRQSpike', 'start':ix[self.warmup-1], 'end':ix[self.warmup+3]}]
        with patch.dict(generate.__globals__, {
            'load_section_time_index':lambda *a,**kw:SimpleNamespace(index=self.idx),
            'load_sections_for_columns':lambda *a,**kw:pd.DataFrame({'x':range(len(self.idx))},index=self.idx),
            'apply_cleaning_layer':lambda df,**kw:(df,{'TRQ':'x'},None),
            'calculate_continuous_predictions':fake_prediction}):
            with self.assertRaisesRegex(ValidationError,'warm-up boundary'):
                generate(job,data_root=fixture.root)

if __name__=='__main__': unittest.main()
