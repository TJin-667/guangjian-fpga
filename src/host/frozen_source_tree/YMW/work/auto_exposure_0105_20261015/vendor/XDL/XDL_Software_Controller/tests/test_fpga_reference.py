"""Independent hand-count and action vectors, with complete primary comparisons."""
from dataclasses import asdict
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from acquisition_control import Controller, ControllerConfig, CaptureEvent, better_setting
from capture_metrics import line_centers, load_algorithm
from fixtures import make_frame, make_metrics, geometry_for


def canonical(value):
    return json.loads(json.dumps(value, allow_nan=False))


def config(**changes):
    values = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text(encoding='utf-8'))
    values.update(changes)
    return values


def observation(identity, exposure=600, **changes):
    n = changes.get('n', 10000)
    item = make_frame(observation_id=identity, exposure_lines=exposure,
                      saved_width=500, saved_height=500, roi=(0, 0, 500, 500),
                      source_metadata=dict(dataset_id='fixture-dataset', capture_id=identity,
                                           frame_id=identity, member=identity + '.png'))
    geometry = geometry_for(item)
    geometry.update(native_area=n, common_area=n, coverage_numerator=n,
                    coverage_denominator=n)
    values = dict(n=n, gray_sum=100*n, effective_count=n, background_count=n,
                  geometry=geometry)
    values.update(changes)
    return CaptureEvent('observation', 'scan_A', identity, exposure, make_metrics(**values), None)


class ScalarReferenceTests(unittest.TestCase):
    # Break caught: counting every weak point instead of three-point centers.
    def test_scalar_matches_hand_count(self):
        from fpga_reference import scalar_metric_reference
        gray = np.full((9, 9), 128, dtype=np.uint8)
        residual = np.zeros((9, 9), dtype=np.int16)
        residual[4, 3:6] = 810
        values = scalar_metric_reference(gray, residual, np.zeros((9, 9), bool),
                                         np.ones((9, 9), bool))
        self.assertEqual(values['line_center_count'], 1)
        self.assertEqual(values['line_contrast_sum_n'], 810)
        self.assertEqual(values['background_count'], 80)
        self.assertEqual(values['background_activity_sum_n'], 1620)

    # Break caught: >=648, sign mixing, wrapped edges or masked witnesses.
    def test_scalar_strict_sign_mask_and_no_wrap(self):
        from fpga_reference import scalar_metric_reference
        gray = np.full((9, 9), 10, np.uint8)
        mask = np.ones((9, 9), bool)
        residual = np.zeros((9, 9), np.int16)
        for values, expected in [([648, 648, 648], 0), ([649, -649, 649], 0),
                                  ([-649, -649, -649], 1)]:
            residual[:] = 0
            residual[4, 3:6] = values
            got = scalar_metric_reference(gray, residual, mask, mask)
            self.assertEqual(got['line_center_count'], expected)
        mask[4, 5] = False
        self.assertEqual(scalar_metric_reference(gray, residual, mask, mask)['line_center_count'], 0)
        mask[:] = True
        residual[:] = 0
        residual[4, [8, 0, 1]] = 649
        self.assertEqual(scalar_metric_reference(gray, residual, mask, mask)['line_center_count'], 0)

    # Break caught: directional omission and narrowed accumulation on frozen H2.
    def test_vector_scalar_random_masks(self):
        from fpga_reference import scalar_metric_reference
        algorithm = load_algorithm(Path(r'D:\FPGA\XDL_Algorithm\software'),
                                   Path(r'D:\FPGA\XDL_Results\2026-10-13_manual_exposure_gain'))
        rng = np.random.default_rng(417)
        for _ in range(12):
            image = rng.integers(0, 256, (17, 19, 3), dtype=np.uint8)
            gray = algorithm['integer_gray'](image)
            residual = algorithm['integer_h2'](gray)['residual_n']
            mask = rng.random(gray.shape) > .2
            rgb = (image == 255).any(axis=2)
            got = scalar_metric_reference(gray, residual, rgb, mask)
            centers = line_centers(residual, mask)
            background = mask & ~centers
            expected = dict(n=int(mask.sum()), gray_sum=int(gray[mask].astype(np.uint64).sum()),
                            dark_count=int((mask & (gray <= 10)).sum()),
                            near_white_count=int((mask & (gray >= 250)).sum()),
                            rgb_max_count=int((mask & rgb).sum()),
                            effective_count=int((mask & ((gray > 10) | (np.abs(residual.astype(np.int64)) > 648))).sum()),
                            line_center_count=int(centers.sum()),
                            line_contrast_sum_n=int(np.abs(residual.astype(np.int64))[centers].sum()),
                            background_count=int(background.sum()),
                            background_activity_sum_n=int(np.abs(residual.astype(np.int64))[background].sum()))
            self.assertEqual(got, expected)

    # Break caught: accepting non-integer/overflowed or shape-mismatched inputs.
    def test_scalar_rejects_invalid_inputs_and_zero_is_exact(self):
        from fpga_reference import scalar_metric_reference
        gray = np.zeros((9, 9), np.uint8)
        residual = np.zeros((9, 9), np.int16)
        mask = np.zeros((9, 9), bool)
        self.assertTrue(all(value == 0 for value in scalar_metric_reference(gray, residual, mask, mask).values()))
        for args in [(gray.astype(float), residual, mask, mask),
                     (gray, residual, mask[:-1], mask),
                     (gray, np.full((9, 9), 20401, np.int32), mask, mask)]:
            with self.assertRaises(ValueError):
                scalar_metric_reference(*args)


