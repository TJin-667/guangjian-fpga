"""Behavioral rules and budget evidence for constructed offline observations."""
import unittest
from dataclasses import asdict, replace
import json
import acquisition_control as ac
from fixtures import make_frame, make_metrics, geometry_for


def observation(exposure=600, serial=1, context='normal_fixture', **metrics):
    frame = make_frame(context_id=context, observation_id=f'r{serial:02}',
                       exposure_lines=exposure,
                       source_metadata=dict(dataset_id='fixture-dataset', capture_id=f'capture-{serial}',
                                            frame_id=f'frame-{serial}', member=f'frame-{serial}.png'))
    return ac.CaptureEvent('observation', context, frame.observation_id, exposure,
                           make_metrics(geometry=geometry_for(frame), **metrics), None)


class ControllerTests(unittest.TestCase):
    def controller(self, **config):
        self.assertTrue(hasattr(ac, 'Controller'), 'Controller rules have not been implemented')
        c = ac.Controller(ac.ControllerConfig(**config), 'normal_fixture')
        c.start()
        return c

    def test_normal_zero_candidates_locks_after_two(self):
        # A missing controller, missed confirmation, or double charge breaks this.
        self.assertTrue(hasattr(ac, 'Controller'), 'Controller rules have not been implemented')
        controller = ac.Controller(ac.ControllerConfig(), 'normal_fixture')
        self.assertEqual(controller.start().next_exposure_lines, 600)
        self.assertEqual(controller.feed(observation()).action_kind, 'confirm_current')
        decision = controller.feed(observation(serial=2))
        self.assertEqual(decision.status, 'LOCKED')
        self.assertEqual(controller.snapshot().consumed_cost, ac.Cost(2, 8, 10000))

    def test_highlight_moves_down(self):
        c = self.controller()
        d = c.feed(observation(rgb_max_count=501))
        self.assertEqual((d.status, d.action_kind, d.next_exposure_lines),
                         ('CONTINUE_ADJUST', 'set_exposure', 500))
        self.assertIn('rgb_risk_warning', d.reason_codes)

    def test_dark_moves_up(self):
        c = self.controller(initial_exposure_lines=500)
        d = c.feed(observation(500, dark_count=1001, effective_count=8999))
        self.assertEqual((d.action_kind, d.next_exposure_lines), ('set_exposure', 600))

    def test_dark_and_glare_reviews(self):
        d = self.controller().feed(observation(dark_count=1001, effective_count=8999,
                                               rgb_max_count=1001))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIn('dark_and_highlight', d.reason_codes)
        self.assertIn('rgb_high_risk', d.reason_codes)

    def test_threshold_equality_is_accepted(self):
        c = self.controller()
        for serial in (1, 2):
            d = c.feed(observation(serial=serial, dark_count=1000, effective_count=9000,
                                   near_white_count=100, rgb_max_count=500))
        self.assertEqual(d.status, 'LOCKED')

    def test_candidate_more_cannot_win(self):
        self.assertTrue(hasattr(ac, 'classify'), 'classification missing')
        left = ac.classify(make_metrics(rgb_max_count=100), ac.ControllerConfig())
        right = ac.classify(make_metrics(rgb_max_count=200, baseline_candidate_count=9999),
                            ac.ControllerConfig())
        self.assertTrue(ac.better_setting(left, right))
        self.assertFalse(ac.better_setting(right, left))

    def test_budget_reservation_not_double_counted(self):
        c = self.controller()
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(1, 4, 5000))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(0, 0, 0))
        c.feed(observation())
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(2, 8, 10000))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(1, 4, 5000))
        c.feed(observation(serial=2))
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(2, 8, 10000))
        self.assertIsNone(c.snapshot().pending_request)

    def test_budget_all_axes_require_full_next_request(self):
        for limits in ({'max_attempts': 1}, {'max_frames': 7}, {'max_time_ms': 9999}):
            with self.subTest(limits=limits):
                c = self.controller(**limits)
                d = c.feed(observation())
                self.assertEqual(d.status, 'NEEDS_REVIEW')
                self.assertIsNone(d.next_exposure_lines)
                self.assertEqual(c.snapshot().requested_cost, ac.Cost(1, 4, 5000))

    def test_initial_budget_insufficient_reserves_nothing(self):
        self.assertTrue(hasattr(ac, 'Controller'))
        c = ac.Controller(ac.ControllerConfig(max_frames=3), 'normal_fixture')
        self.assertEqual(c.start().status, 'NEEDS_REVIEW')
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(0, 0, 0))

    def test_capture_error_retries_once(self):
        c = self.controller()
        error = ac.CaptureEvent('capture_error', 'normal_fixture', None, 600, None, 'timeout')
        self.assertEqual(c.feed(error).action_kind, 'retry_current')
        self.assertEqual(c.feed(error).status, 'CAPTURE_FAILED')
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(2, 8, 10000))
        self.assertEqual(c.snapshot().retry_count[600], 1)

    def test_missing_confirmation_reviews(self):
        c = self.controller()
        c.feed(observation())
        d = c.feed(ac.CaptureEvent('missing_data', 'normal_fixture', None, 600, None, None))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIn('missing_fresh_confirmation', d.reason_codes)
        self.assertEqual(c.snapshot().success_observations, 1)
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(2, 8, 10000))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(1, 4, 5000))
        self.assertEqual(c.snapshot().unfulfilled_cost, ac.Cost(1, 4, 5000))
        self.assertIsNone(c.snapshot().pending_request)

    def test_duplicate_source_rejected(self):
        c = self.controller()
        c.feed(observation())
        frame = make_frame(context_id='normal_fixture', observation_id='new-uuid',
                           source_metadata=dict(dataset_id='fixture-dataset', capture_id='capture-1',
                                                frame_id='frame-1', member='frame-1.png',
                                                source_identity='invented-uuid', storage_root='moved'))
        with self.assertRaises(ValueError):
            c.feed(ac.CaptureEvent('observation', 'normal_fixture', 'new-uuid', 600,
                                   make_metrics(geometry=geometry_for(frame)), None))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(1, 4, 5000))

    def test_distinct_verified_ids_with_identical_pixels_allowed(self):
        c = self.controller()
        c.feed(observation())
        self.assertEqual(c.feed(observation(serial=2)).status, 'LOCKED')
        self.assertEqual(len(c.snapshot().seen_source_identities), 2)

    def test_parameter_change_resets_streak(self):
        c = self.controller()
        c.feed(observation())
        c.feed(observation(serial=2, rgb_max_count=501))
        self.assertEqual(c.snapshot().confirmation_count, 0)
        c.feed(observation(500, serial=3))
        self.assertEqual(c.snapshot().confirmation_count, 1)
        self.assertEqual(c.feed(observation(500, serial=4)).status, 'LOCKED')

    def test_fallback_requires_new_frames_once(self):
        c = self.controller()
        c.feed(observation())
        d = c.feed(observation(serial=2, gray_sum=1030000))
        self.assertEqual((d.action_kind, d.next_exposure_lines), ('fallback_confirm', 600))
        self.assertEqual(c.snapshot().confirmation_count, 0)
        d = c.feed(observation(serial=3))
        self.assertEqual(d.action_kind, 'confirm_current')
        d = c.feed(observation(serial=4, gray_sum=1030000))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertTrue(c.snapshot().fallback_used)

    def test_fallback_can_lock_only_with_two_new_observations(self):
        c = self.controller()
        c.feed(observation())
        c.feed(observation(serial=2, gray_sum=1030000))
        self.assertEqual(c.feed(observation(serial=3)).status, 'CONTINUE_ADJUST')
        self.assertEqual(c.feed(observation(serial=4)).status, 'LOCKED')
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(4, 16, 20000))

    def test_no_search_oscillation(self):
        c = self.controller()
        self.assertEqual(c.feed(observation(rgb_max_count=501)).next_exposure_lines, 500)
        d = c.feed(observation(500, serial=2, dark_count=1001, effective_count=8999))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertEqual(c.snapshot().visited, (500, 600))

    def test_persistent_no_signal_capture_failed(self):
        c = self.controller()
        c.feed(observation(dark_count=10000, effective_count=0, gray_sum=0))
        d = c.feed(observation(700, serial=2, dark_count=10000, effective_count=0, gray_sum=0))
        self.assertEqual(d.status, 'CAPTURE_FAILED')

    def test_wrong_context_rejected(self):
        c = self.controller()
        with self.assertRaises(ValueError):
            c.feed(observation(context='other'))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(0, 0, 0))

    def test_terminal_feed_rejected(self):
        c = self.controller()
        c.feed(observation())
        c.feed(observation(serial=2))
        with self.assertRaises(ValueError):
            c.feed(observation(serial=3))

    def test_inconsistent_partition_counts_rejected(self):
        for counts in ({'dark_count': 9900, 'near_white_count': 101},
                       {'effective_count': 9999}, {'background_count': 9999},
                       {'gray_sum': 1}, {'line_contrast_sum_n': 1}):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                make_metrics(**counts)

    def test_unknown_background_cannot_win(self):
        self.assertTrue(hasattr(ac, 'classify'))
        known = ac.classify(make_metrics(background_activity_sum_n=10000), ac.ControllerConfig())
        unknown = ac.classify(make_metrics(background_count=0, line_center_count=10000),
                              ac.ControllerConfig())
        self.assertTrue(ac.better_setting(known, unknown))
        self.assertFalse(ac.better_setting(unknown, known))
        self.assertIsNone(unknown['background_mean_n'])

    def test_wrong_geometry_fields_rejected_without_charge(self):
        for changes in ({'context_id': 'other'}, {'observation_id': 'other'},
                        {'exposure_lines': 500}, {'channel': 2}, {'gain16': 32}, {'led': 64}):
            with self.subTest(changes=changes):
                c = self.controller()
                event = observation()
                geometry = dict(event.metrics.geometry)
                geometry.update(changes)
                event = replace(event, metrics=replace(event.metrics, geometry=geometry))
                with self.assertRaises(ValueError):
                    c.feed(event)
                self.assertEqual(c.snapshot().consumed_cost, ac.Cost(0, 0, 0))

    def test_different_sample_pose_and_common_area_rejected(self):
        for changes in ({'sample_id': 'sample002'}, {'pose': 'B'}, {'common_mask_sha256': 'e'*64}):
            with self.subTest(changes=changes):
                c = self.controller()
                c.feed(observation())
                event = observation(serial=2)
                geometry = dict(event.metrics.geometry)
                geometry.update(changes)
                with self.assertRaises(ValueError):
                    c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))

    def test_missing_provenance_and_unavailable_geometry_review(self):
        for mode in ('missing_provenance', 'unavailable', 'missing_geometry', 'low_coverage'):
            with self.subTest(mode=mode):
                c = self.controller()
                event = observation()
                geometry = dict(event.metrics.geometry)
                if mode == 'missing_provenance':
                    geometry.update(source_metadata={}, source_identity=None,
                                    source_identity_record=None, source_identity_available=False, available=False)
                elif mode == 'unavailable':
                    geometry['available'] = False
                elif mode == 'missing_geometry':
                    geometry = {}
                else:
                    geometry.update(native_area=20000, coverage_denominator=20000)
                d = c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
                self.assertEqual(d.status, 'NEEDS_REVIEW')
                self.assertEqual(c.snapshot().consumed_cost, ac.Cost(1, 4, 5000))

    def test_forged_source_identity_rejected(self):
        c = self.controller()
        event = observation()
        geometry = dict(event.metrics.geometry)
        geometry['source_identity'] = 'f'*64
        with self.assertRaises(ValueError):
            c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))

    def test_duplicate_observation_id_rejected(self):
        c = self.controller()
        c.feed(observation())
        event = observation(serial=2)
        geometry = dict(event.metrics.geometry)
        geometry['observation_id'] = 'r01'
        with self.assertRaises(ValueError):
            c.feed(replace(event, observation_id='r01', metrics=replace(event.metrics, geometry=geometry)))

    def test_event_validation_and_lifecycle(self):
        self.assertTrue(hasattr(ac, 'CaptureEvent'))
        for fields in (('bad', 'x', None, 600, None, None),
                       ('observation', 'x', 'id', 600, None, None),
                       ('capture_error', 'x', None, True, None, None),
                       ('capture_error', 'x', None, 600, make_metrics(), None)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ac.CaptureEvent(*fields)
        c = ac.Controller(ac.ControllerConfig(), 'normal_fixture')
        with self.assertRaises(ValueError):
            c.feed(observation())
        c.start()
        with self.assertRaises(ValueError):
            c.start()

    def test_integer_stability_boundaries(self):
        for delta, want in ((20000, 'LOCKED'), (20001, 'CONTINUE_ADJUST')):
            with self.subTest(delta=delta):
                c = self.controller()
                c.feed(observation())
                self.assertEqual(c.feed(observation(serial=2, gray_sum=1000000+delta)).status, want)

    def test_large_integer_comparisons_and_json_are_exact(self):
        self.assertTrue(hasattr(ac, 'classify'))
        n = 10**12
        geometry = dict(geometry_for(make_frame()))
        geometry.update(native_area=n, common_area=n, coverage_numerator=n, coverage_denominator=n)
        left = ac.classify(make_metrics(n=n, gray_sum=100*n, effective_count=n,
                                       background_count=n, rgb_max_count=50000000000,
                                       geometry=geometry), ac.ControllerConfig())
        right = ac.classify(make_metrics(n=n, gray_sum=100*n, effective_count=n,
                                        background_count=n, rgb_max_count=50000000001,
                                        geometry=geometry), ac.ControllerConfig())
        self.assertTrue(left['qualified'])
        self.assertFalse(right['qualified'])
        json.dumps(left, allow_nan=False)

    def test_incomplete_geometry_cannot_hide_unsupported_fixed_setting(self):
        c = self.controller()
        event = observation()
        with self.assertRaises(ValueError):
            c.feed(replace(event, metrics=replace(event.metrics, geometry={'channel': 2})))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(0, 0, 0))

    def test_unavailable_geometry_cannot_hide_wrong_sample(self):
        c = self.controller()
        c.feed(observation())
        event = observation(serial=2)
        geometry = dict(event.metrics.geometry)
        geometry.update(sample_id='sample002', available=False)
        with self.assertRaises(ValueError):
            c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(1, 4, 5000))

    def test_geometry_boolean_fields_must_be_boolean(self):
        for field in ('available', 'source_identity_available'):
            c = self.controller()
            event = observation()
            geometry = dict(event.metrics.geometry)
            geometry[field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))

    def test_eight_request_budget_stops_without_ninth_request(self):
        c = self.controller(confirmations=9)
        for serial in range(1, 9):
            d = c.feed(observation(serial=serial))
            self.assertEqual(c.snapshot().requested_cost.attempts, min(serial+1, 8))
            self.assertEqual(c.snapshot().consumed_cost.attempts, serial)
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(8, 32, 40000))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(8, 32, 40000))
        self.assertIsNone(c.snapshot().pending_request)

    def test_capture_error_resets_continuous_confirmation(self):
        c = self.controller()
        c.feed(observation())
        c.feed(ac.CaptureEvent('capture_error', 'normal_fixture', None, 600, None, 'timeout'))
        self.assertEqual(c.snapshot().confirmation_count, 0)
        self.assertEqual(c.feed(observation(serial=2)).action_kind, 'confirm_current')
        self.assertEqual(c.feed(observation(serial=3)).status, 'LOCKED')
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(4, 16, 20000))

    def test_zero_area_reviews_without_nan(self):
        c = self.controller()
        event = observation(n=0, gray_sum=0, effective_count=0, background_count=0)
        d = c.feed(event)
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIsNone(d.input_statistics['mean_gray'])
        self.assertIsNone(d.input_statistics['background_mean_n'])
        json.dumps(asdict(d), allow_nan=False)

    def test_snapshot_and_decision_are_detached_json_records(self):
        c = self.controller()
        snapshot = c.snapshot()
        with self.assertRaises(TypeError):
            snapshot.retry_count[600] = 1
        with self.assertRaises(TypeError):
            snapshot.pending_request['exposure_lines'] = 700
        decision = c.feed(observation())
        with self.assertRaises(TypeError):
            decision.input_statistics['geometry']['available'] = False
        self.assertEqual(snapshot.consumed_cost, ac.Cost(0, 0, 0))
        self.assertEqual(json.loads(json.dumps(asdict(snapshot), allow_nan=False))['retry_count']['600'], 0)
        exported = json.loads(json.dumps(asdict(decision), allow_nan=False))
        self.assertIsNone(exported['budget']['measured_live_control_cost'])
        self.assertEqual(exported['budget']['reserved_cost'], {'attempts': 1, 'frames': 4, 'time_ms': 5000})

    def test_ratio_ranking_uses_cross_products_and_final_exposure_tie(self):
        low_frame = make_frame(exposure_lines=500)
        high_frame = make_frame(exposure_lines=600)
        low = ac.classify(make_metrics(geometry=geometry_for(low_frame)), ac.ControllerConfig())
        high = ac.classify(make_metrics(geometry=geometry_for(high_frame)), ac.ControllerConfig())
        self.assertTrue(ac.better_setting(low, high))
        self.assertFalse(ac.better_setting(high, low))
        equal_candidates = ac.classify(make_metrics(baseline_candidate_count=9999,
                                                    geometry=geometry_for(high_frame)), ac.ControllerConfig())
        self.assertFalse(ac.better_setting(equal_candidates, high))
        self.assertFalse(ac.better_setting(high, equal_candidates))

    def test_effective_and_rgb_stability_are_strict_integer_boundaries(self):
        for second, want in (({'dark_count': 200, 'effective_count': 9800}, 'LOCKED'),
                             ({'dark_count': 201, 'effective_count': 9799}, 'CONTINUE_ADJUST'),
                             ({'rgb_max_count': 50}, 'LOCKED'),
                             ({'rgb_max_count': 51}, 'CONTINUE_ADJUST')):
            with self.subTest(second=second):
                c = self.controller()
                c.feed(observation())
                self.assertEqual(c.feed(observation(serial=2, **second)).status, want)

    def test_missing_data_in_initial_request_does_not_consume(self):
        c = self.controller()
        d = c.feed(ac.CaptureEvent('missing_data', 'normal_fixture', None, 600, None, None))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIn('missing_requested_data', d.reason_codes)
        self.assertEqual(c.snapshot().success_observations, 0)
        self.assertEqual(c.snapshot().requested_cost, ac.Cost(1, 4, 5000))
        self.assertEqual(c.snapshot().consumed_cost, ac.Cost(0, 0, 0))
        self.assertEqual(c.snapshot().unfulfilled_cost, ac.Cost(1, 4, 5000))

    def test_geometry_review_reason_is_preserved(self):
        c = self.controller()
        event = observation()
        geometry = dict(event.metrics.geometry)
        geometry.update(available=False, reason_codes=('manual_mapping_unavailable',))
        d = c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIn('manual_mapping_unavailable', d.reason_codes)

    def test_incomplete_mask_source_record_reviews(self):
        c = self.controller()
        event = observation()
        geometry = dict(event.metrics.geometry)
        source = dict(geometry['mask_sources'][0])
        del source['needs_manual_review']
        geometry['mask_sources'] = (source,)
        d = c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
        self.assertEqual(d.status, 'NEEDS_REVIEW')

    def test_geometry_reason_codes_must_be_strings(self):
        c = self.controller()
        event = observation()
        geometry = dict(event.metrics.geometry)
        geometry['reason_codes'] = (1,)
        with self.assertRaises(ValueError):
            c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))

    def test_snapshot_ready_history_is_explicit_and_strict_json(self):
        # Omitting the fields makes an independent transition lack state even at READY.
        c = ac.Controller(ac.ControllerConfig(), 'normal_fixture')
        before = c.snapshot()
        self.assertTrue(hasattr(before, 'risk_seen'), 'Snapshot omits risk history')
        self.assertTrue(hasattr(before, 'condition_identity'), 'Snapshot omits condition identity')
        self.assertIs(before.risk_seen, False)
        self.assertIsNone(before.condition_identity)
        payload = json.loads(json.dumps(asdict(before), allow_nan=False))
        self.assertIs(payload['risk_seen'], False)
        self.assertIsNone(payload['condition_identity'])
        c.start()
        self.assertIs(c.snapshot().risk_seen, False)
        self.assertIsNone(c.snapshot().condition_identity)

    def test_snapshot_exposes_risk_without_qualified_history(self):
        # Reconstructing history only from qualified would lose this risk bit.
        c = self.controller()
        c.feed(observation(rgb_max_count=501))
        snapshot = c.snapshot()
        self.assertEqual(snapshot.qualified, ())
        self.assertTrue(hasattr(snapshot, 'risk_seen'), 'Snapshot omits risk history')
        self.assertIs(snapshot.risk_seen, True)
        self.assertEqual(snapshot.condition_identity, ('sample001', 'A', 'c' * 64))
        d = c.feed(observation(500, serial=2, dark_count=1001, effective_count=8999))
        self.assertEqual(d.status, 'NEEDS_REVIEW')
        self.assertIs(c.snapshot().risk_seen, True)

    def test_snapshot_exposes_condition_from_unqualified_observation(self):
        # A quality-failing usable frame still establishes the accepted sample/pose.
        c = self.controller()
        c.feed(observation(dark_count=1001, effective_count=8999))
        snapshot = c.snapshot()
        self.assertEqual(snapshot.qualified, ())
        self.assertTrue(hasattr(snapshot, 'condition_identity'), 'Snapshot omits condition identity')
        self.assertEqual(snapshot.condition_identity, ('sample001', 'A', 'c' * 64))
        self.assertIs(snapshot.risk_seen, False)
        event = observation(700, serial=2)
        geometry = dict(event.metrics.geometry)
        geometry['sample_id'] = 'sample002'
        with self.assertRaises(ValueError):
            c.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
        self.assertEqual(c.snapshot(), snapshot)
        self.assertEqual(c.feed(observation(700, serial=2, dark_count=1001,
                                            effective_count=8999)).status, 'CAPTURE_FAILED')

    def test_snapshot_history_survives_error_missing_and_unavailable_events(self):
        for terminal_kind in ('missing_data', 'unavailable_observation'):
            with self.subTest(terminal_kind=terminal_kind):
                c = self.controller()
                c.feed(observation(rgb_max_count=501))
                c.feed(ac.CaptureEvent('capture_error', 'normal_fixture', None, 500, None, 'timeout'))
                snapshot = c.snapshot()
                self.assertTrue(hasattr(snapshot, 'risk_seen'), 'Snapshot omits risk history')
                self.assertIs(snapshot.risk_seen, True)
                self.assertEqual(snapshot.condition_identity, ('sample001', 'A', 'c' * 64))
                if terminal_kind == 'missing_data':
                    event = ac.CaptureEvent('missing_data', 'normal_fixture', None, 500, None, None)
                else:
                    event = observation(500, serial=2)
                    geometry = dict(event.metrics.geometry)
                    geometry['available'] = False
                    event = replace(event, metrics=replace(event.metrics, geometry=geometry))
                self.assertEqual(c.feed(event).status, 'NEEDS_REVIEW')
                after = c.snapshot()
                self.assertIs(after.risk_seen, True)
                self.assertEqual(after.condition_identity, snapshot.condition_identity)
                payload = json.loads(json.dumps(asdict(after), allow_nan=False))
                self.assertEqual(payload['condition_identity'], ['sample001', 'A', 'c' * 64])

    def test_snapshot_history_is_immutable_detached_and_unavailable_does_not_establish_it(self):
        c = self.controller()
        before = c.snapshot()
        self.assertTrue(hasattr(before, 'condition_identity'), 'Snapshot omits condition identity')
        c.feed(observation())
        after = c.snapshot()
        self.assertIsNone(before.condition_identity)
        self.assertEqual(after.condition_identity, ('sample001', 'A', 'c' * 64))
        with self.assertRaises(AttributeError):
            after.risk_seen = True
        with self.assertRaises(TypeError):
            after.condition_identity[0] = 'sample002'
        with self.assertRaises(AttributeError):
            after.condition_identity = None
        unavailable = self.controller()
        event = observation(rgb_max_count=501)
        geometry = dict(event.metrics.geometry)
        geometry['available'] = False
        unavailable.feed(replace(event, metrics=replace(event.metrics, geometry=geometry)))
        self.assertIs(unavailable.snapshot().risk_seen, False)
        self.assertIsNone(unavailable.snapshot().condition_identity)


if __name__ == '__main__':
    unittest.main()
