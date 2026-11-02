"""Run the inherited strict SDK regressions and the actual acceptance window."""
import argparse,hashlib,json,os,socket,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
import generate_acceptance as gen
import sdk_transport as sdk
import acceptance_operator as acceptance

sys.path.append(str(gen.BASE))
import test_operator_host as fixtures
import software_transport_peer

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in gen.HERE.glob('*.py')}
    source_copy=out/'executed_sources';source_copy.mkdir()
    for name in before:(source_copy/Path(name).name).write_bytes(Path(name).read_bytes())
    original=(gen.BASE/'test_sdk_transport.py').read_bytes()
    text=original.decode().replace('0106','0107')
    target=out/'test_inherited_sdk.py';target.write_text(text,encoding='utf-8',newline='\n')
    import importlib.util
    spec=importlib.util.spec_from_file_location('acceptance_inherited_tests',target);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # A persistent, short path prevents fixture failures at Windows MAX_PATH.
    os.environ['GRAY_SDK_TEST_OUTPUT']=str(out/'sdk');(out/'sdk').mkdir()
    Peer,engine=software_transport_peer.make_peer();core=fixtures.board_probe.core_module()
    class Extended(module.SDKTests):
        def test_36_dual_view_one_CAP_original_rgb_and_exact_planes(self):
            with self.session(fmt=50) as (peer,e):
                r=self.capture(e);self.assertEqual(len(peer.captured),1)
                rgb,g,s=sdk.wire.dual_view.decode(r.raw_payload,81,21,codec=sdk.wire.codec)
                self.assertEqual(sdk.wire.legacy.crc64_ecma(rgb),r.metadata['rgb_crc64'])
                self.assertEqual((r.record_path.parent/'same_frame.rgb565').read_bytes(),rgb)
                self.assertEqual(r.metadata['payload_bytes'],5316)
        def test_37_dual_view_wrong_gray_rejected_even_with_self_consistent_length(self):
            with self.session(fmt=50) as (_,e):
                r=self.capture(e);bad=bytearray(r.raw_payload);bad[16]^=1
                with self.assertRaisesRegex(ValueError,'Same frozen'):sdk.wire.planes_from_payload(bytes(bad),81,21,50)
        def test_38_dual_view_wrong_sat_rejected(self):
            with self.session(fmt=50) as (_,e):
                r=self.capture(e);bad=bytearray(r.raw_payload);bad[24]^=128
                with self.assertRaisesRegex(ValueError,'Same frozen'):sdk.wire.planes_from_payload(bytes(bad),81,21,50)
        def test_39_full_actual_window_and_export(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                r=acceptance.run(root/'output',runtime=runtime)
                self.assertEqual(r['summary']['status'],'ENGINEERING_WINDOW_PASSED_RESET_PENDING',r['summary']['error'])
                self.assertEqual(len(peer.captured),9)
                self.assertEqual([row['pixel_format'] for row in peer.captured],[50]+[49]*8)
                group=json.loads((root/'output/workflow/model_inputs/group.json').read_bytes())
                self.assertFalse(group['training_data']);self.assertEqual(len(group['entries']),8)
                self.assertTrue((root/'output.zip').exists())
        def test_40_failed_dual_stops_before_eight(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw',fault='payload_corrupt') as peer:
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                r=acceptance.run(root/'output',runtime=runtime)
                self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(r['summary']['phase'],'same_frozen')
                self.assertEqual(len(peer.captured),1);self.assertFalse((root/'output/workflow').exists())
        def test_41_offline_real_entry_missing_binding_never_opens_socket(self):
            with patch.object(socket,'socket',side_effect=AssertionError('Physical socket forbidden')),patch.object(acceptance,'read',return_value={'schema':'invalid'}):
                with self.assertRaises((OSError,ValueError)):acceptance.prepare()
        def test_42_reset_readback_before_bind_and_fresh_recovery(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                runtime.reset_runtime=lambda:runtime
                def reset():peer._reset();return 'KEY2_PRESSED'
                r=acceptance.run(root/'output',runtime=runtime,reset_action=reset)
                self.assertEqual(r['summary']['status'],'ENGINEERING_WINDOW_PASSED',r['summary']['error'])
                self.assertTrue(r['summary']['button_reset_context_and_recovery_verified'])
                self.assertFalse(r['summary']['hardware_button_reset_verified'])
                self.assertEqual(len(peer.captured),10)
                self.assertEqual([q['kind'] for q in r['summary']['results']['reset']['queries']],[3,14,9])
        def test_43_no_button_press_rejected_before_post_reset_CAP(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                runtime.reset_runtime=lambda:runtime
                r=acceptance.run(root/'output',runtime=runtime,reset_action=lambda:'KEY2_PRESSED')
                self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(r['summary']['phase'],'reset_readback')
                self.assertFalse(r['summary']['hardware_button_reset_verified']);self.assertEqual(len(peer.captured),9)
                self.assertTrue((root/'output/reset_readback.json').exists())
        def test_44_fifth_gray_CRC_failure_preserves_four_and_stops(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                start_capture=peer._start_capture
                def corrupt(*args):
                    if len(peer.captured)==5:peer.fault='payload_corrupt'
                    return start_capture(*args)
                peer._start_capture=corrupt
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                r=acceptance.run(root/'output',runtime=runtime)
                self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(peer.captured),6)
                s=json.loads((root/'output/workflow/acquisition/operator_summary.json').read_bytes())
                self.assertEqual(s['saved_observations'],4);self.assertTrue(s['lights_off']['acknowledged'])
                self.assertFalse((root/'output/workflow/model_inputs').exists())
        def test_45_export_failure_preserves_all_eight_without_recapture(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                with patch.object(acceptance.workflow.bridge,'export_batch',side_effect=OSError('injected export failure')):
                    r=acceptance.run(root/'output',runtime=runtime)
                self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(peer.captured),9)
                self.assertEqual(r['summary']['results']['workflow']['status'],'EXPORT_FAILED_CAPTURE_PRESERVED')
                self.assertTrue((root/'output/workflow/acquisition.zip').is_file())
        def test_46_unacknowledged_off_blocks_export(self):
            root=self.root/'win';root.mkdir()
            with self.Peer(self.engine.root/'ymw') as peer:
                start_capture=peer._start_capture
                def fail_off(*args):
                    if len(peer.captured)==8:peer.fault='off_ack_lost'
                    return start_capture(*args)
                peer._start_capture=fail_off
                runtime=fixtures.FixtureRuntime(root,core,peer,self.engine)
                runtime.evidence_source='software_udp_peer';runtime.bridge_sensor_size=(96,32)
                r=acceptance.run(root/'output',runtime=runtime)
                self.assertEqual(r['summary']['status'],'FAILED');self.assertEqual(len(peer.captured),9)
                self.assertFalse((root/'output/workflow/model_inputs').exists())
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Extended)
    with (out/'unittest.txt').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in gen.HERE.glob('*.py')}
    stable=before==after
    report=dict(status='PASS' if result.wasSuccessful() and stable else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),hardware_contacted=False,
        network_scope='LocalSocket rejects every non-127.0.0.1 bind/send/connect',
        inherited_test_baseline_sha256=hashlib.sha256(original).hexdigest(),
        source_sha256=before,sources_unchanged=stable,
        wall_seconds=time.monotonic()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)
    raise SystemExit(0 if result.wasSuccessful() and stable else 2)

if __name__=='__main__':main()
