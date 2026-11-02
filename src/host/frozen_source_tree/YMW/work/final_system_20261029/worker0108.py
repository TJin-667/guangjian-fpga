"""Read strict physical0108 archive; apply frozen current detector and review."""
import argparse,gzip,json,socket,sys,time
from pathlib import Path
import numpy as np
from archive0108 import load,sha
from hybrid import build_context
from performance import Ledger
from contracts import SYSTEM_VERSION
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--kind');parser.add_argument('--out',type=Path,required=True);parser.add_argument('--validation-mode',choices=('audit','reuse'),default='reuse');a=parser.parse_args();started=time.monotonic();timing=Ledger()
    def deny(*args,**kwargs):raise RuntimeError('0108 archive import prohibits sockets')
    socket.socket=deny;print('PHASE verified0108_archive',flush=True)
    from verified_evidence import load as load_evidence
    with timing.span('native_input_validation',requested_mode=a.validation_mode):x,validation_mode=load_evidence(a.source,mode=a.validation_mode)
    import frozen_algorithm as algorithm
    algorithm.configuration();review=algorithm.frozen_runtime.review.frozen_review
    with timing.span('hybrid_context_quality_and_R32_decode'):
        context,fused,provider=build_context(x['gray'],x['sat1'],x['board'],x['words'])
    record=dict(group_id=x['group_id'],sample=x['sample'],low=400,high=800,root=str(x['root']))
    parent=a.out/'final';parent.mkdir();target=parent/x['group_id']
    rows,scored=algorithm.process(context,record,target,timing=timing)
    with timing.span('finalize_reports_and_freeze_checks'):algorithm.finalize(parent,record,rows,started)
    gallery=[]
    def item(label,path):return dict(label=label,path=str(path),sha256=sha(path))
    gallery+=[item('最终检测 + 局部复检证据分',target/'priority_review.png'),item('当前冻结正式检测',target/'formal_detector.png')]
    originals=review.read(x['root']/'ORIGINALS.json')
    for r in originals:
        p=x['root']/r['png'];assert sha(p)==r['png_sha256'];gallery.append(item(r['label'],p))
    for w in scored['windows']:gallery.append(item(f"复检R{w['id']} / {w['evidence_support_score']}分",target/f"R{w['id']}_comparison.png"))
    result=dict(status='COMPLETE_REQUIRES_HUMAN_REVIEW',group_id=x['group_id'],specimen=x['sample'],roi_xywh=x['roi'],shape_hw=list(x['board'].shape),low_lines=400,high_lines=800,gain16=16,led=128,
                **algorithm.metadata(),integration_version=SYSTEM_VERSION,backend='offload0108_archive',physical_hardware=True,exposure_role='FORMAL_400_800',
                final_root=str(target),gallery=gallery,review_windows=scored['windows'],review_status=scored['status'],automatic_pass=False,probability_calibrated=False,input_source=str(x['root']),source_manifest_sha256=sha(x['root']/'RESULT.json'),
                new_physical_captures=0,html=str(parent/'index.html'),host_residual_access='exact_native_tiles',host_tile_cache_peak_bytes=provider.peak_cache_bytes,
                validation_scope=validation_mode,verification_cache=x.get('cache_receipt'),performance_json=str(a.out/'PERFORMANCE.json'))
    assert all(sha(p)==v for p,v in x['source_hashes'].items());review.write(a.out/'RESULT.json',result)
    capture_profile=x['root'].parent/'CAPTURE_PERFORMANCE.json'
    timing.save(a.out/'PERFORMANCE.json',status='COMPLETE',validation_mode=validation_mode,parameter_freeze_id=result['parameter_freeze_id'],
                physical_hardware_input=True,hardware_contacted_by_this_worker=False,source_capture_profile=str(capture_profile) if capture_profile.is_file() else None,
                source_capture_profile_sha256=sha(capture_profile) if capture_profile.is_file() else None,
                source_group=x['group_id'],caveat='This worker replays saved inputs; its wall time is not FPGA compute time or acquisition end-to-end time.')
    review.write(a.out/'OUTPUT_MANIFEST.json',dict(status='SEALED_FINAL_RESULT',files_sha256={p.relative_to(a.out).as_posix():sha(p) for p in a.out.rglob('*') if p.is_file() and p.name not in ('OUTPUT_MANIFEST.json','worker.log','JOB.json')}))
    print('FINAL0108_ARCHIVE_COMPLETE',str(a.out),flush=True)

if __name__=='__main__':main()
