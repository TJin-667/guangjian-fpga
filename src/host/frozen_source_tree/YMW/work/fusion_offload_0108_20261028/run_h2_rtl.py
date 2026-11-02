"""Actual RGB565 -> unchanged H2 RTL -> new burst scratch writer vs golden."""
import argparse,json,sys,time
from pathlib import Path
import cv2
import numpy as np
from run_real_rtl import HERE,REPO,sha,dump,simulate

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    sys.path.insert(0,str(REPO/'YMW/work/b1_detection_console_20261027'))
    from common import verify_vendor
    vendor,_=verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from ymw_integer_reference import integer_h2
    from light_inspection.real_baseline import assess_quality
    rng=np.random.default_rng(108);cases=[];protected={}
    for h,w in [(9,9),(13,19),(65,65)]:
        rgb=rng.integers(0,65536,(h,w),dtype=np.uint16)
        cases.append(dict(name=f'directed_{w}x{h}',rgb=rgb,real=False))
    freeze=json.loads((REPO/'YMW/handoffs/fusion_final_400_800_20261028/EXISTING_EVIDENCE.json').read_text('utf-8'))
    case=next(g for g in freeze['groups'] if g['specimen']=='sample005');root=Path(case['result'])
    audit=json.loads((root/'input_audit.json').read_text('utf-8'));path=Path(audit['frames'][0]['source_path']);protected[str(path)]=sha(path)
    bgr=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    rgb=((bgr[:,:,2].astype(np.uint16)>>3)<<11)|((bgr[:,:,1].astype(np.uint16)>>2)<<5)|(bgr[:,:,0].astype(np.uint16)>>3)
    cases.append(dict(name='sample005_native_CH1_low',rgb=rgb,real=True,frozen_result=str(root)))
    calls=[];index=[]
    for ci,c in enumerate(cases):
        rgb=c['rgb'];h,w=rgb.shape
        r8=((rgb>>11)<<3)|((rgb>>11)>>2);g6=(rgb>>5)&63;g8=(g6<<2)|(g6>>4);b5=rgb&31;b8=(b5<<3)|(b5>>2)
        gray=((r8.astype(np.uint32)*9798+g8.astype(np.uint32)*19235+b8.astype(np.uint32)*3735+16384)>>15).astype(np.uint8)
        residual=integer_h2(gray)['residual_n']
        valid=assess_quality(gray)['valid_mask']
        if c['real']:
            with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:
                assert np.array_equal(gray,z['gray'][0])
                assert np.array_equal(residual,z['residual_n'][0])
                assert np.array_equal(valid,z['valid'][0])
        words=residual.astype('<i2').view('<u2').astype(np.uint32)|(gray.astype(np.uint32)<<16)|(valid.astype(np.uint32)<<24)
        (out/f'h{ci}_rgb565.hex').write_text(''.join(f'{int(v):04x}\n' for v in rgb.ravel()),'ascii')
        (out/f'h{ci}_expected.hex').write_text(''.join(f'{int(v):08x}\n' for v in words.ravel()),'ascii')
        (out/f'h{ci}_valid.hex').write_text(''.join(f'{int(v):01x}\n' for v in valid.ravel()),'ascii')
        calls.append(f'run_case({ci},{w},{h},0);\n')
        index.append(dict(case=ci,name=c['name'],width=w,height=h,real=c['real']))
    calls.append('run_case(0,9,9,5);\n')
    calls.append('mode=2;run_case(0,9,9,2);mode=3;run_case(0,9,9,2);mode=4;run_case(0,9,9,4);mode=5;run_case(0,9,9,4);mode=0;\n')
    (out/'h2_cases.svh').write_text(''.join(calls),'ascii')
    sources=[REPO/'TJ/work/fpga_image_pipeline/rtl'/f for f in ('rgb565_gray.v','h2_background9.v')]+[HERE/'rtl/h2_scratch_writer.v',HERE/'sim/tb_h2_scratch.sv']
    hashes=simulate(out,'tb_h2_scratch',sources,'H2_SCRATCH_ALL_PASS 9')
    assert all(sha(Path(p))==d for p,d in protected.items())
    dump(out/'VERIFICATION.json',dict(status='PASS',cases=index,extra_BRESP_error_case=True,
        extra_error_cases=['wrong_input_request','malformed_sof','wrong_finish_request','upstream_H2_error'],
        source_sha256=hashes,protected_source_sha256=protected,PC_supplied_exact_valid=True,
        full_ROI_native_real_H2_frames=1,wall_seconds=time.monotonic()-start,
        physical_MIG=False,complete_board_integration=False,bit_generated=False,board_commands=0))
    print('H2_SCRATCH_RTL_PASS',flush=True)

if __name__=='__main__':main()
