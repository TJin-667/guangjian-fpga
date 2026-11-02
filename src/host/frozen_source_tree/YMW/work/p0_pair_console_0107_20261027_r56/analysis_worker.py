"""CPU-only untrained low/high/equal evidence comparisons; never hardware I/O."""
import argparse
import json
import socket
from pathlib import Path
import cv2
import numpy as np
import capture_backend as backend
import xdl_crop_adapter

def forbidden(*args,**kwargs):raise AssertionError('Offline evidence worker prohibits sockets')
socket.socket=forbidden

def analyze(manifest,out):
    from console_workflow import verify_bundle
    verify_bundle()
    runner=xdl_crop_adapter.load()
    if runner.run_manifest(manifest,out)!=0:raise ValueError('Complete verified paired input required')
    status=backend.read(out/'run_status.json');rows=status['groups'];need=backend.need
    need(len(rows)==3,'Exactly low/high/equal evidence outputs expected')
    scores=[]
    for row in rows:
        with np.load(out/row['score_map'],allow_pickle=False) as data:
            score=np.maximum(data['bright'],data['dark']).copy()
        need(np.isfinite(score).all(),'Nonfinite evidence score');scores.append(score)
    scale=max(1e-6,max(float(np.percentile(score,99)) for score in scores))
    panels=[];views=[]
    for row,score in zip(rows,scores):
        display=cv2.applyColorMap(np.clip(score/scale*255,0,255).astype(np.uint8),cv2.COLORMAP_TURBO)
        name=row['mode']+'_evidence.png';need(cv2.imwrite(str(out/name),display),'Evidence PNG failed')
        thumb=cv2.resize(display,(480,270),interpolation=cv2.INTER_AREA)
        panel=np.full((310,480,3),245,np.uint8);panel[35:305]=thumb
        cv2.putText(panel,row['mode']+' evidence',(8,23),cv2.FONT_HERSHEY_SIMPLEX,.62,(25,25,25),1,cv2.LINE_AA)
        panels.append(panel);views.append(dict(mode=row['mode'],image=name))
    cv2.imwrite(str(out/'comparison_shared_scale.png'),np.concatenate(panels,axis=1))
    backend.write(out/'console_analysis.json',dict(status='OFFLINE_EVIDENCE_ONLY',shared_display_p99=scale,views=views,
        comparison='comparison_shared_scale.png',trained_global_or_gate_available=False,quality_or_probability='NOT_EVALUATED',
        input_manifest_sha256=backend.sha(manifest),sockets_forbidden=True))
    # Seal derived analysis separately; raw pair and its ZIP remain unchanged.
    core=backend.original.Runtime().core
    core.finalize_output(out,dict(status='OFFLINE_EVIDENCE_ONLY',hardware_contacted=False,training_data=False,
        quality_evaluated=False,release_ready=False,source_manifest_sha256=backend.sha(manifest)))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();analyze(args.manifest.resolve(),args.out.resolve());print(json.dumps(dict(status='OFFLINE_EVIDENCE_ONLY',output=str(args.out))))
