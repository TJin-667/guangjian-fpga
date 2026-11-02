"""One isolated engineering acceptance window; never substitutes production09."""
import argparse,hashlib,json,math,secrets,socket,time
from pathlib import Path
import numpy as np
import sdk_transport as sdk
import operator_host as host
import gray_acquisition_workflow as workflow

HERE=Path(__file__).resolve().parent

def require(ok,message):
    if not ok:raise ValueError(message)
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class Runtime:
    """Explicit engineering authorization, independently gated from production.

    Native all-one mask tests transport, not a specimen segmentation or label.
    No historical02/03 image is borrowed as a current pose.
    """
    lab=Path('C:/BX72_0105_LAB')
    roi=(0,0,1920,1080)
    bridge_sensor_size=(1920,1080)
    evidence_source='real_board'
    def __init__(self):
        self.core=host.legacy.Runtime(self.lab).core
    def prepare(self,source):
        require(source in (None,'engineering_native_not_training'),'Unexpected engineering source')
        context=host.legacy.backend.Context('ENGINEERING_NOT_TRAINING','unused',self.roi,bytes([1])*math.prod(self.roi[2:]))
        contract=dict(source='engineering_native_not_training',sample_id=context.sample_id,roi=list(self.roi),
            board='192.168.0.2',bind='192.168.0.3',port=5000,
            mask_scope='all-one native transport diagnostic; not physical segmentation',training_data=False)
        return contract,context,{'ENGINEERING_SOURCE.json':sdk.support.json_bytes(contract) if hasattr(sdk.support,'json_bytes') else (json.dumps(contract,indent=2)+'\n').encode()}, {str(Path(__file__)):sha(__file__)}
    def candidate(self):
        # Keep the gate in one implementation while exposing the host's exact
        # (candidate, immutable evidence files, source hashes) contract.
        binding_path=HERE/'FINAL_BUILD_BINDING.json';b=read(binding_path)
        require(b['schema']=='guangjian-0107-engineering-binding-v1' and b['firmware']==263,'Binding schema/firmware')
        require(b['candidate_source_commit']==sdk.SOURCE_COMMIT and len(sdk.SOURCE_COMMIT)==40,'Uncommitted candidate')
        for name,digest in b['required_files_sha256'].items():require(sha(HERE/name)==digest,'Changed acceptance input: '+name)
        require(b['implementation_timing_passed'] is True and b['BRAM_36K_equivalent']<=108,'Implementation gate')
        require(b['rtl_verified'] is True and b['software_verified'] is True,'Acceptance tools not verified')
        require(b['release_ready'] is False and b['external_IO_qualified'] is False,'Engineering scope changed')
        bit=(HERE/b['bit_file']).resolve();require(sha(bit)==b['bit_sha256'],'Changed bit')
        candidate=dict(ready=True,blocked_reasons=[],engineering_acceptance_only=True,release_ready=False,
            binding=dict(candidate_source_commit=sdk.SOURCE_COMMIT,bit_path=str(bit),bit_sha256=sha(bit)))
        return (candidate,{'candidate_evidence/FINAL_BUILD_BINDING.json':binding_path.read_bytes()},
            {str(binding_path):sha(binding_path),str(bit):sha(bit)})
    def guard(self):return self.core.operator_lock(self.lab)
    def executor(self,plan,out):
        base=plan['source_contract'];engine=self.core.load_engine()
        return sdk.TransportExecutor(board=base['board'],bind=base['bind'],port=base['port'],ymw_root=engine.root/'ymw',
            output_root=out/'sdk_calls',pixel_format=plan['pixel_format'],candidate_binding=plan['candidate']['binding'],
            evidence_source=self.evidence_source,mode='strict',command_timeout=1.5,retries=3)
    def archive(self,out,summary):
        summary.update(training_data=False,engineering_acceptance_only=True,release_ready=False,
            external_IO_qualified=False,diagnostic_mask_is_not_a_physical_label=True)
        return self.core.finalize_output(out,summary)
    def reset_runtime(self):
        child=Runtime();child.roi=(896,496,81,21)
        return child

def prepare(runtime=None):
    runtime=runtime or Runtime()
    plan=host.build_plan(runtime,source='engineering_native_not_training',low=400,high=800,
        physical_specimen_id='ENGINEERING_NOT_TRAINING',pose_id='engineering_fixed_window',pair_status='development_trial',
        pair_reference='engineering request sequencing only; 400/800 are not optimized exposure choices',pixel_format=49)[0]
    return plan

