"""Use existing real captures and saved-input RTL output; never contact hardware."""
import argparse,hashlib,json,socket,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
import gray_capture_bridge as bridge
import review_engineering_capture as audit

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    small=Path('C:/Users/yue/Documents/Guangjian0106Transport/20261026_012615_2d0ad3')
    native=Path('C:/Users/yue/Documents/Guangjian0106Native/20261026_015156_3a8f36')
    rows=[]
    with patch.object(socket,'socket',side_effect=AssertionError('Real bridge check must remain offline')):
        for label,source in [('small',small),('native',native)]:
            for fmt in [1,49]:
                record=next((source/f'format_{fmt:02x}').glob('*/committed/result.json'))
                target=out/f'{label}_{fmt:02x}';m=bridge.export_frame(record,target)
                frame,reloaded=bridge.load_frame(target)
                assert reloaded==m
                fields={**m['xdl_fields'],'observation_id':'engineering_only','specimen_id':frame.record['sample_id'],
                    'pose_id':frame.record['round_id'],'direction':'CH1','exposure_role':'unassigned_diagnostic',
                    'exposure_lines':600,'gain16':16,'led':128,'valid_mask_id':frame.record['mask_sha256']}
                try:
                    obs,_=bridge.xdl_reference.load('run')._load_observation(fields,target)
                    accepted=True;error=None
                    assert np.array_equal(obs.gray8,frame.gray) and np.array_equal(obs.sat1.astype(bool),frame.sat)
                except ValueError as exc:accepted=False;error=str(exc)
                assert accepted==(label=='native'),(label,error)
                rows.append(dict(source=label,pixel_format=fmt,source_record_sha256=sha(record),
                    exported_frame_json_sha256=sha(target/'frame.json'),ROI=m['roi_xywh'],
                    payload_sha256=bridge.digest(frame.payload),gray_sha256=bridge.digest(frame.gray.tobytes()),
                    sat_pixels=int(frame.sat.sum()),portable_raw_and_planes_verified=True,
                    unchanged_XDL_file_reader_accepted=accepted,reader_limitation=error))
        baseline,_=bridge.load_frame(out/'native_01')
        rtl=HERE/'verification/same_input_rtl_01/work/rtl_0.gray_sat'
        replay=json.loads((HERE/'verification/same_input_rtl_01/verification.json').read_bytes())
        assert replay['status']=='PASS' and replay['cases'][0]['rtl_payload_sha256']==sha(rtl)
        assert replay['source_rgb_sha256']==bridge.digest(baseline.payload)
        gray,sat=audit.planes(rtl.read_bytes(),1920,1080,49)
        feature=bridge.xdl_reference.load('features')
        before=feature.extract_evidence(baseline.gray,baseline.sat,baseline.mask)
        after=feature.extract_evidence(gray,sat,baseline.mask)
        feature_checks={}
        for name in before.__dataclass_fields__:
            a,b=getattr(before,name),getattr(after,name)
            assert np.array_equal(a,b),name
            feature_checks[name]=dict(equal=True,shape=list(a.shape),dtype=str(a.dtype),sha256=bridge.digest(a.tobytes()))
        threshold_checks={str(v):bool(np.array_equal(np.abs(before.residual_n.astype(np.int32))>v,
            np.abs(after.residual_n.astype(np.int32))>v)) for v in (648,1620)}
        assert all(threshold_checks.values())
    result=dict(schema='guangjian-real-gray-bridge-check-v1',status='PASS',rows=rows,
        same_saved_RGB_RTL_replay_XDL_features=feature_checks,integer_threshold_masks_equal=threshold_checks,
        scope='Same saved real RGB -> actual encoder RTL simulation -> unchanged XDL feature extraction. No new camera frame or labels.',
        source_sha256={str(p):sha(p) for p in [Path(__file__),Path(bridge.__file__),Path(audit.__file__),
            HERE/'verification/same_input_rtl_01/verification.json',HERE/'xdl_reference.py']},
        hardware_contacted=False,new_physical_captures=0,new_bit=False,
        same_frozen_hardware_frame_replayed=False,trained_fusion_or_detection_quality_validated=False,
        original_capture_files_modified=False,release_ready=False,wall_seconds=round(time.monotonic()-start,3))
    (out/'verification.json').write_bytes(bridge.encoded(result))
    print(json.dumps(dict(status='PASS',real_frames_exported=len(rows),exact_XDL_feature_planes=len(feature_checks),
        threshold_masks_equal=all(threshold_checks.values()),wall_seconds=result['wall_seconds'],hardware_contacted=False),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
