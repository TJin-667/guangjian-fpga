import copy
import unittest
import numpy as np
from priority import measure_gap, attach_scores, verify_frozen

BASE = {'gap': {'profile_flank': 2.5, 'raw_contrast': 1., 'thresholds': [5.2, 3.6, 3.2, 2.4, 2.]}}
CORE = {'ignore_gap_at_most_px': 6, 'large_gap_at_least_px': 16}

def fixture():
    board = np.ones((50, 90), bool)
    gray = np.full((8, 50, 90), 100, np.uint8)
    gray[3, 25, 10:61] = 90
    residual = np.zeros_like(gray, dtype='int32')
    residual[3, 25, 10:61] = -405
    path = [[x, 25] for x in range(10, 61)]
    run = dict(begin=5, end=35, length_px=31., start_xy=path[5], end_xy=path[35])
    gap = dict(id=1, review=True, facing_cosine=.95,
               selected_probe=dict(path_xy=path, review_weak_used=2.,
                                   best_fit=dict(frame=4, polarity=-1, exposure='high'),
                                   visual={'visual_runs': [run]}))
    return gap, gray, np.ones_like(gray, bool), board, residual

def score(x): return measure_gap(*x, BASE, CORE)

class PriorityTests(unittest.TestCase):
    def test_strong_raw_line_has_explicit_terms_and_no_probability(self):
        result = score(fixture())
        self.assertEqual(result['evidence_support_score'], 95)
        self.assertIsNone(result['confidence_probability'])
        self.assertFalse(result['automatic_pass'])
    def test_no_cross_frame_borrowing(self):
        x = fixture(); x[4][3] = 0; x[4][7, 25, 10:61] = -405
        self.assertEqual(score(x)['evidence_support_score'], 0)
    def test_no_cross_polarity_borrowing(self):
        x = fixture(); x[4][3] *= -1
        self.assertEqual(score(x)['counts']['joint'], 0)
    def test_only_largest_missing_run_measured(self):
        x = fixture(); x[1][3, 25, 15:46] = 100; x[4][3, 25, 15:46] = 0
        self.assertEqual(score(x)['counts']['joint'], 0)
        self.assertEqual(score(x)['largest_run']['samples'], 31)
    def test_parameter_fragility_lowers_score_without_removing_warning(self):
        x = fixture(); x[4][3, 25, 10:61] = -179
        self.assertGreater(score(x)['counts']['joint'], 0)
        self.assertEqual(score(x)['evidence_support_score'], 0)
    def test_invalid_samples_do_not_support(self):
        x = fixture(); x[2][3] = False
        self.assertEqual(score(x)['counts']['joint'], 0)
    def test_not_admitted_never_receives_score(self):
        x = fixture(); x[0]['review'] = False
        with self.assertRaises(ValueError): score(x)
    def test_microscopic_gap_refused(self):
        x = fixture(); x[0]['selected_probe']['visual']['visual_runs'][0]['length_px'] = 5
        with self.assertRaises(ValueError): score(x)
    def test_no_array_or_input_window_mutation(self):
        x = fixture(); old = [a.copy() for a in x[1:]]
        windows = [dict(id=9, x0=10, y0=20, x1=65, y1=30, gap_ids=[1], largest_visual_gap_px=31.)]
        before = copy.deepcopy(windows)
        result = attach_scores({'gaps': [x[0]]}, windows, *x[1:], BASE, CORE)
        self.assertEqual(windows, before)
        self.assertEqual(result['windows'][0]['id'], 9)
        for a, b in zip(x[1:], old): self.assertTrue(np.array_equal(a, b))
    def test_merged_window_uses_largest_gap_not_best_smaller_gap(self):
        x = fixture(); small = copy.deepcopy(x[0]); small['id'] = 2
        small['selected_probe']['visual']['visual_runs'][0].update(begin=40, end=49, length_px=10.)
        x[1][3, 25, 15:46] = 100; x[4][3, 25, 15:46] = 0
        windows = [dict(id=1, x0=5, y0=15, x1=70, y1=35, gap_ids=[1, 2], largest_visual_gap_px=31.)]
        result = attach_scores({'gaps': [x[0], small]}, windows, *x[1:], BASE, CORE)
        self.assertEqual(result['windows'][0]['representative_gap_id'], 1)
        self.assertEqual(result['windows'][0]['evidence_support_score'], 0)
    def test_empty_does_not_automatically_pass(self):
        x = fixture(); result = attach_scores({'gaps': []}, [], *x[1:], BASE, CORE)
        self.assertFalse(result['automatic_pass'])
        self.assertEqual(result['status'], 'NO_REVIEW_TRIGGER_IN_THIS_ROUTE')
    def test_invalid_real_frame_fails(self):
        x = fixture(); x[0]['selected_probe']['best_fit']['frame'] = 9
        with self.assertRaises(ValueError): score(x)
    def test_nan_path_fails(self):
        x = fixture(); x[0]['selected_probe']['path_xy'][8][0] = float('nan')
        with self.assertRaises(ValueError): score(x)
    def test_frozen_dependency_tampering_is_not_empty_result(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/'rules').write_text('altered')
            with self.assertRaisesRegex(ValueError, 'FROZEN_REVIEW_DEPENDENCY_CHANGED'):
                verify_frozen({'files_sha256': {'rules': '0' * 64}}, root)

if __name__ == '__main__': unittest.main(verbosity=2)
