"""0106 host: offline planning and guarded loopback UDP only."""
import contextlib,copy,json,socket,tempfile,threading,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import board_probe
import frozen_diagnostic
import operator_host as host
from software_transport_peer import make_peer
from test_sdk_transport import LocalSocket

class FixtureRuntime:
    def __init__(self,root,core,peer,engine):
        self.lab=root;self.core=core;self.peer=peer;self.engine=engine
        self.marker=root/'software_fixture.txt';self.marker.write_bytes(b'fixture')
        self.held=False;self.constructed=0;self.changed_on_lock=False;self.executor_instance=None
        self.context=host.legacy.backend.Context('software_sample','unused',(5,7,81,21),bytes([int(i%5<2) for i in range(1701)]))
    def prepare(self,source):
        files={'source_preview.png':b'explicit software fixture only'}
        base=dict(source='software_fixture_only',sample_id=self.context.sample_id,roi=list(self.context.roi),board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1])
        if self.changed_on_lock and self.held:base['source']='changed_while_waiting'
        return base,self.context,files,{str(self.marker):host.sha(self.marker)}
    def candidate(self):
        return dict(ready=True,blocked_reasons=[],binding=None,evidence_source='software_fixture_only'),{},{}
    @contextlib.contextmanager
    def guard(self):
        self.held=True
        try:yield
        finally:self.held=False
    def executor(self,plan,out):
        assert self.held;self.constructed+=1
        e=host.sdk.TransportExecutor(board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1],ymw_root=self.engine.root/'ymw',
            output_root=out/'sdk_calls',pixel_format=plan['pixel_format'],evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.04,retries=2)
        off=e.lights_off;close=e.close
        def locked_off(**kw):assert self.held;return off(**kw)
        def locked_close():assert self.held;return close()
        e.lights_off=locked_off;e.close=locked_close;self.executor_instance=e;return e
    def archive(self,out,summary):
        assert not self.held
        return self.core.finalize_output(out,summary)

class OperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.Peer,cls.engine=make_peer();cls.core=board_probe.core_module()
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.socket_patch=patch.object(socket,'socket',LocalSocket);self.socket_patch.start();self.addCleanup(self.socket_patch.stop)
        self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__();self.addCleanup(lambda:self.peer.__exit__(None,None,None))
        self.runtime=FixtureRuntime(self.root,self.core,self.peer,self.engine);self.out=self.root/'batch'
        self.plan=self.build()
    def build(self,fmt=49):
        return host.build_plan(self.runtime,low=400,high=800,physical_specimen_id='software_plate',pose_id='software_pose',
            pair_status='development_trial',pair_reference='software only; not an exposure recommendation',pixel_format=fmt)[0]
    def run_host(self,**kwargs):
        return host.execute(self.plan,out=self.out,confirmed_same_pose=True,_runtime=self.runtime,single_timeout_s=1.5,**kwargs)
    def archive_summary(self,result):
        with zipfile.ZipFile(result['archive']) as z:
            inventory=json.loads(z.read('output_manifest.json'))['files']
            self.assertEqual(set(z.namelist()),set(inventory)|{'output_manifest.json'})
            for name,digest in inventory.items():self.assertEqual(host.sdk.support.sha_bytes(z.read(name)),digest)
            self.assertEqual(json.loads(z.read('operator_summary.json')),result['summary'])
        self.assertTrue(Path(result['archive']+'.sha256').is_file());return result['summary']
    def test_gray_full_eight_archived_and_cleanup_inside_lock(self):
        result=self.run_host();s=self.archive_summary(result)
        self.assertEqual(s['status'],'ACQUIRED_EIGHT_REVIEW_REQUIRED');self.assertEqual(s['saved_observations'],8)
        self.assertEqual(len(self.peer.captured),8);self.assertEqual(s['recorded_network_cost_totals']['capture_requests'],8)
        self.assertTrue(s['lights_off']['acknowledged']);self.assertFalse(self.runtime.held)
        self.assertFalse(list((self.out/'sdk_calls').glob('*/committed/image.rgb565')))
        dataset=host.read(self.out/'fixed_eight_dataset.json');self.assertEqual(dataset['formal_observations'],8)
    def test_rgb_full_eight_uses_true_color_payload(self):
        self.plan=self.build(1);s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'ACQUIRED_EIGHT_REVIEW_REQUIRED')
        self.assertEqual(len(list((self.out/'sdk_calls').glob('*/committed/image.rgb565'))),8)
    def test_fifth_crc_failure_stops_keeps_four_and_cost(self):
        start=self.peer._start_capture
        def fail_fifth(*args):
            if len(self.peer.captured)==4:self.peer.fault='payload_corrupt'
            return start(*args)
        self.peer._start_capture=fail_fifth
        s=self.archive_summary(self.run_host());self.assertEqual(s['status'],'FAILED');self.assertEqual(s['saved_observations'],4)
        self.assertEqual(len(self.peer.captured),5);self.assertEqual(s['recorded_network_cost_totals']['capture_requests'],5)
        self.assertTrue(s['lights_off']['acknowledged']);self.assertEqual(len(s['outcome_records']),6)
    def test_real_preflight_is_offline_and_blocks_unqualified_0106(self):
        with patch.object(socket,'socket',side_effect=AssertionError('No planning sockets')):
            runtime=host.Runtime('C:/BX72_0105_LAB')
            plan,_,files=host.build_plan(runtime,low=400,high=800,physical_specimen_id='sample005',pose_id='offline_only',
                pair_status='development_trial',pair_reference='offline test, not physical pose confirmation')
            self.assertFalse(plan['candidate']['ready']);self.assertTrue(files['source_preview.png'].startswith(b'\x89PNG'))
            self.assertIn('candidate_evidence/STATUS.json',files)
            with self.assertRaisesRegex(ValueError,'hardware gate blocked'):host.execute(plan,out=self.out,confirmed_same_pose=True,_runtime=runtime)
        self.assertFalse(self.out.exists())
    def test_no_pose_confirmation_never_constructs(self):
        with self.assertRaises(ValueError):host.execute(self.plan,out=self.out,_runtime=self.runtime)
        self.assertEqual(self.runtime.constructed,0);self.assertFalse(self.out.exists())
    def test_plan_format_tampering_never_constructs(self):
        self.plan['pixel_format']=1
        with self.assertRaises(ValueError):self.run_host()
        self.assertEqual(self.runtime.constructed,0)
    def test_source_change_while_locking_is_archived_before_sdk(self):
        self.runtime.changed_on_lock=True;s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'FAILED');self.assertEqual(self.runtime.constructed,0);self.assertFalse(self.peer.captured)
    def test_source_change_after_four_stops_before_fifth(self):
        audit=host.audit_result
        def change_after_four(*args):
            row=audit(*args)
            if len(self.peer.captured)==4:self.runtime.marker.write_bytes(b'changed')
            return row
        with patch.object(host,'audit_result',side_effect=change_after_four):s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'FAILED');self.assertEqual(len(self.peer.captured),4);self.assertEqual(s['saved_observations'],4)
        self.assertTrue(s['changed_source_or_build_files']);self.assertTrue(s['lights_off']['acknowledged'])
    def test_cancel_before_sdk_archives_without_capture(self):
        event=threading.Event();event.set();s=self.archive_summary(self.run_host(cancel=event))
        self.assertEqual(s['status'],'CANCELLED');self.assertEqual(self.runtime.constructed,0)
    def test_off_ack_loss_preserves_eight_but_requires_cleanup(self):
        self.peer.fault='off_ack_lost';s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'ACQUIRED_EIGHT_CLEANUP_REQUIRED');self.assertEqual(s['saved_observations'],8)
        self.assertFalse(s['lights_off']['acknowledged']);self.assertFalse(self.runtime.held)
    def test_old_firmware_never_captures(self):
        self.peer.firmware=0x0105;s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'FAILED');self.assertFalse(self.peer.captured)
    def test_existing_zip_never_overwritten(self):
        zip_path=self.out.with_name('batch.zip');zip_path.write_bytes(b'existing')
        with self.assertRaises(ValueError):self.run_host()
        self.assertEqual(zip_path.read_bytes(),b'existing');self.assertEqual(self.runtime.constructed,0)
    def test_changed_archived_plane_stops_before_next_request(self):
        audit=host.audit_result
        def change(*args):
            result=args[0];result.gray_path.write_bytes(b'changed')
            return audit(*args)
        with patch.object(host,'audit_result',side_effect=change):s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'FAILED');self.assertEqual(s['saved_observations'],0);self.assertEqual(len(self.peer.captured),1)
        self.assertTrue(s['lights_off']['acknowledged'])
    def test_constructor_failure_preserves_failure_archive(self):
        def fail(*args):assert self.runtime.held;raise OSError('injected constructor failure')
        self.runtime.executor=fail;s=self.archive_summary(self.run_host())
        self.assertEqual(s['status'],'FAILED');self.assertEqual(s['saved_observations'],0);self.assertFalse(self.runtime.held)
        self.assertTrue((self.out/'approved_plan.json').exists())
    def test_zip_failure_preserves_all_original_files(self):
        with patch.object(self.core.zipfile,'ZipFile',side_effect=OSError('injected archive disk error')):
            with self.assertRaises(self.core.ArchiveError):self.run_host()
        self.assertTrue((self.out/'fixed_eight_dataset.json').exists());self.assertTrue((self.out/'archive_error.json').exists())
        self.assertFalse(self.runtime.held)
    def test_readonly_probe_sends_only_status_and_no_capture(self):
        with patch.object(board_probe,'core_module',return_value=self.core):
            record=board_probe.probe(lab=self.root,board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1],timeout=.2)
        self.assertEqual(record['status'],'STATUS_CONFIRMED');self.assertEqual(record['firmware_hex'],'0x0106')
        self.assertEqual(len(record['queries']),2);self.assertEqual({row['kind'] for row in self.peer.received},{3});self.assertFalse(self.peer.captured)
    def test_shared_lock_conflict_blocks_probe_before_socket(self):
        with self.core.operator_lock(self.root),patch.object(socket,'socket',side_effect=AssertionError('Lock must be acquired first')):
            with self.assertRaises(RuntimeError):board_probe.probe(lab=self.root)

class FrozenTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'frozen'
        self.rgb=((np.arange(81,dtype=np.uint32)*7919+31)&65535).astype('>u2').tobytes()
        frozen_diagnostic.freeze(self.rgb,width=9,height=9,out=self.root)
        gray,sat=host.sdk.wire.planes_from_payload(self.rgb,9,9,1)
        # Independent grouping, including a one-pixel final group.
        g=gray.reshape(-1);s=sat.reshape(-1);raw=bytearray()
        for first in range(0,81,8):
            raw.extend(g[first:first+8].tobytes());raw.append(sum(int(s[first+i])<<(7-i) for i in range(min(8,81-first))))
        self.gray=bytes(raw)
    def test_full_planes_H1_H2_and_odd_tail_equal(self):
        result=frozen_diagnostic.verify(self.root,rgb_payload=self.rgb,gray_payload=self.gray)
        self.assertEqual(result['status'],'OFFLINE_FROZEN_BYTES_EQUIVALENT');self.assertFalse(result['hardware_freeze_established'])
        self.assertEqual(result['gray_sat_bytes'],92)
    def test_gray_corruption_rejected(self):
        changed=bytes([self.gray[0]^1])+self.gray[1:]
        with self.assertRaisesRegex(ValueError,'GRAY pixels'):frozen_diagnostic.verify(self.root,rgb_payload=self.rgb,gray_payload=changed)
    def test_sat_corruption_rejected(self):
        changed=bytearray(self.gray);changed[8]^=128
        with self.assertRaisesRegex(ValueError,'SAT1'):frozen_diagnostic.verify(self.root,rgb_payload=self.rgb,gray_payload=bytes(changed))
    def test_changed_rgb_is_not_the_frozen_input(self):
        with self.assertRaisesRegex(ValueError,'not the frozen input'):frozen_diagnostic.verify(self.root,rgb_payload=bytes([self.rgb[0]^1])+self.rgb[1:],gray_payload=self.gray)
    def test_nonzero_padding_rejected(self):
        with self.assertRaisesRegex(ValueError,'tail padding'):frozen_diagnostic.verify(self.root,rgb_payload=self.rgb,gray_payload=self.gray[:-1]+bytes([self.gray[-1]|1]))

if __name__=='__main__':unittest.main(verbosity=2)
