"""Literal regressions for final-review I1–I4; no hardware or mock detector."""
from dataclasses import asdict
from pathlib import Path
import unittest

import numpy as np

from acquisition_control import CaptureEvent, Controller, ControllerConfig
from capture_metrics import build_common_area, compute_metrics, load_algorithm
from fixtures import make_frame, make_metrics, geometry_for
from fpga_reference import reference_transition
from replay import canonical, replay_sequence, _sensitivity_records


def observation(identity, mean=100, rgb=0):
    frame = make_frame(observation_id=identity, source_metadata=dict(
        dataset_id='final-fix', capture_id=identity, frame_id=identity, member=identity+'.png'))
    metric = make_metrics(gray_sum=mean*10000, rgb_max_count=rgb, geometry=geometry_for(frame))
    return frame, CaptureEvent('observation', 'scan_A', identity, 600, metric, None)


class FinalTransitionRegressionTests(unittest.TestCase):
    maxDiff = None

    def history(self, events, checkpoints, config=None):
        primary = Controller(config or ControllerConfig(), 'scan_A')
        state = canonical(asdict(primary.snapshot()))
        cfg = canonical(asdict(primary.config))
        answers = []
        for index, event in enumerate([{'kind': 'start'}] + events):
            serialized = event if isinstance(event, dict) else canonical(asdict(event))
            expected_state, expected_decision = reference_transition(state, serialized, cfg)
            decision = primary.start() if index == 0 else primary.feed(event)
            state, answer = canonical(asdict(primary.snapshot())), canonical(asdict(decision))
            # Every serialized field, including histories and all budget axes.
            self.assertEqual(expected_state, state)
            self.assertEqual(expected_decision, answer)
            status, action, requested, consumed, count, fallback = checkpoints[index]
            self.assertEqual((answer['status'], answer['action_kind']), (status, action))
            self.assertEqual(state['confirmation_count'], count)
            self.assertEqual(state['fallback_used'], fallback)
            for record, costs in ((state['requested_cost'], requested), (state['consumed_cost'], consumed)):
                self.assertEqual(record, dict(zip(('attempts', 'frames', 'time_ms'), costs)))
            self.assertEqual(state['unfulfilled_cost'], dict(attempts=0, frames=0, time_ms=0))
            self.assertEqual(answer['budget']['reserved_cost'], dict(
                attempts=requested[0]-consumed[0], frames=requested[1]-consumed[1],
                time_ms=requested[2]-consumed[2]))
            answers.append((state, answer))
        return answers

    # Break caught: qualified history incorrectly grants another acquisition-error fallback.
    def test_qualified_then_two_errors_stops_without_extra_fallback(self):
        error = CaptureEvent('capture_error', 'scan_A', None, 600, None, 'timeout')
        result = self.history([observation('a')[1], error, error], [
            ('CONTINUE_ADJUST', 'set_exposure', (1,4,5000), (0,0,0), 0, False),
            ('CONTINUE_ADJUST', 'confirm_current', (2,8,10000), (1,4,5000), 1, False),
            ('CONTINUE_ADJUST', 'retry_current', (3,12,15000), (2,8,10000), 0, False),
            ('CAPTURE_FAILED', 'stop', (3,12,15000), (3,12,15000), 0, False)])
        state, decision = result[-1]
        self.assertEqual(decision['reason_codes'], ['capture_error', 'retry_exhausted'])
        self.assertEqual(decision['input_statistics'], None)
        self.assertEqual(state['confirmation_reference'], None)
        self.assertEqual(state['pending_request'], None)
        self.assertEqual(len(state['qualified']), 1)
        self.assertEqual(state['retry_count'], {'400':0, '500':0, '600':1, '700':0})

    # Break caught: a second unstable confirmation erases terminal historical reference.
    def test_second_unstable_confirmation_keeps_terminal_history(self):
        result = self.history([observation('a')[1], observation('b', 103)[1],
                               observation('c')[1], observation('d', 103)[1]], [
            ('CONTINUE_ADJUST', 'set_exposure', (1,4,5000), (0,0,0), 0, False),
            ('CONTINUE_ADJUST', 'confirm_current', (2,8,10000), (1,4,5000), 1, False),
            ('CONTINUE_ADJUST', 'fallback_confirm', (3,12,15000), (2,8,10000), 0, True),
            ('CONTINUE_ADJUST', 'confirm_current', (4,16,20000), (3,12,15000), 1, True),
            ('NEEDS_REVIEW', 'stop', (4,16,20000), (4,16,20000), 1, True)])
        state, decision = result[-1]
        self.assertEqual(decision['reason_codes'], ['confirmation_unstable', 'fallback_exhausted'])
        self.assertEqual(state['confirmation_reference']['geometry']['observation_id'], 'c')
        self.assertEqual(state['pending_request'], None)
        self.assertEqual([q['geometry']['observation_id'] for q in state['qualified']], ['a','b','c','d'])

    # Break caught: refused first fallback retains active confirmation despite fallback reset contract.
    def test_unstable_fallback_budget_stop_clears_confirmation_before_reservation(self):
        result = self.history([observation('a')[1], observation('b', 103)[1]], [
            ('CONTINUE_ADJUST', 'set_exposure', (1,4,5000), (0,0,0), 0, False),
            ('CONTINUE_ADJUST', 'confirm_current', (2,8,10000), (1,4,5000), 1, False),
            ('NEEDS_REVIEW', 'stop', (2,8,10000), (2,8,10000), 0, True)],
            ControllerConfig(max_attempts=2))
        self.assertIsNone(result[-1][0]['confirmation_reference'])
        self.assertEqual(result[-1][1]['reason_codes'],
            ['confirmation_unstable','fresh_fallback_confirmation_required','budget_exhausted'])