class ActionReferenceTests(unittest.TestCase):
    maxDiff = None
    def replay(self, events, cfg=None, wants=None):
        from fpga_reference import reference_transition, verify_reference
        cfg = config() if cfg is None else cfg
        primary = Controller(ControllerConfig(**{**cfg, 'exposures': tuple(cfg['exposures'])}), 'scan_A')
        state = canonical(asdict(primary.snapshot()))
        cases, actual = [], []
        for index, event in enumerate([{'kind': 'start'}] + events):
            event_dict = event if isinstance(event, dict) else canonical(asdict(event))
            case = dict(source_type='constructed_statistics', snapshot=state,
                        event=event_dict, config=cfg)
            next_state, decision = reference_transition(state, event_dict, cfg)
            result = primary.start() if index == 0 else primary.feed(event)
            actual.append(dict(state=canonical(asdict(primary.snapshot())),
                               decision=canonical(asdict(result))))
            self.assertEqual(verify_reference([case], [actual[-1]])['mismatches'], [])
            self.assertEqual((next_state, decision), (actual[-1]['state'], actual[-1]['decision']))
            if index and wants:
                want = wants[index-1]
                self.assertEqual((decision['status'], decision['action_kind'], decision['next_exposure_lines']), want[:3])
                for reason in want[3:]:
                    self.assertIn(reason, decision['reason_codes'])
            cases.append(case)
            state = next_state
        self.assertEqual(verify_reference(cases, actual), dict(passed=True, checked=len(cases), mismatches=[]))
        return cases, actual

    # Break caught: strict/equal thresholds, RGB priorities or candidate scoring.
    def test_reference_matches_all_rule_boundaries(self):
        rows = [({}, ('CONTINUE_ADJUST', 'confirm_current', 600)),
                (dict(dark_count=1000, effective_count=9000, gray_sum=900000), ('CONTINUE_ADJUST', 'confirm_current', 600)),
                (dict(dark_count=1001, effective_count=8999, gray_sum=899900), ('CONTINUE_ADJUST', 'set_exposure', 700, 'too_dark', 'insufficient_effective_area')),
                (dict(near_white_count=100), ('CONTINUE_ADJUST', 'confirm_current', 600)),
                (dict(near_white_count=101), ('CONTINUE_ADJUST', 'set_exposure', 500, 'near_white_risk')),
                (dict(rgb_max_count=500), ('CONTINUE_ADJUST', 'confirm_current', 600)),
                (dict(rgb_max_count=501, baseline_candidate_count=9000), ('CONTINUE_ADJUST', 'set_exposure', 500, 'rgb_risk_warning')),
                (dict(rgb_max_count=1000), ('CONTINUE_ADJUST', 'set_exposure', 500, 'rgb_risk_warning')),
                (dict(rgb_max_count=1001), ('CONTINUE_ADJUST', 'set_exposure', 500, 'rgb_high_risk')),
                (dict(dark_count=1001, effective_count=8999, gray_sum=899900, rgb_max_count=501), ('NEEDS_REVIEW', 'stop', None, 'dark_and_highlight'))]
        for changes, want in rows:
            with self.subTest(changes=changes):
                self.replay([observation('a', **changes)], wants=[want])

    # Break caught: locking on the first frame or requiring candidates.
    def test_normal_no_candidates_lock_and_stability_equalities(self):
        self.replay([observation('a', rgb_max_count=100),
                     observation('b', gray_sum=1020000, effective_count=9800,
                                 dark_count=200, rgb_max_count=150)],
                    wants=[('CONTINUE_ADJUST', 'confirm_current', 600),
                           ('LOCKED', 'stop', None, 'offline_policy_locked')])

    # Break caught: each temporal gate is skipped or integer ratios rounded.
    def test_stability_each_just_outside_boundary_and_unequal_n(self):
        for changes in [dict(gray_sum=1020001),
                        dict(dark_count=201, effective_count=9799), dict(rgb_max_count=51)]:
            self.replay([observation('a'), observation('b', **changes)],
                        wants=[('CONTINUE_ADJUST', 'confirm_current', 600),
                               ('CONTINUE_ADJUST', 'fallback_confirm', 600, 'confirmation_unstable')])
        self.replay([observation('a', n=10000, rgb_max_count=100),
                     observation('b', n=20000, gray_sum=2040000, dark_count=400,
                                 effective_count=19600, rgb_max_count=300)],
                    wants=[('CONTINUE_ADJUST', 'confirm_current', 600), ('LOCKED', 'stop', None)])

    # Break caught: streak fails to reset on fallback or capture error.
    def test_fallback_needs_two_fresh_observations(self):
        self.replay([observation('a'), observation('b', gray_sum=1030000),
                     observation('c'), observation('d')],
                    wants=[('CONTINUE_ADJUST', 'confirm_current', 600),
                           ('CONTINUE_ADJUST', 'fallback_confirm', 600, 'confirmation_unstable'),
                           ('CONTINUE_ADJUST', 'confirm_current', 600), ('LOCKED', 'stop', None)])
        self.replay([observation('a'), CaptureEvent('capture_error', 'scan_A', None, 600, None, 'timeout'),
                     observation('b'), observation('c')],
                    wants=[('CONTINUE_ADJUST', 'confirm_current', 600),
                           ('CONTINUE_ADJUST', 'retry_current', 600),
                           ('CONTINUE_ADJUST', 'confirm_current', 600), ('LOCKED', 'stop', None)])

    # Break caught: loss of risk_seen once the pending lower setting has no signal.
    def test_risk_history_survives_later_no_signal(self):
        self.replay([observation('risk', rgb_max_count=501),
                     observation('dark', 500, dark_count=10000, effective_count=0, gray_sum=0)],
                    wants=[('CONTINUE_ADJUST', 'set_exposure', 500),
                           ('NEEDS_REVIEW', 'stop', None)])

    # Break caught: condition identity lost while snapshot contains no qualified frame.
    def test_condition_identity_from_unqualified_observation(self):
        from fpga_reference import reference_transition
        cases, actual = self.replay([observation('dark', dark_count=2000, effective_count=8000, gray_sum=800000)])
        state = actual[-1]['state']
        other = canonical(asdict(observation('new', 700)))
        other['metrics']['geometry']['sample_id'] = 'different-board'
        with self.assertRaises(ValueError):
            reference_transition(state, other, config())

    # Break caught: charged missing data or model reservation released.
    def test_missing_data_cost_and_each_budget_axis(self):
        self.replay([observation('a'), CaptureEvent('missing_data', 'scan_A', None, 600, None, None)],
                    wants=[('CONTINUE_ADJUST', 'confirm_current', 600),
                           ('NEEDS_REVIEW', 'stop', None, 'missing_fresh_confirmation')])
        self.replay([CaptureEvent('missing_data', 'scan_A', None, 600, None, None)],
                    wants=[('NEEDS_REVIEW', 'stop', None, 'missing_requested_data')])
        for changes in [dict(max_attempts=1), dict(max_frames=4), dict(max_time_ms=5000)]:
            with self.subTest(changes=changes):
                self.replay([observation('a')], config(**changes),
                            [('NEEDS_REVIEW', 'stop', None, 'budget_exhausted')])

    # Break caught: eighth request is denied early or a ninth one reserved.
    def test_exact_eighth_request_budget_boundary(self):
        self.replay([observation(str(i)) for i in range(8)], config(confirmations=9),
                    [('CONTINUE_ADJUST', 'confirm_current', 600)]*7 +
                    [('NEEDS_REVIEW', 'stop', None, 'budget_exhausted')])

    # Break caught: unavailable geometry/small area/zero denominator gets lock.
    def test_geometry_review_zero_denominators_and_strict_coverage(self):
        for changes, reason in [(dict(n=0, gray_sum=0, dark_count=0, effective_count=0,
                                      background_count=0), 'insufficient_common_area'),
                                (dict(n=9999), 'insufficient_common_area')]:
            self.replay([observation('a', **changes)], wants=[('NEEDS_REVIEW', 'stop', None, reason)])
        for numerator, native, reason in [(10000, 10526, None), (10000, 10527, 'insufficient_common_coverage')]:
            event = observation('a')
            values = canonical(asdict(event.metrics))
            values['geometry']['native_area'] = native
            values['geometry']['coverage_denominator'] = native
            event = CaptureEvent('observation', 'scan_A', 'a', 600, type(event.metrics)(**values), None)
            self.replay([event], wants=[('CONTINUE_ADJUST', 'confirm_current', 600)] if reason is None else
                        [('NEEDS_REVIEW', 'stop', None, reason)])
        event = observation('a')
        values = canonical(asdict(event.metrics))
        del values['geometry']['mask_sources']
        self.replay([CaptureEvent('observation', 'scan_A', 'a', 600, type(event.metrics)(**values), None)],
                    wants=[('NEEDS_REVIEW', 'stop', None, 'geometry_unavailable')])

    # Break caught: null background wins by inventing zero; final exposure tie.
    def test_unknown_background_loses_and_exposure_breaks_complete_tie(self):
        from fpga_reference import reference_transition
        for left_changes, right_changes in [
                (dict(background_count=0, line_center_count=10000), dict(background_activity_sum_n=10000)),
                ({}, {})]:
            _, left_run = self.replay([observation('l', **left_changes)])
            _, right_run = self.replay([observation('r', 500, **right_changes)], config(initial_exposure_lines=500))
            left, right = left_run[-1]['decision']['input_statistics'], right_run[-1]['decision']['input_statistics']
            self.assertTrue(better_setting(right, left))
            state = copy.deepcopy(left_run[-1]['state'])
            state['qualified'] = [left, right]
            unstable = observation('u', gray_sum=1030000, **left_changes)
            _, decision = reference_transition(state, canonical(asdict(unstable)), config())
            self.assertEqual(decision['next_exposure_lines'], 500)

    # Break caught: validation leaks KeyError/TypeError instead of ValueError.
    def test_malformed_snapshot_and_cost_reject_cleanly(self):
        from fpga_reference import reference_transition
        cases, actual = self.replay([observation('a')])
        state = actual[-1]['state']
        for bad in [None, [], {**state, 'pending_request': {**state['pending_request'], 'cost': {}}},
                    {**state, 'confirmation_count': True}]:
            with self.assertRaises(ValueError):
                reference_transition(bad, canonical(asdict(observation('b'))), config())
        with self.assertRaises(ValueError):
            reference_transition(state, canonical(asdict(observation('b'))), config(extra_hardware_flag=True))

    # Break caught: unavailable geometry hides a contradictory setting/sample.
    def test_incomplete_geometry_cannot_hide_identity_or_fixed_setting(self):
        from fpga_reference import reference_transition
        cases, actual = self.replay([observation('a')])
        state = actual[-1]['state']
        for changes, removed in [(dict(gain16=17), 'pose'),
                                 (dict(sample_id='other', available=False), None)]:
            event = canonical(asdict(observation('b')))
            event['metrics']['geometry'].update(changes)
            if removed:
                del event['metrics']['geometry'][removed]
            with self.assertRaises(ValueError):
                reference_transition(state, event, config())
        for changes in [dict(available=1), dict(source_identity_available='true'),
                        dict(reason_codes='geometry_unavailable')]:
            event = canonical(asdict(observation('b')))
            event['metrics']['geometry'].update(changes)
            with self.assertRaises(ValueError):
                reference_transition(state, event, config())

    # Break caught: unavailable evidence establishes risk or condition history.
    def test_unavailable_geometry_does_not_establish_risk_or_condition(self):
        event = observation('risk', rgb_max_count=501)
        values = canonical(asdict(event.metrics))
        values['geometry']['available'] = False
        self.replay([CaptureEvent('observation', 'scan_A', 'risk', 600, type(event.metrics)(**values), None)],
                    wants=[('NEEDS_REVIEW', 'stop', None, 'geometry_unavailable')])

    # Break caught: visits reused for search or no-signal reported as lock.
    def test_search_exhaustion_and_retry_exhaustion(self):
        dark = dict(dark_count=10000, effective_count=0, gray_sum=0)
        self.replay([observation('a', **dark), observation('b', 700, **dark)],
                    wants=[('CONTINUE_ADJUST', 'set_exposure', 700),
                           ('CAPTURE_FAILED', 'stop', None, 'search_exhausted', 'no_qualified_fallback')])
        self.replay([CaptureEvent('capture_error', 'scan_A', None, 600, None, None)]*2,
                    wants=[('CONTINUE_ADJUST', 'retry_current', 600),
                           ('CAPTURE_FAILED', 'stop', None, 'retry_exhausted')])

    # Break caught: accepting replayed source/UUID, wrong context, wrong exposure.
    def test_rejected_identity_and_terminal_do_not_mutate_input(self):
        from fpga_reference import reference_transition
        _, actual = self.replay([observation('a')])
        state = actual[-1]['state']
        events = [canonical(asdict(observation('a'))), canonical(asdict(observation('b', 500))),
                  canonical(asdict(observation('b')))]
        events[-1]['context_id'] = 'other'
        duplicate_source = canonical(asdict(observation('b')))
        duplicate_source['metrics']['geometry'] = copy.deepcopy(actual[-1]['decision']['input_statistics']['geometry'])
        duplicate_source['metrics']['geometry']['observation_id'] = 'b'
        events.append(duplicate_source)
        for event in events:
            before = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                reference_transition(state, event, config())
            self.assertEqual(state, before)
        _, locked = self.replay([observation('a'), observation('b')])
        with self.assertRaises(ValueError):
            reference_transition(locked[-1]['state'], canonical(asdict(observation('c'))), config())

    # Break caught: raw-count ranking instead of unequal-denominator fractions.
    def test_unequal_denominator_rgb_effective_background_ranking(self):
        from fpga_reference import reference_transition
        vectors = [
            (dict(n=10000, rgb_max_count=200), dict(n=20000, rgb_max_count=300), 500),
            (dict(n=10000, dark_count=100, effective_count=9900), dict(n=20000, dark_count=1000, effective_count=19000), 600),
            (dict(n=10000, background_activity_sum_n=10000), dict(n=20000, background_activity_sum_n=15000), 500),
        ]
        for left_changes, right_changes, expected in vectors:
            _, left_run = self.replay([observation('l', **left_changes)])
            _, right_run = self.replay([observation('r', 500, **right_changes)], config(initial_exposure_lines=500))
            left = left_run[-1]['decision']['input_statistics']
            right = right_run[-1]['decision']['input_statistics']
            self.assertEqual(better_setting(right, left), expected == 500)
            state = copy.deepcopy(left_run[-1]['state'])
            state['qualified'] = [left, right]
            unstable = observation('unstable', **{**left_changes, 'gray_sum': 103*left_changes['n']})
            _, decision = reference_transition(state, canonical(asdict(unstable)), config())
            self.assertEqual(decision['next_exposure_lines'], expected)
            self.assertEqual(decision['action_kind'], 'fallback_confirm')

    # Break caught: missing scalar/decision/state mutation comparison.
    def test_reference_diff_is_detected(self):
        from fpga_reference import verify_reference
        cases, actual = self.replay([observation('a')])
        for category, key, value in [('decision', 'next_exposure_lines', 500),
                                     ('decision', 'reason_codes', ['wrong_reason']),
                                     ('state', 'risk_seen', True)]:
            corrupted = copy.deepcopy(actual)
            corrupted[-1][category][key] = value
            report = verify_reference(cases, corrupted)
            self.assertFalse(report['passed'])
            self.assertIn(key, str(report['mismatches']))
        self.assertFalse(verify_reference(cases, actual[:-1])['passed'])

    # Break caught: narrowing cumulative sums or cross products to uint32.
    def test_width_bounds_not_uint32(self):
        from fpga_reference import bit_width_contract, scalar_metric_reference
        widths = bit_width_contract(1920*1080)
        self.assertEqual(widths['gray_sum']['max'], 528768000)
        self.assertEqual(widths['residual_absolute_sum']['max'], 42301440000)
        self.assertEqual(widths['residual_absolute_sum']['bits'], 36)
        self.assertEqual(widths['basis_point_cross_product']['bits'], 35)
        self.assertGreater(widths['stability_gray_cross_product']['bits'], 32)
        self.assertEqual(widths['background_ranking_cross_product']['bits'], 57)
        # Constructed residuals exercise accumulation, not a physical gray/H2 pair.
        gray = np.full((512, 512), 255, np.uint8)
        residual = np.full((512, 512), 20400, np.int16)
        mask = np.ones((512, 512), bool)
        values = scalar_metric_reference(gray, residual, mask, mask)
        self.assertEqual(values['line_center_count'], 262140)
        self.assertEqual(values['line_contrast_sum_n'], 5347656000)
        self.assertEqual(values['background_count'], 4)
        self.assertEqual(values['background_activity_sum_n'], 81600)

    # Break caught: goldens save copied primary actions or erase source category.
    def test_goldens_mark_source_type_and_retain_complete_input(self):
        from fpga_reference import export_golden
        cases, _ = self.replay([observation('a')])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'golden.json'
            export_golden(cases, path)
            value = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(value['cases'][1]['source_type'], 'constructed_statistics')
            self.assertEqual(value['cases'][1]['input'], cases[1])
            self.assertEqual(value['cases'][1]['expected']['decision']['next_exposure_lines'], 600)
            with self.assertRaises(FileExistsError):
                export_golden(cases, path)
            bad = copy.deepcopy(cases)
            bad[1]['source_type'] = 'real_camera'
            with self.assertRaises(ValueError):
                export_golden(bad, Path(directory) / 'bad.json')

    # Break caught: expected interface rejection becomes a capture-failure action.
    def test_validation_failures_export_and_compare_explicitly(self):
        from fpga_reference import export_golden, verify_reference
        cases, actual = self.replay([observation('a')])
        case = dict(source_type='constructed_statistics', config=config(),
                    snapshot=actual[-1]['state'], event=canonical(asdict(observation('b'))),
                    expected_validation_error='ValueError')
        case['event']['context_id'] = 'other'
        expected = [{'validation_error': 'ValueError'}]
        self.assertTrue(verify_reference([case], expected)['passed'])
        self.assertFalse(verify_reference([case], [{'decision': {'status': 'CAPTURE_FAILED'}}])['passed'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rejected.json'
            export_golden([case], path)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['cases'][0]['expected'], expected[0])
        case['event']['context_id'] = 'scan_A'
        with self.assertRaises(ValueError):
            verify_reference([case], expected)

    # Break caught: reusable golden builder wraps primary output or omits rejection.
    def test_constructed_goldens_reusable_match_primary_and_checkpoints(self):
        from fpga_reference import constructed_golden_cases, verify_reference
        cases = constructed_golden_cases(config())
        actual = []
        rejection_ids = set()
        primary = None
        for case in cases:
            if case['event']['kind'] == 'start':
                cfg = case['config']
                primary = Controller(ControllerConfig(**{**cfg, 'exposures': tuple(cfg['exposures'])}), case['snapshot']['context_id'])
            self.assertEqual(canonical(asdict(primary.snapshot())), case['snapshot'])
            if case.get('expected_validation_error'):
                rejection_ids.add(case['scenario_id'])
                with self.assertRaises(ValueError):
                    event = case['event']
                    primary.feed(CaptureEvent(**{**event, 'metrics': type(observation('unused').metrics)(**event['metrics'])}))
                actual.append({'validation_error': 'ValueError'})
            else:
                event = case['event']
                decision = primary.start() if event['kind'] == 'start' else primary.feed(CaptureEvent(**{
                    **event, 'metrics': type(observation('unused').metrics)(**event['metrics']) if event['metrics'] else None}))
                got = canonical(asdict(decision))
                checkpoint = case['checkpoint']
                self.assertEqual({key: got[key] for key in checkpoint}, checkpoint)
                actual.append(dict(state=canonical(asdict(primary.snapshot())), decision=got))
        self.assertTrue({'duplicate_identity', 'wrong_context', 'terminal_rejection'} <= rejection_ids)
        self.assertTrue(verify_reference(cases, actual)['passed'])

    # Break caught: history-dependent branch/cost mismatch beyond literal paths.
    def test_bounded_generated_sessions_match_complete_state(self):
        from fpga_reference import reference_transition
        rng = np.random.default_rng(9004)
        for session in range(80):
            primary = Controller(ControllerConfig(), 'scan_A')
            cfg = config()
            state = canonical(asdict(primary.snapshot()))
            state, decision = reference_transition(state, {'kind': 'start'}, cfg)
            self.assertEqual(decision, canonical(asdict(primary.start())))
            history = []
            for step in range(8):
                if state['status'] != 'CONTINUE_ADJUST':
                    break
                exposure = state['pending_request']['exposure_lines']
                draw = int(rng.integers(0, 10))
                if draw < 2:
                    event = CaptureEvent('capture_error', 'scan_A', None, exposure, None, 'generated_error')
                elif draw == 2:
                    event = CaptureEvent('missing_data', 'scan_A', None, exposure, None, None)
                else:
                    dark = int(rng.choice([0, 1000, 1001, 2000, 10000]))
                    white = int(rng.choice([0, 100, 101])) if dark < 10000 else 0
                    ordinary = 10000-dark-white
                    gray_sum = 5*dark + int(rng.choice([99, 100, 102, 103]))*ordinary + 252*white
                    event = observation(f'generated-{session}-{step}', exposure,
                                        dark_count=dark, near_white_count=white, gray_sum=gray_sum,
                                        effective_count=10000-dark, rgb_max_count=int(rng.choice([0, 500, 501, 1001])))
                history.append((event.kind, exposure, None if event.metrics is None else
                                (event.metrics.dark_count, event.metrics.near_white_count, event.metrics.rgb_max_count)))
                state, decision = reference_transition(state, canonical(asdict(event)), cfg)
                got = primary.feed(event)
                self.assertEqual(decision, canonical(asdict(got)), (session, step, history))
                self.assertEqual(state, canonical(asdict(primary.snapshot())), (session, step))


if __name__ == '__main__':
    unittest.main()
