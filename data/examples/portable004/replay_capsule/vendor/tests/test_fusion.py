import importlib.util
import unittest

import numpy as np


class DualExposureB1Tests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('dual_exposure_b1.fusion'),
                             'dual exposure response fusion not implemented')
        from dual_exposure_b1 import fusion
        return fusion

    def arrays(self):
        return np.zeros((8, 12, 12), np.int16), np.ones((8, 12, 12), bool)

    def test_connects_across_exposures_and_directions_not_mask_union(self):
        f = self.api()
        r, v = self.arrays()
        r[0, 5, 2] = 1700
        r[1, 5, 3:5] = -900
        r[4, 5, 5:8] = 800
        result = f.fuse_two_stage(r, v)
        self.assertEqual(int(result['directions'][0]['mask'].sum()), 3)
        self.assertEqual(int(result['final']['mask'].sum()), 6)
        union = np.logical_or.reduce([f.maxabs_connect(r[i:i+1], v[i:i+1])['mask'] for i in range(8)])
        self.assertEqual(int(union.sum()), 1)

    def test_hierarchical_and_direct_signed_response_and_source_match(self):
        f = self.api()
        rng = np.random.default_rng(92)
        r = rng.integers(-20655, 20656, (8, 12, 12), dtype=np.int16)
        v = rng.random(r.shape) > .3
        r[:, 4, 4] = [2000, -2000, 2000, -2000, 2000, -2000, 2000, -2000]
        result = f.fuse_two_stage(r, v)
        direct = f.maxabs_connect(r, v, source_ids=np.arange(1, 9))
        for key in ('residual_n', 'source_frame', 'mask', 'weak', 'strong', 'unknown'):
            np.testing.assert_array_equal(result['final'][key], direct[key])

    def test_negative_tie_first_frame_and_invalid_winner(self):
        f = self.api()
        r, v = self.arrays()
        r[:, 5, 5] = [-1800, 1800, 1900, 1700, 0, 0, 0, 0]
        v[2, 5, 5] = False
        x = f.fuse_two_stage(r, v)['final']
        self.assertEqual(x['residual_n'][5, 5], -1800)
        self.assertEqual(x['source_frame'][5, 5], 1)
        v[0, 5, 5] = False
        self.assertEqual(f.fuse_two_stage(r, v)['final']['source_frame'][5, 5], 2)

    def test_thresholds_strict_and_unknown_zero_source(self):
        f = self.api()
        r, v = self.arrays()
        r[0, 5, 2:6] = [1620, 648, 1621, -649]
        v[:, 6, 6] = False
        x = f.fuse_two_stage(r, v)['final']
        self.assertFalse(x['strong'][5, 2])
        self.assertFalse(x['weak'][5, 3])
        self.assertTrue(x['mask'][5, 4])
        self.assertTrue(x['mask'][5, 5])
        self.assertTrue(x['unknown'][6, 6])
        self.assertEqual(x['source_frame'][6, 6], 0)
        self.assertEqual(x['residual_n'][6, 6], 0)
        self.assertEqual(x['source_frame'][0, 0], 1)

    def test_every_single_frame_and_low_high_b1_are_subsets(self):
        f = self.api()
        rng = np.random.default_rng(8)
        r = rng.integers(-2300, 2301, (8, 12, 12), dtype=np.int16)
        v = rng.random(r.shape) > .3
        original = r.copy()
        final = f.fuse_two_stage(r, v)['final']['mask']
        for ids in [[i] for i in range(8)] + [[0, 2, 4, 6], [1, 3, 5, 7]]:
            mask = f.maxabs_connect(r[ids], v[ids])['mask']
            self.assertFalse(np.any(mask & ~final))
        np.testing.assert_array_equal(r, original)

    def test_frozen_four_frame_b1_matches(self):
        f = self.api()
        from dual_exposure_b1.frozen_reference.fourlight_fusion.fusion import fuse
        rng = np.random.default_rng(4)
        r = rng.integers(-20655, 20656, (4, 12, 12), dtype=np.int16)
        v = rng.random(r.shape) > .2
        original = fuse(r, v, 'B1')
        actual = f.maxabs_connect(r, v)
        for a, b in (('residual_n', 'residual_n'), ('mask', 'mask'), ('source_frame', 'source_channel')):
            np.testing.assert_array_equal(actual[a], original[b])

    def test_board_applied_after_connection_and_does_not_change_response(self):
        f = self.api()
        r, v = self.arrays()
        r[0, 5, 2:7] = [1700, 900, 900, 900, 900]
        board = np.zeros((12, 12), bool)
        board[5, 5:7] = True
        a = f.fuse_two_stage(r, v)['final']
        b = f.fuse_two_stage(r, v, board=board)['final']
        self.assertEqual(int(b['mask'].sum()), 2)
        np.testing.assert_array_equal(a['residual_n'], b['residual_n'])
        np.testing.assert_array_equal(b['mask'], a['mask'] & board)

    def test_malformed_inputs_rejected(self):
        f = self.api()
        r, v = self.arrays()
        for bad_r, bad_v in ((r[:7], v[:7]), (r.astype(float), v), (r, v.astype(np.uint8))):
            with self.assertRaises(ValueError):
                f.fuse_two_stage(bad_r, bad_v)
        with self.assertRaises(ValueError):
            f.fuse_two_stage(r, v, board=np.ones((2, 2), bool))


if __name__ == '__main__':
    unittest.main()