class EmptyGeometryRegressionTests(unittest.TestCase):
    # Break caught: real producer null denominator crashes verified metric-to-replay.
    def test_actual_empty_native_mask_returns_review_with_null_ratios(self):
        algorithm = load_algorithm(Path(r'D:\FPGA\XDL_Algorithm\software'),
                                   Path(r'D:\FPGA\XDL_Results\2026-10-13_manual_exposure_gain'))
        frame = make_frame(source_mode='synthetic_image', source_metadata=dict(
            dataset_id='final-fix', capture_id='empty', frame_id='empty', member='empty.png',
            mask_source='synthetic_empty_native', board_mask_needs_manual_review=True))
        mask = np.zeros((100,100), bool)
        area = build_common_area([frame], [mask], sensor_shape=(100,100))
        metric, arrays = compute_metrics(np.full((100,100,3), 100, np.uint8), frame, mask, area, algorithm)
        self.assertIsNone(metric.geometry['coverage_denominator'])
        self.assertEqual(metric.n, 0)
        result = replay_sequence([frame], ControllerConfig(), lambda _: (metric, arrays))
        self.assertEqual(result['decision_reference_verification'], dict(passed=True, checked=2, mismatches=[]))
        decision = result['final_decision']
        self.assertEqual((decision['status'], decision['action_kind'], decision['next_exposure_lines']),
                         ('NEEDS_REVIEW','stop',None))
        self.assertEqual(decision['reason_codes'], ['insufficient_common_area','insufficient_native_coverage',
            'geometry_unavailable','geometry_inconsistent','insufficient_common_coverage','insufficient_effective_area'])
        stats = decision['input_statistics']
        self.assertIsNone(stats['mean_gray'])
        self.assertIsNone(stats['background_mean_n'])
        self.assertIsNone(stats['geometry']['coverage_denominator'])
        cost = dict(attempts=1, frames=4, time_ms=5000)
        self.assertEqual(decision['budget']['requested_cost'], cost)
        self.assertEqual(decision['budget']['consumed_cost'], cost)
        for key in ('reserved_cost', 'unfulfilled_cost'):
            self.assertEqual(decision['budget'][key], dict(attempts=0,frames=0,time_ms=0))
        self.assertIsNone(result['measured_live_control_cost'])

    # Break caught: nullable denominator handling also accepts malformed numeric geometry.
    def test_available_geometry_rejects_malformed_coverage_denominator(self):
        frame, event = observation('a')
        controller = Controller(ControllerConfig(), frame.context_id)
        controller.start()
        state = canonical(asdict(controller.snapshot()))
        for value in (-1, True, '10000', 10000.0):
            with self.subTest(value=value):
                raw = canonical(asdict(event))
                raw['metrics']['geometry']['coverage_denominator'] = value
                with self.assertRaises(ValueError):
                    reference_transition(state, raw, canonical(asdict(controller.config)))