def same_frozen(out,*,runtime,plan):
    """Exactly one CAP, both views from a single frozen DDR stream."""
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    diagnostic=json.loads(json.dumps(plan));diagnostic['pixel_format']=50
    executor=None;row=None;failure=None;off={'acknowledged':False};started=time.monotonic()
    try:
        with runtime.guard():
            try:
                require(not host.check_hashes(plan),'Changed source before diagnostic')
                executor=runtime.executor(diagnostic,out)
                _,context,_,_=runtime.prepare('engineering_native_not_training')
                result=executor.acquire(light_channel=1,brightness=128,exposure_lines=600,gain16=16,
                    roi=context.roi,board_mask=context.mask,settle_frames=1,discard_frames=3,timeout_s=300,
                    sample_id=context.sample_id,round_id='same_frozen_input')
                record=read(result.record_path);m=record['diagnostic'];w,h=m['roi'][2:]
                raw=result.raw_payload
                rgb,gray,sat=sdk.wire.dual_view.decode(raw,w,h,codec=sdk.wire.codec)
                require(record==result.metadata and m['pixel_format']==50 and m['valid'] and not m['error'],'Uncommitted diagnostic')
                require(sdk.wire.legacy.crc64_ecma(rgb)==m['rgb_crc64'] and sdk.wire.legacy.crc64_ecma(raw)==m['payload_crc64'],'CRC mismatch')
                for name,digest in record['archived_file_sha256'].items():require(sha(result.record_path.parent/name)==digest,'Archived diagnostic changed')
                require((result.record_path.parent/'same_frame.rgb565').read_bytes()==rgb,'Saved original RGB changed')
                mask=np.frombuffer(context.mask,np.uint8).reshape(h,w).astype(bool)
                require(sdk.wire.recompute(gray,sat,mask)==(m['statistics'],m['features']),'H1/H2 mismatch')
                require(m['roi']==list(context.roi) and m['fifo_reads']==math.prod(runtime.bridge_sensor_size),'ROI/drain mismatch')
                require(record['cost']['capture_requests']==1,'More than one logical CAP')
                row=dict(identity=m['identity'],bank=m['bank'],roi=m['roi'],pixels=w*h,
                    rgb_sha256=hashlib.sha256(rgb).hexdigest(),payload_sha256=hashlib.sha256(raw).hexdigest(),
                    original_rgb_crc64=m['rgb_crc64'],payload_crc64=m['payload_crc64'],
                    gray_mismatches=0,sat_mismatches=0,h1_h2_equal=True,logical_CAP_requests=1,
                    record=result.record_path.relative_to(out).as_posix())
            finally:
                if executor is not None:
                    try:off=executor.lights_off(timeout_s=3)
                    finally:executor.close()
    except BaseException as exc:failure=dict(type=type(exc).__name__,message=str(exc),needs_reset=getattr(exc,'needs_reset',None))
    summary=dict(schema='guangjian-0107-same-frozen-v1',status='SAME_FROZEN_INPUT_VERIFIED' if row and failure is None and off['acknowledged'] else 'FAILED',
        evidence_source=runtime.evidence_source,row=row,error=failure,lights_off=off,elapsed_s=time.monotonic()-started,
        same_camera_capture=True,training_data=False,release_ready=False,external_IO_qualified=False)
    return runtime.archive(out,summary)

def verify_reset(runtime,receipt_path=None):
    """Read reset context BEFORE any BIND/configuration can invalidate evidence."""
    contract,_,_,_=runtime.prepare('engineering_native_not_training')
    protocol_path=runtime.core.load_engine().root/'ymw/host/protocol.py'
    protocol=sdk.wire.pinned_module('_acceptance_reset_wire',protocol_path,sha(protocol_path))
    rows=[];base=secrets.randbelow(65532);endpoint=(contract['board'],contract['port'])
    with runtime.guard(),socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind((contract['bind'],0))
        for index,kind in enumerate((3,14,9)):
            seq=base+index;packet=protocol.command(kind,seq) if kind==3 else sdk.wire.legacy.command(kind,seq,0)
            row=dict(kind=kind,seq=seq,request_hex=packet.hex(),responses=[]);rows.append(row)
            if receipt_path:sdk.support.write_json(receipt_path,dict(status='INCOMPLETE',queries=rows))
            sock.sendto(packet,endpoint);deadline=time.monotonic()+3;ack=None;item=None
            while time.monotonic()<deadline:
                sock.settimeout(max(.001,deadline-time.monotonic()))
                try:data,peer=sock.recvfrom(65535)
                except socket.timeout:break
                if peer!=endpoint or len(data)<10 or int.from_bytes(data[6:8],'big')!=seq:continue
                row['responses'].append(data.hex())
                if receipt_path:sdk.support.write_json(receipt_path,dict(status='INCOMPLETE',queries=rows))
                if kind==9 and data[5]==0x85:item=sdk.wire.decode_metadata(data,seq);break
                if kind==14 and data[5]==0x86:item=sdk.wire.decode_capabilities(data,seq);break
                decoded=protocol.control(data)
                if decoded['type']==protocol.ACK:
                    require(decoded['original']==3 and decoded['result']==0,'Reset status ACK rejected');ack=decoded
                elif decoded['type']==protocol.STATUS:item=decoded
                if kind==3 and ack is not None and item is not None:break
            require(item is not None and (kind!=3 or ack is not None),'Missing reset query response')
            row['decoded']=item
            if receipt_path:sdk.support.write_json(receipt_path,dict(status='READBACK_PENDING_VALIDATION',queries=rows))
    status,caps,meta=[row['decoded'] for row in rows]
    require(status['firmware']==263 and status['state']&16 and not status['state']&3 and status['error']==0,'Reset did not restore ready0107')
    require(status['frames']==0 and caps['format']==1,'Reset did not clear frame count/format')
    require(meta['request_counter']==0 and not meta['valid'] and not meta['mask_valid'] and
        meta['identity']['session']==0 and meta['identity']['request_id']==0,'Reset did not clear session/mask/metadata')
    return dict(status='RESET_CONTEXT_VERIFIED',queries=rows,captures_requested=0,configuration_commands=0)

