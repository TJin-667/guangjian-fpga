import contextlib,json,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import resume_acceptance as app

sys.path.append(str(app.BASE))
sys.path.append(str(app.BASE.parent/'gray_transport_0105_20261025'))
from test_operator_host import FixtureRuntime
from test_sdk_transport import LocalSocket
from software_transport_peer import make_peer
import board_probe

ROOT=Path('C:/bx72_ymw_0105_20261015/r107resume_tests02')

class ResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ROOT.mkdir(exist_ok=False);cls.Peer,cls.engine=make_peer();cls.core=board_probe.core_module()
    def setUp(self):
        self.root=ROOT/self._testMethodName.split('_')[1];self.root.mkdir()
        patcher=patch.object(socket,'socket',LocalSocket);patcher.start();self.addCleanup(patcher.stop)
        self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__();self.addCleanup(lambda:self.peer.__exit__(None,None,None))
        self.runtime=FixtureRuntime(self.root,self.core,self.peer,self.engine)
        self.runtime.evidence_source='software_udp_peer';self.runtime.bridge_sensor_size=(96,32);self.runtime.reset_runtime=lambda:self.runtime
        self.source=self.root/'saved';plan=app.original.prepare(self.runtime)
        result=app.original.same_frozen(self.source,runtime=self.runtime,plan=plan)
        self.assertEqual(result['summary']['status'],'SAME_FROZEN_INPUT_VERIFIED')
        self.before=len(self.peer.captured);self.messages=[]
    def run_it(self,action=None):
        if action is None:
            def action():self.peer._reset();return 'KEY2_PRESSED'
        return app.run(self.root/'run',source=self.source,runtime=self.runtime,reset_action=action,emit=self.messages.append,interval=.02)
    def test_01_complete_reuses_frozen_and_keeps_eight_single_session(self):
        result=self.run_it();s=result['summary'];self.assertEqual(s['status'],'ENGINEERING_RESUME_PASSED',s['error'])
        new=self.peer.captured[self.before:];self.assertEqual(len(new),9);self.assertEqual([c['pixel_format'] for c in new],[49]*8+[50])
        self.assertEqual(len({c['identity']['session'] for c in new[:8]}),1)
        self.assertFalse(s['hardware_complete']);self.assertFalse(s['training_data']);self.assertFalse(s['frozen_recaptured'])
        self.assertIn('STARTED.',self.messages[0]);self.assertTrue(any('verified gray slots' in v for v in self.messages))
        group=app.bridge.load_group(self.root/'run/workflow/model_inputs',purpose='interface_test');self.assertEqual(len(group.observations),8)
    def test_02_saved_plane_tampering_blocks_every_new_CAP(self):
        record=app.read(self.source/'operator_summary.json')['row']['record'];folder=(self.source/record).parent
        (folder/'image.gray8').write_bytes(b'changed')
        result=self.run_it();self.assertEqual(result['summary']['phase'],'offline_preflight');self.assertEqual(result['summary']['status'],'FAILED')
        self.assertEqual(len(self.peer.captured),self.before)
    def test_03_fifth_CRC_failure_stops_and_preserves_four(self):
        start=self.peer._start_capture
        def corrupt(*args):
            if len(self.peer.captured)==self.before+4:self.peer.fault='payload_corrupt'
            return start(*args)
        self.peer._start_capture=corrupt
        r=self.run_it();self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(self.peer.captured)-self.before,5)
        s=app.read(self.root/'run/workflow/acquisition/operator_summary.json');self.assertEqual(s['saved_observations'],4);self.assertTrue(s['lights_off']['acknowledged'])
    def test_04_without_actual_reset_no_recovery_CAP(self):
        r=self.run_it(action=lambda:'KEY2_PRESSED');self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(r['summary']['phase'],'reset_readback')
        self.assertEqual(len(self.peer.captured)-self.before,8);self.assertFalse((self.root/'run/post_reset').exists())
    def test_05_OFF_failure_never_starts_new_CAP(self):
        self.peer.fault='off_ack_lost';r=self.run_it();self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(r['summary']['phase'],'startup_OFF')
        self.assertEqual(len(self.peer.captured),self.before)
    def test_06_export_failure_keeps_eight_without_extra_CAP(self):
        with patch.object(app.workflow.bridge,'export_batch',side_effect=OSError('injected export failure')):r=self.run_it()
        self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(self.peer.captured)-self.before,8)
        self.assertTrue((self.root/'run/workflow/acquisition.zip').exists())
    def test_07_wrong_binding_and_source_rejected_offline(self):
        with self.assertRaises(ValueError):app.review_frozen(self.source,sensor_size=(96,32),binding={'bit_sha256':'bad','candidate_source_commit':'bad'})
        self.assertEqual(len(self.peer.captured),self.before)
    def test_08_progress_handles_incomplete_and_unacknowledged_trace(self):
        folder=self.root/'watch';folder.mkdir();trace=folder/'frame_trace.jsonl'
        trace.write_text(json.dumps(dict(event='command',kind=10,ack=None,args='00000001ffffffff'))+'\n{"incomplete"')
        self.assertIsNone(app.trace_status(folder))
        trace.write_text(json.dumps(dict(event='command',kind=10,ack={'result':0},args='00000009ffffffff'))+'\n')
        self.assertEqual(app.trace_status(folder),'mask word 10/64800')

if __name__=='__main__':
    import hashlib,time
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')};start=time.monotonic()
    with (ROOT.parent/'r107resume_unittest02.txt').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResumeTests))
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    app.write(ROOT.parent/'r107resume_verification02.json',dict(status='PASS' if r.wasSuccessful() and before==after else 'FAIL',tests=r.testsRun,
        failures=len(r.failures),errors=len(r.errors),source_sha256=before,sources_unchanged=before==after,wall_seconds=time.monotonic()-start,
        hardware_contacted=False,network_scope='LocalSocket permits127.0.0.1 only'))
    print('RESUME_TESTS',r.testsRun,'PASS' if r.wasSuccessful() else 'FAIL',flush=True)
    raise SystemExit(0 if r.wasSuccessful() and before==after else 2)