class ConfigurationDomainRegressionTests(unittest.TestCase):
    # Break caught: standalone oracle permits unsupported version, geometry, cost or types.
    def test_literal_invalid_configurations_reject_in_both_interfaces(self):
        cfg = canonical(asdict(ControllerConfig()))
        state = canonical(asdict(Controller(ControllerConfig(), 'scan_A').snapshot()))
        vectors = [('rule_version','unsupported-rule'), ('threshold_status','stable'),
            ('cost_status','measured'), ('channel',2), ('channel',True), ('led',127), ('gain16',17),
            ('discard_frames_per_request',0), ('exposures',[400.0,500.0,600.0,700.0]),
            ('exposures',[400,500,600,701]), ('initial_exposure_lines',600.0),
            ('initial_exposure_lines',300), ('min_area',9999), ('min_area',1),
            ('min_coverage_bp',9499), ('min_coverage_bp',0), ('min_coverage_bp',10001),
            ('confirmations',1), ('max_mean_delta_gray',256), ('max_attempts',0),
            ('max_attempts',9), ('max_frames',0), ('max_frames',33), ('max_time_ms',0),
            ('max_time_ms',40001), ('frame_time_ms',0), ('settle_time_ms',-1),
            ('retry_limit',-1), ('retry_limit',2), ('rgb_review_bp',499)]
        for name in ('min_effective_bp','max_dark_bp','max_near_white_bp','rgb_warn_bp',
                     'rgb_review_bp','max_effective_delta_bp','max_rgb_delta_bp'):
            vectors.extend([(name,-1), (name,10001), (name,True), (name,0.0)])
        for name in ('min_area','min_coverage_bp','confirmations','max_mean_delta_gray',
                     'max_attempts','max_frames','max_time_ms','frame_time_ms','settle_time_ms','retry_limit'):
            vectors.extend([(name,True), (name,1.0)])
        for name, value in vectors:
            with self.subTest(name=name, value=value):
                payload = {**cfg, name:value}
                with self.assertRaises(ValueError):
                    ControllerConfig.from_dict(payload)
                with self.assertRaises(ValueError):
                    reference_transition(state, {'kind':'start'}, payload)

    # Break caught: parity fix rejects valid exact bounds and configurable timing.
    def test_literal_valid_boundaries_start_with_equal_complete_outputs(self):
        vectors = [dict(min_area=10000,min_coverage_bp=9500), dict(min_area=10001,min_coverage_bp=10000),
            dict(min_effective_bp=0,max_dark_bp=0,max_near_white_bp=0,rgb_warn_bp=0,rgb_review_bp=0,
                 max_effective_delta_bp=0,max_rgb_delta_bp=0,max_mean_delta_gray=0),
            dict(min_effective_bp=10000,max_dark_bp=10000,max_near_white_bp=10000,rgb_warn_bp=10000,
                 rgb_review_bp=10000,max_effective_delta_bp=10000,max_rgb_delta_bp=10000,max_mean_delta_gray=255),
            dict(confirmations=2,retry_limit=0,frame_time_ms=1,settle_time_ms=0),
            dict(confirmations=9,retry_limit=1,frame_time_ms=10001,settle_time_ms=40001),
            dict(max_attempts=1,max_frames=1,max_time_ms=1),
            dict(max_attempts=8,max_frames=32,max_time_ms=40000)]
        vectors.extend(dict(initial_exposure_lines=e) for e in (400,500,600,700))
        for changes in vectors:
            with self.subTest(changes=changes):
                cfg = ControllerConfig(**changes)
                primary = Controller(cfg, 'scan_A')
                state = canonical(asdict(primary.snapshot()))
                expected = reference_transition(state, {'kind':'start'}, canonical(asdict(cfg)))
                decision = primary.start()
                self.assertEqual(expected, (canonical(asdict(primary.snapshot())), canonical(asdict(decision))))


class SensitivityRegressionTests(unittest.TestCase):
    # Break caught: warn800 invalidates low review500 and baseline is silently raised.
    def test_low_review_threshold_has_separate_valid_sweep_floor(self):
        frame, event = observation('risk', rgb=600)
        cfg = ControllerConfig(rgb_warn_bp=300, rgb_review_bp=500)
        before = canonical(asdict(cfg))
        baseline = replay_sequence([frame], cfg, lambda _: (event.metrics, {}))
        runs = _sensitivity_records([frame], cfg, [dict(frame=frame,metrics=event.metrics,arrays={})])
        self.assertEqual(len(runs), 9)
        self.assertEqual(canonical(asdict(cfg)), before)
        self.assertEqual(baseline['decisions'][1]['decision']['reason_codes'], ['rgb_risk_warning','rgb_high_risk'])
        for run in runs:
            self.assertEqual(run['requested_rgb_review_bp'], 500)
            self.assertEqual(run['sensitivity_rgb_review_bp'], 800)
            self.assertTrue(run['sensitivity_review_threshold_adjusted'])
            self.assertEqual(run['baseline_config'], before)
            self.assertIn('rgb_review_bp', run['baseline_comparison']['changed_config_fields'])
            self.assertTrue(run['baseline_comparison']['rgb_review_bp_differs'])
            self.assertEqual(run['baseline_actions'], [[r['decision'][k] for k in
                ('status','action_kind','next_exposure_lines','reason_codes')] for r in baseline['decisions']])
            self.assertEqual(ControllerConfig.from_dict(run['config']).rgb_review_bp, 800)
            self.assertTrue(run['decision_reference_verification']['passed'])

    # Break caught: floor inadvertently changes default suite review threshold/inventory.
    def test_default_sweep_keeps_review1000_and_nine_variants(self):
        frame, event = observation('a')
        runs = _sensitivity_records([frame], ControllerConfig(), [dict(frame=frame,metrics=event.metrics,arrays={})])
        self.assertEqual([(r['config']['min_effective_bp'], r['config']['rgb_warn_bp']) for r in runs],
            [(8500,300),(8500,500),(8500,800),(9000,300),(9000,500),(9000,800),(9500,300),(9500,500),(9500,800)])
        for run in runs:
            self.assertEqual(run['config']['rgb_review_bp'], 1000)
            self.assertEqual(run['requested_rgb_review_bp'], 1000)
            self.assertEqual(run['sensitivity_rgb_review_bp'], 1000)
            self.assertFalse(run['sensitivity_review_threshold_adjusted'])
            self.assertFalse(run['baseline_comparison']['rgb_review_bp_differs'])


if __name__ == '__main__':
    unittest.main()
