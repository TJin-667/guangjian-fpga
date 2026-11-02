"""Real UDP SDK tests limited to 127.0.0.1; never physical capture."""
import contextlib,json,os,shutil,socket,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import sdk_transport as sdk
from software_transport_peer import make_peer
from fixed_eight import validate_eight

class LocalSocket(socket.socket):
    def bind(self,address):
        if address[0]!='127.0.0.1':raise AssertionError('Physical bind forbidden')
        return super().bind(address)
    def sendto(self,data,*args):
        if args[-1][0]!='127.0.0.1':raise AssertionError('Physical destination forbidden')
        return super().sendto(data,*args)
    def connect(self,address):
        if address[0]!='127.0.0.1':raise AssertionError('Physical connection forbidden')
        return super().connect(address)

class SDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.Peer,cls.engine=make_peer()

    def setUp(self):
        patcher=patch.object(socket,'socket',LocalSocket);patcher.start();self.addCleanup(patcher.stop)
        root=os.environ.get('GRAY_SDK_TEST_OUTPUT')
        if root:self.root=Path(root)/self._testMethodName;self.root.mkdir(parents=True,exist_ok=False)
        else:
            tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.mask=bytes([int(i%5<2) for i in range(81*21)])

    @contextlib.contextmanager
    def session(self,fmt=49,fault='',**kwargs):
        with self.Peer(self.engine.root/'ymw',fault=fault) as peer:
            with sdk.TransportExecutor(board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',
                ymw_root=self.engine.root/'ymw',output_root=self.root/'sdk_calls',pixel_format=fmt,
                evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.04,retries=2,**kwargs) as executor:
                try:yield peer,executor
                finally:self.cleanup=executor.lights_off(timeout_s=.15)

    def capture(self,executor,**kwargs):
        args=dict(light_channel=1,brightness=128,exposure_lines=400,gain16=16,roi=(5,7,81,21),
            board_mask=self.mask,timeout_s=1,sample_id='software_sample',round_id='software_pose')
        args.update(kwargs);return executor.acquire(**args)

    def outcome(self):
        paths=[p for p in (self.root/'sdk_calls').glob('*/outcome.json') if not p.parent.name.startswith('cleanup_')]
        return [json.loads(p.read_bytes()) for p in paths]

    def assert_failed(self,executor,**kwargs):
        with self.assertRaises(sdk.AcquisitionError) as error:self.capture(executor,**kwargs)
        self.assertFalse(list((self.root/'sdk_calls').glob('*/committed')))
        self.assertEqual(self.outcome()[-1]['status'],'FAILED');return error.exception

    def test_01_gray_archive_true_payload_and_final_query_bytes(self):
        with self.session() as (peer,e):
            result=self.capture(e);record=result.metadata;folder=result.record_path.parent
            self.assertEqual(record['status'],'COMMITTED');self.assertEqual(record['pixel_format'],49)
            self.assertEqual(record['payload_bytes'],1914);self.assertEqual(result.png_path.name,'image.gray.png')
            self.assertFalse((folder/'image.rgb565').exists());self.assertFalse((folder/'image.png').exists())
            raw=(folder/'metadata_packet.bin').read_bytes()
            self.assertEqual(sdk.wire.decode_metadata(raw,record['metadata_query_seq']),record['diagnostic'])
            self.assertEqual(int.from_bytes(raw[6:8],'big'),record['diagnostic']['seq'])
            self.assertGreaterEqual(peer.valid_query_count,3)
            events=[json.loads(line) for line in (folder.parent/'frame_trace.jsonl').read_text().splitlines()]
            queries=[v for v in events if v['event']=='command' and v['kind']==9]
            self.assertEqual(record['metadata_query_seq'],queries[-1]['seq']);self.assertEqual(len({q['seq'] for q in queries}),len(queries))
            self.assertTrue(record['strict_verified']);self.assertFalse(record['physical_freshness_verified'])
            for name,digest in record['archived_file_sha256'].items():self.assertEqual(sdk.support.sha_file(folder/name),digest)
            sat=np.unpackbits(np.frombuffer(result.sat_path.read_bytes(),np.uint8),bitorder='big')
            np.testing.assert_array_equal(sat[:1701].reshape(21,81),result.validated['sat']);self.assertFalse(sat[1701:].any())
        self.assertTrue(self.cleanup['acknowledged'])

    def test_02_rgb_archive_preserves_rgb_and_crc_semantics(self):
        with self.session(fmt=1) as (peer,e):
            result=self.capture(e);record=result.metadata
            self.assertEqual(len(result.raw_payload),3402);self.assertEqual(result.png_path.name,'image.png')
            self.assertEqual(record['payload_crc64'],record['rgb_crc64']);self.assertTrue((result.record_path.parent/'image.rgb565').is_file())

    def test_03_same_synthetic_input_cross_format_planes_equal(self):
        results=[]
        for fmt in (1,49):
            self.root=self.root/str(fmt)
            with self.session(fmt=fmt) as (_,e):results.append(self.capture(e))
        np.testing.assert_array_equal(results[0].validated['gray'],results[1].validated['gray'])
        np.testing.assert_array_equal(results[0].validated['sat'],results[1].validated['sat'])
        self.assertEqual(results[0].metadata['rgb_crc64'],results[1].metadata['rgb_crc64'])

    def test_04_eight_requests_mask_reuse_forward_identity_and_frame_wrap(self):
        with self.session(initial_seq=65520) as (peer,e):
            peer.fid=65534;records=[]
            for channel in range(1,5):
                for role,exposure in [('low',400),('high',800)]:
                    r=self.capture(e,light_channel=channel,exposure_lines=exposure)
                    records.append(dict(channel=channel,role=role,sample_id='software_sample',pose_id='software_pose',validated=r.validated))
            result=validate_eight(records,sample_id='software_sample',pose_id='software_pose',low=400,high=800,
                roi=[5,7,81,21],board=np.frombuffer(self.mask,np.uint8).reshape(21,81).astype(bool))
            self.assertEqual(result['formal_observations'],8);self.assertEqual(len(peer.captured),8)
            self.assertEqual([r['validated']['metadata']['identity']['frame_id'] for r in records][:3],[65535,0,1])
            self.assertEqual(sum(r['cost']['mask_commands'] for r in self.outcome()),(1701+31)//32+1)

    def test_05_reconnect_accepts_old_invalid_snapshot_but_new_capture_nonce(self):
        with self.session() as (peer,e):
            first=self.capture(e);port=e.sock.getsockname()[1];e.reconnect();second=self.capture(e)
            self.assertNotEqual(first.metadata['session'],second.metadata['session']);self.assertNotEqual(port,e.sock.getsockname()[1])
            self.assertEqual(second.metadata['identity']['request_id'],1);self.assertEqual(second.metadata['pixel_format'],49)

    def test_06_old_firmware_rejected_before_capture(self):
        with self.session() as (peer,e):
            peer.firmware=0x0105;error=self.assert_failed(e)
            self.assertEqual(error.code,'UNSUPPORTED_FIRMWARE');self.assertFalse(peer.captured)

    def test_07_bad_capability_rejected_before_capture(self):
        with self.session(fault='bad_capability') as (peer,e):self.assert_failed(e);self.assertFalse(peer.captured)

    def test_08_wrong_capability_query_sequence_rejected(self):
        with self.session(fault='wrong_capability_seq') as (peer,e):self.assert_failed(e);self.assertFalse(peer.captured)

    def test_09_format_ack_does_not_replace_readback(self):
        with self.session(fault='ignored_format_set') as (peer,e):
            error=self.assert_failed(e);self.assertEqual(error.code,'FORMAT_MISMATCH');self.assertFalse(peer.captured)

    def test_10_format_set_unknown_completion_poisoned_identical_retries(self):
        with self.session(fault='format_set_ack_lost') as (peer,e):
            error=self.assert_failed(e);self.assertTrue(error.needs_reset);self.assertTrue(e._poisoned)
            sent=[r for r in peer.received if r['kind']==15];self.assertEqual(len(sent),2)
            self.assertEqual(sent[0]['request_hex'],sent[1]['request_hex']);count=peer.commands
            with self.assertRaises(sdk.AcquisitionError) as second:self.capture(e)
            self.assertEqual(second.exception.code,'NEEDS_RESET');self.assertEqual(peer.commands,count)

    def test_11_second_final_descriptor_query_must_stay_stable(self):
        with self.session(fault='descriptor_changed_second') as (_,e):
            self.assertEqual(self.assert_failed(e).code,'DIAGNOSTIC_CHANGED')

    def test_12_third_final_descriptor_query_must_stay_stable(self):
        with self.session(fault='descriptor_changed_third') as (_,e):
            self.assertEqual(self.assert_failed(e).code,'DIAGNOSTIC_CHANGED')

    def test_13_payload_crc_corruption_rejected(self):
        with self.session(fault='payload_corrupt') as (_,e):self.assert_failed(e)

    def test_14_wrong_payload_crc_descriptor_rejected(self):
        with self.session(fault='wrong_payload_crc') as (_,e):self.assert_failed(e)

    def test_15_wrong_H1_rejected(self):
        with self.session(fault='wrong_H1') as (_,e):self.assert_failed(e)

    def test_16_wrong_H2_rejected(self):
        with self.session(fault='wrong_H2') as (_,e):self.assert_failed(e)

    def test_17_wrong_packet_format_rejected(self):
        with self.session(fault='wrong_packet_format') as (_,e):self.assert_failed(e)

    def test_18_wrong_metadata_format_rejected(self):
        with self.session(fault='wrong_format') as (_,e):self.assert_failed(e)

    def test_19_wrong_session_rejected(self):
        with self.session(fault='wrong_session') as (_,e):self.assert_failed(e)

    def test_20_missing_packet_timeout_retired_without_commit(self):
        with self.session(fault='missing_packet') as (_,e):self.assert_failed(e,timeout_s=.2)

    def test_21_conflicting_duplicate_rejected(self):
        with self.session(fault='conflict') as (_,e):self.assert_failed(e)

    def test_22_identical_duplicate_accepted(self):
        with self.session(fault='duplicate') as (_,e):
            result=self.capture(e);self.assertGreater(result.metadata['cost']['duplicate_image_packets'],0)

    def test_23_reordered_packets_accepted(self):
        with self.session(fault='out_of_order') as (_,e):self.assertEqual(self.capture(e).metadata['status'],'COMMITTED')

    def test_24_capture_metadata_wrong_query_sequence_rejected(self):
        with self.session(fault='wrong_query_seq') as (_,e):self.assert_failed(e,timeout_s=.3)

    def test_25_camera_post_capture_readback_preserved(self):
        with self.session(fault='camera_changed_after') as (_,e):self.assertEqual(self.assert_failed(e).code,'READBACK_MISMATCH')

    def test_26_ROI_post_capture_readback_preserved(self):
        with self.session(fault='roi_changed_after') as (_,e):self.assertEqual(self.assert_failed(e).code,'ROI_MISMATCH')

    def test_27_cancel_active_capture_retired_and_cleanup_off(self):
        with self.session(fault='cancel') as (peer,e):
            cancel=threading.Event()
            trigger=threading.Thread(target=lambda:(peer.capture_event.wait(1),cancel.set()));trigger.start()
            try:error=self.assert_failed(e,cancel=cancel)
            finally:trigger.join(2)
            self.assertEqual(error.code,'CANCELLED');self.assertTrue(self.outcome()[-1]['retirement_confirmed'])
        self.assertTrue(self.cleanup['acknowledged'])

    def test_28_unknown_retirement_requires_recovery(self):
        with self.session(fault='unknown_retirement') as (_,e):
            error=self.assert_failed(e,timeout_s=.2);self.assertTrue(error.needs_reset)
            with self.assertRaises(sdk.AcquisitionError) as second:self.capture(e)
            self.assertEqual(second.exception.code,'NEEDS_RESET')

    def test_29_post_publication_source_failure_quarantines_result(self):
        with self.session() as (_,e):
            original=sdk.verify_sources
            def fail_after_publication():
                original()
                if list((self.root/'sdk_calls').glob('*/committed')):raise sdk.AcquisitionError('SOURCE_CHANGED','injected post-publication failure')
            with patch.object(sdk,'verify_sources',side_effect=fail_after_publication):self.assert_failed(e)
            self.assertTrue(list((self.root/'sdk_calls').glob('*/quarantined/provisional.json')))

    def test_30_atomic_publish_failure_preserves_failed_pending(self):
        with self.session() as (_,e):
            with patch.object(sdk.publication,'atomic_publish',side_effect=PermissionError('injected publication failure')):self.assert_failed(e)
            self.assertTrue(list((self.root/'sdk_calls').glob('*/pending/provisional.json')))

    def test_31_real_board_constructor_requires_bit_binding_before_socket(self):
        with patch.object(socket,'socket',side_effect=AssertionError('Must reject before socket')):
            with self.assertRaises(ValueError):sdk.TransportExecutor(board='192.168.0.2',port=5000,bind='192.168.0.3',ymw_root=self.engine.root/'ymw',output_root=self.root)

    def test_32_input_zero_mask_rejected_before_any_command(self):
        with self.session() as (peer,e):
            with self.assertRaises(sdk.AcquisitionError):self.capture(e,board_mask=bytes(1701))
            self.assertFalse(peer.received)

    def test_33_cleanup_missing_ack_not_claimed_off(self):
        with self.session(fault='off_ack_lost') as (_,e):self.capture(e)
        self.assertFalse(self.cleanup['acknowledged']);self.assertFalse(self.cleanup['physical_off_verified'])

    def test_34_provisional_oversized_datagram_rejected(self):
        with self.session(fault='oversized_provisional_packet') as (_,e):self.assertEqual(self.assert_failed(e).code,'IMAGE_INVALID')

    def test_35_loaded_protocol_file_change_rejected_before_commands(self):
        clone=self.root/'ymw_copy';shutil.copytree(self.engine.root/'ymw',clone)
        with self.Peer(self.engine.root/'ymw') as peer,sdk.TransportExecutor(board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',
            ymw_root=clone,output_root=self.root/'sdk_calls',pixel_format=49,evidence_source='software_udp_peer',
            sensor_size=(96,32),command_timeout=.04,retries=2) as e:
            try:
                (clone/'host/protocol.py').write_bytes(b'changed fixture copy only')
                self.assertEqual(self.assert_failed(e).code,'SOURCE_CHANGED');self.assertFalse(peer.received)
            finally:e.lights_off(timeout_s=.15)

if __name__=='__main__':unittest.main(verbosity=2)
