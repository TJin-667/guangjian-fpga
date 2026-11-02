"""Real miniature originals: breaks catch identity, integrity, and cost errors."""
import dataclasses
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import cv2
import numpy as np
from capture_metrics import FrameInput
try:
    import dataset_io as dio
except ModuleNotFoundError:
    dio = None

SCAN_COMMIT = '7ccb753ffacff752a5cd65d4b3a13ff7be9875c6'
REPEAT_COMMIT = 'de18e3b604158c1b53b87b08f22ddc59ed52cfe2'

def digest(b):
    return hashlib.sha256(b).hexdigest()

def encoded(obj):
    return json.dumps(obj).encode('utf-8')

def make_frame():
    return FrameInput('c', 'o', 'sample001', 'A', 600, 16, 1, 128,
                      12, 12, (0, 0, 12, 12), 'a'*64, 'b'*64, 'scan',
                      {'dataset_id':'d', 'capture_id':'c', 'frame_id':1, 'member':'p.png'})

def pictures(value):
    raw = np.full((12, 12), value, dtype='>u2').tobytes()
    v = np.full((12, 12), value, dtype=np.uint16)
    r, g, b = (v >> 11)&31, (v >> 5)&63, v&31
    rgb = np.stack(((r<<3)|(r>>2), (g<<2)|(g>>4), (b<<3)|(b>>2)), -1).astype('uint8')
    return cv2.imencode('.png', rgb[..., ::-1])[1].tobytes(), raw

def session(sample, capture, frame_id, exposure, png, raw, generation=1, prefix=4):
    registers = {'0x3500':0, '0x3501':(exposure*16)>>8,
                 '0x3502':(exposure*16)&255, '0x350A':0, '0x350B':16}
    camera = {'locked':True, 'error':0, 'exposure_lines':exposure,
              'gain16':16, 'generation':generation, 'raw_registers':registers}
    frame = {'frame_id':frame_id, 'width':12, 'height':12,
             'camera_before':camera, 'camera_after':camera, 'discarded':False}
    return {'sample_id':sample, 'group_id':capture, 'firmware':260,
            'saved_frames':1, 'requested':{'channel':1, 'light_mask':1,
            'exposure_lines':exposure, 'gain16':16, 'brightness':128},
            'camera_readback':camera, 'discarded_frames':[{'frame_id':frame_id-n-1, 'discarded':True} for n in range(3)], 'total_capture_requests':prefix,
            'total_complete_frames_received':prefix,
            'views':[{'channel':1, 'mask':1, 'brightness':128, 'status':'COMPLETE',
                      'saved_width':12, 'saved_height':12, 'roi':[0,0,12,12],
                      'frame':frame, 'png':'p.png', 'rgb565':'p.rgb565',
                      'sha256_rgb565':digest(raw)}]}

