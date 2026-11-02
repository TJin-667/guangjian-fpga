"""Independent offline entry: a sealed existing B1 result -> new experiment dir.

Never acquires a frame, downloads a bit, modifies a source result or installs
over the current capture/detection program. The deployed firmware is irrelevant
to this read-only operation; real gray observations must already be retained.
"""
import argparse,hashlib,importlib.util,json,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from seeded_gate import build,masks
from run_study import read,write,sha,labelled

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def verify_package():
    binding=read(HERE/'PACKAGE_BINDING.json')
    for relative,digest in binding['files_sha256'].items():
        if sha(HERE/relative)!=digest:raise ValueError('Package file changed: '+relative)
    return sha(HERE/'PACKAGE_BINDING.json')
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    binding_sha=verify_package();source=a.input.resolve();out=a.out.resolve()
    if source==out or source in out.parents or out in source.parents:raise ValueError('Output must be separate from original result tree')
    if out.exists():raise FileExistsError('Use a new output directory')
    def deny(*a,**k):raise RuntimeError('Offline entry prohibits sockets')
    socket.socket=deny;start=time.monotonic();frozen=read(HERE/'FROZEN_CONFIG.json');config=frozen['selected']['config'];summary=read(source/'summary.json');audit=read(source/'input_audit.json');seal=read(source/'OUTPUT_MANIFEST.json')
    expected=['CH1_low','CH1_high','CH2_low','CH2_high','CH3_low','CH3_high','CH4_low','CH4_high']
    if summary['frame_order']!=expected or summary['gain16']!=16 or summary['led']!=128:raise ValueError('Frame order / validated gain / lighting mismatch')
    files={str(source/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts'])
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Source hash mismatch '+path)
    spec=importlib.util.spec_from_file_location('_seeded_single_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor))
    from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    with np.load(source/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
    with np.load(source/'arrays/all8_B1.npz',allow_pickle=False) as z:original={k:z[k].copy() for k in z.files}
    fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];differences={k:int(np.count_nonzero(fused[k]!=original[k])) for k in original}
    if any(differences.values()):raise ValueError('Original frozen B1 output differs')
    response=np.abs(fused['residual_n'].astype('int32'));valid=~fused['unknown'];board=planes['board'];core=hysteresis_connect(response,valid,486,1620)['mask']&board;loose=hysteresis_connect(response,valid,486,972)['mask']&board
    cache=build(response,valid,board,core,loose,planes['gray'],planes['valid'],profile_variants=[(config['length'],config['flank'])]);result,routes=masks(cache,config)
    if (original['mask']&~result['candidate']).any():raise AssertionError('Original detector pixels lost')
    # Verify every admitted piece against an actual valid strict seed, separately.
    n,labels=cv2.connectedComponents(result['supplement'].astype('uint8'),connectivity=8)
    for label in range(1,n):
        if not np.any((labels==label)&valid&(response>81*config['strong'])):raise AssertionError('Unseeded supplement')
    out.mkdir(parents=True,exist_ok=False);np.savez_compressed(out/'masks.npz',original=original['mask'],protected=core,loose=loose,**result)
    mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[core]=[255,210,0];rgb[result['supplement']]=[0,225,240]
    labelled(rgb,[f'有种子弱段补充 EXPERIMENTAL | {summary["low_lines"]}/{summary["high_lines"]}行','黄=6/20保护，青=新增；不是置信概率',summary['group_id']]).save(out/'selected.png')
    rgb[result['review']]=[255,120,40];labelled(rgb,['橙=未准入的6/12新增，保留待复检','橙色不是误检真值；无种子弱线不进入检测',summary['group_id']]).save(out/'review.png')
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Source changed during inference '+path)
    verify_package();write(out/'receipt.json',dict(status='SEEDED_EXPERIMENT_COMPLETE_REQUIRES_REVIEW',group_id=summary['group_id'],source_result=str(source),package_binding_sha256=binding_sha,
        config=config,config_id=frozen['selected']['id'],candidate_pixels=int(result['candidate'].sum()),supplement_pixels=int(result['supplement'].sum()),review_pixels=int(result['review'].sum()),
        original_b1_differences=differences,input_files_verified=len(files),all_inputs_unchanged=True,all_additions_have_actual_seed=True,routes=routes,runtime_seconds=time.monotonic()-start,formal_detector_changed=False,FPGA_changed=False))
    print(json.dumps(dict(status='SEEDED_EXPERIMENT_COMPLETE_REQUIRES_REVIEW',directory=str(out)),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
