"""Replay breaks: future leakage, reused captures, lost costs and false evidence."""
import contextlib
import io
import json
import tempfile
import unittest
import numpy as np
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from acquisition_control import ControllerConfig
from fixtures import make_frame, make_metrics, geometry_for
try:
    import replay
except ImportError:
    replay = None


def fresh(identity, **changes):
    return make_frame(observation_id=identity, source_metadata={
        'dataset_id': 'fixture', 'capture_id': identity, 'frame_id': identity,
        'member': identity + '.png'}, **changes)


def evaluate(frame):
    return make_metrics(geometry=geometry_for(frame)), {}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(replay, 'replay feature is missing')

    def test_scan_missing_confirm_not_reused(self):
        result = replay.replay_sequence([make_frame()], ControllerConfig(), lambda frame: (make_metrics(), {}))
        self.assertEqual(result['final_decision']['status'], 'NEEDS_REVIEW')
        self.assertIn('missing_fresh_confirmation', result['final_decision']['reason_codes'])
        self.assertEqual(len(result['consumed_observation_ids']), 1)

    def test_unseen_future_metrics_cannot_change_action(self):
        frames = [fresh('first'), fresh('future', exposure_lines=700)]
        def unreachable(frame):
            if frame.observation_id == 'future':
                raise AssertionError('unrequested future was evaluated')
            return evaluate(frame)
        result = replay.replay_sequence(frames, ControllerConfig(), unreachable)
        self.assertEqual(result['consumed_observation_ids'], ['first'])
        self.assertEqual(result['decisions'][1]['decision']['action_kind'], 'confirm_current')

    def test_repeat_not_scan_confirmation(self):
        with self.assertRaises(ValueError):
            replay.replay_sequence([fresh('scan'), fresh('repeat', context_id='repeat_001')], ControllerConfig(), evaluate)

    def test_duplicate_source_is_not_fresh_confirmation(self):
        one = fresh('one')
        with self.assertRaises(ValueError):
            replay.replay_sequence([one, replace(one, observation_id='renamed')], ControllerConfig(), evaluate)

    def test_terminal_does_not_feed_third_repeat(self):
        result = replay.replay_sequence([fresh(str(i)) for i in range(3)], ControllerConfig(), evaluate)
        self.assertEqual(result['final_decision']['status'], 'LOCKED')
        self.assertEqual(result['consumed_observation_ids'], ['0', '1'])

    def test_three_cost_categories_separate(self):
        result = replay.replay_sequence([fresh('one')], ControllerConfig(), evaluate)
        self.assertIsNone(result['historical_capture_cost'])
        self.assertIsNone(result['measured_live_control_cost'])
        self.assertEqual(result['modeled_control_cost']['requested_cost'], {'attempts': 2, 'frames': 8, 'time_ms': 10000})
        self.assertEqual(result['modeled_control_cost']['consumed_cost'], {'attempts': 1, 'frames': 4, 'time_ms': 5000})
        self.assertEqual(result['modeled_control_cost']['unfulfilled_cost'], {'attempts': 1, 'frames': 4, 'time_ms': 5000})

    def test_modeled_time_not_walltime(self):
        with patch.object(replay, 'perf_counter', side_effect=[10.0, 30.0]):
            result = replay.replay_sequence([fresh('one')], ControllerConfig(), evaluate)
        self.assertEqual(result['compute_walltime_ms'], 20000)
        self.assertEqual(result['modeled_control_cost']['consumed_cost']['time_ms'], 5000)

    def test_log_reconstructs_requested_consumed_pending(self):
        result = replay.replay_sequence([fresh('one')], ControllerConfig(), evaluate)
        for row in result['decisions']:
            self.assertIn('risk_seen', row['state'])
            self.assertIn('condition_identity', row['state'])
            budget = row['decision']['budget']
            for key in ('attempts', 'frames', 'time_ms'):
                self.assertEqual(budget['requested_cost'][key], sum(budget[c][key] for c in ('consumed_cost', 'reserved_cost', 'unfulfilled_cost')))
        self.assertTrue(result['decision_reference_verification']['passed'])
        self.assertEqual(result['decision_reference_verification']['checked'], 3)

    def test_partial_evidence_not_passed(self):
        self.assertFalse(replay.verification_status({'decision_reference': {'passed': True}})['offline_verified'])
        self.assertFalse(replay.replay_sequence([fresh('one')], ControllerConfig(), evaluate)['offline_verified'])

    def test_nonempty_but_incomplete_evidence_not_passed(self):
        evidence = {k: {'passed': True, 'checked': 1} for k in ('source_integrity', 'scalar_statistics',
                    'native_reference', 'decision_reference', 'constructed_actions', 'golden_inventory', 'repeat_stability')}
        self.assertFalse(replay.verification_status(evidence)['offline_verified'])

    def test_cli_output_must_stay_in_results_root(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(replay.main(['--output', str(Path(folder)/'2026-10-14_software_controller_10')]), 0)

    def test_output_existing_or_inside_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            output = base / '2026-10-14_software_controller_10'
            output.mkdir()
            with self.assertRaises(ValueError): replay.write_run(output, {})
            source = base / 'inputs'; source.mkdir()
            with self.assertRaises(ValueError): replay.write_run(source / '2026-10-14_software_controller_10', {'input_roots': [str(source)]})

    def test_json_nan_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / '2026-10-14_software_controller_10'
            with self.assertRaises(ValueError): replay.write_run(output, {'config': {'bad': float('nan')}})
            self.assertFalse(output.exists())

    def test_bad_cli_nonzero(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(replay.main(['--unknown']), 0)

    def test_constructed_golden_inventory_and_rejections(self):
        cases, actual = replay.constructed_validation()
        self.assertEqual(len(cases), 42)
        self.assertEqual(len({c['scenario_id'] for c in cases}), 15)
        self.assertEqual({c['scenario_id'] for c in cases if c.get('expected_validation_error')}, {'duplicate_identity', 'wrong_context', 'terminal_rejection', 'different_sample'})
        self.assertTrue(replay.verify_reference(cases, actual)['passed'])
        with self.assertRaises(ValueError): replay.require_golden_inventory(cases[:-3])

    def test_write_strict_logs_and_independent_golden(self):
        cases, actual = replay.constructed_validation()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / '2026-10-14_software_controller_10'
            replay.write_run(output, {'config': asdict(ControllerConfig()), 'golden_cases': cases,
                                     'frame_metrics': [], 'decisions': [], 'repeat_stability': [],
                                     'provenance': {}, 'verification': {'offline_verified': False}})
            self.assertEqual(len(json.loads((output/'golden_actions.json').read_text())['cases']), 42)
            for stem in ('frame_metrics', 'decisions', 'repeat_stability'):
                self.assertTrue((output/(stem+'.csv')).is_file())
                self.assertTrue((output/(stem+'.json')).is_file())

    def test_partial_evidence_cannot_set_exported_golden_verified(self):
        cases, _ = replay.constructed_validation()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'2026-10-14_software_controller_10'
            replay.write_run(output, {'golden_cases': cases, 'verification': {'offline_verified': False}})
            self.assertFalse(json.loads((output/'golden_actions.json').read_text())['offline_verified'])

    def test_sensitivity_all_nine_configs_use_own_reference(self):
        frames = [fresh('one')]
        records = [dict(frame=frames[0], metrics=evaluate(frames[0])[0], arrays={})]
        with patch.object(replay, '_study_records', return_value=(records, None)):
            runs = replay.sensitivity_runs(frames, ControllerConfig(), {})
        self.assertEqual({(r['config']['min_effective_bp'], r['config']['rgb_warn_bp']) for r in runs},
                         {(a, b) for a in (8500, 9000, 9500) for b in (300, 500, 800)})
        self.assertEqual(len(runs), 9)
        self.assertTrue(all(r['decision_reference_verification']['passed'] for r in runs))
        self.assertTrue(all(c['config'] == r['config'] for r in runs for c in r['golden_cases']))

    def test_real_metric_pipeline_diagnostics_all_three_controller_only_two(self):
        base = Path(__file__).resolve().parents[2]
        algorithm = replay.load_algorithm(base/'XDL_Algorithm/software', base/'XDL_Results/2026-10-13_manual_exposure_gain')
        frames = [fresh(str(i), context_id='repeat_001', pose='repeat_001', source_mode='synthetic_image',
                        saved_width=140, saved_height=140, roi=(0, 0, 140, 140)) for i in range(3)]
        frames = [replace(f, source_metadata={**f.source_metadata, 'analysis_polygon': [(0,0),(139,0),(139,139),(0,139)],
                                             'board_mask_needs_manual_review': True, 'mask_source': 'synthetic polygon'}) for f in frames]
        with patch.object(replay, 'read_frame', return_value=np.full((140,140,3), 128, np.uint8)):
            result = replay.run_repeat_study(frames, ControllerConfig(), algorithm)
            scan = replay.run_scan(frames, ControllerConfig(), algorithm)
        self.assertEqual(result['source_type'], 'synthetic_image')
        self.assertEqual(result['consumed_observation_ids'], ['0','1'])
        self.assertEqual(len(result['frame_metrics']), 3)
        self.assertEqual(len(result['repeat_stability']['pairs']), 3)
        self.assertTrue(all(r['scalar_verification']['passed'] and r['native_verification']['passed'] for r in result['frame_metrics']))
        self.assertEqual(len(scan['sensitivity']), 9)
        self.assertTrue(result['evaluation_area']['manual_review_pending'])

    def test_corrupted_preserved_native_quality_label_is_detected(self):
        base = Path(__file__).resolve().parents[2]
        algorithm = replay.load_algorithm(base/'XDL_Algorithm/software', base/'XDL_Results/2026-10-13_manual_exposure_gain')
        frame = fresh('one', source_mode='synthetic_image', saved_width=140, saved_height=140, roi=(0,0,140,140))
        frame = replace(frame, source_metadata={**frame.source_metadata, 'analysis_polygon': [(0,0),(139,0),(139,139),(0,139)],
                                               'board_mask_needs_manual_review': True, 'mask_source': 'synthetic'})
        real_compute = replay.compute_metrics
        def corrupted(*args):
            metrics, arrays = real_compute(*args)
            return replace(metrics, native_reference_statistics={**metrics.native_reference_statistics, 'quality_status': 'corrupted'}), arrays
        with patch.object(replay, 'read_frame', return_value=np.full((140,140,3),128,np.uint8)), patch.object(replay, 'compute_metrics', side_effect=corrupted):
            result = replay.run_scan([frame], ControllerConfig(), algorithm)
        self.assertFalse(result['frame_metrics'][0]['native_verification']['passed'])


if __name__ == '__main__': unittest.main()
