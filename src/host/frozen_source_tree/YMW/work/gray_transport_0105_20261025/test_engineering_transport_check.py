"""Engineering operator tests: protected loopback only, never a real board."""
import contextlib
import json
import os
import socket
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import engineering_transport_check as check
from software_transport_peer import make_peer
from test_sdk_transport import LocalSocket


class FixtureRuntime:
    evidence_source = 'software_udp_peer'
    sensor_size = (96, 32)
    roi = [5, 7, 81, 21]
    timeout_s = 1.5

    def __init__(self, root, fault='', fault_format=49):
        self.root, self.fault, self.fault_format = root, fault, fault_format
        self.core = check.probe.core_module()
        self.Peer, self.engine = make_peer()
        self.marker = root / 'fixture.txt'
        self.marker.write_bytes(b'stable software fixture')
        self.held = False
        self.constructed = []
        self.peers = []
        self.closed = []

    def prepare(self):
        return dict(schema='software-test-plan', evidence_source=self.evidence_source, sensor_size=list(self.sensor_size),
                    roi=self.roi, parameters=check.PARAMETERS, pixel_formats=[1,49], maximum_capture_requests=2,
                    candidate_binding=None, source_sha256={str(self.marker):check.sdk.support.sha_file(self.marker)})

    @contextlib.contextmanager
    def guard(self):
        self.held = True
        try:
            yield
        finally:
            self.held = False

    def executor(self, plan, fmt, out):
        assert self.held
        self.constructed.append(fmt)
        fault = self.fault if fmt == self.fault_format else ''
        peer_fault = fault if fault in ('payload_corrupt','wrong_H2') else ''
        peer = self.Peer(self.engine.root / 'ymw', fault=peer_fault,
                         firmware=0x0105 if fault == 'old_firmware' else 0x0106)
        peer.__enter__()
        self.peers.append(peer)
        executor = check.sdk.TransportExecutor(board='127.0.0.1', bind='127.0.0.1', port=peer.endpoint[1],
            ymw_root=self.engine.root / 'ymw', output_root=out, pixel_format=fmt, mode='strict',
            evidence_source='software_udp_peer', sensor_size=self.sensor_size, command_timeout=.06, retries=2)
        off, close = executor.lights_off, executor.close

        def locked_off(**kwargs):
            assert self.held
            result = off(**kwargs)
            if fault == 'off_failure':
                result['acknowledged'] = False
                result['fixture_failure'] = 'software injected OFF failure'
            return result

        def locked_close():
            assert self.held
            close()
            self.closed.append(fmt)

        executor.lights_off, executor.close = locked_off, locked_close
        if fault == 'source_changed':
            self.marker.write_bytes(b'changed during first request')
        if fault == 'sat_file_tampered':
            acquire = executor.acquire
            def damaged(**kwargs):
                result = acquire(**kwargs)
                path = result.record_path.parent / 'image.sat1'
                data = bytearray(path.read_bytes()); data[0] ^= 0x80; path.write_bytes(data)
                return result
            executor.acquire = damaged
        return executor

    def finish(self):
        for peer in reversed(self.peers):
            peer.__exit__(None, None, None)


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ['ENGINEERING_CHECK_TEST_OUTPUT']) / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        patcher = patch.object(socket, 'socket', LocalSocket)
        patcher.start(); self.addCleanup(patcher.stop)

    def run_case(self, fault='', fault_format=49):
        runtime = FixtureRuntime(self.root, fault, fault_format)
        self.addCleanup(runtime.finish)
        result = check.execute(self.root / 'batch', _runtime=runtime)
        self.assertFalse(runtime.held)
        self.assertEqual(runtime.constructed, runtime.closed)
        with zipfile.ZipFile(result['archive']) as archive:
            inventory = json.loads(archive.read('output_manifest.json'))['files']
            self.assertEqual(set(archive.namelist()), set(inventory) | {'output_manifest.json'})
            for name, digest in inventory.items():
                self.assertEqual(check.sdk.support.sha_bytes(archive.read(name)), digest)
        return result['summary'], runtime

    def test_01_two_formats_real_bytes_crc_H1_H2_and_zip(self):
        summary, runtime = self.run_case()
        self.assertEqual(summary['status'], 'ENGINEERING_TRANSPORT_VERIFIED')
        self.assertEqual([row['payload_bytes'] for row in summary['rows']], [3402,1914])
        self.assertEqual([row['packets'] for row in summary['rows']], [3,2])
        self.assertEqual(runtime.constructed, [1,49])
        self.assertTrue(all(row['actual_payload_crc_and_H1_H2_recomputed'] for row in summary['rows']))
        self.assertFalse(summary['same_frozen_input'])
        self.assertFalse(summary['release_ready'])

    def test_02_first_frame_crc_failure_stops_before_gray(self):
        summary, runtime = self.run_case('payload_corrupt', 1)
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(summary['captures_verified'], 0)
        self.assertEqual(runtime.constructed, [1])
        self.assertTrue(summary['cleanup'][0]['acknowledged'])

    def test_03_gray_crc_failure_preserves_verified_rgb(self):
        summary, _ = self.run_case('payload_corrupt')
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(summary['captures_verified'], 1)
        self.assertEqual(summary['rows'][0]['pixel_format'], 1)
        self.assertTrue(all(row['acknowledged'] for row in summary['cleanup']))

    def test_04_gray_H2_corruption_rejected(self):
        summary, _ = self.run_case('wrong_H2')
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(summary['captures_verified'], 1)

    def test_05_off_failure_stops_before_gray(self):
        summary, runtime = self.run_case('off_failure', 1)
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(runtime.constructed, [1])
        self.assertEqual(summary['captures_verified'], 1)

    def test_06_source_change_stops_before_second_capture(self):
        summary, runtime = self.run_case('source_changed', 1)
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(runtime.constructed, [1])
        self.assertTrue(summary['source_changed'])

    def test_07_old_firmware_rejected_without_capture(self):
        summary, runtime = self.run_case('old_firmware', 1)
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(summary['captures_verified'], 0)
        self.assertFalse(runtime.peers[0].captured)

    def test_08_saved_sat_file_tamper_rejected(self):
        summary, runtime = self.run_case('sat_file_tampered', 1)
        self.assertEqual(summary['status'], 'FAILED')
        self.assertEqual(runtime.constructed, [1])
        self.assertEqual(summary['captures_verified'], 0)


if __name__ == '__main__':
    unittest.main()
