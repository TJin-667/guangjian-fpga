"""Replay an archived real RGB frame through the exact gray encoder RTL, offline."""
import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import frozen_diagnostic as frozen
import review_engineering_capture as audit
from run_verification import simulate

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
SOURCE_COMMIT='46f9d50cf2d854f2e9f31bf8b0dddfe9b2025c07'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,obj):p.write_bytes((json.dumps(obj,indent=2)+'\n').encode())

def run(source_run,out,bin_path):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();source_run=Path(source_run).resolve()
    review=audit.review(source_run)
    if review['roi']!=[0,0,1920,1080]:raise ValueError('Native real source required')
    src=next((source_run/'format_01').glob('*/committed/result.json'))
    record=json.loads(src.read_bytes());rgb=(src.parent/'image.rgb565').read_bytes()
    encoder=HERE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v'
    rel=encoder.relative_to(REPO).as_posix()
    implemented=subprocess.check_output(['git','show',SOURCE_COMMIT+':'+rel],cwd=REPO)
    if encoder.read_bytes()!=implemented:raise ValueError('Encoder differs from implemented source commit')
    work=out/'work';work.mkdir()
    source=np.frombuffer(rgb,dtype='>u2').reshape(1080,1920)
    geometries=[[0,0,1920,1080],[896,496,81,21]]
    expected=[];cases=[]
    for index,(x,y,w,h) in enumerate(geometries):
        words=source[y:y+h,x:x+w].copy();raw=words.astype('>u2').tobytes()
        gray,sat=audit.planes(raw,w,h,1)
        encoded=frozen.wire.codec.encode(gray,sat)
        (work/f'input_{index}.hex').write_text(''.join(f'{v:04x}\n' for v in words.reshape(-1)),encoding='ascii')
        (work/f'expected_{index}.hex').write_text(''.join(f'{v:02x}\n' for v in encoded),encoding='ascii')
        frozen.freeze(raw,width=w,height=h,out=work/f'frozen_{index}')
        cases.append(dict(index=index,source_crop_xywh=[x,y,w,h],pixels=w*h,bytes=len(encoded),
            frozen_rgb_sha256=hashlib.sha256(raw).hexdigest(),golden_payload_sha256=hashlib.sha256(encoded).hexdigest()))
        expected.append((raw,encoded))
    (work/'saved_cases.svh').write_text(''.join(f"run_case({c['index']},{c['pixels']},{c['bytes']});\n" for c in cases),encoding='ascii')
    sources=[encoder,HERE/'tb_saved_gray_equivalence.sv']
    source_hashes=simulate(work,'tb_saved_gray_equivalence',sources,Path(bin_path),'SAVED_RGB_EQUIVALENCE_ALL_PASS 2')
    rows=list(csv.DictReader((work/'rtl_receipt.csv').open()))
    if len(rows)!=2 or any(r['status']!='PASS' for r in rows):raise ValueError('RTL receipt missing')
    for case,(raw,golden) in zip(cases,expected):
        actual=(work/f"rtl_{case['index']}.gray_sat").read_bytes()
        if actual!=golden:raise ValueError('Actual RTL output differs from frozen-input golden')
        checked=frozen.verify(work/f"frozen_{case['index']}",rgb_payload=raw,gray_payload=actual)
        case.update(full_gray_and_SAT_planes_equal=checked['full_gray_and_SAT_planes_equal'],
            rtl_payload_sha256=hashlib.sha256(actual).hexdigest(),H1=checked['H1'],H2=checked['H2'])
    wrong=next((source_run/'format_31').glob('*/committed/image.gray_sat')).read_bytes()
    try:frozen.verify(work/'frozen_0',rgb_payload=rgb,gray_payload=wrong)
    except ValueError as exc:negative=str(exc)
    else:raise ValueError('Different real DVP frame was incorrectly accepted as same frozen input')
    if sha(src.parent/'image.rgb565')!=record['raw_payload_sha256']:raise ValueError('Source changed during replay')
    result=dict(schema='guangjian-real-rgb-offline-rtl-equivalence-v1',status='PASS',cases=cases,
        source_run=str(source_run),source_record_sha256=sha(src),source_rgb_sha256=hashlib.sha256(rgb).hexdigest(),
        source_identity=record['diagnostic']['identity'],source_archive_sha256=review['archive_sha256'],
        implemented_RTL_source_commit=SOURCE_COMMIT,source_sha256={**source_hashes,**{str(p):sha(p) for p in
            [Path(__file__),Path(frozen.__file__),Path(audit.__file__),Path(frozen.wire.__file__)]}},
        actual_different_DVP_frame_rejected=negative,
        all_gray_pixels_and_SAT_bits_equal=True,H1_H2_equal=True,
        evidence_source='RTL simulation using archived real RGB bytes',
        hardware_same_input_replay_verified=False,detector_quality_evaluated=False,
        hardware_contacted=False,new_physical_captures=0,new_bit=False,release_ready=False,
        wall_seconds=round(time.monotonic()-started,3))
    write(out/'verification.json',result)
    print(json.dumps({k:result[k] for k in ['status','all_gray_pixels_and_SAT_bits_equal','wall_seconds','hardware_contacted']},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--vivado-bin',type=Path,default=Path('F:/Xilinx/Vivado/2018.3/bin'))
    a=p.parse_args();run(a.source_run,a.out,a.vivado_bin)
