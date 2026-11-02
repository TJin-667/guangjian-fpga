import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from multiobs.contracts import CaptureRequest, Limits, Stop
from multiobs.ports import CaptureFailure
from multiobs.runner import ScriptedPolicy, run
from tests.fixtures import Clock, FakePort, context, identity, reidentify


def bases():
    return [CaptureRequest('base' + str(ch), ch, exposure, 'base', 'scripted software fixture')
            for ch, exposure in enumerate((400, 500, 600, 800), 1)]


def bad_readback(p):
    p.record['camera_readback']['gain16'] = 32
    return p


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'new'
        self.clock = Clock()
        self.port = FakePort(self.clock)

    def execute(self, actions=None, limits=None, **kw):
        return run(context(), limits or Limits(12, 60, 20, 1),
                   ScriptedPolicy(actions if actions is not None else bases() + [Stop('STOP', 'script complete')]),
                   kw.pop('open_port', lambda: self.port), self.out, clock=self.clock, **kw)

    def assert_shutdown(self):
        self.assertTrue(self.port.off_called)
        self.assertTrue(self.port.closed)

    def test_four_bases_two_same_direction_supplements(self):
        actions = bases() + [CaptureRequest('s1', 1, 800, 'supplement', 'weak-segment fixture'),
                             CaptureRequest('s2', 1, 600, 'supplement', 'second fixture'), Stop('STOP', 'script complete')]
        result = self.execute(actions)
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(len(result['observations']), 6)
        self.assertEqual(result['budget']['reserved_transaction_frames'], 30)
        self.assertEqual(len({o['observation_id'] for o in result['observations']}), 6)
        self.assertEqual(len({o['files']['png'] for o in result['observations']}), 6)
        self.assertTrue(result['base_directions_complete'])
        self.assertFalse(result['multi_exposure_fusion_implemented'])
        self.assertEqual([o['parameters']['exposure_lines'] for o in result['observations']], [400, 500, 600, 800, 800, 600])
        self.assert_shutdown()

    def test_confirmation_same_pixels_has_distinct_identity(self):
        actions = [bases()[0], CaptureRequest('confirm1', 1, 400, 'confirm', 'fresh confirmation fixture'), Stop('REVIEW', 'partial test')]
        result = self.execute(actions)
        a, b = result['observations']
        self.assertEqual(a['raw_sha256'], b['raw_sha256'])
        self.assertNotEqual(a['identity'], b['identity'])
        self.assertEqual(result['budget']['attempts'], 2)

    def test_wrap_is_preserved(self):
        self.port.first_frame = 65535
        result = self.execute()
        self.assertEqual([o['identity']['frame_id'] for o in result['observations']], [65535, 0, 1, 2])
        self.assertEqual(result['status'], 'STOP')

    def test_retry_consumes_budget_and_has_new_attempt(self):
        self.port.behaviors = [bad_readback]
        result = self.execute()
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(result['budget']['attempts'], 5)
        self.assertEqual(result['budget']['reserved_transaction_frames'], 25)
        self.assertEqual(len(result['budget']['calls']), 5)
        self.assertEqual(len({c['attempt_id'] for c in self.port.calls}), 5)
        self.assertEqual(result['observations'][0]['identity']['request_id'], 2)
        self.assertEqual(result['budget']['calls'][0]['status'], 'REJECTED')

    def test_rejected_frame_advances_watermark(self):
        self.port.behaviors = [bad_readback, lambda p: reidentify(p, identity(1))]
        result = self.execute()
        self.assertEqual(result['status'], 'CAPTURE_FAILED')
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['last_observed_identity']['request_id'], 1)
        self.assertEqual(result['budget']['attempts'], 2)
        self.assertIn('NONFORWARD_request_id', result['budget']['calls'][1]['error'])
        self.assert_shutdown()

    def test_persistent_missing_frame_stops_after_one_retry(self):
        self.port.behaviors = [CaptureFailure('IMAGE_TIMEOUT'), CaptureFailure('IMAGE_TIMEOUT')]
        result = self.execute()
        self.assertEqual(result['status'], 'CAPTURE_FAILED')
        self.assertEqual(len(self.port.calls), 2)
        self.assertEqual(result['budget']['reserved_transaction_frames'], 10)
        self.assert_shutdown()

    def test_no_retry_on_poisoned_sdk(self):
        self.port.behaviors = [CaptureFailure('NEEDS_RESET', needs_reset=True)]
        result = self.execute()
        self.assertEqual(result['stop_reason'], 'NEEDS_RESET')
        self.assertEqual(len(self.port.calls), 1)
        self.assert_shutdown()

    def test_cross_session_cannot_be_silently_joined(self):
        def foreign(p):
            ident = p.receipt.copy()
            ident['session'] += 1
            return reidentify(p, ident)
        self.port.behaviors = [None, foreign]
        result = self.execute()
        self.assertEqual(result['stop_reason'], 'SESSION_CHANGED')
        self.assertEqual(len(self.port.calls), 2)
        self.assertEqual(len(result['observations']), 1)
        self.assert_shutdown()

    def test_retry_cannot_bypass_total_request_budget(self):
        self.port.behaviors = [bad_readback]
        result = self.execute(limits=Limits(1, 60, 20, 1))
        self.assertEqual(result['stop_reason'], 'TOTAL_BUDGET_EXHAUSTED')
        self.assertEqual(len(self.port.calls), 1)
        self.assert_shutdown()

    def test_total_frame_budget(self):
        result = self.execute(limits=Limits(12, 9, 20, 1))
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(result['budget']['reserved_transaction_frames'], 5)
        self.assertEqual(len(self.port.calls), 1)

    def test_initialization_is_inside_time_budget(self):
        def slow_open():
            self.clock.time += 20
            return self.port
        result = self.execute(open_port=slow_open)
        self.assertEqual(result['stop_reason'], 'TOTAL_BUDGET_EXHAUSTED')
        self.assertEqual(len(self.port.calls), 0)
        self.assertTrue(result['budget']['total_deadline_exceeded'] is False)
        self.assert_shutdown()

    def test_late_capture_not_accepted(self):
        self.port.delay = 20.1
        result = self.execute()
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(result['observations'], [])
        self.assertTrue(result['budget']['total_deadline_exceeded'])
        self.assert_shutdown()

    def test_cancel_before_open_does_not_create_port(self):
        cancel = threading.Event()
        cancel.set()
        opened = []
        result = self.execute(cancel=cancel, open_port=lambda: opened.append(True))
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(opened, [])

    def test_cancel_during_capture_does_not_commit_image(self):
        cancel = threading.Event()
        def trigger(p):
            cancel.set()
            return p
        self.port.behaviors = [trigger]
        result = self.execute(cancel=cancel)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['budget']['attempts'], 1)
        self.assert_shutdown()

    def test_cancel_during_pixel_validation_does_not_publish_observation(self):
        cancel = threading.Event()
        from multiobs.validation import validate_payload
        def validate(*args):
            result = validate_payload(*args)
            cancel.set()
            return result
        with patch('multiobs.runner.validate_payload', side_effect=validate):
            result = self.execute(cancel=cancel)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(result['observations'], [])
        self.assert_shutdown()

    def test_interrupt_during_shutdown_still_closes_and_archives(self):
        def interrupt():
            raise KeyboardInterrupt()
        self.port.lights_off = interrupt
        result = self.execute()
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertTrue(self.port.closed)
        self.assertFalse(result['lights_off']['acknowledged'])
        self.assertTrue((self.out / 'completion.json').is_file())

    def test_off_ack_failure_does_not_claim_success(self):
        self.port.off_ack = False
        result = self.execute()
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(result['stop_reason'], 'LIGHTS_OFF_UNCONFIRMED')
        self.assertFalse(result['lights_off']['physical_off_verified'])
        self.assert_shutdown()

    def test_off_exception_and_close_exception_are_preserved(self):
        def fail():
            raise RuntimeError('injected')
        self.port.lights_off = fail
        self.port.close = fail
        result = self.execute()
        self.assertEqual(result['status'], 'REVIEW')
        self.assertFalse(result['lights_off']['acknowledged'])
        events = (self.out / 'events.jsonl').read_text(encoding='utf-8')
        self.assertIn('close_failed', events)

    def test_missing_direction_is_review_even_without_candidates(self):
        result = self.execute([bases()[0], Stop('STOP', 'no candidates')])
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(result['stop_reason'], 'MISSING_BASE_DIRECTIONS')

    def test_quality_conflict_is_external_policy_review(self):
        result = self.execute([bases()[0], Stop('REVIEW', 'XDL_SPATIAL_HIGHLIGHT_DARK_CONFLICT')])
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(len(self.port.calls), 1)

    def test_normal_quality_can_stop_after_complete_base_coverage(self):
        result = self.execute(bases() + [Stop('STOP', 'XDL_quality_background_stable_without_candidates')])
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(len(self.port.calls), 4)

    def test_third_supplement_has_no_hardware_request(self):
        additions = [CaptureRequest('s'+str(n), 1, 800, 'supplement', 'test') for n in range(3)]
        result = self.execute(bases() + additions)
        self.assertEqual(result['stop_reason'], 'SUPPLEMENT_BUDGET')
        self.assertEqual(len(self.port.calls), 6)

    def test_supplement_without_base_rejected_before_capture(self):
        result = self.execute([CaptureRequest('s1', 1, 800, 'supplement', 'test')])
        self.assertEqual(result['stop_reason'], 'SUPPLEMENT_WITHOUT_BASE')
        self.assertEqual(len(self.port.calls), 0)

    def test_reused_action_cannot_create_extra_image(self):
        result = self.execute([bases()[0], bases()[0]])
        self.assertEqual(result['stop_reason'], 'REUSED_ACTION')
        self.assertEqual(len(self.port.calls), 1)

    def test_policy_exception_still_exits(self):
        class Broken:
            policy_id = 'broken_fixture'
            def reset(self, *args):
                pass
            def next_action(self, *args):
                raise RuntimeError('injected policy failure')
            def finalize(self, *args):
                return {}
        result = run(context(), Limits(12, 60, 20, 1), Broken(), lambda: self.port, self.out, clock=self.clock)
        self.assertEqual(result['status'], 'FAILED')
        self.assert_shutdown()

    def test_policy_reset_consume_finalize_have_reproducible_inputs(self):
        class Consumer(ScriptedPolicy):
            def reset(self, ctx, root, profile):
                self.ctx, self.root = ctx, root
                self.received = []
            def consume(self, observation):
                self.received.append(observation)
                assert (self.root / observation.files['raw']).is_file()
                assert observation.statistics['board_count'] == sum(self.ctx.mask)
                observation.identity['session'] = 999  # must not change validated history
            def finalize(self, status, observations, budget):
                return dict(received=len(self.received), final_status=status)
        policy = Consumer(bases() + [Stop('STOP', 'complete')])
        result = run(context(), Limits(12, 60, 20, 1), policy, lambda: self.port, self.out, clock=self.clock)
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(result['policy_report']['received'], 4)
        self.assertEqual(result['observations'][0]['identity']['session'], 123456789)

    def test_policy_consume_failure_does_not_lose_committed_cost(self):
        class Broken(ScriptedPolicy):
            def consume(self, observation):
                raise RuntimeError('injected consume failure')
        result = run(context(), Limits(12, 60, 20, 1), Broken(bases()), lambda: self.port, self.out, clock=self.clock)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(len(result['budget']['calls']), 1)
        self.assert_shutdown()

    def test_policy_finalization_inside_whole_run_budget(self):
        clock = self.clock
        class Slow(ScriptedPolicy):
            def finalize(self, *args):
                clock.time += 25
                return {}
        result = run(context(), Limits(12, 60, 20, 1), Slow(bases() + [Stop('STOP', 'complete')]), lambda: self.port, self.out, clock=self.clock)
        self.assertEqual(result['status'], 'REVIEW')
        self.assertTrue(result['budget']['total_deadline_exceeded'])
        self.assert_shutdown()

    def test_unexpected_capture_error_keeps_reserved_cost(self):
        self.port.behaviors = [RuntimeError('unhandled backend failure')]
        result = self.execute()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['budget']['attempts'], 1)
        self.assertEqual(len(result['budget']['calls']), 1)
        self.assertEqual(result['budget']['reserved_transaction_frames'], 5)
        self.assert_shutdown()

    def test_invalid_cost_does_not_break_error_archive(self):
        def invalid_cost(p):
            p.record['cost'] = {'host_elapsed_s': float('nan')}
            return p
        self.port.behaviors = [invalid_cost, invalid_cost]
        result = self.execute()
        self.assertEqual(result['status'], 'CAPTURE_FAILED')
        self.assertTrue(result['budget']['calls'][0]['sdk_cost']['unknown'])
        self.assertTrue((self.out / 'completion.json').is_file())
        self.assert_shutdown()

    def test_sealed_outputs_and_authoritative_completion(self):
        result = self.execute()
        completion = json.loads((self.out / 'completion.json').read_bytes())
        self.assertEqual(completion['status'], result['status'])
        from multiobs.contracts import sha
        manifest = json.loads((self.out / 'manifest.json').read_bytes())['files']
        for name, expected in manifest.items():
            self.assertEqual(sha((self.out / name).read_bytes()), expected)
        self.assertEqual(completion['report_sha256'], sha((self.out / 'report.json').read_bytes()))
        self.assertEqual(completion['manifest_sha256'], sha((self.out / 'manifest.json').read_bytes()))

    def test_existing_output_never_overwritten(self):
        self.out.mkdir()
        (self.out / 'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertFalse(self.port.off_called)
        self.assertEqual((self.out / 'keep.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
