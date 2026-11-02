"""Separate experimental entry for the final sleeve configuration."""
import argparse,socket,time
from pathlib import Path
import numpy as np
from sleeve_runtime import load_sealed,predict,verify_inputs
from joint_package_contract import verify_package
from run_study import read,write,labelled

HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();package_sha=verify_package();root=a.input.resolve();out=a.out.resolve()
    if out.exists() or root==out or root in out.parents or out in root.parents:raise ValueError('Use a new separate output directory')
    def deny(*a,**k):raise RuntimeError('Offline only')
    socket.socket=deny;start=time.monotonic();frozen=read(HERE/'FROZEN_SLEEVE_CONFIG.json');c=frozen['selected']['config'];x=load_sealed(root);res=predict(x,c);out.mkdir(parents=True,exist_ok=False);np.savez_compressed(out/'masks.npz',**res)
    mean=np.rint(x['planes']['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[x['original']]=[255,210,0];rgb[res['candidate']&~x['original']]=[0,225,240]
    labelled(rgb,[f'弱{c["weak"]:g}/强{c["strong"]:g} | 侧向上限6/20 | 套内半径{c["side_radius"]}px','黄=旧8/20，青=受控新增；独立离线实验',x['summary']['group_id']]).save(out/'selected.png');rgb[x['guide']&~res['candidate']]=[255,120,40]
    labelled(rgb,['橙=从6/20收回，不是已确认误检','侧向增长不超6/20；端部延伸另受走向和连接限制',x['summary']['group_id']]).save(out/'retracted.png');verify_inputs(x);verify_package()
    write(out/'receipt.json',dict(status='SLEEVE_EXPERIMENT_COMPLETE_REQUIRES_REVIEW',group_id=x['summary']['group_id'],config_id=frozen['selected']['id'],config=c,package_sha256=package_sha,candidate_pixels=int(res['candidate'].sum()),added_pixels=int((res['candidate']&~x['original']).sum()),side_added_pixels=int(res['side_addition'].sum()),retracted6_20_pixels=int((x['guide']&~res['candidate']).sum()),original_b1_differences=x['original_differences'],input_files_verified=len(x['files']),inputs_unchanged=True,runtime_seconds=time.monotonic()-start,formal_detector_changed=False,FPGA_changed=False))
    print('SLEEVE_SINGLE_ENTRY_PASS',out,flush=True)
if __name__=='__main__':main()
