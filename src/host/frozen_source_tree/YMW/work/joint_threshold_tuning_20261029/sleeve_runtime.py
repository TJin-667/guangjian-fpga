"""Reusable sealed-array offline runtime; no annotation or sample-ID logic."""
import importlib.util,sys
from pathlib import Path
import numpy as np
from joint_gate import build_cache,cutoff
from body_guard import supplements,extend
from sleeve_guard import prepare as prepare_sleeve,apply as apply_sleeve
from run_study import read,sha

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def load_sealed(root):
    root=Path(root).resolve();summary=read(root/'summary.json');audit=read(root/'input_audit.json');seal=read(root/'OUTPUT_MANIFEST.json')
    if summary['frame_order']!=[f'CH{i}_{e}' for i in range(1,5) for e in ('low','high')] or summary['gain16']!=16 or summary['led']!=128:raise ValueError('Observation contract mismatch')
    files={str(root/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts'])
    for path,digest in files.items():
        if sha(path)!=digest:raise ValueError('Input SHA mismatch '+path)
    spec=importlib.util.spec_from_file_location('_sleeve_runtime_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
    with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
    fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved}
    if any(diff.values()):raise ValueError('Original frozen B1 differs')
    r=np.abs(fused['residual_n'].astype('int32'));v=~fused['unknown'];b=planes['board'];guide=hysteresis_connect(r,v,486,1620)['mask']&b
    return dict(root=root,summary=summary,files=files,planes=planes,r=r,v=v,board=b,original=saved['mask'],guide=guide,hysteresis=hysteresis_connect,caches={},tip_cache={},sleeve=prepare_sleeve(saved['mask'],guide,r),original_differences=diff)

def predict(context,config):
    x=context;c=config;h=x['hysteresis']
    for weak in set([6.,c['weak']]):
        if weak not in x['caches']:
            wp=h(x['r'],x['v'],cutoff(weak),1620)['mask']&x['board'];pool=h(x['r'],x['v'],cutoff(weak),1134)['mask']&x['board'];x['caches'][weak]=build_cache(x['r'],x['v'],x['board'],x['guide'],wp,pool,x['planes']['gray'],x['planes']['valid'],policy='fixed6_20_isolated_supplements')
    base,anchor,s6,low=supplements(x['caches'][6.],x['caches'][c['weak']],c,x['original']);ordinary=h(x['r'],x['v'],cutoff(c['weak']),cutoff(c['strong']))['mask']&x['board'];body=extend(base,anchor,ordinary,x['r'],c,c['reach'],c['half_width'],x['tip_cache']);res=apply_sleeve(body['candidate'],x['sleeve'],c['side_radius'],c['strong'])
    if (x['original']&~res['candidate']).any() or (res['candidate']&~ordinary).any():raise AssertionError('Containment failed')
    return dict(original=x['original'],guide6_20=x['guide'],without_sleeve=body['candidate'],candidate=res['candidate'],side_addition=res['side_addition'],side_envelope=res['side_envelope'],isolated6=s6,isolated_low=low,terminal_extension=body['extension'],ordinary=ordinary)

def verify_inputs(context):
    for path,digest in context['files'].items():
        if sha(path)!=digest:raise ValueError('Input changed during inference')
