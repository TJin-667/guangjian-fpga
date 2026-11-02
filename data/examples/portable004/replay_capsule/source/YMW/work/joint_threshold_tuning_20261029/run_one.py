"""Separate offline entry for the joint configuration, never production install."""
import argparse,importlib.util,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from joint_gate import build_cache,output,cutoff
from run_study import read,write,sha,labelled

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def verify_package():
    b=read(HERE/'PACKAGE_BINDING.json')
    for relative,digest in b['files_sha256'].items():
        if sha(HERE/relative)!=digest:raise ValueError('Package changed: '+relative)
    return sha(HERE/'PACKAGE_BINDING.json')
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();package_sha=verify_package();source=a.input.resolve();out=a.out.resolve()
    if out.exists() or source==out or source in out.parents or out in source.parents:raise ValueError('Use a new separate output directory')
    def deny(*a,**k):raise RuntimeError('Offline entry prohibits sockets')
    socket.socket=deny;start=time.monotonic();frozen=read(HERE/'FROZEN_CONFIG.json');c=frozen['selected']['config'];s=read(source/'summary.json');audit=read(source/'input_audit.json');seal=read(source/'OUTPUT_MANIFEST.json')
    if s['frame_order']!=[f'CH{i}_{exposure}' for i in range(1,5) for exposure in ('low','high')] or s['gain16']!=16 or s['led']!=128:raise ValueError('Input observation contract mismatch')
    files={str(source/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts'])
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Input SHA mismatch '+path)
    spec=importlib.util.spec_from_file_location('_single_joint_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor))
    from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    with np.load(source/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
    with np.load(source/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
    fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];differences={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved}
    if any(differences.values()):raise ValueError('Frozen B1 differs')
    response=np.abs(fused['residual_n'].astype('int32'));valid=~fused['unknown'];board=planes['board'];reference=hysteresis_connect(response,valid,486,1620)['mask']&board
    wp=hysteresis_connect(response,valid,cutoff(c['weak']),1620)['mask']&board;pool=hysteresis_connect(response,valid,cutoff(c['weak']),1134)['mask']&board
    cache=build_cache(response,valid,board,reference,wp,pool,planes['gray'],planes['valid'],policy=c['policy']);res,routes=output(cache,c);ordinary=hysteresis_connect(response,valid,cutoff(c['weak']),cutoff(c['strong']))['mask']&board
    if (saved['mask']&~res['candidate']).any() or (res['candidate']&~ordinary).any():raise AssertionError('Output containment failed')
    n,labels=cv2.connectedComponents(res['supplement'].astype('uint8'),connectivity=8)
    for label in range(1,n):
        if not ((labels==label)&valid&(response>cutoff(c['strong']))).any():raise AssertionError('Actual strong seed absent')
    out.mkdir(parents=True,exist_ok=False);np.savez_compressed(out/'masks.npz',original=saved['mask'],reference=reference,ordinary=ordinary,**res)
    mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[reference]=[255,210,0];rgb[res['supplement']]=[0,225,240]
    labelled(rgb,[f'联合阈值实验：补充弱{c["weak"]:g}/强{c["strong"]:g}','黄=固定6/20，青=有实际种子的隔离补充',s['group_id']]).save(out/'selected.png');rgb[res['review']]=[255,120,40]
    labelled(rgb,['橙=未准入的弱阈值候选；不是误检真值','现用正式算法与bit未修改',s['group_id']]).save(out/'review.png')
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Source changed during run')
    verify_package();write(out/'receipt.json',dict(status='JOINT_THRESHOLD_EXPERIMENT_COMPLETE_REQUIRES_REVIEW',group_id=s['group_id'],config=c,config_id=frozen['selected']['id'],package_sha256=package_sha,
        candidate_pixels=int(res['candidate'].sum()),supplement_pixels=int(res['supplement'].sum()),review_pixels=int(res['review'].sum()),original_b1_differences=differences,input_files_verified=len(files),inputs_unchanged=True,
        routes=routes,runtime_seconds=time.monotonic()-start,formal_detector_changed=False,FPGA_changed=False))
    print('JOINT_SINGLE_ENTRY_PASS',out,flush=True)
if __name__=='__main__':main()
