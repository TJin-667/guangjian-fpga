"""Guarded fixed-eight capture followed by verified gray input export.

All existing production hardware gates remain in operator_host. No capture
retry, format override, release override, or installed-software replacement.
"""
import argparse,json
from pathlib import Path
import operator_host as host
import gray_capture_bridge as bridge

def inspect(plan,*,_runtime=None):
    runtime=_runtime or host.Runtime(plan['lab_root'])
    fresh,_,_=host.refresh(runtime,plan)
    host.require(fresh==plan,'Plan or source changed; prepare a new plan')
    return dict(status='READY_FOR_EXPLICIT_POSE_CONFIRMATION' if fresh['candidate']['ready'] else 'HARDWARE_GATE_BLOCKED',
        candidate=fresh['candidate'],hardware_contacted=False)

def execute(plan,*,out,confirmed_same_pose=False,_runtime=None,_exporter=None,**capture_budgets):
    host.require(confirmed_same_pose is True,'Explicit same specimen/pose confirmation required')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    exporter=_exporter or bridge.export_batch
    status='FAILED';phase='preflight';result=None;error=None;group=None
    try:
        preflight=inspect(plan,_runtime=_runtime)
        host.require(preflight['status']=='READY_FOR_EXPLICIT_POSE_CONFIRMATION','Hardware gate blocked: '+', '.join(preflight['candidate']['blocked_reasons']))
        phase='capture'
        result=host.execute(plan,out=out/'acquisition',confirmed_same_pose=True,_runtime=_runtime,**capture_budgets)
        if result['summary']['status']!='ACQUIRED_EIGHT_REVIEW_REQUIRED':
            status='CAPTURE_INCOMPLETE_NO_EXPORT'
        else:
            phase='export'
            # The SDK already completed cleanup and its archive before export.
            # Export cannot initiate another CAP or change that immutable batch.
            size=(1920,1080) if _runtime is None else getattr(_runtime,'bridge_sensor_size',(1920,1080))
            group=exporter(out/'acquisition',out/'model_inputs',sensor_size=size)
            status='GRAY_INPUTS_READY_FOR_REVIEW';phase='complete'
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        status='EXPORT_FAILED_CAPTURE_PRESERVED' if phase=='export' else 'BLOCKED_OR_FAILED'
    receipt=dict(schema='guangjian-gray-acquisition-export-workflow-v1',status=status,phase=phase,error=error,
        acquisition_result=result,model_inputs='model_inputs/group.json' if group is not None else None,
        labels='UNLABELED',training_quality_evaluated=False,release_ready=False,
        automatic_recapture=False,production_gate_modified=False)
    (out/'workflow.json').write_bytes(bridge.encoded(receipt));return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('inspect');a.add_argument('--plan',type=Path,required=True)
    a=sub.add_parser('run');a.add_argument('--plan',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    a.add_argument('--confirm-same-pose',action='store_true')
    args=p.parse_args();plan=json.loads(args.plan.read_bytes())
    if args.action=='inspect':result=inspect(plan)
    else:result=execute(plan,out=args.out,confirmed_same_pose=args.confirm_same_pose)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status'] in ('GRAY_INPUTS_READY_FOR_REVIEW','READY_FOR_EXPLICIT_POSE_CONFIRMATION') else 2)
