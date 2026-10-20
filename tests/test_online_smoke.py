"""Test the exact backend function exposed by the opt-in online smoke-test button."""
import unittest
from drillmate_validation.smoke_test import run_builtin_validation_selftest

class OnlineSmokeTests(unittest.TestCase):
    def test_examples_use_production_engines(self):
        result = run_builtin_validation_selftest()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual((result['symptom']['TP'],result['symptom']['FP'],result['symptom']['FN']), (1,1,0))
        self.assertAlmostEqual(result['activity']['time_weighted_accuracy'],11/12)

if __name__=='__main__':
    unittest.main()
