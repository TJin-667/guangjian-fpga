"""Behavioral checks: coordinates, integer evidence, provenance and old reference."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np
import cv2

from capture_metrics import (FrameInput, FrameMetrics, build_common_area,
                             compare_repeats, compute_metrics, line_centers,
                             load_algorithm, source_identity)


ROOT = Path(r'D:\FPGA')


def frame(width=9, height=9, x=0, y=0, observation='one', **changes):
    values = dict(context_id='context', observation_id=observation, sample_id='board',
                  pose='A', exposure_lines=600, gain16=16, channel=1, led=128,
                  saved_width=width, saved_height=height, roi=(x, y, width, height),
                  png_sha256='a' * 64, rgb565_sha256='b' * 64,
                  source_mode='constructed_fixture', source_metadata={
                      'dataset_id': 'fixture', 'capture_id': observation,
                      'frame_id': 1, 'member': 'CH1.png'})
    values.update(changes)
    return FrameInput(**values)


class CaptureMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.algorithm = load_algorithm(ROOT / 'XDL_Algorithm/software',
                                       ROOT / 'XDL_Results/2026-10-13_manual_exposure_gain')

    def compute(self, image, mask=None, item=None):
        mask = np.ones(image.shape[:2], bool) if mask is None else mask
        item = frame(image.shape[1], image.shape[0]) if item is None else item
        area = build_common_area([item], [mask], sensor_shape=image.shape[:2])
        return compute_metrics(image, item, mask, area, self.algorithm), area

    def test_line_three_same_sign_no_wrap(self):
        residual = np.zeros((9, 9), dtype=np.int16)
        residual[4, 3:6] = 810
        found = line_centers(residual, np.ones((9, 9), dtype=bool))
        self.assertEqual(int(found.sum()), 1)
        self.assertTrue(found[4, 4])
        residual[:] = 0
        residual[4, [8, 0, 1]] = 810
        self.assertEqual(int(line_centers(residual, np.ones((9, 9), bool)).sum()), 0)

    def test_different_sign_not_line(self):
        residual = np.zeros((9, 9), np.int16)
        residual[4, 3:6] = [810, -810, 810]
        self.assertFalse(line_centers(residual, np.ones((9, 9), bool)).any())

    def test_four_directions_and_masked_neighbor(self):
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            with self.subTest(direction=(dy, dx)):
                residual = np.zeros((9, 9), np.int16)
                for offset in (-1, 0, 1):
                    residual[4 + offset * dy, 4 + offset * dx] = -810
                mask = np.ones((9, 9), bool)
                self.assertEqual(int(line_centers(residual, mask).sum()), 1)
                mask[4 + dy, 4 + dx] = False
                self.assertFalse(line_centers(residual, mask).any())

    def test_full_and_crop_same_full_coordinates(self):
        full, crop = frame(20, 20), frame(9, 9, 5, 7, 'two')
        full_mask = np.zeros((20, 20), bool)
        full_mask[7:16, 5:14] = True
        area = build_common_area([full, crop], [full_mask, np.ones((9, 9), bool)], (20, 20))
        self.assertEqual(int(area.mask.sum()), 81)
        self.assertTrue(area.mask[7:16, 5:14].all())
        self.assertFalse(area.mask[:7].any())
        self.assertEqual([c['native_area'] for c in area.coverage], [81, 81])

    def test_intersection_cannot_shrink_silently(self):
        first, second = frame(200, 100), frame(200, 100, observation='two')
        masks = [np.ones((100, 200), bool), np.ones((100, 200), bool)]
        masks[1][:, :20] = False
        area = build_common_area([first, second], masks, (100, 200))
        self.assertEqual(int(area.mask.sum()), 18000)
        self.assertFalse(area.available)
        self.assertIn('insufficient_native_coverage', area.reason_codes)

    def test_different_sample_cannot_form_common_area(self):
        with self.assertRaises(ValueError):
            build_common_area([frame(), frame(sample_id='other')], [np.ones((9, 9), bool)] * 2)

    def test_reflect_border_unchanged(self):
        (metrics, arrays), _ = self.compute(np.full((9, 9, 3), 128, np.uint8))
        self.assertTrue((arrays['sum9'] == 10368).all())
        self.assertTrue((arrays['residual_n'] == 0).all())
        self.assertEqual(metrics.gray_sum, 10368)
        image = np.zeros((9, 9, 3), np.uint8)
        image[0, 0] = 81
        (_, arrays), _ = self.compute(image)
        self.assertEqual(int(arrays['sum9'][0, 0]), 81)
        self.assertEqual(int(arrays['residual_n'][0, 0]), 6480)

    def test_strict_threshold_equality(self):
        residual = np.array([[-1621, -1620, -649, -648, 648, 649, 1620, 1621]], np.int16)
        weak, strong = self.algorithm['integer_thresholds'](residual)
        self.assertEqual(weak.tolist(), [[True, True, True, False, False, True, True, True]])
        self.assertEqual(strong.tolist(), [[True, False, False, False, False, False, False, True]])
        residual = np.full((9, 9), 648, np.int16)
        self.assertFalse(line_centers(residual, np.ones((9, 9), bool)).any())

    def test_rgbmax_is_counted_not_deleted(self):
        image = np.full((9, 9, 3), 100, np.uint8)
        # Integer gray is 209, a >20-gray strong seed above the 100 background.
        image[4, 3:6] = [255, 255, 100]
        (metrics, arrays), _ = self.compute(image)
        self.assertEqual(metrics.rgb_max_count, 3)
        self.assertTrue(arrays['baseline_mask'][4, 3:6].all())
        self.assertGreater(metrics.baseline_candidate_count, 0)

    def test_old_connection_keeps_support_outside_board(self):
        image = np.full((9, 9, 3), 100, np.uint8)
        image[4, 3:6] = [140, 130, 110]
        image[4, 2] = 255
        mask = np.zeros((9, 9), bool)
        mask[4, 3:6] = True
        (_, arrays), _ = self.compute(image, mask)
        self.assertTrue(arrays['baseline_mask'][4, 3:6].all())

    def test_zero_area_unavailable_and_json_has_no_nan(self):
        (metrics, _), area = self.compute(np.zeros((9, 9, 3), np.uint8), np.zeros((9, 9), bool))
        self.assertEqual(metrics.n, 0)
        self.assertFalse(area.available)
        self.assertFalse(metrics.geometry['available'])
        json.dumps(metrics.geometry, allow_nan=False)
        self.assertIsNone(metrics.controller_statistics['background_mean_n'])
        self.assertIsNone(metrics.controller_statistics['mean_gray'])

    def test_controller_summary_preserves_exact_means(self):
        (metrics, _), _ = self.compute(np.full((9, 9, 3), 128, np.uint8))
        self.assertEqual(metrics.controller_statistics['mean_gray'], {'numerator': 10368, 'denominator': 81})
        self.assertEqual(metrics.controller_statistics['background_mean_n'], {'numerator': 0, 'denominator': 81})
        self.assertNotIn('background_mean_n', metrics.native_reference_statistics)

    def test_repeat_gray_diff_and_metric_deltas_are_exact(self):
        items = [frame(100, 100), frame(100, 100, observation='two')]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 100))
        records = []
        for item, gray_value in zip(items, [128, 130]):
            metrics, arrays = compute_metrics(np.full((100, 100, 3), gray_value, np.uint8), item, mask, area, self.algorithm)
            records.append((item, metrics, arrays))
        pair = compare_repeats(records, area)['pairs'][0]
        self.assertEqual(pair['gray_abs_diff_sum'], 20000)
        self.assertEqual(pair['mean_gray_delta'], {'numerator': 200000000, 'denominator': 100000000})
        self.assertEqual(pair['effective_delta_bp'], {'numerator': 0, 'denominator': 100000000})
        self.assertEqual(pair['rgb_delta_bp'], {'numerator': 0, 'denominator': 100000000})

    def test_repeat_repackaging_same_capture_is_unavailable(self):
        one = frame(100, 100)
        two = replace(one, observation_id='renamed', source_metadata={**one.source_metadata, 'storage_root': 'D:/new'})
        mask = np.ones((100, 100), bool)
        area = build_common_area([one, two], [mask, mask], (100, 100))
        records = [(item, *compute_metrics(np.full((100, 100, 3), 128, np.uint8), item, mask, area, self.algorithm))
                   for item in [one, two]]
        self.assertIn('missing_or_duplicate_source_identity', compare_repeats(records, area)['reason_codes'])

    def test_repeat_relabelled_exposures_rejected_against_metric_trace(self):
        items = [frame(100, 100, exposure_lines=400),
                 frame(100, 100, observation='two', exposure_lines=500)]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 100))
        records = [(replace(item, exposure_lines=600),
                    *compute_metrics(np.full((100, 100, 3), 128, np.uint8), item, mask, area, self.algorithm))
                   for item in items]
        result = compare_repeats(records, area)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason_codes'], ['repeat_geometry_mismatch'])
        self.assertEqual(result['pairs'], [])

    def test_repeat_shifted_roi_rejected_before_remapping(self):
        items = [frame(100, 100), frame(100, 100, observation='two')]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 101))
        records = [(item, *compute_metrics(np.full((100, 100, 3), 128, np.uint8), item, mask, area, self.algorithm))
                   for item in items]
        shifted, metrics, arrays = records[1]
        records[1] = (replace(shifted, roi=(1, 0, 100, 100)), metrics, arrays)
        result = compare_repeats(records, area)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason_codes'], ['repeat_geometry_mismatch'])
        self.assertEqual(result['pairs'], [])

    def test_repeat_area_source_association_mismatch_rejected(self):
        items = [frame(100, 100), frame(100, 100, observation='two')]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 100))
        records = [(item, *compute_metrics(np.full((100, 100, 3), 128, np.uint8), item, mask, area, self.algorithm))
                   for item in items]
        unrelated = [frame(100, 100, observation='three'), frame(100, 100, observation='four')]
        other_area = build_common_area(unrelated, [mask, mask], (100, 100))
        result = compare_repeats(records, other_area)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason_codes'], ['repeat_geometry_mismatch'])
        self.assertEqual(result['pairs'], [])

    def test_repeat_relocated_source_metadata_remains_available(self):
        items = [frame(100, 100), frame(100, 100, observation='two')]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 100))
        records = [(replace(item, source_metadata={**item.source_metadata,
                                                  'storage_root': 'D:/relocated', 'png_path': 'D:/relocated/CH1.png'}),
                    *compute_metrics(np.full((100, 100, 3), 128, np.uint8), item, mask, area, self.algorithm))
                   for item in items]
        result = compare_repeats(records, area)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['pairs'][0]['gray_abs_diff_sum'], 0)

    def test_source_identity_survives_relocation_but_distinguishes_capture(self):
        one = frame()
        two = replace(one, observation_id='renamed', source_metadata={**one.source_metadata, 'storage_root': 'D:/elsewhere'})
        self.assertEqual(source_identity(one), source_identity(two))
        self.assertNotEqual(source_identity(one), source_identity(frame(observation='two')))
        metadata = dict(one.source_metadata)
        metadata.pop('capture_id')
        self.assertIsNone(source_identity(replace(one, source_metadata=metadata)))

    def test_metadata_and_mask_are_immutable(self):
        metadata = {'dataset_id': 'fixture', 'capture_id': 'one', 'frame_id': 1,
                    'member': 'a', 'nested': {'roi': [1, 2]}}
        item = frame(source_metadata=metadata)
        metadata['nested']['roi'][0] = 9
        self.assertEqual(item.source_metadata['nested']['roi'][0], 1)
        with self.assertRaises(TypeError):
            item.source_metadata['nested']['changed'] = True
        area = build_common_area([item], [np.ones((9, 9), bool)], (9, 9))
        with self.assertRaises(ValueError):
            area.mask[0, 0] = False
        with self.assertRaises(ValueError):
            area.mask.setflags(write=True)

    def test_invalid_input_types_and_roi(self):
        for changes in ({'exposure_lines': True}, {'saved_width': 8}, {'roi': (-1, 0, 9, 9)},
                        {'roi': (0, 0, 8, 9)}, {'png_sha256': 'bad'}, {'source_metadata': {'x': float('nan')}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                frame(**changes)
        with self.assertRaises(ValueError):
            line_centers(np.ones((9, 9), float), np.ones((9, 9), bool))

    def test_metrics_reject_impossible_gray_partitions_and_counts(self):
        (valid, _), _ = self.compute(np.full((9, 9, 3), 128, np.uint8))
        for changes in ({'gray_sum': 0}, {'dark_count': 81, 'near_white_count': 1},
                        {'effective_count': 80}, {'line_center_count': 1},
                        {'gray_sum': np.int64(10368)}, {'line_contrast_sum_n': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)

    def test_zero_union_iou_is_null(self):
        image = np.full((100, 100, 3), 128, np.uint8)
        records = []
        items = [frame(100, 100), frame(100, 100, observation='two')]
        mask = np.ones((100, 100), bool)
        area = build_common_area(items, [mask, mask], (100, 100))
        for item in items:
            metrics, arrays = compute_metrics(image, item, mask, area, self.algorithm)
            records.append((item, metrics, arrays))
        result = compare_repeats(records, area)
        self.assertEqual(result['status'], 'available')
        self.assertIsNone(result['pairs'][0]['line_iou'])
        self.assertIsNone(result['pairs'][0]['baseline_iou'])
        self.assertEqual(result['pairs'][0]['gray_abs_diff_sum'], 0)

    def test_different_sample_or_setting_not_repeat(self):
        image = np.full((100, 100, 3), 128, np.uint8)
        first = frame(100, 100)
        area = build_common_area([first], [np.ones((100, 100), bool)], (100, 100))
        metrics, arrays = compute_metrics(image, first, np.ones((100, 100), bool), area, self.algorithm)
        for changes in ({'sample_id': 'other'}, {'exposure_lines': 500}, {'pose': 'B'}, {'context_id': 'other'}):
            second = replace(first, observation_id='two', **changes)
            with self.subTest(changes=changes):
                result = compare_repeats([(first, metrics, arrays), (second, metrics, arrays)], area)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIn('not_same_condition_repeat', result['reason_codes'])

    def test_native_four_h1_h2_and_masks_match_pinned_reference(self):
        reference_root = ROOT / 'XDL_Results/2026-10-13_integer_reference_01'
        history_root = ROOT / 'XDL_Results/2026-10-13_manual_exposure_gain'
        manifest = json.loads((reference_root / 'reference_manifest.json').read_text(encoding='utf-8'))
        inputs = json.loads((history_root / 'analysis_inputs.json').read_text(encoding='utf-8'))
        golden = json.loads((history_root / 'golden_statistics.json').read_text(encoding='utf-8'))
        group_ids = ['E0400_G1', 'E0500_G1', 'E0600_G1', 'E0700_G1']
        selected = [next(r for r in manifest['frames'] if r['group_id'] == group and r['channel'] == 'CH1')
                    for group in group_ids]
        geometry = {r['group_id']: r for r in inputs['geometry_records']}
        frames, images, masks, archives = [], [], [], []
        for reference in selected:
            group = reference['group_id']
            row = next(r for r in inputs['index']['images'] if r['group_id'] == group and r['channel'] == 1)
            png = ROOT / 'YMW/YMW_manual_20261013' / reference['input_png']
            content = png.read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), row['png_sha256'])
            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            item = frame(row['width'], row['height'], row['roi_x'], row['roi_y'], group,
                         sample_id=row['specimen_id'], exposure_lines=row['exposure_lines'],
                         png_sha256=row['png_sha256'], rgb565_sha256=row['rgb565_sha256'],
                         source_mode='verified_real', source_metadata={
                             'dataset_id': manifest['data_commit'], 'capture_id': group,
                             'frame_id': row['frame_id'], 'member': row['zip_png_member'],
                             'mask_source': row['analysis_mask_source'],
                             'board_mask_needs_manual_review': reference['board_mask_needs_manual_review']})
            native = self.algorithm['board_mask'](image.shape[:2], geometry[group]['analysis_polygon'], item.roi[:2])
            npz_path = reference_root / reference['path']
            self.assertEqual(hashlib.sha256(npz_path.read_bytes()).hexdigest(), reference['sha256'])
            with np.load(npz_path, allow_pickle=False) as arrays:
                archives.append({key: arrays[key].copy() for key in arrays.files})
            frames.append(item)
            images.append(image)
            masks.append(native)
        area = build_common_area(frames, masks)
        self.assertTrue(area.available)
        for item, image, mask, old in zip(frames, images, masks, archives):
            with self.subTest(exposure=item.exposure_lines):
                metrics, arrays = compute_metrics(image, item, mask, area, self.algorithm)
                for key, expected in old.items():
                    np.testing.assert_array_equal(arrays[key], expected, err_msg=key)
                old_stats = next(r for r in golden['frames'] if r['group_id'] == item.observation_id and r['channel'] == 'CH1')
                for key in ('saved_frame_integer_statistics', 'board_integer_statistics'):
                    self.assertEqual(metrics.native_reference_statistics[key], old_stats[key])
                for point in old_stats['h2_samples']:
                    y, x = point['saved_y'], point['saved_x']
                    for key in ('gray', 'sum9', 'residual_n'):
                        self.assertEqual(int(arrays[key][y, x]), point[key])
                    self.assertEqual(bool(arrays['strong_raw'][y, x]), point['strong_t20'])
                self.assertEqual(metrics.n, int(area.mask.sum()))
                print('NATIVE_REFERENCE', item.exposure_lines, json.dumps({
                    'saved_shape': list(image.shape[:2]), 'common_n': metrics.n,
                    'native': dict(metrics.native_reference_statistics['board_integer_statistics']),
                    'common_gray_sum': metrics.gray_sum, 'arrays_exact': len(old),
                    'h2_samples_exact': len(old_stats['h2_samples'])}, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