class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dio, 'dataset_io feature is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path, data):
        target=self.root/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def fixture(self, repeat=True):
        records=[]; members=[]; groups=[]; images=[]; geometries=[]; logs=[]
        for i in range(6 if repeat else 4):
            sample='sample001' if i<3 or not repeat else 'sample002'
            capture=f'cap{i}'; exposure=600 if repeat else [400,500,600,700][i]
            png, raw=pictures(0x2100+i)
            prefix=[505,514,517,4,4,4][i] if repeat else 4
            s=session(sample,capture,100+i,exposure,png,raw,prefix=prefix)
            arc=f'archives/{capture}.zip'
            content={'p.png':png,'p.rgb565':raw,'session.json':encoded(s),'capture_log.jsonl':b'{}\n'}
            z=io.BytesIO()
            with zipfile.ZipFile(z,'w',zipfile.ZIP_STORED) as out:
                for name, data in content.items():
                    member=f'{capture}/{name}'
                    out.writestr(member,data)
                    members.append({'archive':Path(arc).name if repeat else arc,
                                    'member':member,'extracted_path':f'{sample}/r{i%3+1:02d}/{name}',
                                    'bytes':len(data),'sha256':digest(data),'group_id':capture})
                    if not repeat:
                        self.write(member,data)
            self.write(arc,z.getvalue())
            rec={'sample_id':sample,'repeat_id':f'r{i%3+1:02d}', 'archive':arc,
                 'archive_sha256':digest(z.getvalue()),'archive_bytes':len(z.getvalue()),
                 'original_zip_prefix':f'{capture}/','png':f'{sample}/r{i%3+1:02d}/p.png',
                 'rgb565':f'{sample}/r{i%3+1:02d}/p.rgb565',
                 'session':f'{sample}/r{i%3+1:02d}/session.json', 'width':12,'height':12,
                 'roi':[0,0,12,12],'channel':1,'exposure_lines':exposure,'gain16':16,
                 'brightness':128,'frame_id':100+i,'camera_generation':1,
                 'sha256_png':digest(png),'sha256_rgb565':digest(raw),
                 'register_values':s['camera_readback']['raw_registers'],
                 'acquisition_mode':'shared_preview' if i<3 else 'independent_single',
                 'preview_session_id':'preview' if i<3 else None,
                 'capture_log':'logs/preview.jsonl' if i<3 else f'logs/single{i}.jsonl',
                 'stored_session_complete_frames':prefix}
            records.append(rec)
            if not repeat:
                groups.append({**rec,'group_id':f'E{exposure:04d}_G1','specimen_id':sample,'pose_block':'A'})
                images.append({**rec,'group_id':f'E{exposure:04d}_G1','specimen_id':sample,
                               'pose_block':'A','zip_png_member':f'{capture}/p.png',
                               'png_sha256':digest(png),'rgb565_sha256':digest(raw),'roi_x':0,'roi_y':0})
                geometries.append({'group_id':f'E{exposure:04d}_G1','pose':'A',
                                   'analysis_polygon':[[0,0],[11,0],[11,11],[0,11]],
                                   'analysis_mask_source':'fixture approximation'})
        if repeat:
            for name,count in [('preview',884),('single3',4),('single4',4),('single5',4)]:
                events=[{'event':'start','value':{'mode':'preview' if name=='preview' else 'single'}}]
                events += [{'event':'complete_received_frame' if name=='preview' else 'frame','value':{'frame_id':n if name=='preview' else 100+int(name[-1])}} for n in range(count if name=='preview' else 1)]
                events += [{'event':'done','value':{'failed':False}}]
                data=b'\n'.join(encoded(e) for e in events)
                self.write(f'logs/{name}.jsonl',data)
                logs.append({'path':f'logs/{name}.jsonl','bytes':len(data),'sha256':digest(data)})
            index={'schema_version':1,'dataset_id':'ch1_repeat_defect_near_normal_20261013',
                   'records':records,'archive_members':members,'supplementary_logs':logs}
            self.write('dataset_index.json',encoded(index))
            regions={'version':'repeat-regions-1','dataset_commit':REPEAT_COMMIT,'boards':{}}
            for sample,i in [('sample001',0),('sample002',3)]:
                regions['boards'][sample]={'polygon':[[1,1],[10,1],[10,10],[1,10]],
                    'source_png_sha256':records[i]['sha256_png'],'source_repeat_id':'r01',
                    'manual_review_pending':True,'mask_source':'visual approximation'}
            self.write('regions.json',encoded(regions))
            self.addCleanup(patch.stopall)
            patch.object(dio,'REPEAT_INDEX_SHA256',digest(encoded(index))).start()
            return index
        index={'dataset_revision':2,'groups':groups,'images':images,'archive_members':members}
        bundle={'github_commit':SCAN_COMMIT,'index':index,'geometry_records':geometries}
        self.write('expected/analysis_inputs.json',encoded(bundle))
        self.addCleanup(patch.stopall)
        patch.object(dio,'SCAN_INPUTS_SHA256',digest(encoded(bundle))).start()
        return bundle

    def test_storage_location_is_not_new_provenance(self):
        original=make_frame()
        moved=dataclasses.replace(original,source_metadata={**original.source_metadata,'storage_root':'other'})
        self.assertEqual(dio.source_identity(original),dio.source_identity(moved))

    def test_reject_wrong_revision_pose_gain(self):
        for field,value in [('dataset_revision',1),('pose_block','B'),('gain16',32)]:
            with self.subTest(field=field):
                bundle=self.fixture(False)
                if field=='dataset_revision': bundle['index'][field]=value
                else: bundle['index']['images'][0][field]=value
                data=encoded(bundle);self.write('expected/analysis_inputs.json',data)
                with patch.object(dio,'SCAN_INPUTS_SHA256',digest(data)):
                    with self.assertRaises(ValueError): dio.load_scan_inputs(self.root,self.root/'expected')

    def test_verify_all_members(self):
        self.fixture(False)
        self.write('cap3/capture_log.jsonl',b'bad')
        with self.assertRaises(ValueError): dio.load_scan_inputs(self.root,self.root/'expected')

    def test_zip_member_escape_rejected(self):
        j=self.fixture();j['archive_members'][0]['member']='../outside'
        data=encoded(j);self.write('dataset_index.json',data)
        with patch.object(dio,'REPEAT_INDEX_SHA256',digest(data)):
            with self.assertRaises(ValueError): dio.load_repeat_inputs(self.root,self.root/'regions.json')

    def test_bad_crc_or_hash_rejected(self):
        self.fixture();p=self.root/'archives/cap0.zip';b=bytearray(p.read_bytes());b[60]^=1;p.write_bytes(b)
        with self.assertRaises(ValueError): dio.load_repeat_inputs(self.root,self.root/'regions.json')

    def test_bad_member_crc_rejected_after_valid_outer_hash(self):
        self.fixture()
        path = self.root/'archives/cap0.zip'
        content = bytearray(path.read_bytes())
        # ZIP_STORED fixture: alter p.png payload while preserving its old CRC.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            member = archive.infolist()[0]
            offset = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
        content[offset] ^= 1
        path.write_bytes(content)
        record = {'archive': 'archives/cap0.zip', 'archive_sha256': digest(content), 'archive_bytes': len(content)}
        index = json.loads((self.root/'dataset_index.json').read_bytes())
        members = [r for r in index['archive_members'] if r['archive'] == 'cap0.zip']
        with self.assertRaisesRegex(ValueError, 'invalid ZIP or CRC'):
            dio._zip_members(self.root, record, members)

    def test_duplicate_frame_provenance_rejected(self):
        j=self.fixture();j['records'][1]=dict(j['records'][0]);data=encoded(j);self.write('dataset_index.json',data)
        with patch.object(dio,'REPEAT_INDEX_SHA256',digest(data)):
            with self.assertRaises(ValueError): dio.load_repeat_inputs(self.root,self.root/'regions.json')

    def test_three_repeats_per_board_separate(self):
        self.fixture();frames=dio.load_repeat_inputs(self.root,self.root/'regions.json')
        self.assertEqual([f.sample_id for f in frames],['sample001']*3+['sample002']*3)
        self.assertNotEqual(frames[0].context_id,frames[3].context_id)
        self.assertTrue(frames[0].source_metadata['needs_manual_review'])
        self.assertEqual(dio.read_frame(frames[0]).shape,(12,12,3))

    def test_overlapping_session_prefix_not_added(self):
        self.fixture();cost=dio.historical_cost(self.root)
        self.assertEqual(cost['historical_capture_cost']['received_frames'],896)
        self.assertEqual(cost['historical_capture_cost']['samples']['sample001']['received_frames'],884)
        self.assertEqual(cost['historical_capture_cost']['samples']['sample002']['received_frames'],12)
        self.assertIsNone(cost['measured_live_control_cost'])

    def test_missing_log_unknown_not_zero(self):
        self.fixture();(self.root/'logs/preview.jsonl').unlink();cost=dio.historical_cost(self.root)
        self.assertIsNone(cost['historical_capture_cost']['received_frames'])
        self.assertIsNone(cost['historical_capture_cost']['samples']['sample001']['received_frames'])
        self.assertEqual(cost['historical_capture_cost']['samples']['sample001']['prefix_lower_bound'],517)

    def test_read_frame_reverifies_current_bytes(self):
        self.fixture(False);frames=dio.load_scan_inputs(self.root,self.root/'expected')
        self.write('cap0/p.png',pictures(0xFFFF)[0])
        with self.assertRaises(ValueError): dio.read_frame(frames[0])

    def test_index_pin_rejected(self):
        self.fixture();self.write('dataset_index.json',b'{}')
        with self.assertRaises(ValueError): dio.load_repeat_inputs(self.root,self.root/'regions.json')

    def test_scan_native_mask_provenance(self):
        self.fixture(False);frames=dio.load_scan_inputs(self.root,self.root/'expected')
        self.assertEqual([f.exposure_lines for f in frames],[400,500,600,700])
        self.assertEqual(frames[0].source_metadata['analysis_polygon'],((0,0),(11,0),(11,11),(0,11)))
        self.assertEqual(frames[0].source_metadata['session']['group_id'],'cap0')

    def test_manual_review_uses_common_area_contract_key(self):
        self.fixture();frames=dio.load_repeat_inputs(self.root,self.root/'regions.json')
        from capture_metrics import build_common_area
        area=build_common_area(frames[:3],[np.ones((12,12),dtype=bool)]*3,sensor_shape=(12,12))
        self.assertIs(area.sources[0]['needs_manual_review'],True)

    def test_read_frame_rejects_relabelled_settings(self):
        self.fixture(False);frame=dio.load_scan_inputs(self.root,self.root/'expected')[0]
        with self.assertRaises(ValueError): dio.read_frame(dataclasses.replace(frame,exposure_lines=700))

    def test_png_rgb565_mismatch_rejected(self):
        png,raw=pictures(0xFFFF);wrong_raw=pictures(0)[1]
        self.write('p.png',png);self.write('p.rgb565',wrong_raw);self.write('session.json',b'{}')
        verification={name:{'sha256':digest(data),'bytes':len(data)} for name,data in
                      [('p.png',png),('p.rgb565',wrong_raw),('session.json',b'{}')]}
        frame=dataclasses.replace(make_frame(),png_sha256=digest(png),rgb565_sha256=digest(wrong_raw),
            source_metadata={**make_frame().source_metadata,'storage_root':str(self.root),
            'storage_kind':'files','member':'p.png','rgb565_member':'p.rgb565',
            'session_member':'session.json','session_sha256':digest(b'{}'),'member_verification':verification})
        with self.assertRaises(ValueError): dio.read_frame(frame)

    def test_actual_originals_and_pinned_native_masks(self):
        base=Path(__file__).resolve().parents[2]
        scan=dio.load_scan_inputs(base/'YMW/YMW_manual_20261013',base/'XDL_Results/2026-10-13_manual_exposure_gain')
        self.assertEqual(scan[0].source_metadata['verified_member_count'],198)
        from capture_metrics import load_algorithm,build_common_area
        algorithm=load_algorithm(base/'XDL_Algorithm/software',base/'XDL_Results/2026-10-13_manual_exposure_gain')
        manifest=json.loads((base/'XDL_Results/2026-10-13_integer_reference_01/reference_manifest.json').read_bytes())
        native=[]
        for frame in scan:
            image=dio.read_frame(frame)
            mask=algorithm['board_mask'](image.shape[:2],frame.source_metadata['analysis_polygon'],frame.roi[:2])
            ref=next(r for r in manifest['frames'] if r['group_id']==frame.source_metadata['group_id'] and r['channel']=='CH1')
            self.assertEqual(digest(mask.astype('uint8').tobytes()),ref['arrays']['board_mask']['sha256_c_order'])
            native.append(mask)
        self.assertEqual([int(n.sum()) for n in native],[602804,602804,602804,602420])
        repeat_root=base/'YMW/ch1_repeat_defect_near_normal_20261013'
        frames=dio.load_repeat_inputs(repeat_root,base/'XDL_Software_Controller/repeat_regions.json')
        self.assertEqual(len(frames),6)
        self.assertEqual(len({dio.source_identity(f) for f in frames}),6)
        for frame in frames:
            self.assertEqual((frame.exposure_lines,frame.gain16,frame.led,frame.channel),(600,16,128,1))
            image=dio.read_frame(frame)
            self.assertEqual(image.shape,(1080,1920,3))
        for start in (0,3):
            group=frames[start:start+3]
            masks=[algorithm['board_mask']((1080,1920),f.source_metadata['analysis_polygon'],f.roi[:2]) for f in group]
            area=build_common_area(group,masks)
            self.assertTrue(area.available)
            self.assertIs(area.sources[0]['needs_manual_review'],True)
        self.assertEqual(dio.historical_cost(repeat_root)['historical_capture_cost']['received_frames'],896)

if __name__=='__main__': unittest.main()