def run(out,*,runtime=None,reset_action=None):
    runtime=runtime or Runtime();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    status='FAILED';phase='preflight';error=None;results={}
    try:
        plan=prepare(runtime);sdk.support.write_json(out/'approved_plan.json',plan)
        phase='same_frozen';results['same_frozen']=same_frozen(out/'same_frozen',runtime=runtime,plan=plan)
        require(results['same_frozen']['summary']['status']=='SAME_FROZEN_INPUT_VERIFIED','Same-frozen diagnostic failed; stop')
        phase='eight_request_workflow'
        results['workflow']=workflow.execute(plan,out=out/'workflow',confirmed_same_pose=True,_runtime=runtime,single_timeout_s=300,timeout_s=900)
        require(results['workflow']['status']=='GRAY_INPUTS_READY_FOR_REVIEW','Eight-request workflow failed; stop')
        group=read(out/'workflow/model_inputs/group.json')
        require(group['training_data'] is False,'Engineering data must remain outside training')
        phase='complete';status='ENGINEERING_WINDOW_PASSED_RESET_PENDING'
        if reset_action is not None:
            phase='await_operator_button_reset';sdk.support.write_json(out/'window_progress.json',dict(status=status,phase=phase))
            require(reset_action()=='KEY2_PRESSED','Button-reset step was not explicitly completed')
            phase='reset_readback';results['reset']=verify_reset(runtime,out/'reset_readback.json')
            sdk.support.write_json(out/'reset_readback.json',results['reset'])
            phase='post_reset_recovery';child=runtime.reset_runtime();child_plan=prepare(child)
            results['post_reset']=same_frozen(out/'post_reset',runtime=child,plan=child_plan)
            require(results['post_reset']['summary']['status']=='SAME_FROZEN_INPUT_VERIFIED','Post-reset recovery failed')
            before=results['same_frozen']['summary']['row']['identity']['session'];after=results['post_reset']['summary']['row']['identity']['session']
            require(before!=after,'Post-reset session is not fresh')
            phase='complete';status='ENGINEERING_WINDOW_PASSED'
    except BaseException as exc:
        status='FAILED';error=dict(type=type(exc).__name__,message=str(exc))
    summary=dict(schema='guangjian-0107-window-v1',status=status,phase=phase,error=error,results=results,
        evidence_source=runtime.evidence_source,maximum_capture_requests=10 if reset_action else 9,training_data=False,
        release_ready=False,production_09_switched=False,button_reset_context_and_recovery_verified=status=='ENGINEERING_WINDOW_PASSED',
        hardware_button_reset_verified=status=='ENGINEERING_WINDOW_PASSED' and runtime.evidence_source=='real_board')
    return runtime.archive(out,summary)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--out',type=Path);a=p.parse_args()
    if a.check_only:
        plan=prepare();print(json.dumps(dict(status='OFFLINE_ACCEPTANCE_READY',hardware_contacted=False,
            roi=plan['source_contract']['roi'],maximum_CAP=10,production_09_switched=False),indent=2))
    else:
        def button_reset():
            print('Nine engineering captures and export complete. Press board KEY2 once, release, wait 5 seconds.',flush=True)
            # Tee-Object forwards complete lines; print the instruction before
            # waiting so the operator never waits on an invisible input prompt.
            print('Then type RESET and press Enter (or type STOP to preserve partial results).',flush=True)
            response=input().strip()
            return 'KEY2_PRESSED' if response=='RESET' else 'NOT_CONFIRMED'
        require(a.out is not None,'New output required');r=run(a.out,reset_action=button_reset);print(json.dumps(r,indent=2))
        raise SystemExit(0 if r['summary']['status']=='ENGINEERING_WINDOW_PASSED' else 2)
