import contextlib,copy,importlib.util,json,socket,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import fixed_pair_runner as runner

spec=importlib.util.spec_from_file_location('_fixed_pair_fixtures',runner.DEPENDENCIES/'tests/fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)

class FixedPairRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)/'new';self.clock=fixtures.Clock();self.port=fixtures.FakePort(self.clock)
        self.context=fixtures.context();self.held=False;self.factory_calls=0
        self.source={'verified_from_02_03':True,'source_full_png_sha256':'a'*64,'source_session_sha256':'b'*64,
                     'source_roi_session_sha256':'c'*64,'native_mask_sha256':self.context.mask_sha256,'physical_specimen_id':'offline_plate'}
        original_capture=self.port.capture;original_off=self.port.lights_off;original_close=self.port.close
        def capture(*args,**kw):self.assertTrue(self.held);return original_capture(*args,**kw)
        def off():self.assertTrue(self.held);return original_off()
        def close():self.assertTrue(self.held);return original_close()
        self.port.capture=capture;self.port.lights_off=off;self.port.close=close

    @contextlib.contextmanager
    def guard(self):
        self.assertFalse(self.held);self.held=True
        try:yield
        finally:self.held=False

    def factory(self):
        self.assertTrue(self.held);self.factory_calls+=1;return self.port

    def run_round(self,**kw):
        args=dict(low=400,high=800,pair_status='development_trial',pair_reference='offline fixture, not frozen physical selection',
            source_binding=self.source,port_factory=self.factory,guard_factory=self.guard,out=self.out,
            pose_confirmed=True,clock=self.clock)
        args.update(kw)
        with patch.object(socket,'socket',side_effect=AssertionError('offline tests forbid sockets')):
            return runner.run_fixed_eight(self.context,**args)

    def test_exact_eight_pairs_unique_files_no_search_or_retry(self):
        def factory_with_nested_metadata():
            log=self.out/'sdk_calls'/'fixture_call';log.mkdir(parents=True)
            (log/'manifest.json').write_text('{"fixture":true}',encoding='utf-8')
            (log/'completion.json').write_text('{"status":"fixture"}',encoding='utf-8')
            return self.factory()
        result=self.run_round(port_factory=factory_with_nested_metadata);self.assertEqual(result['status'],'COMPLETE_EIGHT')
        self.assertEqual([(r['channel'],r['exposure_lines']) for r in self.port.calls],[(c,e) for c in range(1,5) for e in (400,800)])
        self.assertEqual(len({r['directory'] for r in result['observations']}),8)
        self.assertEqual(result['validated_observation_transaction_frames'],40)
        self.assertFalse(result['automatic_exposure_search']);self.assertEqual(result['automatic_observation_retries'],0)
        self.assertEqual(result['evidence_source'],'software_fake');self.assertFalse(result['physical_freshness_verified'])
        self.assertEqual(result['physical_specimen_id'],'offline_plate')
        self.assertTrue(self.port.off_called);self.assertTrue(self.port.closed);self.assertFalse(self.held)
        m=json.loads((self.out/'manifest.json').read_text());completion=json.loads((self.out/'completion.json').read_text())
        self.assertIn('sdk_calls/fixture_call/manifest.json',m['sha256'])
        self.assertIn('sdk_calls/fixture_call/completion.json',m['sha256'])
        self.assertNotIn('manifest.json',m['sha256']);self.assertNotIn('completion.json',m['sha256'])
        self.assertEqual(completion['manifest_sha256'],runner.digest((self.out/'manifest.json').read_bytes()))
        for name,sha in m['sha256'].items():self.assertEqual(runner.digest((self.out/name).read_bytes()),sha)

    def test_fifth_failure_stops_no_retry_preserves_cost_and_closes(self):
        self.port.behaviors=[None]*4+[RuntimeError('fifth fixture failure')]
        with self.assertRaises(runner.RoundFailure) as error:self.run_round()
        self.assertEqual(len(self.port.calls),5);self.assertEqual(len(error.exception.summary['observations']),4)
        self.assertTrue(error.exception.summary['attempts'][-1]['cost']['unavailable'])
        self.assertTrue(self.port.off_called);self.assertTrue(self.port.closed)

    def test_wrong_exposure_or_registers_rejected_not_retried(self):
        def corrupt(p):p.record['camera_readback']['gain16']=32;return p
        self.port.behaviors=[corrupt]
        with self.assertRaises(runner.RoundFailure) as error:self.run_round()
        self.assertEqual(len(self.port.calls),1);self.assertEqual(error.exception.summary['attempts'][0]['status'],'REJECTED')
        self.assertFalse(error.exception.summary['observations'])

    def test_duplicate_published_identity_rejected(self):
        self.port.behaviors=[None,lambda p:fixtures.reidentify(p,fixtures.identity(1))]
        with self.assertRaises(runner.RoundFailure):self.run_round()
        self.assertEqual(len(self.port.calls),2);self.assertTrue(self.port.closed)

    def test_same_pixels_new_identity_are_valid(self):
        result=self.run_round();self.assertEqual(len({r['raw_sha256'] for r in result['observations']}),1)
        self.assertEqual(len({r['identity']['request_id'] for r in result['observations']}),8)

    def test_frame_id_wrap_valid(self):
        self.port.first_frame=65535;result=self.run_round()
        self.assertEqual([r['identity']['frame_id'] for r in result['observations']][:3],[65535,0,1])

    def test_missing_pose_or_source_never_initializes_sdk(self):
        with self.assertRaises(ValueError):self.run_round(pose_confirmed=False)
        bad=dict(self.source,native_mask_sha256='d'*64)
        with self.assertRaises(ValueError):self.run_round(source_binding=bad)
        self.assertEqual(self.factory_calls,0);self.assertFalse(self.out.exists())

    def test_existing_output_never_initializes_sdk(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):self.run_round()
        self.assertEqual(self.factory_calls,0)

    def test_cancel_before_start_and_after_first(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(runner.RoundFailure):self.run_round(cancel=cancel)
        self.assertEqual(self.factory_calls,0)
        self.out=Path(self.temp.name)/'second';cancel.clear()
        def stop(p):cancel.set();return p
        self.port.behaviors=[stop]
        with self.assertRaises(runner.RoundFailure) as error:self.run_round(cancel=cancel)
        self.assertEqual(error.exception.summary['status'],'CANCELLED');self.assertEqual(len(self.port.calls),1)
        self.assertTrue(self.port.closed)

    def test_init_time_is_included_in_deadline(self):
        def slow_factory():self.clock.time+=2;return self.factory()
        with self.assertRaises(runner.RoundFailure):self.run_round(port_factory=slow_factory,timeout_s=1)
        self.assertFalse(self.port.calls);self.assertTrue(self.port.off_called);self.assertTrue(self.port.closed)

    def test_missing_off_ack_never_success(self):
        self.port.off_ack=False
        with self.assertRaises(runner.RoundFailure) as error:self.run_round()
        self.assertEqual(len(error.exception.summary['observations']),8)
        self.assertEqual(json.loads((self.out/'completion.json').read_text())['status'],'FAILED')
        self.assertTrue(self.port.closed)

    def test_invalid_cost_is_recorded_as_unknown_and_rejected(self):
        def corrupt(p):p.record['cost']={'invalid':float('nan')};return p
        self.port.behaviors=[corrupt]
        with self.assertRaises(runner.RoundFailure) as error:self.run_round()
        self.assertTrue(error.exception.summary['attempts'][0]['cost']['unavailable']);self.assertTrue(self.port.closed)

    def test_fake_adapter_cannot_claim_a_verified_sdk(self):
        self.port.execution_mode='sdk_adapter'
        with self.assertRaises(runner.RoundFailure):self.run_round()
        self.assertFalse(self.port.calls);self.assertTrue(self.port.off_called);self.assertTrue(self.port.closed)

if __name__=='__main__':unittest.main(verbosity=2)
