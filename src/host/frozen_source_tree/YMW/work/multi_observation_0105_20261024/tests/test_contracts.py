import copy
import unittest

from multiobs.contracts import CaptureRequest, Context, ContractError, Limits, Profile, validate_progress
from multiobs.validation import Payload, validate_payload
from tests.fixtures import context, identity, payload


class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.ctx, self.profile = context(), Profile()
        self.request = CaptureRequest('a1', 1, 800, 'base', 'test')

    def test_e800_passes_software_binding(self):
        result = validate_payload(payload(self.request, self.ctx, self.profile, identity(1)), self.request, self.ctx, self.profile)
        self.assertTrue(all(result.values()))

    def test_frozen_identity_widths_and_wrap(self):
        old, new = identity(1, first_frame=65535), identity(2, first_frame=65535)
        validate_progress(old, new)
        self.assertEqual(new['frame_id'], 0)
        for key in ('config_epoch', 'camera_generation', 'light_generation'):
            new[key] = old[key]
        validate_progress(old, new)

    def test_reused_backward_and_half_range_are_rejected(self):
        old = identity(10)
        for key, value in (('frame_id', old['frame_id']), ('request_id', 9), ('dvp_sequence', old['dvp_sequence']),
                           ('publish_sequence', old['publish_sequence'] + (1 << 31))):
            with self.subTest(key=key):
                new = identity(11)
                new[key] = value
                with self.assertRaises(ContractError):
                    validate_progress(old, new)

    def test_cross_session_requires_reset(self):
        new = identity(2)
        new['session'] += 1
        with self.assertRaises(ContractError) as error:
            validate_progress(identity(1), new)
        self.assertTrue(error.exception.needs_reset)

    def test_bad_request_has_no_admission(self):
        for channel, exposure, gain in ((True, 400, 16), (0, 400, 16), (1, 900, 16), (1, 400, 32), (1, 400, 48)):
            with self.subTest(channel=channel, exposure=exposure, gain=gain), self.assertRaises(ContractError):
                CaptureRequest('bad', channel, exposure, 'base', 'test', gain).parameters(self.profile)

    def test_bad_context_and_budget(self):
        with self.assertRaises(ContractError):
            Context('s', 'p', (0, 0, 9, 9), bytes([2])*81)
        for args in ((1, 5, float('nan'), 1), (1, 5, 2, 2), (True, 5, 3, 1)):
            with self.subTest(args=args), self.assertRaises(ContractError):
                Limits(*args)

    def test_rejects_metadata_and_content_faults(self):
        def set_camera(key, value):
            return lambda p: p.record['camera_readback'].__setitem__(key, value)
        mutations = {
            'wrong_sample': lambda p: p.record.__setitem__('sample_id', 'another'),
            'wrong_roi': lambda p: p.record.__setitem__('roi', [4, 8, 16, 17]),
            'wrong_mask': lambda p: p.record.__setitem__('mask_sha256', 'f'*64),
            'wrong_requested_exposure': lambda p: p.record['requested'].__setitem__('exposure_lines', 400),
            'wrong_light': lambda p: p.record['actual_parameters'].__setitem__('light_mask', 2),
            'wrong_gain': set_camera('gain16', 32),
            'parameter_bool': lambda p: p.record['actual_parameters'].__setitem__('light_mask', True),
            'wrong_readback_exposure': set_camera('exposure_lines', 400),
            'wrong_raw_register': lambda p: p.record['camera_readback']['raw_registers'].__setitem__('0x3502', 1),
            'unlocked': set_camera('locked', False),
            'auto_mode': set_camera('mode', 0),
            'wrong_camera_generation': set_camera('generation', 999),
            'wrong_receipt': lambda p: p.record['identity'].__setitem__('config_epoch', 999),
            'incomplete': lambda p: p.record.__setitem__('complete_packets', 0),
            'wrong_hash': lambda p: p.record.__setitem__('png_sha256', '0'*64),
            'wrong_crc': lambda p: p.record.__setitem__('crc64', 1),
            'wrong_h1': lambda p: (p.record['statistics'].__setitem__('board_gray_sum', 0), p.record['diagnostic']['statistics'].__setitem__('board_gray_sum', 0)),
            'wrong_h2': lambda p: (p.record['features'].__setitem__('sum9_total', 0), p.record['diagnostic']['features'].__setitem__('sum9_total', 0)),
            'wrong_wait': lambda p: p.record.__setitem__('device_reported_settle_frames', 0),
            'wrong_discard': lambda p: p.record['diagnostic'].__setitem__('discard_complete_frames', 0),
            'provisional': lambda p: p.record.__setitem__('strict_verified', False),
            'wrong_source': lambda p: p.record.__setitem__('evidence_source', 'real_board'),
            'invalid_cost': lambda p: p.record.__setitem__('cost', {'host_elapsed_s': float('nan')}),
        }
        for name, mutate in mutations.items():
            with self.subTest(fault=name):
                p = payload(self.request, self.ctx, self.profile, identity(1))
                mutate(p)
                with self.assertRaises(ContractError):
                    validate_payload(p, self.request, self.ctx, self.profile)

    def test_same_length_corruption_cannot_be_hidden_by_rehash(self):
        from multiobs.contracts import sha
        p = payload(self.request, self.ctx, self.profile, identity(1))
        raw = bytes([p.raw[0] ^ 1]) + p.raw[1:]
        p.record['raw_rgb565_sha256'] = sha(raw)
        from multiobs.validation import crc64
        p.record['crc64'] = p.record['diagnostic']['rgb_crc64'] = crc64(raw)
        p = Payload(p.record, p.png, raw, p.receipt, p.execution_mode)
        with self.assertRaisesRegex(ContractError, 'PNG_RAW_PIXELS'):
            validate_payload(p, self.request, self.ctx, self.profile)


if __name__ == '__main__':
    unittest.main()
