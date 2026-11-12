"""Independent offline-prediction-exchange safety tests."""
import ast
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from agents.activity_agents import ActivityConfig
from agents.symptom_agents import SymptomConfig
from drillmate_validation.events import ValidationError
from drillmate_validation.offline_prediction_exchange import (
    make_job, validate_job, make_prediction_file, verify_prediction_file,
    source_fingerprint, section_path,
)


class OfflineExchangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in ('agents','services','data_access','drillmate_validation','tools','ui','data'):
            (self.root / folder).mkdir()
            (self.root / folder / 'test.py').write_text('# test module\n')
        for file in ('config.py','app.py','tools/generate_full_section_predictions.py','ui/final_validation_panel.py'):
            (self.root / file).write_text('# source\n')
        (self.root / 'data/W_12_25in.parquet').write_bytes(b'example parquet content')
        self.params = dict(root=self.root, well='W', section='12.25',
            agent='TRQSpike', agent_kind='symptom', full_sample_count=4,
            log_utc_offset='+00:00', cadence_seconds=1.0, max_gap_seconds=1.0,
            activity_ui={'enabled':True,'selected_activity':'All activities','config':ActivityConfig()},
            symptom_ui={'enabled':True,'selected_symptom':'TRQSpike','config':SymptomConfig()},
            requested_columns=['TRQ'], label_to_column={'TRQ':'TRQ'},
            cleaning_rules={}, required_activity_labels=['TRQ'],required_symptom_labels=['TRQ'])
        self.times = pd.date_range('2026-01-01', periods=4, freq='s')

    def _file(self):
        job = make_job(**self.params)
        coverage=[{'start':'2026-01-01T00:00:00+00:00', 'end':'2026-01-01T00:00:04+00:00'}]
        rows=[{'id':'p1', 'agent':'TRQSpike','start':'2026-01-01T00:00:00+00:00','end':'2026-01-01T00:00:02+00:00'}]
        from services.offline_gap_segments import split_at_gaps
        _, _, segments = split_at_gaps(self.times, log_utc_offset='+00:00',
            cadence_seconds=1.0, max_gap_seconds=1.0,
            restart_warmup_samples=job['gap_restart_warmup_samples'])
        return job, make_prediction_file(job, rows, coverage, 4, segments=segments)

    def test_valid_roundtrip(self):
        job, file = self._file()
        validate_job(job, root=self.root)
        rows,cov=verify_prediction_file(file,expected_job=job,full_time_index=self.times)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(cov),1)

    def test_uploaded_predictions_can_be_scored_by_production_engine(self):
        from drillmate_validation.events import evaluate_events, RULE_VERSION
        job, file = self._file()
        preds, cov = verify_prediction_file(file, expected_job=job,
                                           full_time_index=self.times)
        score = evaluate_events({
            'schema_version': 1, 'well': 'W', 'section': '12.25',
            'agent': 'TRQSpike', 'agent_kind': 'symptom',
            'reviewed_intervals': cov,
            'prediction_coverage': cov,
            'predictions_complete': True,
            'prediction_generation': 'continuous',
            'expert_tags': [{'id':'t1','agent':'TRQSpike',
                             'start':'2026-01-01T00:00:00+00:00',
                             'end':'2026-01-01T00:00:02+00:00'}],
            'predictions': preds,
            'matching': {'version':RULE_VERSION, 'method':'iou_one_to_one',
                         'min_iou':0.5,'min_overlap_seconds':0},
        })
        self.assertEqual(score['event_counts']['TP'],1)
        self.assertEqual(score['event_counts']['FP'],0)

    def test_reject_corrupt_prediction(self):
        job,file=self._file()
        file['predictions'][0]['end']='2026-01-01T00:00:03+00:00'
        with self.assertRaisesRegex(ValidationError,'modified'):
            verify_prediction_file(file,expected_job=job,full_time_index=self.times)

    def test_reject_other_agent_settings(self):
        job,file=self._file()
        self.params['symptom_ui']['config']=SymptomConfig(trq_spike_ratio_level_1=1.5)
        revised=make_job(**self.params)
        with self.assertRaisesRegex(ValidationError,'settings/version'):
            verify_prediction_file(file,expected_job=revised,full_time_index=self.times)

    def test_reject_changed_data(self):
        job,file=self._file()
        (self.root / 'data/W_12_25in.parquet').write_bytes(b'some new parquet bytes')
        with self.assertRaisesRegex(ValidationError, 'Parquet'):
            validate_job(job, root=self.root)

    def test_reject_changed_code(self):
        job,file=self._file()
        (self.root / 'agents/test.py').write_text('X = 1\n')
        with self.assertRaisesRegex(ValidationError,'software'):
            validate_job(job, root=self.root)

    def test_reject_missing_time_point(self):
        job,file=self._file()
        with self.assertRaises(ValidationError):
            verify_prediction_file(file,expected_job=job,full_time_index=self.times.delete(2))

    def test_reject_wrong_section(self):
        job,file=self._file()
        file['section']='17.5'
        file['prediction_payload_sha256'] = __import__('drillmate_validation.offline_prediction_exchange',fromlist=['digest']).digest({k:v for k,v in file.items() if k != 'prediction_payload_sha256'})
        with self.assertRaisesRegex(ValidationError,'section'):
            verify_prediction_file(file,expected_job=job,full_time_index=self.times)

    def test_reject_prediction_outside_data(self):
        from drillmate_validation.offline_prediction_exchange import digest
        job,file=self._file()
        file['predictions'][0]['end']='2026-01-01T00:00:05+00:00'
        file['prediction_payload_sha256']=digest({k:v for k,v in file.items() if k!='prediction_payload_sha256'})
        with self.assertRaisesRegex(ValidationError,'outside'):
            verify_prediction_file(file,expected_job=job,full_time_index=self.times)

    def test_block_path_traversal(self):
        with self.assertRaises(ValidationError):
            section_path('../W','12.25',data_dir=self.root/'data')

    def test_offline_resolver_ast_identical_to_app(self):
        root=Path(__file__).resolve().parents[1]
        app=ast.parse((root/'app.py').read_text())
        offline=ast.parse((root/'services/offline_temporal.py').read_text())
        def get(node, name):
            return next(x for x in node.body if isinstance(x,ast.FunctionDef) and x.name==name)
        self.assertEqual(ast.dump(get(app,'_apply_temporal_activity_resolution')),
                         ast.dump(get(offline,'_apply_temporal_activity_resolution')))
        def cfg(node):
            return next(x.value for x in node.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_PRODUCTION_TEMPORAL_ACTIVITY_CONFIG' for t in x.targets))
        self.assertEqual(ast.dump(cfg(app)),ast.dump(cfg(offline)))

if __name__=='__main__': unittest.main()
