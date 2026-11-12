"""Offline Parquet provenance-only duplicate safeguards; never edits data."""
from __future__ import annotations

import copy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from drillmate_validation.events import ValidationError
from services.offline_duplicate_rows import (
    verified_offline_keep_mask, verified_offline_unique_index,
)


class _FakeColumn:
    def __init__(self, series):
        self.series = series

    def to_pandas(self):
        return self.series


class _FakeArrowTable:
    def __init__(self, dataframe):
        self.dataframe = dataframe

    def to_pandas(self):
        return self.dataframe

    def column(self, name):
        return _FakeColumn(self.dataframe[name])


class _FakeParquet:
    def __init__(self, row_groups):
        self.groups = row_groups
        self.num_row_groups = len(row_groups)
        self.schema_arrow = types.SimpleNamespace(names=list(row_groups[0].columns))
        self.all_column_reads = []

    def read_row_group(self, rg, columns=None):
        if columns is None:
            self.all_column_reads.append(rg)
        return _FakeArrowTable(self.groups[rg] if columns is None
                               else self.groups[rg][columns])


def _groups():
    a = pd.DataFrame({'TIME': pd.to_datetime(['2026-01-01 00:00:00',
                                             '2026-01-01 00:00:01']),
                      'TRQ': [1.5, 2.2], 'SPPA': [10., 12.],
                      '_source_file': ['file1','file1']})
    b = pd.DataFrame({'TIME': pd.to_datetime(['2026-01-01 00:00:01',
                                             '2026-01-01 00:00:02']),
                      'TRQ': [2.2, 3.3], 'SPPA': [12., 14.],
                      '_source_file': ['file2','file2']})
    return a, b


class OfflineDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = _groups()
        self.times = pd.DatetimeIndex(pd.concat([self.a.TIME,self.b.TIME],ignore_index=True))

    def check_with_fake(self, groups, index=None):
        fake = _FakeParquet(groups)
        parquet_module = types.ModuleType('pyarrow.parquet')
        parquet_module.ParquetFile = lambda unused: fake
        pyarrow_module = types.ModuleType('pyarrow')
        pyarrow_module.__path__ = []
        with patch.dict(sys.modules, {'pyarrow':pyarrow_module,
                                      'pyarrow.parquet':parquet_module}):
            mask = verified_offline_keep_mask(
                self.times if index is None else index, Path('ignored.parquet'))
        return mask, fake

    def test_identical_raw_drilling_data_only_source_differs(self):
        mask, fake = self.check_with_fake([self.a,self.b])
        self.assertEqual(mask,[True,True,False,True])
        self.assertEqual(fake.all_column_reads,[0,1])

    def test_conflicting_unselected_sensor_fails_closed(self):
        different = self.b.copy()
        different.loc[0,'SPPA'] = 999.
        with self.assertRaisesRegex(ValidationError, 'Conflicting raw drilling'):
            self.check_with_fake([self.a,different])

    def test_nan_equality_but_conflicting_nan_rejected(self):
        a=self.a.copy(); b=self.b.copy()
        a.loc[1,'SPPA'] = float('nan'); b.loc[0,'SPPA'] = float('nan')
        self.assertEqual(self.check_with_fake([a,b])[0],[True,True,False,True])
        b.loc[0,'SPPA'] = 12.
        with self.assertRaisesRegex(ValidationError,'Conflicting raw drilling'):
            self.check_with_fake([a,b])

    def test_unexpected_missing_duplicate_row_refused(self):
        b=self.b.iloc[[1]]
        with self.assertRaisesRegex(ValidationError,'multiplicities'):
            self.check_with_fake([self.a,b])

    def test_non_monotonic_index_rejected(self):
        with self.assertRaisesRegex(ValidationError,'sorted'):
            self.check_with_fake([self.a,self.b],self.times[::-1])

    def test_unique_index_requires_no_arrow_and_preserves_all_rows(self):
        times=pd.date_range('2026-01-01', periods=5, freq='s')
        with patch.dict(sys.modules,{'pyarrow': None}):
            self.assertEqual(verified_offline_unique_index(times,Path('unused.parquet')).tolist(),times.tolist())

    def test_duplicate_policy_rejects_excessive_repeats(self):
        index=pd.DatetimeIndex([pd.Timestamp('2026-01-01')]*10003)
        with self.assertRaisesRegex(ValidationError,'Too many'):
            verified_offline_keep_mask(index,Path('unused.parquet'))

    def test_generator_and_upload_use_same_normalized_index(self):
        # Real generator control flow; agent and Parquet IO are mocked only.
        from unittest.mock import patch as mockpatch
        from types import SimpleNamespace
        from tests.test_offline_prediction_exchange import OfflineExchangeTests
        fixture=OfflineExchangeTests('test_valid_roundtrip')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.params['full_sample_count']=3
        job=__import__('drillmate_validation.offline_prediction_exchange',fromlist=['make_job']).make_job(**fixture.params)
        if 'tools.generate_full_section_predictions' not in sys.modules:
            stub = types.ModuleType('data_access.data_loader')
            stub.load_section_time_index = lambda *a, **k: None
            stub.load_sections_for_columns = lambda *a, **k: None
            with mockpatch.dict(sys.modules, {'data_access.data_loader': stub}):
                import tools.generate_full_section_predictions as runner
        else:
            import tools.generate_full_section_predictions as runner
        from drillmate_validation.offline_prediction_exchange import verify_prediction_file
        raw_df = pd.DataFrame({'x':[10.,20.,20.,30.]},index=self.times)
        calls=[]
        def fake_predict(**kw):
            calls.append(kw['full_df'].index)
            return []
        with mockpatch.dict(runner.generate.__globals__, {
                'load_section_time_index':lambda *a,**k: SimpleNamespace(index=self.times),
                'load_sections_for_columns':lambda *a,**k:raw_df.copy(),
                'verified_offline_keep_mask':lambda ix, unused:[True,True,False,True],
                'apply_cleaning_layer':lambda df, **kw:(df, {'TRQ':'x'},None),
                'calculate_continuous_predictions':fake_predict}):
            result=runner.generate(job,data_root=fixture.root)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].tolist(),self.times[[0,1,3]].tolist())
        self.assertEqual(result['sample_count'],3)
        self.assertEqual(len(result['prediction_segments']),1)
        self.assertEqual(len(verify_prediction_file(result, expected_job=job,
            full_time_index=self.times[[0,1,3]])[1]),1)

    def test_v2_manifest_must_not_be_accepted(self):
        from tests.test_offline_prediction_exchange import OfflineExchangeTests
        from drillmate_validation.offline_prediction_exchange import make_job, validate_job
        fixture=OfflineExchangeTests('test_valid_roundtrip'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job=make_job(**fixture.params)
        job['schema_version']=2
        with self.assertRaisesRegex(ValidationError,'Invalid offline'):
            validate_job(job,root=fixture.root)


if __name__=='__main__':
    unittest.main()
