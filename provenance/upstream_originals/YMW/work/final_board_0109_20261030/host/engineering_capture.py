"""Prepare offline, then run one reviewed native-ROI engineering group.

No real-board mode is possible without a checkpoint/bit/source qualification.
This command never configures a network adapter, disconnects Cisco or loads bit.
"""
import argparse,hashlib,ipaddress,json,sys,time,uuid,math,contextlib
from pathlib import Path
import numpy as np
from sdk_loader import load,HERE
from qualification import validate,sha,require
def write(path,obj):
    with Path(path).open('w',encoding='utf-8',newline='\n') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')
def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
def plan_digest(plan):return hashlib.sha256(canonical({k:v for k,v in plan.items() if k!='plan_sha256'})).hexdigest()
def prepare(args):
    require(type(args.low_lines) is int and type(args.high_lines) is int and 1<=args.low_lines<args.high_lines<=1116,'Legal ordered manual exposure pair required')
    qualification,proofs=validate(args.qualification)
    x,y,w,h=args.roi;require(min(x,y)>=0 and min(w,h)>=9 and x+w<=1920 and y+h<=1080,'Native1920x1080 ROI bounds')
    raw=args.mask.read_bytes();require(len(raw)==w*h and any(raw) and all(v in (0,1) for v in raw),'Mask must contain native-ROI0/1 bytes')
    reservation=math.ceil(w*h/32)+8*(600+math.ceil((math.ceil(w/32)*math.ceil(h/32))/32))+math.ceil(4*w*h/1024)+64
    require(reservation<65536,'Dense mask plus this full group/result exceeds strict16-bit command space; choose a reviewed native ROI')
    require(1<=args.port<=65535 and args.lab_root.is_dir(),'UDP port and existing lab root required')
    for value in (args.board,args.bind):
        address=ipaddress.IPv4Address(value);require(not address.is_loopback and not address.is_multicast and not address.is_unspecified,'Actual board/local adapter addresses required')
    require(args.sample.strip() and len(args.sample)<=80,'Sample name required, at most80 characters')
    args.out.mkdir(parents=True,exist_ok=False);group=time.time_ns()
    plan=dict(schema='0109-engineering-capture-plan-v1',qualification=str(args.qualification.resolve()),qualification_sha256=sha(args.qualification),
        candidate_source_commit=qualification['candidate_source_commit'],roi=args.roi,mask=str(args.mask.resolve()),mask_sha256=sha(args.mask),
        sample=args.sample,pose=args.pose,group=group,board=str(ipaddress.IPv4Address(args.board)),bind=str(ipaddress.IPv4Address(args.bind)),port=args.port,lab_root=str(args.lab_root.resolve()),control_sequence_reservation=reservation,
        low_lines=args.low_lines,high_lines=args.high_lines,gain16=16,LED=128,settle_frames=1,discard_frames=3,whole_round_timeout_s=480,single_capture_timeout_s=60,
        pixel_format=args.pixel_format,
        result_directory=str((args.out/'run').resolve()),same_pose_confirmation_required=True,engineering_only=True,
        downloaded_bit_sha_readback_verified=False,bit_path=qualification['bit_path'],bit_sha256=qualification['bit_sha256'])
    plan['digest128']=hashlib.sha256(canonical(plan)).hexdigest()[:32];plan['plan_sha256']=plan_digest(plan)
    write(args.out/'PLAN.json',plan)
    print(json.dumps(dict(status='OFFLINE_PLAN_READY_NO_BOARD_COMMANDS',plan=str((args.out/'PLAN.json').resolve()),sample=plan['sample'],roi=args.roi,low_high=[args.low_lines,args.high_lines]),ensure_ascii=False))
