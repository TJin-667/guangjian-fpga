"""Relocatable, offline mathematical replay of one real frozen f09 group.

Original numerical modules are copied byte-exact into replay_capsule/source.
No installed YMW paths, transport, hardware, retuning or source monkeypatches.
"""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
import argparse
import gzip
import hashlib
import importlib.util
import json
import socket
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok:raise ValueError(message)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    need(not out.exists() and out!=HERE and HERE not in out.parents,'Choose a NEW output directory outside the handoff package')
    out.mkdir(parents=True,exist_ok=False)
    allowed=[HERE,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),out]
    opened=set()
    def audit(event,values):
        if event in ('socket.__new__','socket.connect','subprocess.Popen','os.system'):
            raise RuntimeError('Portable replay prohibits network, hardware and child processes')
        if event=='open' and isinstance(values[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(values[0])).resolve()
            if not any(p==base or p.is_relative_to(base) for base in allowed):
                raise RuntimeError('Replay attempted an external file read: '+str(p))
            opened.add(str(p))
    sys.addaudithook(audit)
    case=HERE/'cases/sample004_gray49';index=read(case/'CASE.json')
    for rel,digest in read(case/'MANIFEST.json')['files_sha256'].items():need(sha(case/rel)==digest,'Case bytes changed: '+rel)
    capsule=HERE/'replay_capsule'
    binding=read(capsule/'SOURCE_MANIFEST.json')
    for rel,digest in binding['files_sha256'].items():need(sha(capsule/rel)==digest,'Original numerical source changed: '+rel)
    import numpy as np
    import cv2
    cv2.setNumThreads(1)
    work=capsule/'source/YMW/work'
    sys.path.insert(0,str(capsule/'vendor'))
    from dual_exposure_b1.fusion import single_features,fuse_two_stage
    from light_inspection.real_baseline import hysteresis_connect
    codec_spec=importlib.util.spec_from_file_location('_portable_original_format49',work/'gray_sat_0105_20261025/codec.py')
    codec=importlib.util.module_from_spec(codec_spec);codec_spec.loader.exec_module(codec)
    gray=[];sat=[];board=None;identities=[]
    for i,frame in enumerate(index['frames'],1):
        need(frame['slot']==i,'Formal frame order changed')
        record=read(case/frame['record'])
        need(record['status']=='COMMITTED' and record['strict_verified'] is True and record['firmware']==264,'Not an original strict0108 frame')
        for name,digest in record['archived_file_sha256'].items():need(sha((case/frame['record']).parent/name)==digest,'Archived source changed')
        p=record['actual_parameters'];need(p['exposure_lines']==(400 if i%2 else 800) and p['gain16']==16 and p['brightness']==128 and p['light_mask']==1<<((i-1)//2),'Actual exposure/light identity changed')
        g=np.frombuffer((case/frame['gray']).read_bytes(),np.uint8).reshape(index['height'],index['width'])
        s=np.unpackbits(np.frombuffer((case/frame['sat']).read_bytes(),np.uint8),bitorder='big')[:g.size].reshape(g.shape).astype(bool)
        m=np.frombuffer((case/frame['mask']).read_bytes(),np.uint8).reshape(g.shape)
        need(np.all(m<=1) and m.any(),'Invalid board mask')
        if board is None:board=m.astype(bool)
        need(np.array_equal(board,m.astype(bool)),'Mixed masks')
        payload=(case/frame['raw']).read_bytes()
        decoded_gray,decoded_sat=codec.decode(payload,index['width'],index['height'])
        need(np.array_equal(decoded_gray,g) and np.array_equal(decoded_sat,s),'GRAY8/SAT do not match original format49 payload')
        gray.append(g);sat.append(s);identities.append(record['identity'])
    need(len({x['session'] for x in identities})==1 and len({(x['session'],x['request_id'],x['frame_id']) for x in identities})==8,'Repeated/mixed frame identities')
    gray=np.stack(gray);sat=np.stack(sat)
    features=[single_features(g) for g in gray]
    residual=np.stack([f['residual_n'] for f in features]);valid=np.stack([f['valid'] for f in features])
    fused=fuse_two_stage(residual,valid,board=board)['final']
    sys.path.insert(0,str(work/'fusion_offload_0108_20261028/host'))
    from result_codec import decode_words
    words=np.frombuffer((case/'fusion/fpga_result.r32').read_bytes(),dtype='<u4').reshape(board.shape)
    actual,selected_gray=decode_words(words,board,hysteresis_connect)
    fusion_diff={k:int(np.count_nonzero(actual[k]!=v)) for k,v in fused.items()}
    need(not any(fusion_diff.values()),'Same input FPGA R32 differs from PC fusion')
    yy,xx=np.indices(board.shape);source=fused['source_frame'];expected_gray=gray[np.maximum(source.astype(int)-1,0),yy,xx].copy();expected_gray[source==0]=0
    need(np.array_equal(selected_gray,expected_gray),'Selected-source gray differs')
    sys.path.insert(0,str(work/'final_parameter_check_20261030'))
    import frozen_runtime
    from sleeve_guard import prepare
    amplitude=np.abs(fused['residual_n'].astype('int32'));usable=~fused['unknown']
    guide=hysteresis_connect(amplitude,usable,486,1620)['mask']&board
    context=dict(planes=dict(gray=gray,sat1=sat,residual_n=residual,valid=valid,board=board),r=amplitude,v=usable,board=board,
        original=fused['mask'],guide=guide,hysteresis=hysteresis_connect,caches={},tip_cache={},sleeve=prepare(fused['mask'],guide,amplitude),original_differences=fusion_diff)
    output,evidence,scored=frozen_runtime.process(context)
    with np.load(case/'expected/formal_arrays.npz',allow_pickle=False) as saved:
        differences={k:int(np.count_nonzero(value!=saved[k])) for k,value in output.items()}
    with gzip.open(case/'expected/GAP_REVIEWS.json.gz','rt',encoding='utf-8') as stream:expected_evidence=json.load(stream)
    expected_scores=read(case/'expected/REVIEW_PRIORITY.json')
    score_identity=frozen_runtime.review.score_identity
    need(not any(differences.values()) and evidence==expected_evidence and score_identity(scored)==score_identity(expected_scores),'Frozen final detector/review differs from saved physical group')
    np.savez_compressed(out/'formal_arrays.npz',**output)
    with gzip.open(out/'GAP_REVIEWS.json.gz','wt',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,allow_nan=False)
    write(out/'REVIEW_PRIORITY.json',scored)
    for rel,digest in binding['files_sha256'].items():need(sha(capsule/rel)==digest,'Original source changed during replay')
    report=dict(status='PASS_RELOCATABLE_FROZEN_REPLAY',group_id=index['group_id'],parameter_freeze_id='f09eb5885e1d',formal_frames=8,
        same_input_fusion_differences=fusion_diff,selected_gray_differences=0,formal10_differences=differences,full_review_evidence_equal=True,
        full_score_equal=True,external_project_paths_read=False,network_and_hardware_access=False,physical_input=True,new_physical_captures=0,
        scope='Mathematical replay of existing real-board bytes; not a new physical run or original raw-wire protocol re-certification',original_numerical_sources_changed=False)
    write(out/'REPLAY_VERIFICATION.json',report)
    write(out/'READ_ACCESS.json',dict(allowed_roots=[str(p) for p in allowed],files=sorted(opened),scope='All Python open events restricted to this package, Python runtime and new output'))
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
