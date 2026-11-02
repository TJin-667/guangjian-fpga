"""New bridge checks: only one software UDP fixture; real sockets are prohibited."""
import copy,io,json,os,shutil,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import gray_capture_bridge as bridge
import operator_host as host
from test_operator_host import FixtureRuntime
from test_sdk_transport import LocalSocket
from software_transport_peer import make_peer
import board_probe

class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=Path(os.environ['GRAY_BRIDGE_TEST_OUTPUT'])
        cls.fixture=cls.output/'software_fixture';cls.fixture.mkdir()
        Peer,engine=make_peer();core=board_probe.core_module()
        with patch.object(socket,'socket',LocalSocket),Peer(engine.root/'ymw') as peer:
            runtime=FixtureRuntime(cls.fixture,core,peer,engine)
            plan=host.build_plan(runtime,low=400,high=800,physical_specimen_id='software_plate',pose_id='software_pose',
                pair_status='development_trial',pair_reference='software only; no physical exposure selection')[0]
            cls.batch=cls.fixture/'batch'
            result=host.execute(plan,out=cls.batch,confirmed_same_pose=True,_runtime=runtime,single_timeout_s=3)
            if result['summary']['status']!='ACQUIRED_EIGHT_REVIEW_REQUIRED':raise AssertionError(result['summary'])
            cls.capture_count=len(peer.captured)
        cls.bundle=cls.fixture/'portable_eight'
        bridge.export_batch(cls.batch,cls.bundle,sensor_size=(96,32))
        cls.frame=cls.bundle/'frames/CH1_low'

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def frame_copy(self):
        dest=self.root/'frame';shutil.copytree(self.frame,dest);return dest
    def group_copy(self):
        dest=self.root/'group';shutil.copytree(self.bundle,dest);return dest
    def change_json(self,path,change):
        obj=bridge.read(path);change(obj);path.write_bytes(bridge.encoded(obj));return obj
    def commit_copy(self):
        dest=self.root/'commit';shutil.copytree(self.frame/'capture',dest);return dest

    def test_01_eight_requests_single_mask_upload_and_roundtrip(self):
        self.assertEqual(self.capture_count,8)
        records=[bridge.read(p) for p in self.batch.glob('sdk_calls/*/committed/result.json')]
        self.assertEqual(sum(r['cost']['mask_commands'] for r in records),55)
        self.assertEqual(sorted(r['cost']['mask_commands'] for r in records),[0]*7+[55])
        group=bridge.load_group(self.bundle,purpose='interface_test')
        self.assertEqual(len(group.observations),8);self.assertEqual(group.observations[0].roi_xywh,(5,7,81,21))
        self.assertFalse(bridge.read(self.bundle/'group.json')['training_data'])
    def test_02_reader_never_opens_socket(self):
        with patch.object(socket,'socket',side_effect=AssertionError('No offline sockets')):
            frame,_=bridge.load_frame(self.frame);group=bridge.load_group(self.bundle,purpose='interface_test')
        self.assertEqual(frame.gray.shape,(21,81));self.assertEqual(len(group.observations),8)
    def test_03_xdl_baselines_accept_verified_roi_arrays(self):
        fusion=bridge.xdl_reference.load('fusion');group=bridge.load_group(self.bundle,purpose='interface_test')
        cache=fusion.prepare_evidence(group)
        for mode in ['low_only','high_only','equal_weight']:
            result=fusion.fuse_group(group,mode,evidence_cache=cache)
            self.assertEqual(result.score.shape,(21,81));self.assertTrue(np.isfinite(result.score).all())
    def test_04_legacy_file_reader_rejects_global_crop_of_saved_roi(self):
        frame,m=bridge.load_frame(self.frame);fields={**m['xdl_fields'],
            'observation_id':'interface_only','specimen_id':'software_plate','pose_id':'software_pose',
            'direction':'CH1','exposure_role':'low','exposure_lines':400,'gain16':16,'led':128,
            'valid_mask_id':frame.record['mask_sha256']}
        with self.assertRaisesRegex(ValueError,'gray8 does not match'):
            bridge.xdl_reference.load('run')._load_observation(fields,self.frame)
    def test_05_training_purpose_rejected(self):
        with self.assertRaisesRegex(ValueError,'interface_test'):
            bridge.load_group(self.bundle,purpose='fit')
    def test_06_wrong_wire_crc_rejected_even_after_file_sha_update(self):
        dest=self.commit_copy();p=dest/'image.gray_sat';data=bytearray(p.read_bytes());data[0]^=1;p.write_bytes(data)
        self.change_json(dest/'result.json',lambda r:(r['archived_file_sha256'].update({'image.gray_sat':bridge.digest(data)}),r.update(raw_payload_sha256=bridge.digest(data))))
        with self.assertRaisesRegex(ValueError,'CRC'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_07_saved_SAT_tamper_rejected(self):
        dest=self.commit_copy();p=dest/'image.sat1';data=bytearray(p.read_bytes());data[0]^=128;p.write_bytes(data)
        self.change_json(dest/'result.json',lambda r:r['archived_file_sha256'].update({'image.sat1':bridge.digest(data)}))
        with self.assertRaisesRegex(ValueError,'Saved gray/SAT'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_08_record_identity_tamper_rejected(self):
        dest=self.commit_copy();self.change_json(dest/'result.json',lambda r:r['identity'].update(request_id=100))
        with self.assertRaisesRegex(ValueError,'identity'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_09_nonbinary_mask_rejected(self):
        dest=self.commit_copy();p=dest/'board_mask.bin';data=bytearray(p.read_bytes());data[0]=2;p.write_bytes(data)
        self.change_json(dest/'result.json',lambda r:r['archived_file_sha256'].update({'board_mask.bin':bridge.digest(data)}))
        with self.assertRaisesRegex(ValueError,'Nonbinary'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_10_gray_PNG_cannot_disagree_with_wire(self):
        dest=self.commit_copy();p=dest/'image.gray.png';img=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),0);img[0,0]^=1
        ok,data=cv2.imencode('.png',img);self.assertTrue(ok);p.write_bytes(data.tobytes())
        self.change_json(dest/'result.json',lambda r:r['archived_file_sha256'].update({'image.gray.png':bridge.digest(data.tobytes())}))
        with self.assertRaisesRegex(ValueError,'PNG differs'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_11_SDK_artifact_path_escape_rejected(self):
        dest=self.commit_copy();self.change_json(dest/'result.json',lambda r:r['archived_file_sha256'].update({'../outside':bridge.digest(b'x')}))
        with self.assertRaisesRegex(ValueError,'Unsafe'):bridge.load_commit(dest/'result.json',sensor_size=(96,32))
    def test_12_portable_SAT_array_tamper_rejected_after_SHA_update(self):
        dest=self.frame_copy();p=dest/'planes/sat1.npy';a=np.load(p,allow_pickle=False);a[0,0]^=1;data=bridge.npy_bytes(a);p.write_bytes(data)
        self.change_json(dest/'frame.json',lambda m:m['artifacts'].update({'planes/sat1.npy':bridge.digest(data)}))
        with self.assertRaisesRegex(ValueError,'sat1 differs'):bridge.load_frame(dest)
    def test_13_portable_ROI_origin_tamper_rejected(self):
        dest=self.frame_copy();self.change_json(dest/'frame.json',lambda m:m.update(saved_origin_xy=[0,0]))
        with self.assertRaisesRegex(ValueError,'metadata/binding'):bridge.load_frame(dest)
    def test_14_portable_digest_identity_tamper_rejected(self):
        dest=self.frame_copy();self.change_json(dest/'frame.json',lambda m:m['xdl_fields'].update(session_id='wrong'))
        with self.assertRaisesRegex(ValueError,'metadata/binding'):bridge.load_frame(dest)
    def test_15_unlisted_portable_file_rejected(self):
        dest=self.frame_copy();(dest/'extra.txt').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError,'inventory'):bridge.load_frame(dest)
    def test_16_existing_export_directory_not_overwritten(self):
        dest=self.root/'existing';dest.mkdir();(dest/'keep.txt').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'new directory'):
            bridge.export_frame(self.frame/'capture/result.json',dest,sensor_size=(96,32))
        self.assertEqual((dest/'keep.txt').read_bytes(),b'keep')
    def test_17_missing_eighth_rejected(self):
        dest=self.group_copy();self.change_json(dest/'group.json',lambda g:g['entries'].pop())
        with self.assertRaisesRegex(ValueError,'eight'):bridge.load_group(dest,purpose='interface_test')
    def test_18_duplicate_frame_rejected(self):
        dest=self.group_copy();self.change_json(dest/'group.json',lambda g:g['entries'][1].update(frame_root=g['entries'][0]['frame_root']))
        with self.assertRaises(ValueError):bridge.load_group(dest,purpose='interface_test')
    def test_19_group_pose_tamper_rejected(self):
        dest=self.group_copy();self.change_json(dest/'group.json',lambda g:g.update(pose_id='wrong_pose'))
        with self.assertRaisesRegex(ValueError,'specimen/pose'):bridge.load_group(dest,purpose='interface_test')
    def test_20_swapped_roles_rejected(self):
        dest=self.group_copy();self.change_json(dest/'group.json',lambda g:g['entries'][0].update(role='high'))
        with self.assertRaises(ValueError):bridge.load_group(dest,purpose='interface_test')
    def test_21_cleanup_required_batch_rejected(self):
        dest=self.root/'batch';shutil.copytree(self.batch,dest)
        self.change_json(dest/'operator_summary.json',lambda s:s['lights_off'].update(acknowledged=False))
        with self.assertRaisesRegex(ValueError,'cleaned-up'):bridge.export_batch(dest,self.root/'export',sensor_size=(96,32))
        self.assertFalse((self.root/'export').exists())
    def test_22_no_scope_promotion(self):
        dest=self.group_copy();self.change_json(dest/'group.json',lambda g:g.update(training_data=True))
        with self.assertRaisesRegex(ValueError,'scope'):bridge.load_group(dest,purpose='interface_test')
    def test_23_preimported_identical_XDL_checkout_reuses_its_classes(self):
        existing=self.root/'existing';existing.mkdir()
        shutil.copytree(bridge.xdl_reference.ROOT/'exposure_fusion_v1',existing/'exposure_fusion_v1')
        code='''import sys,socket\nfrom unittest.mock import patch\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nimport exposure_fusion_v1.models as original\nsys.path.insert(0,sys.argv[2])\nimport gray_capture_bridge as bridge\nwith patch.object(socket,'socket',side_effect=AssertionError('No sockets')):\n    group=bridge.load_group(sys.argv[3],purpose='interface_test')\n    assert isinstance(group,original.ObservationGroup)\n    result=bridge.xdl_reference.load('fusion').fuse_group(group,'equal_weight')\n    assert result.score.shape==(21,81)\nprint('PREIMPORTED_XDL_VERIFIED')\n'''
        run=subprocess.run([sys.executable,'-B','-c',code,str(existing),str(Path(bridge.__file__).parent),str(self.bundle)],
            capture_output=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr);self.assertIn('PREIMPORTED_XDL_VERIFIED',run.stdout)
