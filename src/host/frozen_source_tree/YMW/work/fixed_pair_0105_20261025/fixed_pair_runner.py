"""Fixed eight-request backend for an explicitly supplied, strict 0105 SDK port.

No socket or executor is created on import. A live host must verify its 02/03
source and acquire the existing operator lock through guard_factory.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib,inspect,json,math,sys,threading,time

HERE=Path(__file__).resolve().parent
DEPENDENCIES=HERE.parent/'multi_observation_0105_20261024'
PINS={'multiobs/contracts.py':'333c3feef499c34a13de44a6ab78d1a65d097f38113b63d1e2e0be03431e952f',
      'multiobs/validation.py':'f6fe3cfba1c50133d51439a2ec02961141f90d1825e78fb4cdfa675c7a1d17f2',
      'multiobs/ports.py':'19d5c8f9cc9144b5223bc081be9a966626e93cc04f63234adaa1b1deb0edb838'}
for relative,expected in PINS.items():
    if hashlib.sha256((DEPENDENCIES/relative).read_bytes()).hexdigest()!=expected:raise ValueError('changed validation dependency '+relative)
sys.path.insert(0,str(DEPENDENCIES))
from multiobs.contracts import CaptureRequest,Context,validate_progress,identifier
from multiobs.validation import validate_payload
from multiobs.ports import SdkPort
for item,relative in [(CaptureRequest,'multiobs/contracts.py'),(validate_payload,'multiobs/validation.py'),(SdkPort,'multiobs/ports.py')]:
    if Path(inspect.getfile(item)).resolve()!=(DEPENDENCIES/relative).resolve():raise ValueError('unexpected cached validation module '+relative)

@dataclass(frozen=True)
class FixedProfile:
    exposures:tuple
    gain16:int=16
    brightness:int=128
    settle_frames:int=1
    discard_frames:int=3

class RoundFailure(RuntimeError):
    def __init__(self,summary,path):
        super().__init__(summary['status']);self.summary=summary;self.path=path

def digest(data):return hashlib.sha256(data).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def safe_cost(value):
    try:
        if not isinstance(value,dict) or not value:raise ValueError('unknown cost')
        return json.loads(json.dumps(value,allow_nan=False))
    except (ValueError,TypeError):return {'unavailable':True,'invalid_or_missing_cost':True}

def run_fixed_eight(context,*,low,high,pair_status,pair_reference,source_binding,
                    port_factory,guard_factory,out,pose_confirmed=False,
                    timeout_s=240,single_timeout_s=30,cancel=None,clock=time.monotonic):
    started=clock()
    source_hashes={str(Path(__file__).resolve()):digest(Path(__file__).read_bytes()),
                   **{str((DEPENDENCIES/k).resolve()):v for k,v in PINS.items()}}
    if not isinstance(context,Context) or pose_confirmed is not True:raise ValueError('verified source context and explicit same-pose confirmation required')
    if any(type(v) is not int or not 400<=v<=800 for v in (low,high)) or low>=high:raise ValueError('two ordered fixed exposures required')
    if pair_status not in ('development_trial','XDL_frozen') or not isinstance(pair_reference,str) or not pair_reference.strip():raise ValueError('explicit trial/frozen provenance required')
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (timeout_s,single_timeout_s)):raise ValueError('bounded deadlines')
    if not callable(port_factory) or not callable(guard_factory):raise ValueError('explicit SDK port and operator guard factories required')
    required=('source_full_png_sha256','source_session_sha256','source_roi_session_sha256','native_mask_sha256')
    if not isinstance(source_binding,dict) or source_binding.get('verified_from_02_03') is not True or any(not isinstance(source_binding.get(k),str) or len(source_binding[k])!=64 or any(c not in '0123456789abcdef' for c in source_binding[k]) for k in required) or source_binding['native_mask_sha256']!=context.mask_sha256:
        raise ValueError('02/03 source and mask binding required')
    identifier(source_binding.get('physical_specimen_id'))
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    cancel=cancel or threading.Event();profile=FixedProfile((low,high));port=None;previous=None;seen_calls=set()
    summary={'schema':'fixed-eight-0105-rgb-v1','status':'IN_PROGRESS','context':context.describe(),
        'pair_status':pair_status,'pair_reference':pair_reference,'low':low,'high':high,
        'automatic_exposure_search':False,'automatic_observation_retries':0,'formal_budget':8,'observations':[],
        'attempts':[],'lights_off':{'requested':False,'acknowledged':False},'executor_closed':False,
        'physical_freshness_verified':False,'fusion_or_detector_quality_validated':False,'evidence_source':None}
    summary['implementation_sha256']=source_hashes
    summary['physical_specimen_id']=source_binding['physical_specimen_id']
    write(out/'source_binding.json',source_binding);(out/'native_mask.bin').write_bytes(context.mask)
    def remaining():
        elapsed=clock()-started
        if not math.isfinite(elapsed) or elapsed<0 or elapsed>=timeout_s:raise TimeoutError('complete round deadline')
        return timeout_s-elapsed
    try:
        with guard_factory():
            remaining()
            if cancel.is_set():raise InterruptedError('cancelled before SDK initialization')
            port=port_factory()
            try:
                if port.execution_mode not in ('sdk_adapter','software_fake'):raise ValueError('live SDK or explicit software fixture only')
                if port.execution_mode=='sdk_adapter':
                    if not isinstance(port,SdkPort):raise ValueError('verified frozen SDK adapter required')
                    if Path(port.executor.output_root).resolve()!=out/'sdk_calls':raise ValueError('SDK logs must remain inside the round archive under sdk_calls')
                for channel,direction in ((1,'top'),(2,'right'),(3,'bottom'),(4,'left')):
                    for role,exposure in (('low',low),('high',high)):
                        budget=remaining()
                        if cancel.is_set():raise InterruptedError('cancelled between fixed observations')
                        observation_id=f'CH{channel}_{role}';attempt_id=observation_id+'_attempt1'
                        request=CaptureRequest(observation_id,channel,exposure,'base','fixed exposure pair; no selection or supplements')
                        attempt={'observation_id':observation_id,'attempt_id':attempt_id,'status':'STARTED','cost':{'unavailable':True}}
                        summary['attempts'].append(attempt)
                        try:payload=port.capture(request,context,profile,attempt_id,min(single_timeout_s,budget),cancel)
                        except Exception as exc:
                            attempt.update(status='FAILED',cost=safe_cost(getattr(exc,'cost',None)),error=str(exc))
                            raise
                        attempt.update(status='SDK_RETURNED',cost=safe_cost(payload.record.get('cost')))
                        summary['last_observed_identity']=payload.receipt.copy()
                        try:
                            checks=validate_payload(payload,request,context,profile)
                            validate_progress(previous,payload.receipt)
                        except Exception as exc:
                            attempt.update(status='REJECTED',error=str(exc));raise
                        if payload.record['call_id'] in seen_calls:raise ValueError('reused SDK call')
                        if summary['evidence_source'] is None:summary['evidence_source']=payload.record['evidence_source']
                        if payload.record['evidence_source']!=summary['evidence_source']:raise ValueError('evidence source changed')
                        remaining()
                        folder=out/'observations'/observation_id;folder.mkdir(parents=True,exist_ok=False)
                        (folder/'image.rgb565').write_bytes(payload.raw);(folder/'image.png').write_bytes(payload.png)
                        write(folder/'result.json',payload.record);write(folder/'trusted_publication.json',payload.receipt);write(folder/'checks.json',checks)
                        summary['observations'].append({'observation_id':observation_id,'channel':channel,'direction':direction,'role':role,
                            'exposure_lines':exposure,'call_id':payload.record['call_id'],'identity':payload.receipt.copy(),
                            'png_sha256':digest(payload.png),'raw_sha256':digest(payload.raw),'directory':folder.relative_to(out).as_posix(),
                            'label_status':'UNLABELED_PENDING_XDL'})
                        attempt['status']='ACCEPTED';previous=payload.receipt.copy();seen_calls.add(payload.record['call_id'])
                        write(out/'progress.json',summary)
            finally:
                try:
                    summary['lights_off']=port.lights_off()
                    if summary['lights_off'].get('acknowledged') is not True:raise RuntimeError('lights-off ACK unavailable')
                finally:
                    summary['close_attempted']=True
                    port.close();summary['executor_closed']=True
            if len(summary['observations'])!=8:raise ValueError('incomplete fixed exposure pairs')
    except BaseException as exc:
        summary.update(status='CANCELLED' if isinstance(exc,(InterruptedError,KeyboardInterrupt)) or getattr(exc,'code','')=='CANCELLED' else 'FAILED',
            error={'type':type(exc).__name__,'message':str(exc),'needs_reset':getattr(exc,'needs_reset',False)})
    finally:
        if port is not None and not summary.get('close_attempted'):
            try:port.close();summary['executor_closed']=True
            except BaseException as exc:summary.update(status='FAILED',close_error=str(exc))
    if summary['status']=='IN_PROGRESS':summary['status']='CANCELLED' if cancel.is_set() else 'COMPLETE_EIGHT'
    if any(digest(Path(name).read_bytes())!=expected for name,expected in source_hashes.items()):summary.update(status='FAILED',source_changed_during_round=True)
    try:remaining()
    except Exception as exc:summary.update(status='FAILED',deadline_error=str(exc))
    summary.update(host_elapsed_s_before_archive=clock()-started,validated_formal_observations=len(summary['observations']),
        validated_observation_transaction_frames=5*len(summary['observations']),
        incomplete_or_rejected_costs_preserved=True,total_actual_sensor_frames='UNKNOWN_USE_SDK_ATTEMPT_COSTS',
        timing_excludes_previous_02_03_captures=True,workflow_complete_end_to_end_measured=False)
    write(out/'summary.json',summary)
    def seal():
        files={p.relative_to(out).as_posix():digest(p.read_bytes()) for p in out.rglob('*') if p.is_file() and p not in (out/'manifest.json',out/'completion.json')}
        write(out/'manifest.json',{'sha256':files})
    seal()
    try:remaining()
    except Exception as exc:
        summary.update(status='FAILED',deadline_error=str(exc));write(out/'summary.json',summary);seal()
    write(out/'completion.json',{'status':summary['status'],'manifest_sha256':digest((out/'manifest.json').read_bytes()),
        'summary_sha256':digest((out/'summary.json').read_bytes()),'host_elapsed_s_before_completion_write':clock()-started,
        'completion_file_own_write_excluded':True})
    if summary['status']!='COMPLETE_EIGHT':raise RoundFailure(summary,out)
    return summary
