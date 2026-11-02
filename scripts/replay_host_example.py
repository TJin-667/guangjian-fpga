"""Replay the eight real example frames through the packaged GUI algorithm API."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import argparse,gzip,hashlib,importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(value,message):
    if not value:raise ValueError(message)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    out=a.out.resolve();need(not out.exists(),'Use a new output directory');out.mkdir(parents=True)
    allowed=[ROOT,out,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve()]
    def audit(event,values):
        if event.startswith('socket.') or event in ('subprocess.Popen','os.system'):raise RuntimeError('Offline replay cannot contact devices or start processes')
        if event=='open' and isinstance(values[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(values[0])).resolve()
            need(any(p.is_relative_to(base) for base in allowed),'External project path read: '+str(p))
    sys.addaudithook(audit);sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT/'scripts'))
    from export_guard import verify
    verify()
    from export_paths import SOURCE_ROOT,vendor_root
    case=ROOT/'data/examples/portable004/cases/sample004_gray49';index=read(case/'CASE.json')
    for rel,digest in read(case/'MANIFEST.json')['files_sha256'].items():need(sha(case/rel)==digest,'Example changed: '+rel)
    import cv2,numpy as np
    cv2.setNumThreads(1)
    work=SOURCE_ROOT/'YMW/work'
    sys.path.insert(0,str(vendor_root()))
    from dual_exposure_b1.fusion import single_features,fuse_two_stage
    from light_inspection.real_baseline import hysteresis_connect
    spec=importlib.util.spec_from_file_location('_host_replay_codec',work/'gray_sat_0105_20261025/codec.py')
    codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
    gray=[];sat=[];board=None
    for i,frame in enumerate(index['frames'],1):
        need(frame['slot']==i,'Frame order changed')
        record=read(case/frame['record']);p=record['actual_parameters']
        need(record['status']=='COMMITTED' and record['strict_verified'] and record['firmware']==264,'Not the archived0108 physical frame')
        need(p['exposure_lines']==(400 if i%2 else 800) and p['gain16']==16 and p['brightness']==128 and p['light_mask']==1<<((i-1)//2),'Actual exposure/light changed')
        for name,digest in record['archived_file_sha256'].items():need(sha((case/frame['record']).parent/name)==digest,'Archived source changed')
        shape=(index['height'],index['width'])
        g=np.frombuffer((case/frame['gray']).read_bytes(),np.uint8).reshape(shape)
        s=np.unpackbits(np.frombuffer((case/frame['sat']).read_bytes(),np.uint8),bitorder='big')[:g.size].reshape(shape).astype(bool)
        m=np.frombuffer((case/frame['mask']).read_bytes(),np.uint8).reshape(shape)
        need(np.all(m<=1) and m.any(),'Invalid mask')
        if board is None:board=m.astype(bool)
        need(np.array_equal(board,m.astype(bool)),'Mixed masks')
        dg,ds=codec.decode((case/frame['raw']).read_bytes(),index['width'],index['height'])
        need(np.array_equal(dg,g) and np.array_equal(ds,s),'Payload/planes mismatch')
        gray.append(g);sat.append(s)
    need(len(gray)==8,'Eight physical frames required')
    gray=np.stack(gray);sat=np.stack(sat)
    features=[single_features(g) for g in gray]
    residual=np.stack([f['residual_n'] for f in features]);valid=np.stack([f['valid'] for f in features])
    fused=fuse_two_stage(residual,valid,board=board)['final']
    sys.path.insert(0,str(work/'fusion_offload_0108_20261028/host'))
    from result_codec import decode_words
    actual,selected=decode_words(np.frombuffer((case/'fusion/fpga_result.r32').read_bytes(),'<u4').reshape(board.shape),board,hysteresis_connect)
    fusion_diff={k:int(np.count_nonzero(actual[k]!=v)) for k,v in fused.items()}
    need(not any(fusion_diff.values()),'Existing FPGA result differs from PC input fusion')
    sys.path.insert(0,str(work/'final_board_0109_20261030/runtime'))
    from frozen_algorithm import configuration
    configuration()
    import frozen_runtime
    from sleeve_guard import prepare
    r=np.abs(fused['residual_n'].astype('int32'));v=~fused['unknown']
    guide=hysteresis_connect(r,v,486,1620)['mask']&board
    context=dict(planes=dict(gray=gray,sat1=sat,residual_n=residual,valid=valid,board=board),r=r,v=v,board=board,
                 original=fused['mask'],guide=guide,hysteresis=hysteresis_connect,caches={},tip_cache={},
                 sleeve=prepare(fused['mask'],guide,r),original_differences=fusion_diff)
    result,evidence,scored=frozen_runtime.process(context)
    with np.load(case/'expected/formal_arrays.npz',allow_pickle=False) as z:
        diffs={k:int(np.count_nonzero(value!=z[k])) for k,value in result.items()}
    with gzip.open(case/'expected/GAP_REVIEWS.json.gz','rt',encoding='utf8') as f:expected=json.load(f)
    scores=read(case/'expected/REVIEW_PRIORITY.json')
    score_identity=frozen_runtime.review.score_identity
    need(not any(diffs.values()) and evidence==expected and score_identity(scored)==score_identity(scores),'Packaged host algorithm/review differs')
    verify()
    report=dict(status='PACKAGED_HOST_REPLAY_PASSED',group_id=index['group_id'],formal_frames=8,
                freeze='f09eb5885e1d',same_input_fusion_differences=fusion_diff,formal10_differences=diffs,
                full_review_evidence_equal=True,full_score_equal=True,external_project_reads=0,
                network_and_hardware_operations=0,new_physical_captures=0,
                scope='Existing0108 real bytes replayed through the current packaged host API; no new0109 physical capture')
    (out/'HOST_REPLAY_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
