"""Offline review evidence next to, never inside, the frozen detector output."""
import argparse,socket,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from confidence_runtime import assess
from shadow_package_contract import verify
from sleeve_runtime import load_sealed,verify_inputs
from joint_package_contract import verify_package as verify_formal
from run_study import read,write,labelled,font

HERE=Path(__file__).resolve().parent;FORMAL=HERE.parent/'joint_threshold_tuning_20261029'
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();root=a.input.resolve();out=a.out.resolve();binding=verify();formal_binding=verify_formal()
    if out.exists() or root==out or root in out.parents or out in root.parents:raise ValueError('Choose a new separate output directory')
    def deny(*a,**k):raise RuntimeError('Offline confidence entry prohibits sockets')
    socket.socket=deny;start=time.monotonic();plan=read(HERE/'PLAN_V4.json');config=read(FORMAL/'FROZEN_SLEEVE_CONFIG.json')['selected']['config'];x=load_sealed(root);res=assess(x,config,plan);verify_inputs(x)
    out.mkdir(parents=True,exist_ok=False);np.savez_compressed(out/'confidence_reference_arrays.npz',**res['arrays']);write(out/'RESULT.json',res['result']);write(out/'RAW_EVIDENCE.json',res['raw_evidence']);write(out/'REVIEW_REGIONS.json',res['review_regions']);write(out/'SHADOW_COMPARISONS.json',res['shadow_comparisons'])
    mean=np.rint(x['planes']['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[res['arrays']['formal_detector_mask']]=[255,210,0];labelled(rgb,['正式参考掩膜保持不变','黄色=冻结检测，置信度对照不增加检测像素',x['summary']['group_id']]).save(out/'formal.png');view=Image.fromarray(rgb);d=ImageDraw.Draw(view)
    for w in res['review_regions'][:12]:d.rectangle((w['x0'],w['y0'],w['x1']-1,w['y1']-1),outline='#ff42ae',width=2);d.text((w['x0']+2,max(0,w['y0']-22)),str(w['id']),font=font(17),fill='#ff42ae')
    labelled(np.asarray(view),[res['result']['status'],'粉框=复检区；未标定为正确率，正式检测不变',x['summary']['group_id']]).save(out/'review_regions.png');verify();verify_formal()
    write(out/'receipt.json',dict(status='CONFIDENCE_REFERENCE_EXPERIMENT_COMPLETE',group_id=x['summary']['group_id'],package_sha256=binding,formal_package_sha256=formal_binding,input_files_verified=len(x['files']),formal_original_b1_differences=x['original_differences'],inputs_unchanged=True,manual_reference_used=False,FPGA_changed=False,new_captures=0,runtime_seconds=time.monotonic()-start))
    print('CONFIDENCE_ONE_COMPLETE',out,flush=True)
if __name__=='__main__':main()
