"""Fresh native handoff + actual child pipeline, matched saved physical input."""
from export_paths import legacy_location, data_path, lab_root, network
import argparse
import gzip
import json
from pathlib import Path
import socket
import statistics
import sys
import time
import traceback
import bootstrap as b
import numpy as np

GROUPS=('20261030_225025_a644ed97','20261030_230733_a1944cee','20261030_230958_696830ab')

def check(saved, result, score_identity):
    output=Path(result['final_root']); saved=Path(saved['final_root'])
    with np.load(saved/'formal_arrays.npz',allow_pickle=False) as a,np.load(output/'formal_arrays.npz',allow_pickle=False) as z:
        b.need(set(a.files)==set(z.files) and all(np.array_equal(a[k],z[k]) for k in a.files),'Formal arrays changed')
    with gzip.open(saved/'GAP_REVIEWS.json.gz','rt',encoding='utf-8') as a,gzip.open(output/'GAP_REVIEWS.json.gz','rt',encoding='utf-8') as z:
        b.need(json.load(a)==json.load(z),'Full review evidence changed')
    b.need(score_identity(b.read(saved/'REVIEW_PRIORITY.json'))==score_identity(b.read(output/'REVIEW_PRIORITY.json')),'Scores changed')

def run(out,repetitions):
    def deny(*args,**kwargs):raise RuntimeError('Saved-input replay prohibits sockets')
    socket.socket=socket.create_connection=deny
    b.verify();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(b.HERE.parent/'system_benchmark_0109_20261031'))
    from core import Tools,environment
    tools=Tools(False)
    import archive0109 as archive
    import verified_evidence as original
    import combined_evidence as combined
    from speed_pipeline import run as pipeline
    rows=[];summaries=[]
    b.write(out/'EXECUTED_CANDIDATE.json',b.read(b.HERE/'CANDIDATE_BINDING.json'))
    b.write(out/'ENVIRONMENT.json',environment())
    try:
        for gi,gid in enumerate(GROUPS):
            old=legacy_location('E:/GuangjianData/UnifiedInspection')/gid
            original_manifest=b.read(old/'OUTPUT_MANIFEST.json')['files_sha256']
            b.need(all(b.sha(old/name)==sha for name,sha in original_manifest.items()),'Original final seal changed')
            saved=b.read(old/'RESULT.json');x=archive.load(saved['input_source'])
            # Both deployed capture paths already build these audit fields;
            # reconstruct once from strict existing source, outside both timers.
            x['residual_n']=np.stack([tools.h2(g)['residual_n'] for g in x['gray']])
            x['valid']=np.stack([tools.quality(g)['valid_mask'] for g in x['gray']])
            b.need(np.array_equal(tools.pack(x['gray'],x['residual_n'],x['valid']),x['words']),'Reconstructed audit differs from actual PL R32')
            group_rows=[]
            for repetition in range(1,repetitions+1):
                order=('reference','combined') if (gi+repetition)%2 else ('combined','reference')
                for method in order:
                    target=out/gid/f'{method}_r{repetition}';target.mkdir(parents=True)
                    cache_base=target/'cache'
                    started=time.perf_counter();cpu=time.process_time()
                    cache=(original if method=='reference' else combined).seal(x,cache_base,origin='OFFLINE_RECONSTRUCTION_OF_CAPTURE_AUDIT_NOT_NEW_BOARD_DATA')
                    parent_seal_seconds=time.perf_counter()-started
                    final,status=pipeline(x['root'],'0109',target/'analysis',cache_base=cache_base,reference=method=='reference')
                    seconds=time.perf_counter()-started
                    b.need(status['status']=='COMPLETE',str(status))
                    result=b.read(final/'RESULT.json')
                    b.need(result['validation_scope']==('VERIFIED_HASH_REUSE' if method=='reference' else 'COMBINED_VERIFIED_HASH_REUSE'),'Wrong measured path')
                    check(saved,result,tools.algorithm.frozen_runtime.review.score_identity)
                    row=dict(source_group=gid,method=method,repetition=repetition,seconds=seconds,parent_seal_seconds=parent_seal_seconds,
                             parent_only_CPU_seconds=time.process_time()-cpu,child_process_wall_seconds=status['worker_process_wall_seconds'],
                             source=str(x['root']),source_result_sha256=b.sha(x['root']/'RESULT.json'),analysis=str(final),cache=str(cache),
                             cache_bytes=(cache/'native.npz').stat().st_size,formal_arrays_full_review_scores_equal=True)
                    rows.append(row);group_rows.append(row)
                    b.write(out/'PROGRESS.json',dict(status='RUNNING',completed=len(rows),expected=len(GROUPS)*repetitions*2,latest=row))
                    print(gid,method,repetition,f'{seconds:.3f}s exact=PASS',flush=True)
                    b.need(seconds<120,'LONG_HOST_PAUSE: preserve entire batch; no automatic retry')
            a=[r['seconds'] for r in group_rows if r['method']=='reference'];c=[r['seconds'] for r in group_rows if r['method']=='combined']
            am,cm=statistics.median(a),statistics.median(c)
            summaries.append(dict(group=gid,reference_seconds=a,combined_seconds=c,reference_median=am,combined_median=cm,
                                  reduction_percent=100*(am-cm)/am,software_phase_reference_over_combined=am/cm))
            b.need(all(b.sha(name)==sha for name,sha in x['source_hashes'].items()),'Original input changed')
            b.write(out/'GROUPS.json',summaries)
        b.verify()
        b.write(out/'RESULT.json',dict(status='PASS_MATCHED_HANDOFF_CHILD_AND_FULL_EXPORT',groups=summaries,runs=rows,repetitions=repetitions,
              new_CAP=0,hardware_contacted=False,system_speedup=None,FPGA_compute_speedup=None,
              candidate_binding_sha256=b.sha(b.HERE/'CANDIDATE_BINDING.json'),
              scope='Same saved physical eight frames/R32, existing audit arrays in RAM -> fresh complete native/derivative handoff -> actual subprocess startup, validation, frozen math, images/reports, pipeline sealing. Excludes acquisition, FPGA service/FETCH, positioning, one-time parent imports and independent proofs. Parent-only CPU clock excludes child CPU.'))
    except BaseException as exc:
        b.write(out/'FAILED.json',dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc(),completed=rows))
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--repetitions',type=int,default=3)
    a=p.parse_args();run(a.out,a.repetitions)
