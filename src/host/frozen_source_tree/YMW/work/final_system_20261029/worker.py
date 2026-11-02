"""Stable backend adapter; strict baseline input then the current frozen API."""
import argparse,csv,importlib.util,json,socket,sys,time
from pathlib import Path
import numpy as np
from contracts import validate_planes,ORDER,SYSTEM_VERSION
from performance import Ledger
HERE=Path(__file__).resolve().parent

class FileCancellation:
    def __init__(self,path):self.path=path
    def is_set(self):return self.path.exists()
    def wait(self,seconds):
        import time
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self.is_set():return True
            time.sleep(min(.03,max(0,deadline-time.monotonic())))
        return self.is_set()

def main():
    started=time.monotonic();timing=Ledger()
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--kind',choices=('capture','b1'),required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--validation-mode',choices=('audit','reuse'),default='reuse');a=p.parse_args()
    def deny(*args,**kwargs):raise RuntimeError('Offline final worker prohibits sockets')
    socket.socket=deny
    sys.path.insert(0,str(HERE.parent/'b1_detection_console_20261027'))
    from engine import run_job,verify_result
    from common import read,write,sha
    if a.kind=='capture':
        print('PHASE strict_input_and_baseline',flush=True);b1,status=run_job(a.source,a.out/'baseline',cancel=FileCancellation(a.out/'CANCEL_REQUESTED'),notify=lambda s:print(s,flush=True))
        if status['status']!='COMPLETED':raise RuntimeError(status.get('error','Baseline failed'))
    else:b1=a.source.resolve()
    meta=verify_result(b1)
    with np.load(b1/'arrays/original_eight_frames.npz',allow_pickle=False) as z:validate_planes({k:z[k] for k in z.files})
    frames=list(csv.DictReader((b1/'frame_inputs.csv').open(encoding='utf-8-sig')))
    if tuple(r['observation'] for r in frames)!=ORDER:raise ValueError('Eight-frame identity order differs')
    import frozen_algorithm as algorithm
    algorithm.configuration()
    review=algorithm.frozen_runtime.review.frozen_review
    group=dict(group_id=meta['group_id'],sample=meta['specimen'],low=meta['low_lines'],high=meta['high_lines'],root=str(b1))
    target=a.out/'final';target.mkdir();print('PHASE frozen_detection_and_review',flush=True)
    with timing.span('sealed_B1_input_validation_and_PC_fusion'):context=review.load_sealed(b1)
    rows,scored=algorithm.process(context,group,target/group['group_id'],timing=timing)
    review.verify_inputs(context)
    # Reuse the existing eight-frame comparison; no new captures or geometry changes.
    from PIL import Image
    with Image.open(b1/'raw_eight_comparison.png') as im:im.convert('RGB').save(target/group['group_id']/'original8_preview.jpg',quality=94)
    with timing.span('finalize_reports_and_freeze_checks'):algorithm.finalize(target,group,rows,started)
    final=target/group['group_id'];window_data=read(final/'REVIEW_PRIORITY.json');gallery=[]
    def item(label,path):return dict(label=label,path=str(path),sha256=sha(path))
    gallery.append(item('最终检测 + 局部复检证据分',final/'priority_review.png'))
    gallery.append(item('当前冻结正式检测',final/'formal_detector.png'))
    gallery.append(item('同组八张原片',b1/'raw_eight_comparison.png'))
    for frame in frames:gallery.append(item(f"原片 {frame['observation']} / {frame['exposure_lines']}行",Path(frame['source_path'])))
    for w in scored['windows']:gallery.append(item(f"复检R{w['id']} / {w['evidence_support_score']}分",final/f"R{w['id']}_comparison.png"))
    result=dict(status='COMPLETE_REQUIRES_HUMAN_REVIEW',group_id=meta['group_id'],specimen=meta['specimen'],roi_xywh=meta['roi_xywh'],shape_hw=meta['shape_hw'],low_lines=meta['low_lines'],high_lines=meta['high_lines'],gain16=16,led=128,
                **algorithm.metadata(),integration_version=SYSTEM_VERSION,backend='stable0107_pc',exposure_role='FORMAL_400_800' if (meta['low_lines'],meta['high_lines'])==(400,800) else 'EXPERIMENTAL_EXPOSURE',
                baseline_root=str(b1),final_root=str(final),gallery=gallery,review_windows=window_data['windows'],review_status=window_data['status'],automatic_pass=False,probability_calibrated=False,
                input_source=str(a.source.resolve()),source_manifest=meta['source_manifest'],source_manifest_sha256=meta['source_manifest_sha256'],new_physical_captures=0,html=str(target/'index.html'),performance_json=str(a.out/'PERFORMANCE.json'))
    timing.save(a.out/'PERFORMANCE.json',status='COMPLETE',backend='stable0107_pc',parameter_freeze_id=result['parameter_freeze_id'],hardware_contacted=False)
    write(a.out/'RESULT.json',result);write(a.out/'OUTPUT_MANIFEST.json',dict(status='SEALED_FINAL_RESULT',files_sha256={p.relative_to(a.out).as_posix():sha(p) for p in a.out.rglob('*') if p.is_file() and p.name not in ('OUTPUT_MANIFEST.json','worker.log','JOB.json')}))
    print('FINAL_COMPLETE '+str(a.out),flush=True)

if __name__=='__main__':main()
