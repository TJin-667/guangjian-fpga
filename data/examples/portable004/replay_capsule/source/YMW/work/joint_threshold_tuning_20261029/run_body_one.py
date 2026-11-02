"""Offline one-group entry for original8/20 protection and controlled tips."""
import argparse,importlib.util,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from joint_gate import build_cache,cutoff
from body_guard import supplements,extend
from run_study import read,write,sha,labelled
from joint_package_contract import verify_package

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();package_sha=verify_package();source=a.input.resolve();out=a.out.resolve()
    if out.exists() or source==out or source in out.parents or out in source.parents:raise ValueError('Use a new separate output directory')
    def deny(*a,**k):raise RuntimeError('Offline entry prohibits sockets')
    socket.socket=deny;start=time.monotonic();frozen=read(HERE/'FROZEN_BODY_CONFIG.json');c=frozen['selected']['config'];summary=read(source/'summary.json');audit=read(source/'input_audit.json');seal=read(source/'OUTPUT_MANIFEST.json')
    if summary['frame_order']!=[f'CH{i}_{e}' for i in range(1,5) for e in ('low','high')] or summary['gain16']!=16 or summary['led']!=128:raise ValueError('Observation contract mismatch')
    files={str(source/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts'])
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Input SHA mismatch '+path)
    spec=importlib.util.spec_from_file_location('_body_single_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    with np.load(source/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
    with np.load(source/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
    fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved}
    if any(diff.values()):raise ValueError('Frozen original B1 differs')
    r=np.abs(fused['residual_n'].astype('int32'));v=~fused['unknown'];b=planes['board'];original=saved['mask'];guide=hysteresis_connect(r,v,486,1620)['mask']&b;caches={}
    for weak in set([6.,c['weak']]):
        wp=hysteresis_connect(r,v,cutoff(weak),1620)['mask']&b;plain14=hysteresis_connect(r,v,cutoff(weak),1134)['mask']&b;caches[weak]=build_cache(r,v,b,guide,wp,plain14,planes['gray'],planes['valid'],policy='fixed6_20_isolated_supplements')
    base,anchor,s6,low=supplements(caches[6.],caches[c['weak']],c,original);ordinary=hysteresis_connect(r,v,cutoff(c['weak']),cutoff(c['strong']))['mask']&b;res=extend(base,anchor,ordinary,r,c,c['reach'],c['half_width']);mask=res['candidate']
    if (original&~mask).any() or (mask&~ordinary).any():raise AssertionError('Original protection or observed containment failed')
    n,labels=cv2.connectedComponents(mask.astype('uint8'),connectivity=8)
    for label in np.unique(labels[mask&~original]):
        if label and not ((labels==label)&v&(r>cutoff(c['strong']))).any():raise AssertionError('Unseeded component has new pixels')
    out.mkdir(parents=True,exist_ok=False);np.savez_compressed(out/'masks.npz',original=original,guide6_20=guide,isolated6=s6,isolated_low=low,ordinary=ordinary,**{k:v for k,v in res.items() if k!='tip_count'})
    mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[original]=[255,210,0];rgb[mask&~original]=[0,225,240]
    labelled(rgb,[f'受控结构实验：弱{c["weak"]:g}/强{c["strong"]:g}','黄=旧8/20保护，青=受控新增；6/20不再逐像素锁死',summary['group_id']]).save(out/'selected.png');rgb[guide&~mask]=[255,120,40]
    labelled(rgb,['橙=从6/20收回；非已确认误检','只读离线处理，现用程序与bit未修改',summary['group_id']]).save(out/'retracted.png')
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Input changed during run')
    verify_package();write(out/'receipt.json',dict(status='BODY_GUARD_EXPERIMENT_COMPLETE_REQUIRES_REVIEW',group_id=summary['group_id'],config_id=frozen['selected']['id'],config=c,package_sha256=package_sha,
        original_pixels=int(original.sum()),candidate_pixels=int(mask.sum()),added_pixels=int((mask&~original).sum()),retracted6_20_pixels=int((guide&~mask).sum()),original_b1_differences=diff,input_files_verified=len(files),inputs_unchanged=True,
        runtime_seconds=time.monotonic()-start,formal_detector_changed=False,FPGA_changed=False))
    print('BODY_SINGLE_ENTRY_PASS',out,flush=True)
if __name__=='__main__':main()
