"""Offline and loopback-only host integration. Physical endpoints prohibited."""
import contextlib,copy,importlib.util,json,socket,tempfile,threading,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import paired_host as host
import test_fixed_pair_runner as existing

fixtures=existing.fixtures

class FixtureRuntime:
    def __init__(self,root,core):
        self.lab=root;self.core=core;self.count=0;self.held=False;self.port_calls=0;self.change_on_lock=False
        self.marker=root/'runtime_fixture.txt';self.marker.write_bytes(b'fixture')
        self.clock=fixtures.Clock();self.fake=fixtures.FakePort(self.clock)
        self.context=fixtures.context()

    def prepare(self,source):
        self.count+=1
        files={'source_preview.png':b'explicit software fixture preview',
               'source_session.json':b'{"software_fixture":true}',
               'source_roi_session.json':b'{"software_fixture":true}'}
        base=dict(source='software_fixture_only',sample_id=self.context.sample_id,roi=list(self.context.roi),
            source_full_png_sha256='a'*64,source_session_sha256=host.backend.digest(files['source_session.json']),
            source_roi_session_sha256=host.backend.digest(files['source_roi_session.json']),native_mask_sha256=self.context.mask_sha256,
            board='192.168.0.2',bind='192.168.0.3',port=5000)
        if self.change_on_lock and self.held:base['source_session_sha256']='b'*64
        return base,self.context,files,{str(self.marker):host.sha(self.marker)}

    @contextlib.contextmanager
    def guard(self):
        self.held=True
        try:yield
        finally:self.held=False

    def port(self,base,out):
        assert self.held;self.port_calls+=1
        original_off=self.fake.lights_off;original_close=self.fake.close
        def off():assert self.held;return original_off()
        def close():assert self.held;return original_close()
        self.fake.lights_off=off;self.fake.close=close
        return self.fake

    def archive(self,out,summary):return self.core.finalize_output(out,summary)

