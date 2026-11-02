"""Independent 0107 fixed-eight operator CLI; prepare is offline.

Current RTL release is blocked. This entry cannot turn a local bit-file hash
into hardware qualification, nor silently fall back to the installed 0105 SDK.
"""
import argparse,json,math,sys,time
from pathlib import Path
import numpy as np
import sdk_transport as sdk
import fixed_eight

HERE=Path(__file__).resolve().parent
PAIR=HERE.parent/'fixed_pair_0105_20261025'
if str(PAIR) not in sys.path:sys.path.insert(0,str(PAIR))
legacy=sdk.wire.pinned_module('_gray_operator_preflight',PAIR/'paired_host.py',
    'a120cb113e499f00e89e4216de32be2f62736d76d96fdbfb749badcfa30f4e5f')
sha=legacy.sha;read=legacy.read;require=legacy.require;write=sdk.support.write_json

class Runtime(legacy.Runtime):
    def candidate(self):
        names=['STATUS.json','verification/postroute_03/verification.json',
               'verification/postroute_03/READONLY_AUDIT.json']
        files={'candidate_evidence/'+name:(HERE/name).read_bytes() for name in names}
        status=read(HERE/names[0]);route=read(HERE/names[1]);audit=read(HERE/names[2])
        blocked=[]
        for key in ('release_ready','bit_generated','external_IO_qualified','CDC_DRC_review_complete'):
            if status.get(key) is not True:blocked.append(key+' is not true')
        if status.get('candidate_source_commit')!=sdk.SOURCE_COMMIT:blocked.append('RTL source mismatch')
        if route.get('source_constraints_preserved') is not True or route.get('wns_ns',-1)<0 or route.get('whs_ns',-1)<0:
            blocked.append('Routed timing/source qualification missing')
        if audit.get('route_errors')!=0 or audit.get('unconstrained_internal_max_delay_endpoints')!=0:
            blocked.append('Read-only routed audit failed')
        if audit.get('warnings_fully_qualified') is not True or audit.get('board_release_ready') is not True:
            blocked.append('Detailed IO/CDC/DRC audit is not qualified')
        binding=None;artifact=status.get('bit_artifact',{});extra_hashes={}
        # There is deliberately no operator CLI override for these gates.
        if not blocked:
            path=Path(artifact.get('path',''))
            receipt_path=Path(artifact.get('build_receipt_path',''))
            require(path.is_file() and sha(path)==artifact.get('sha256'),'Actual candidate bit is missing/changed')
            require(receipt_path.is_file() and sha(receipt_path)==artifact.get('build_receipt_sha256'),'Build receipt missing/changed')
            receipt=read(receipt_path)
            require(receipt.get('schema')=='guangjian-bit-from-qualified-checkpoint-v1' and
                receipt.get('source_commit')==sdk.SOURCE_COMMIT and receipt.get('bit_sha256')==sha(path) and
                receipt.get('input_checkpoint_sha256')==audit.get('checkpoint_sha256') and
                receipt.get('write_bitstream_succeeded') is True,'Bit is not bound to the reviewed routed checkpoint')
            files['candidate_evidence/bit_build_receipt.json']=receipt_path.read_bytes()
            extra_hashes={str(path.resolve()):sha(path),str(receipt_path.resolve()):sha(receipt_path)}
            binding=dict(candidate_source_commit=sdk.SOURCE_COMMIT,bit_path=str(path.resolve()),bit_sha256=sha(path))
        return dict(ready=not blocked,blocked_reasons=blocked,binding=binding,
            board_bit_sha_readback_verified=False),files,{**{str(HERE/name):sha(HERE/name) for name in names},**extra_hashes}

    def executor(self,plan,out):
        require(plan['candidate']['ready'] is True,'0107 release qualification incomplete')
        engine=self.core.load_engine();base=plan['source_contract']
        return sdk.TransportExecutor(board=base['board'],bind=base['bind'],port=base['port'],
            ymw_root=engine.root/'ymw',output_root=out/'sdk_calls',mode='strict',
            pixel_format=plan['pixel_format'],candidate_binding=plan['candidate']['binding'],
            evidence_source='real_board',command_timeout=1.5,retries=3)

