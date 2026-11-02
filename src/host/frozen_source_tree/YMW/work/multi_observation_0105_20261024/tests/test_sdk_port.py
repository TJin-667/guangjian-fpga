import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from multiobs.contracts import CaptureRequest, Profile, ContractError
from multiobs.ports import CaptureFailure, SdkPort
from tests.fixtures import context, identity, payload


class SdkPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx, self.profile = context(), Profile()
        self.request = CaptureRequest('a1', 1, 800, 'base', 'test')
        self.kwargs = []
        self.sdk = SimpleNamespace(mode='strict', _publication=None, close=lambda: None)
        self.off_calls = []
        self.off = lambda e: self.off_calls.append(e) or dict(requested=True, acknowledged=True)

    def acquire(self, **kwargs):
        self.kwargs.append(kwargs)
        p = payload(self.request, self.ctx, self.profile, identity(1), execution_mode='sdk_adapter', source='software_udp_peer')
        p.record['round_id'] = kwargs['round_id']
        root = Path(self.temp.name)
        (root / 'image.png').write_bytes(p.png)
        (root / 'image.rgb565').write_bytes(p.raw)
        (root / 'result.json').write_text(json.dumps(p.record), encoding='utf-8')
        self.sdk._publication = (p.receipt.copy(), p.record['bank'])
        self.sdk._capture_context = {k: p.receipt[k] for k in ('session', 'request_id', 'config_epoch', 'roi_generation', 'camera_generation', 'light_generation', 'frame_id')}
        self.sdk.session, self.sdk._request_id, self.sdk._frame_id = p.receipt['session'], p.receipt['request_id'], p.receipt['frame_id']
        return SimpleNamespace(metadata=p.record, record_path=root / 'result.json', png_path=root / 'image.png', raw_rgb565=p.raw)

    def port(self):
        # API-shape test only. The real SDK is never instantiated or executed.
        with patch('multiobs.ports.verify_sdk_source'):
            return SdkPort(self.sdk, self.off)

    def test_request_args_and_independent_publication_receipt(self):
        self.sdk.acquire = self.acquire
        port = self.port()
        value = port.capture(self.request, self.ctx, self.profile, 'attempt42', 2.5, threading.Event())
        args = self.kwargs[0]
        self.assertEqual(args['exposure_lines'], 800)
        self.assertEqual(args['gain16'], 16)
        self.assertEqual(args['round_id'], 'fixed_pose/attempt42')
        self.assertEqual(args['board_mask'], self.ctx.mask)
        self.assertEqual(args['timeout_s'], 2.5)
        self.assertEqual(value.execution_mode, 'sdk_adapter')
        self.assertEqual(value.receipt, self.sdk._publication[0])
        value.record['identity']['config_epoch'] = 999
        self.assertNotEqual(value.record['identity'], value.receipt)
        self.assertTrue(port.lights_off()['acknowledged'])
        self.assertEqual(self.off_calls, [self.sdk])

    def test_committed_record_difference_is_rejected(self):
        def corrupted(**kwargs):
            result = self.acquire(**kwargs)
            result.metadata['sample_id'] = 'wrong'
            return result
        self.sdk.acquire = corrupted
        with self.assertRaisesRegex(ContractError, 'SDK_COMMITTED_RECORD'):
            self.port().capture(self.request, self.ctx, self.profile, 'a', 1, threading.Event())

    def test_failed_call_preserves_reset_and_cost(self):
        path = Path(self.temp.name) / 'outcome.json'
        path.write_text(json.dumps(dict(cost={'command_retries': 2})))
        class Error(Exception):
            code = 'READBACK_MISMATCH'
            needs_reset = True
            record_path = path
        def failure(**kwargs):
            raise Error()
        self.sdk.acquire = failure
        with self.assertRaises(CaptureFailure) as caught:
            self.port().capture(self.request, self.ctx, self.profile, 'a', 1, threading.Event())
        self.assertTrue(caught.exception.needs_reset)
        self.assertEqual(caught.exception.cost, {'command_retries': 2})

    def test_failure_before_new_publication_does_not_reobserve_previous_frame(self):
        self.sdk._publication = (identity(1), 0)
        def failure(**kwargs):
            raise CaptureFailure('NO_NEW_FRAME', needs_reset=False)
        self.sdk.acquire = failure
        with self.assertRaises(CaptureFailure) as caught:
            self.port().capture(self.request, self.ctx, self.profile, 'a', 1, threading.Event())
        self.assertIsNone(caught.exception.receipt)
