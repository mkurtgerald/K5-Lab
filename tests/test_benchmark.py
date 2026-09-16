import math
import unittest
import numpy as np
from mosaic_lab.benchmark import make_split, synthetic, scores, benchmark

class BenchmarkTests(unittest.TestCase):
    def test_deterministic_fixtures(self):
        a,b=synthetic(600,17);c,d=synthetic(600,17)
        np.testing.assert_array_equal(a,c);np.testing.assert_array_equal(b,d)
    def test_distinct_seed(self):
        a,_=synthetic(600,17);b,_=synthetic(600,18)
        self.assertFalse(np.array_equal(a,b))
    def test_chronological_disjoint_split(self):
        s=make_split(600)
        self.assertEqual((s.train.start,s.train.stop,s.validation.start,s.validation.stop,s.test.start,s.test.stop),(0,360,360,480,480,600))
    def test_small_input_rejected(self):
        with self.assertRaises(ValueError): make_split(10)
    def test_sample_budget(self):
        with self.assertRaises(ValueError): synthetic(50001)
    def test_invalid_predictions(self):
        for p in ([math.nan,.8], [-.1,.8], [.1,1.1], [.1]):
            with self.subTest(p=p),self.assertRaises(ValueError): scores(np.array([0,1]),p)
    def test_benchmark_reports_real_results(self):
        result=benchmark(size=600)
        selected=min(result["validation"],key=lambda n:(result["validation"][n]["log_loss"],n))
        self.assertEqual(result["selected_model"],selected)
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["saved_weights"])
        self.assertEqual(result["external_actions"],0)
        self.assertGreater(result["test"][selected]["balanced_accuracy"],.6)
