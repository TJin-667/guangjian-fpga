"""Meaningful P0 lifecycle checks using only guarded127.0.0.1 UDP."""
import hashlib
import json
import socket
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import p0_capture as app
sys.path.append(str(app.shared.BASE))
sys.path.append(str(app.shared.BASE.parent/'gray_transport_0105_20261025'))
from test_operator_host import FixtureRuntime
from test_sdk_transport import LocalSocket
from software_transport_peer import make_peer
import board_probe

ROOT=Path('C:/bx72_ymw_0105_20261015/p0_pair_tests02')


class Fixture(app.Runtime):
    evidence_source='software_udp_peer'
    sensor_size=(96,32)
    bridge_sensor_size=(96,32)
    def __init__(self, base):
        self.core=base.core; self.lab=base.lab; self.fixture=base
        self.specimen='sample005'; self.variant='A_v1'; self.pose='sample005_A_v1_software_only'
        self.mask_path=self.preview_record=self.preview_png=None
    def candidate(self):return self.fixture.candidate()
    def guard(self):return self.fixture.guard()
    def executor(self, plan, out):return self.fixture.executor(plan,out)


class P0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ROOT.mkdir(exist_ok=False); cls.Peer,cls.engine=make_peer(); cls.core=board_probe.core_module()
    def setUp(self):
        self.root=ROOT/self._testMethodName.split('_')[1];self.root.mkdir()
        p=patch.object(socket,'socket',LocalSocket);p.start();self.addCleanup(p.stop)
        self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__();self.addCleanup(lambda:self.peer.__exit__(None,None,None))
        self.base=FixtureRuntime(self.root,self.core,self.peer,self.engine);self.runtime=Fixture(self.base)
    def select(self,*args):return [(2,2),(93,2),(93,29),(2,29)]
    def run_it(self,selector=None):return app.run(self.root/'run',self.runtime,selector or self.select)
    def test_01_complete_RGB_sources_real_mask_and_exact_XDL_loader(self):
        r=self.run_it();self.assertEqual(r['summary']['status'],'P0_PAIR_READY_FOR_LABEL_REVIEW',r['summary']['error'])
        self.assertEqual(len(self.peer.captured),9);formal=self.peer.captured[1:]
        self.assertTrue(all(p['pixel_format']==1 for p in self.peer.captured))
        self.assertEqual(len({p['identity']['session'] for p in formal}),1)
        manifest=app.read(self.root/'run/XDL_manifest.json');observations=manifest['groups'][0]['observations']
        self.assertEqual(len(observations),8);self.assertEqual([o['exposure_lines'] for o in observations],[400,800]*4)
        for item in observations:
            frame,provenance=app.bridge.xdl_reference.load('run')._load_observation(item,self.root/'run')
            self.assertGreater(int(frame.valid_mask.sum()),0);self.assertLess(int(frame.valid_mask.sum()),96*32)
            self.assertEqual(item['frame_payload_sha256'],None)
        self.assertEqual(app.bridge.xdl_reference.load('run').run_manifest(self.root/'run/XDL_manifest.json',self.root/'baseline'),0)
        self.assertFalse(r['summary']['training_data']);self.assertFalse(r['summary']['release_ready'])
    def test_02_cancel_selection_only_preview_OFF_no_formal(self):
        def cancel(*args):raise ValueError('Operator cancelled')
        r=self.run_it(cancel);self.assertEqual(r['summary']['phase'],'select_board');self.assertEqual(len(self.peer.captured),1)
        self.assertTrue(app.read(self.root/'run/preview/operator_summary.json')['lights_off']['acknowledged'])
        self.assertFalse((self.root/'run/acquisition').exists());self.assertTrue(Path(r['archive']).exists())
    def test_03_fifth_formal_CRC_stops_at_four_preserves_and_OFF(self):
        start=self.peer._start_capture
        def corrupt(*args):
            if len(self.peer.captured)==5:self.peer.fault='payload_corrupt'
            return start(*args)
        self.peer._start_capture=corrupt;r=self.run_it()
        self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(self.peer.captured),6)
        summary=app.read(self.root/'run/acquisition/operator_summary.json')
        self.assertEqual(summary['saved_observations'],4);self.assertTrue(summary['lights_off']['acknowledged'])
        self.assertFalse((self.root/'run/XDL_manifest.json').exists())
    def test_04_preview_OFF_missing_ACK_blocks_all_formal(self):
        self.peer.fault='off_ack_lost';r=self.run_it()
        self.assertEqual(r['summary']['phase'],'preview');self.assertEqual(len(self.peer.captured),1)
        self.assertFalse((self.root/'run/acquisition').exists())
    def test_05_export_failure_keeps_eight_no_recapture(self):
        with patch.object(app.bridge,'export_batch',side_effect=OSError('injected export failure')):r=self.run_it()
        self.assertEqual(r['summary']['phase'],'export');self.assertEqual(len(self.peer.captured),9)
        self.assertTrue((self.root/'run/acquisition.zip').exists());self.assertFalse((self.root/'run/XDL_manifest.json').exists())
    def test_06_changed_candidate_blocks_before_preview(self):
        self.runtime.candidate=lambda:(_ for _ in ()).throw(ValueError('Changed bit/source'))
        r=self.run_it();self.assertEqual(r['summary']['phase'],'preflight');self.assertEqual(len(self.peer.captured),0)
    def test_07_invalid_crossed_or_outside_polygon_cannot_start_formal(self):
        for points in ([(0,0),(90,30),(90,0),(0,30)],[(0,0),(96,0),(96,30),(0,30)],[(0,0),(1,0),(1,1),(0,1)]):
            with self.assertRaises(ValueError):app.polygon_mask(points,(96,32))
        r=self.run_it(lambda *args:[(0,0),(90,30),(90,0),(0,30)])
        self.assertEqual(len(self.peer.captured),1);self.assertEqual(r['summary']['status'],'FAILED')


if __name__=='__main__':
    before={p.name:app.sha(p) for p in Path(__file__).parent.glob('*.py')};start=time.monotonic()
    with (ROOT.parent/'p0_pair_tests02.txt').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(P0Tests))
    after={p.name:app.sha(p) for p in Path(__file__).parent.glob('*.py')}
    app.write(ROOT.parent/'p0_pair_verification02.json',dict(status='PASS' if result.wasSuccessful() and before==after else 'FAIL',
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),source_sha256=before,sources_unchanged=before==after,
        wall_seconds=time.monotonic()-start,hardware_contacted=False,network_scope='LocalSocket127.0.0.1 only'))
    print('P0_TESTS',result.testsRun,'PASS' if result.wasSuccessful() else 'FAIL')
    raise SystemExit(0 if result.wasSuccessful() and before==after else 2)