class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=host.Runtime('C:/BX72_0105_LAB')
        cls.core=cls.runtime.core
        # SHA-verified by the unchanged core; do not load or run the exposure loop.
        cls.engine=cls.core.load_engine(include_peer=True)
        spec=importlib.util.spec_from_file_location('_fixed_pair_test_peer',cls.core.ADAPTER/'software_peer.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cls.Peer=module.make_peer_class(cls.engine)

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.service=FixtureRuntime(self.root,self.core);self.out=self.root/'round'
        self.plan,_,_=host.build_plan(self.service,low=400,high=800,physical_specimen_id='offline_plate',
            pose_id='fixture_pose',pair_status='development_trial',pair_reference='software fixture only')

    def run_fixture(self,**kw):
        args=dict(out=self.out,confirmed_same_pose=True,_runtime=self.service)
        args.update(kw)
        with patch.object(socket,'socket',side_effect=AssertionError('No sockets in offline fixtures')):
            return host.execute(self.plan,**args)

    def verify_archive(self,result):
        with zipfile.ZipFile(result['archive']) as z:
            manifest=json.loads(z.read('output_manifest.json'))['files']
            self.assertEqual(set(z.namelist()),set(manifest)|{'output_manifest.json'})
            for name,digest in manifest.items():self.assertEqual(host.backend.digest(z.read(name)),digest)
            summary=json.loads(z.read('operator_summary.json'))
        self.assertEqual(summary,result['summary']);return summary

    def test_actual_02_03_preflight_is_socket_free(self):
        with patch.object(socket,'socket',side_effect=AssertionError('Planning must not open sockets')):
            plan,context,files=host.build_plan(self.runtime,low=400,high=800,physical_specimen_id='sample005',
                pose_id='offline_plan_only',pair_status='development_trial',pair_reference='contract test, not exposure freeze')
        self.assertEqual(plan['source_contract']['gain16'],16);self.assertEqual(plan['formal_observations'],8)
        self.assertEqual(len(context.mask),context.roi[2]*context.roi[3]);self.assertTrue(files['source_preview.png'].startswith(b'\x89PNG'))
        self.assertIn('source_full.rgb565',files);self.assertIn('source_roi.rgb565',files)
        self.assertGreater(len(plan['runtime_sha256']),100)

    def test_complete_group_and_full_zip_inventory(self):
        result=self.run_fixture();summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'ACQUIRED_EIGHT_REVIEW_REQUIRED');self.assertEqual(summary['saved_observations'],8)
        self.assertEqual(summary['evidence_source'],'software_fake');self.assertFalse(summary['physical_freshness_verified'])
        self.assertTrue(summary['lights_off']['acknowledged']);self.assertTrue(self.service.fake.closed)
        self.assertTrue(Path(result['archive']+'.sha256').exists());self.assertFalse(self.service.held)
        self.assertGreaterEqual(summary['host_preflight_ms'],0)

    def test_fifth_failure_still_archives_partial_and_closes(self):
        self.service.fake.behaviors=[None]*4+[RuntimeError('fifth fixture failure')]
        result=self.run_fixture();summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'FAILED');self.assertEqual(summary['saved_observations'],4)
        self.assertEqual(len(self.service.fake.calls),5);self.assertTrue(self.service.fake.closed)

    def test_unconfirmed_never_prepares_or_creates_port(self):
        count=self.service.count
        with self.assertRaises(ValueError):self.run_fixture(confirmed_same_pose=False)
        self.assertEqual(self.service.count,count);self.assertEqual(self.service.port_calls,0);self.assertFalse(self.out.exists())

    def test_forged_endpoint_rejected_before_port(self):
        self.plan['source_contract']['board']='127.0.0.1'
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertEqual(self.service.port_calls,0)

    def test_changed_source_under_lock_never_initializes_port(self):
        self.service.change_on_lock=True
        result=self.run_fixture();summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'FAILED');self.assertEqual(self.service.port_calls,0)
        self.assertFalse(self.service.held)

    def test_changed_runtime_after_capture_never_reports_complete(self):
        def change(payload):self.service.marker.write_bytes(b'changed');return payload
        self.service.fake.behaviors=[change]
        result=self.run_fixture();summary=self.verify_archive(result)
        self.assertEqual(summary['backend_status'],'COMPLETE_EIGHT');self.assertEqual(summary['status'],'FAILED')
        self.assertEqual(summary['changed_runtime_files'],[str(self.service.marker)])

    def test_existing_zip_blocks_new_acquisition(self):
        self.out.with_name('round.zip').write_bytes(b'previous archive')
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertEqual(self.service.port_calls,0);self.assertEqual(self.out.with_name('round.zip').read_bytes(),b'previous archive')

    def test_cancel_before_sdk_preserves_failed_group(self):
        cancel=threading.Event();cancel.set()
        result=self.run_fixture(cancel=cancel);summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'CANCELLED');self.assertEqual(self.service.port_calls,0)

    def test_archive_failure_preserves_raw_data(self):
        with patch.object(self.core.zipfile,'ZipFile',side_effect=OSError('fixture disk error')):
            with self.assertRaises(self.core.ArchiveError):self.run_fixture()
        self.assertTrue((self.out/'summary.json').exists());self.assertFalse(self.out.with_name('round.zip').exists())
        self.assertTrue(self.service.fake.closed)

    def run_sdk_peer(self,fault=None):
        original_socket=socket.socket
        class LoopbackOnly(original_socket):
            def bind(sock,address):
                if address[0]!='127.0.0.1':raise AssertionError('Non-loopback bind prohibited')
                return super().bind(address)
            def sendto(sock,data,*args):
                if args[-1][0]!='127.0.0.1':raise AssertionError('Physical endpoint prohibited')
                return super().sendto(data,*args)
            def connect(sock,address):
                if address[0]!='127.0.0.1':raise AssertionError('Physical endpoint prohibited')
                return super().connect(address)
        with patch.object(socket,'socket',LoopbackOnly),self.Peer(sensor_size=(32,32),fault_plan={5:fault} if fault else {}) as peer:
            actual=self.engine.sdk.acquisition_executor.AcquisitionExecutor
            def sdk_factory(**kwargs):
                self.assertTrue(self.service.held);self.assertEqual(kwargs['evidence_source'],'real_board')
                self.assertEqual(kwargs['board'],'192.168.0.2')
                kwargs.update(board='127.0.0.1',bind='127.0.0.1',port=peer.endpoint[1],evidence_source='software_udp_peer',sensor_size=(32,32),command_timeout=.05,retries=2)
                return actual(**kwargs)
            shim=SimpleNamespace(root=self.engine.root,sdk=SimpleNamespace(acquisition_executor=SimpleNamespace(AcquisitionExecutor=sdk_factory)))
            def real_port(base,out):
                self.service.port_calls+=1
                with patch.object(self.core,'load_engine',return_value=shim):return host.Runtime.port(self.service,base,out)
            self.service.port=real_port
            result=host.execute(self.plan,out=self.out,confirmed_same_pose=True,_runtime=self.service,single_timeout_s=3)
            captures=copy.deepcopy(peer.captured)
        return result,captures

    def test_exact_sdk_eight_over_guarded_loopback(self):
        result,captures=self.run_sdk_peer();summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'ACQUIRED_EIGHT_REVIEW_REQUIRED');self.assertEqual(summary['evidence_source'],'software_udp_peer')
        self.assertEqual(len(captures),8);self.assertTrue(summary['lights_off']['acknowledged'])
        self.assertEqual([c['parameters']['exposure_lines'] for c in captures],[400,800]*4)
        self.assertTrue(list((self.out/'sdk_calls').glob('*/frame_trace.jsonl')))

    def test_exact_sdk_fifth_crc_failure_stops_over_loopback(self):
        result,captures=self.run_sdk_peer('old_image');summary=self.verify_archive(result)
        self.assertEqual(summary['status'],'FAILED');self.assertEqual(summary['saved_observations'],4)
        self.assertEqual(len(captures),5)

if __name__=='__main__':unittest.main(verbosity=2)