def build_plan(runtime,*,pixel_format=49,**kwargs):
    require(type(pixel_format) is int and pixel_format in sdk.wire.FORMATS,'Exact RGB565 or GRAY8+SAT1 format required')
    plan,context,files=legacy.build_plan(runtime,**kwargs)
    candidate,proofs,hashes=runtime.candidate();files.update(proofs)
    plan.update(schema='fixed-pair-operator-0107-v1',pixel_format=pixel_format,candidate=candidate,
        source_initialization_firmware='0x0105/schema1 historical 02/03 only',
        capture_firmware='0x0107/schema2 strict, no fallback',
        source_02_03_is_not_a_new_0107_capture=True,
        source_snapshot_sha256={name:sdk.support.sha_bytes(data) for name,data in files.items()})
    plan['runtime_sha256'].update(hashes)
    plan['implementation_sha256'].update(sdk.SOURCE_SNAPSHOT)
    plan['implementation_sha256'].update({str(p):sha(p) for p in [Path(__file__),Path(fixed_eight.__file__)]})
    plan['plan_sha256']=sdk.support.sha_bytes(json.dumps(plan,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
    return plan,context,files

def refresh(runtime,plan):
    return build_plan(runtime,source=plan['source_contract']['source'],low=plan['low'],high=plan['high'],
        physical_specimen_id=plan['physical_specimen_id'],pose_id=plan['pose_id'],
        pair_status=plan['pair_status'],pair_reference=plan['pair_reference'],pixel_format=plan['pixel_format'])

def check_hashes(plan):
    changed=[]
    for path,digest in {**plan['runtime_sha256'],**plan['implementation_sha256']}.items():
        try:equal=sha(path)==digest
        except OSError:equal=False
        if not equal:changed.append(path)
    binding=plan['candidate']['binding']
    if binding:
        try:equal=sha(binding['bit_path'])==binding['bit_sha256']
        except OSError:equal=False
        if not equal:changed.append(binding['bit_path'])
    return changed

def audit_result(result,plan,context,out,channel,role,previous):
    folder=result.record_path.resolve().parent
    require(folder.is_relative_to((out/'sdk_calls').resolve()) and folder.name=='committed','Capture escaped batch output')
    record=read(result.record_path)
    require(record==result.metadata and record['status']=='COMMITTED' and record['strict_verified'] is True,'SDK record changed')
    for name,digest in record['archived_file_sha256'].items():
        require(Path(name).name==name and sha(folder/name)==digest,'Changed SDK artifact: '+name)
    require((folder/record['raw_payload_file']).read_bytes()==result.raw_payload==result.validated['payload'],'Changed actual payload')
    require((folder/'metadata_packet.bin').read_bytes()==result.validated['metadata_packet'],'Changed metadata packet')
    meta=sdk.wire.decode_metadata(result.validated['metadata_packet'],record['metadata_query_seq'])
    require(meta==record['diagnostic']==result.validated['metadata'],'Final metadata object/bytes mismatch')
    expected=dict(exposure_lines=plan[role],gain16=16,brightness=128,light_mask=1<<(channel-1),settle_frames=1,discard_frames=3)
    require(meta['parameters']==expected and meta['roi']==list(context.roi) and meta['pixel_format']==plan['pixel_format'],'Readback differs from approved request')
    require(meta['valid'] and meta['mask_valid'] and meta['parameters_valid'] and not meta['error'],'Invalid committed metadata')
    require(record['mask_sha256']==sdk.support.sha_bytes(context.mask)==result.validated['board_mask_sha256'],'Changed board mask')
    require((folder/'image.gray8').read_bytes()==result.validated['gray'].tobytes(),'Changed gray plane')
    require((folder/'image.sat1').read_bytes()==np.packbits(result.validated['sat'].reshape(-1),bitorder='big').tobytes(),'Changed SAT plane')
    if previous is not None:
        before=previous['validated']['metadata']['identity'];tag=meta['identity']
        require(tag['session']==before['session'] and tag['request_id']==before['request_id']+1 and
                tag['roi_generation']==before['roi_generation'],'Session, ROI or request continuity changed')
        for key,bits in [('frame_id',16),('dvp_sequence',32),('publish_sequence',32)]:
            require(0<(tag[key]-before[key])%(1<<bits)<1<<(bits-1),'Nonforward '+key)
    return dict(channel=channel,role=role,sample_id=context.sample_id,pose_id=context.pose_id,validated=result.validated)

def execute(plan,*,out,confirmed_same_pose=False,cancel=None,timeout_s=360,single_timeout_s=60,_runtime=None):
    require(confirmed_same_pose is True,'Review exact source preview and confirm specimen/pose before capture')
    require(all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) and t>0 for t in (timeout_s,single_timeout_s)),'Finite positive budgets required')
    started_ns=time.monotonic_ns();runtime=_runtime or Runtime(plan['lab_root'])
    fresh,context,files=refresh(runtime,plan)
    require(fresh==plan,'Source, implementation, build or approved plan changed; prepare again')
    require(plan['candidate']['ready'] is True,'0107 hardware gate blocked: '+', '.join(plan['candidate']['blocked_reasons']))
    out=Path(out).resolve()
    require(not any(p.exists() for p in [out,out.with_name(out.name+'.zip'),out.with_name(out.name+'.zip.sha256'),out.with_name(out.name+'.zip.receipt.json')]),'Use a new output/archive path')
    out.mkdir(parents=True,exist_ok=False)
    observations=[];entries=[];failure=None;executor=None;off=dict(requested=False,acknowledged=False,physical_off_verified=False)
    status='FAILED';dataset=None;evidence='not_started';deadline=time.monotonic()+timeout_s
    try:
        with runtime.guard():
            try:
                locked,_,_=refresh(runtime,plan)
                require(locked==plan,'Source/build changed while waiting for shared operator lock')
                for name,data in files.items():
                    path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                (out/'board_mask.bin').write_bytes(context.mask);write(out/'approved_plan.json',plan)
                if cancel is not None and cancel.is_set():raise KeyboardInterrupt('Cancelled before SDK construction')
                executor=runtime.executor(plan,out)
                require(type(executor) is sdk.TransportExecutor,'Only the exact independent strict 0107 SDK is accepted')
                evidence=executor.evidence_source
                for channel in range(1,5):
                    for role in ('low','high'):
                        require(not check_hashes(plan),'Source/build changed during batch')
                        if cancel is not None and cancel.is_set():raise KeyboardInterrupt('Cancelled between requests')
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError('Whole-round acquisition deadline exhausted')
                        result=executor.acquire(light_channel=channel,brightness=128,exposure_lines=plan[role],gain16=16,
                            roi=context.roi,board_mask=context.mask,settle_frames=1,discard_frames=3,
                            timeout_s=min(single_timeout_s,remaining),cancel=cancel,sample_id=context.sample_id,round_id=context.pose_id)
                        row=audit_result(result,plan,context,out,channel,role,observations[-1] if observations else None)
                        observations.append(row)
                        entries.append(dict(observation_id=f'CH{channel}_{role}',physical_specimen_id=plan['physical_specimen_id'],
                            sample_id=context.sample_id,pose_id=context.pose_id,channel=channel,role=role,
                            record=result.record_path.relative_to(out).as_posix(),identity=row['validated']['metadata']['identity'],
                            payload_sha256=row['validated']['payload_sha256'],label_status='UNLABELED_PENDING_XDL',quality='NOT_EVALUATED'))
                        write(out/'observations.json',entries)
                dataset=fixed_eight.validate_eight(observations,sample_id=context.sample_id,pose_id=context.pose_id,
                    low=plan['low'],high=plan['high'],roi=list(context.roi),board=np.frombuffer(context.mask,np.uint8).reshape(context.roi[3],context.roi[2]).astype(bool))
                write(out/'fixed_eight_dataset.json',dataset);status='ACQUIRED_EIGHT_REVIEW_REQUIRED'
            finally:
                if executor is not None:
                    try:off=executor.lights_off(timeout_s=3)
                    except BaseException as exc:off=dict(requested=True,acknowledged=False,physical_off_verified=False,error=str(exc))
                    finally:executor.close()
    except BaseException as exc:
        status='CANCELLED' if isinstance(exc,KeyboardInterrupt) or getattr(exc,'code',None)=='CANCELLED' else 'FAILED'
        failure=dict(type=type(exc).__name__,code=getattr(exc,'code',None),message=str(exc),needs_reset=getattr(exc,'needs_reset',None))
    changed=check_hashes(plan)
    if changed:status='FAILED'
    if status=='ACQUIRED_EIGHT_REVIEW_REQUIRED' and not off.get('acknowledged'):
        status='ACQUIRED_EIGHT_CLEANUP_REQUIRED'
    # Sum only recorded network costs. Unknown physical costs remain unknown.
    outcomes=[dict(path=p.relative_to(out).as_posix(),record=read(p)) for p in sorted((out/'sdk_calls').glob('*/outcome.json'))]
    totals={key:sum(row['record'].get('cost',{}).get(key,0) for row in outcomes) for key in
        ('udp_sent_packets','udp_sent_bytes','udp_received_packets','udp_received_bytes','command_retries','capture_requests')}
    summary=dict(schema='fixed-pair-operator-0107-v1',status=status,error=failure,evidence_source=evidence,
        physical_specimen_id=plan['physical_specimen_id'],sample_id=context.sample_id,pose_id=context.pose_id,
        low=plan['low'],high=plan['high'],pair_status=plan['pair_status'],pair_reference=plan['pair_reference'],
        pixel_format=plan['pixel_format'],gain16=16,brightness=128,saved_observations=len(observations),
        lights_off=off,changed_source_or_build_files=changed,recorded_network_cost_totals=totals,
        outcome_records=[row['path'] for row in outcomes],physical_cost_is_not_inferred_from_missing_records=True,
        acquisition_budget_s=timeout_s,cleanup_has_separate_3s_budget=True,
        acquisition_budget_excludes_initial_preflight_and_final_zip=True,operator_started_monotonic_ns=started_ns,
        historical_initialization_frames_are_not_new_observations=True,
        operator_same_specimen_and_pose_confirmed=True,physical_freshness_verified=False,
        board_bit_sha_readback_verified=False,quality_or_confidence='NOT_EVALUATED',hardware_0107_workflow_validated=False)
    return runtime.archive(out,summary)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'));a.add_argument('--source',type=Path)
    a.add_argument('--low',type=int,required=True);a.add_argument('--high',type=int,required=True)
    a.add_argument('--physical-specimen-id',required=True);a.add_argument('--pose-id',required=True)
    a.add_argument('--pair-status',choices=['development_trial','XDL_frozen'],required=True);a.add_argument('--pair-reference',required=True)
    a.add_argument('--pixel-format',type=lambda s:int(s,0),choices=[1,49],default=49);a.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('capture');a.add_argument('--plan',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--confirm-same-pose',action='store_true')
    args=p.parse_args()
    if args.action=='prepare':
        plan,_,files=build_plan(Runtime(args.lab_root),source=args.source,low=args.low,high=args.high,
            physical_specimen_id=args.physical_specimen_id,pose_id=args.pose_id,pair_status=args.pair_status,pair_reference=args.pair_reference,pixel_format=args.pixel_format)
        args.out.mkdir(parents=True,exist_ok=False);write(args.out/'plan.json',plan);(args.out/'source_preview.png').write_bytes(files['source_preview.png'])
        print(json.dumps(dict(status='OFFLINE_PLAN_REVIEW_REQUIRED',board_contacted=False,candidate=plan['candidate'],plan=str((args.out/'plan.json').resolve())),indent=2));return
    result=execute(read(args.plan),out=args.out,confirmed_same_pose=args.confirm_same_pose)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['summary']['status']!='ACQUIRED_EIGHT_REVIEW_REQUIRED':raise SystemExit(2)

if __name__=='__main__':main()
