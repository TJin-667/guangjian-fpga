"""Visible-progress entry; reuse a verified frozen frame, keep strict eight intact."""
import argparse,contextlib,hashlib,json,math,sys,threading,time,zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'acceptance_0107_20261026'
sys.path.insert(0,str(BASE))
import numpy as np
import acceptance_operator as original
import gray_acquisition_workflow as workflow
import gray_capture_bridge as bridge
import sdk_transport as sdk

SAVED=Path('C:/Users/yue/Documents/Guangjian0107Acceptance/20261026_112752_60c452/acceptance/same_frozen')

def require(ok,message):
    if not ok:raise ValueError(message)
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):Path(p).parent.mkdir(parents=True,exist_ok=True);sdk.support.write_json(Path(p),obj)
def say(message):print(time.strftime('[%H:%M:%S] ')+message,flush=True)

def review_frozen(root,*,sensor_size=(1920,1080),binding=None):
    """Recompute from archived bytes; no SDK constructor, socket or new capture."""
    root=Path(root).resolve();summary=read(root/'operator_summary.json')
    require(summary['status']=='SAME_FROZEN_INPUT_VERIFIED' and summary['row']['logical_CAP_requests']==1,'Not a verified single-CAP source')
    require(summary['lights_off']['acknowledged'] and summary['lights_off']['ack']['original']==1 and summary['lights_off']['ack']['result']==0,'Missing original OFF ACK')
    relative=summary['row']['record'];path=(root/relative).resolve()
    require(path.is_relative_to(root),'Unsafe saved record path')
    record=read(path);folder=path.parent
    require(record['status']=='COMMITTED' and record['strict_verified'] is True and record['pixel_format']==50,'Not committed diagnostic50')
    require(record['evidence_source']==summary['evidence_source'],'Evidence scope differs')
    files={}
    for name,digest in record['archived_file_sha256'].items():
        require(Path(name).name==name and '/' not in name and '\\' not in name,'Unsafe artifact name')
        data=(folder/name).read_bytes();require(hashlib.sha256(data).hexdigest()==digest,'Changed saved artifact '+name);files[name]=data
    m=sdk.wire.decode_metadata(files['metadata_packet.bin'],record['metadata_query_seq'])
    require(m==record['diagnostic'] and m['identity']==record['identity']==summary['row']['identity'] and m['bank']==summary['row']['bank'],'Saved identity differs')
    require(m['valid'] and m['mask_valid'] and m['parameters_valid'] and m['logical_association_available'] and not m['error'] and m['pixel_format']==50,'Uncommitted metadata')
    require(m['roi']==record['requested']['roi']==summary['row']['roi'] and m['fifo_reads']==math.prod(sensor_size),'Geometry/drain differs')
    require(m['parameters']=={k:record['requested'][k] for k in sdk.wire.PARAM_KEYS},'Parameters differ')
    require(m['parameters']==dict(exposure_lines=600,gain16=16,light_mask=1,brightness=128,settle_frames=1,discard_frames=3),'Unexpected engineering parameters')
    raw=files[record['raw_payload_file']];x,y,w,h=m['roi'];n=w*h
    require(len(raw)==3*n+(n+7)//8==m['payload_bytes'],'Diagnostic length')
    # Independent group unpacking and independent integer gray/SAT/H1/H2 review.
    groups,tail=divmod(n,8);blocks=np.frombuffer(raw[:groups*25],np.uint8).reshape(groups,25)
    rgb=bytearray(blocks[:,:16].copy().tobytes());g=blocks[:,16:24].copy().reshape(-1);s=np.unpackbits(blocks[:,24].copy(),bitorder='big')
    if tail:
        at=groups*25;rgb.extend(raw[at:at+2*tail]);g=np.concatenate((g,np.frombuffer(raw[at+2*tail:at+3*tail],np.uint8)))
        require(raw[-1]&((1<<(8-tail))-1)==0,'SAT tail padding')
        s=np.concatenate((s,np.unpackbits(np.array([raw[-1]],np.uint8),bitorder='big')[:tail]))
    rgb=bytes(rgb);gray=g.reshape(h,w);sat=s.astype(bool).reshape(h,w)
    expected_gray,expected_sat=bridge.audit.planes(rgb,w,h,1)
    require(np.array_equal(gray,expected_gray) and np.array_equal(sat,expected_sat),'Same-frozen pixel/SAT mismatch')
    require(bridge.audit.crc64(raw)==m['payload_crc64'] and bridge.audit.crc64(rgb)==m['rgb_crc64'],'Raw CRC mismatch')
    require(files['same_frame.rgb565']==rgb and files['image.gray8']==gray.tobytes() and
        files['image.sat1']==np.packbits(sat.reshape(-1),bitorder='big').tobytes(),'Saved planes differ')
    maskraw=files['board_mask.bin'];require(len(maskraw)==n and set(maskraw)<={0,1} and any(maskraw),'Mask')
    mask=np.frombuffer(maskraw,np.uint8).reshape(h,w).astype(bool)
    require(bridge.audit.h1_h2(gray,sat,mask)==(m['statistics'],m['features']),'H1/H2 mismatch')
    require(record['cost']['capture_requests']==record['cost']['capture_command_transmissions']==1 and
        record['cost']['missing_image_packets']==0 and record['complete_packets']==math.ceil(len(raw)/1380),'Capture/packet count')
    if binding is not None:
        require(isinstance(record.get('candidate_binding'),dict),'Saved source lacks candidate binding')
        require(record['candidate_binding']['bit_sha256']==binding['bit_sha256'] and
            record['candidate_source_commit']==binding['candidate_source_commit'],'Different saved bit/source')
    archive=root.with_name(root.name+'.zip');archive_verified=False
    if archive.exists():
        receipt=read(archive.with_name(archive.name+'.receipt.json'))
        require(sha(archive)==receipt['archive_sha256'] and archive.stat().st_size==receipt['archive_bytes'],'Saved ZIP differs')
        inventory=read(root/'output_manifest.json')['files']
        with zipfile.ZipFile(archive) as z:
            require(set(z.namelist())==set(inventory)|{'output_manifest.json'} and len(z.namelist())==len(set(z.namelist())),'ZIP inventory differs')
            for name,digest in inventory.items():require(hashlib.sha256(z.read(name)).hexdigest()==digest and sha(bridge.inside(root,name))==digest,'Saved ZIP member differs')
        archive_verified=True
    return dict(status='PASS',source_root=str(root),record=str(path),evidence_source=record['evidence_source'],
        identity=m['identity'],pixels=n,gray_mismatches=0,sat_mismatches=0,H1_H2_equal=True,
        payload_bytes=len(raw),payload_sha256=hashlib.sha256(raw).hexdigest(),rgb_sha256=hashlib.sha256(rgb).hexdigest(),
        payload_crc64=m['payload_crc64'],rgb_crc64=m['rgb_crc64'],archive_verified=archive_verified,
        source_record_sha256=sha(path),original_OFF_ACK_verified=True,additional_CAP_requests=0,
        hardware_verified=record['evidence_source']=='real_board',training_data=False,release_ready=False)

def trace_status(folder):
    paths=list(Path(folder).rglob('frame_trace.jsonl'))
    if not paths:return None
    latest=max(paths,key=lambda p:p.stat().st_mtime_ns)
    with latest.open('rb') as stream:
        stream.seek(max(0,latest.stat().st_size-16384));lines=stream.read().splitlines()
    for line in reversed(lines):
        try:event=json.loads(line)
        except (ValueError,UnicodeDecodeError):continue
        if event.get('event')=='command' and event.get('kind')==10 and (event.get('ack') or {}).get('result')==0:
            return 'mask word '+str((int(event['args'],16)>>32)+1)+'/64800'
        if event.get('event') in ('capture_requested','capture_ack','image_complete','result_verified','result_published'):
            return event['event']
    return None

class Progress:
    def __init__(self,folder,*,interval=5,emit=say):self.folder=Path(folder);self.interval=interval;self.emit=emit;self.stop=threading.Event()
    def __enter__(self):
        self.started=time.monotonic();self.thread=threading.Thread(target=self.watch,daemon=True);self.thread.start();return self
    def watch(self):
        while not self.stop.wait(self.interval):
            try:
                observations=list(self.folder.rglob('observations.json'))
                count=len(read(observations[-1])) if observations else 0
                detail=trace_status(self.folder)
                self.emit(f'Running: {time.monotonic()-self.started:.0f}s; verified gray slots {count}/8; '+(detail or 'device/configuration/verification/archive in progress')+'. Please keep this window open.')
            except (OSError,ValueError,TypeError):self.emit('Running: verifying files; please keep this window open.')
    def __exit__(self,*args):self.stop.set();self.thread.join(timeout=2)

def prepare(runtime=None,source=SAVED):
    runtime=runtime or original.Runtime();plan=original.prepare(runtime)
    proof=review_frozen(source,sensor_size=runtime.bridge_sensor_size,binding=plan['candidate'].get('binding'))
    require(proof['evidence_source']==runtime.evidence_source,'Saved evidence source differs from runtime')
    return runtime,plan,proof

def run(out,*,source=SAVED,runtime=None,reset_action=None,emit=say,interval=5):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);results={};phase='offline_preflight';error=None;status='FAILED'
    emit('STARTED. Checking local sources and the saved frozen-input result; no new photo in this step.')
    try:
        runtime,plan,proof=prepare(runtime,source);write(out/'reused_frozen_review.json',proof);write(out/'approved_plan.json',plan)
        emit('Saved same-frozen RGB/GRAY/SAT verification PASS. It will not be captured again.')
        phase='startup_OFF';emit('Preparing board: requesting lights OFF, then a fresh strict eight-request session.')
        with runtime.guard():
            executor=runtime.executor(plan,out/'startup_cleanup')
            try:off=executor.lights_off(timeout_s=3)
            finally:executor.close()
        write(out/'startup_OFF.json',off);require(off['acknowledged'],'OFF not acknowledged; stop before CAP')
        phase='strict_eight_workflow';emit('Eight gray requests started. First full-frame mask upload normally takes about45s; progress follows every5s.')
        with Progress(out,interval=interval,emit=emit):
            results['workflow']=workflow.execute(plan,out=out/'workflow',confirmed_same_pose=True,_runtime=runtime,single_timeout_s=300,timeout_s=900)
        require(results['workflow']['status']=='GRAY_INPUTS_READY_FOR_REVIEW','Eight-request workflow failed; original files preserved')
        emit('8/8 gray frames verified; lights OFF acknowledged; acquisition ZIP and model-input export complete.')
        phase='await_KEY2';write(out/'window_progress.json',dict(phase=phase,status='EIGHT_AND_EXPORT_PASSED'))
        require(reset_action is not None and reset_action()=='KEY2_PRESSED','KEY2 step not confirmed')
        phase='reset_readback';emit('Checking reset state BEFORE BIND/configuration; no CAP in this step.')
        results['reset']=original.verify_reset(runtime,out/'reset_readback.json');write(out/'reset_readback.json',results['reset'])
        phase='post_reset';emit('Reset state PASS. Taking only one81x21 recovery frame.')
        child=runtime.reset_runtime();child_plan=original.prepare(child)
        with Progress(out/'post_reset',interval=interval,emit=emit):results['post_reset']=original.same_frozen(out/'post_reset',runtime=child,plan=child_plan)
        require(results['post_reset']['summary']['status']=='SAME_FROZEN_INPUT_VERIFIED','Post-reset recovery failed')
        require(results['post_reset']['summary']['row']['identity']['session']!=proof['identity']['session'],'Post-reset session is not fresh')
        phase='complete';status='ENGINEERING_RESUME_PASSED';emit('PASS: saved frozen proof + strict eight + export + KEY2 recovery. Archiving final result.')
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc));emit('STOPPED: '+str(exc)+'. Results are preserved; do not repeat blindly.')
    summary=dict(schema='guangjian0107-visible-resume-v1',status=status,phase=phase,error=error,results=results,
        evidence_source=getattr(runtime,'evidence_source','not_started'),reused_frozen=str(source),maximum_new_CAP=9,
        frozen_recaptured=False,strict_eight_preserved=True,training_data=False,release_ready=False,production09_switched=False,
        hardware_complete=status=='ENGINEERING_RESUME_PASSED' and getattr(runtime,'evidence_source',None)=='real_board')
    if runtime is not None:return runtime.archive(out,summary)
    write(out/'operator_summary.json',summary)
    return dict(summary=summary,archive=None)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path);p.add_argument('--check-only',action='store_true');p.add_argument('--source',type=Path,default=SAVED);a=p.parse_args()
    say('0107 RESUME ENTRY STARTED. No bit programming or network changes are performed.')
    if a.check_only:
        _,_,proof=prepare(source=a.source);print(json.dumps(dict(status='OFFLINE_READY',source_review=proof,hardware_contacted=False),indent=2));raise SystemExit(0)
    def reset_action():
        say('Now press board KEY2 once, release, wait5seconds. Then type RESET and press Enter. Type STOP to preserve results and stop.')
        return 'KEY2_PRESSED' if input().strip()=='RESET' else 'NOT_CONFIRMED'
    require(a.out is not None,'New output directory required');result=run(a.out,source=a.source,reset_action=reset_action)
    print(json.dumps(dict(status=result['summary']['status'],result=result.get('archive'),directory=str(a.out)),indent=2))
    raise SystemExit(0 if result['summary']['status']=='ENGINEERING_RESUME_PASSED' else 2)