def capture(args):
    plan=json.loads(args.plan.read_text('utf-8'));require(plan['schema']=='0109-engineering-capture-plan-v1' and plan['plan_sha256']==plan_digest(plan),'Reviewed plan changed')
    require(args.confirm_same_pose is True,'Review current specimen/pose and use --confirm-same-pose')
    require(sha(plan['qualification'])==plan['qualification_sha256'] and sha(plan['mask'])==plan['mask_sha256'],'Qualification/mask changed since prepare')
    qualification,_=validate(plan['qualification']);require(qualification['candidate_source_commit']==plan['candidate_source_commit'],'Candidate commit changed')
    module=load('_off109_qualified_engineering',HERE/'engineering_executor.py',QUALIFICATION_PATH=plan['qualification'])
    sdk=module.sdk;root=Path(plan['result_directory']);root.mkdir(parents=True,exist_ok=False)
    # Original executable protocol and board configuration remain SHA pinned by
    # the inherited lifecycle. These are read-only local dependencies.
    module_peer=sdk.wire.pinned_module('_off109_core_probe',HERE.parents[1]/'auto_exposure_0105_20261015/app_core.py','448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
    engine=module_peer.load_engine();roi=plan['roi'];board=np.frombuffer(Path(plan['mask']).read_bytes(),np.uint8).reshape(roi[3],roi[2]).astype(bool)
    binding=dict(candidate_source_commit=qualification['candidate_source_commit'],bit_path=qualification['bit_path'],bit_sha256=qualification['bit_sha256'])
    executor=None;failure=None;cleanup=None;started=time.monotonic();records=[];ownership=contextlib.ExitStack()
    try:
        ownership.enter_context(module_peer.operator_lock(Path(plan['lab_root'])))
        executor=module.EngineeringExecutor(group_id=plan['group'],group_digest=bytes.fromhex(plan['digest128']),group_roi=roi,group_board=board,group_low=plan['low_lines'],group_high=plan['high_lines'],result_directory=root/'fusion',
            board=plan['board'],port=plan['port'],bind=plan['bind'],ymw_root=engine.root/'ymw',output_root=root/'captures',pixel_format=plan['pixel_format'],mode='strict',evidence_source='real_board',candidate_binding=binding)
        for slot in range(1,9):
            remaining=plan['whole_round_timeout_s']-(time.monotonic()-started);require(remaining>0,'Whole round deadline exhausted')
            result=executor.acquire(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=plan['low_lines'] if slot%2 else plan['high_lines'],gain16=16,roi=roi,board_mask=board.astype(np.uint8).tobytes(),
                settle_frames=1,discard_frames=3,timeout_s=min(remaining,plan['single_capture_timeout_s']),sample_id=plan['sample'],round_id=plan['pose'])
            records.append(str(result.record_path));print('FRAME_COMMITTED',slot,flush=True)
    except BaseException as exc:failure=dict(type=type(exc).__name__,message=str(exc),code=getattr(exc,'code',None))
    finally:
        if executor is not None:
            try:cleanup=executor.lights_off(timeout_s=3)
            except BaseException as exc:cleanup=dict(acknowledged=False,error=str(exc))
            finally:executor.close()
        ownership.close()
    status='ENGINEERING_SAME_INPUT_PASSED' if failure is None and (root/'fusion/RESULT.json').is_file() else 'FAILED'
    summary=dict(status=status,error=failure,cleanup=cleanup,records=records,plan_sha256=plan['plan_sha256'],wall_seconds=time.monotonic()-started,
        engineering_only=True,release_ready=False,downloaded_bit_sha_readback_verified=False)
    write(root/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False))
    if failure:raise SystemExit(1)
def main():
    p=argparse.ArgumentParser();commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('prepare');a.add_argument('--qualification',type=Path,required=True);a.add_argument('--roi',type=int,nargs=4,required=True);a.add_argument('--mask',type=Path,required=True)
    a.add_argument('--sample',required=True);a.add_argument('--pose',default='A_v1');a.add_argument('--board',required=True);a.add_argument('--bind',required=True);a.add_argument('--port',type=int,default=5000);a.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'));a.add_argument('--out',type=Path,required=True)
    a.add_argument('--low-lines',type=int,default=400);a.add_argument('--high-lines',type=int,default=800)
    a.add_argument('--pixel-format',type=int,choices=(49,50),default=50,help='50: same frozen RGB565+gray+SAT engineering audit (default);49: gray+SAT')
    a=commands.add_parser('capture');a.add_argument('--plan',type=Path,required=True);a.add_argument('--confirm-same-pose',action='store_true')
    args=p.parse_args();prepare(args) if args.command=='prepare' else capture(args)
if __name__=='__main__':main()
