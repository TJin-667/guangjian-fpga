"""Reuse the qualified engineering executor; UI-triggered IO only, cooperative cleanup."""
from export_paths import legacy_location, data_path, lab_root, network
import contextlib,hashlib,importlib.util,json,sys,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from archive0108 import HOST,QUALIFICATION,read,sha,need

def module(name,path,**injected):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);m.__dict__.update(injected);sys.modules[name]=m;spec.loader.exec_module(m);return m

def prepare(catalogue,destination,*,pixel_format=50):
    """Prepare from a known nativeROI/mask. No network or hardware commands."""
    need(catalogue.get('input_ready') and len(catalogue['frames'])==8,'Complete nativeROI template required')
    first=catalogue['frames'][0];roi=list(first['roi_xywh']);source=Path(first['mask'])
    summary=catalogue['summary'];sample=summary['physical_specimen_id'];pose=summary.get('pose_id','existing_pose')
    return prepare_native(roi,source,sample,pose,destination,pixel_format=pixel_format)

def prepare_native(roi,source,sample,pose,destination,*,pixel_format=50):
    """Prepare an explicit native ROI; no fabricated frame catalogue or hardware IO."""
    need(type(pixel_format) is int and pixel_format in (49,50),'0108 format must be49 or50')
    sys.path.insert(0,str(HOST));entry=module('_final0108_prepare',HOST/'engineering_capture.py')
    destination=Path(destination).resolve();need(destination.is_relative_to(legacy_location('E:/GuangjianData').resolve()),'Plan must remain in project data onE')
    need(not destination.exists(),'New plan directory required')
    destination.parent.mkdir(parents=True,exist_ok=True)
    args=SimpleNamespace(qualification=QUALIFICATION,roi=roi,mask=source,sample=sample,pose=pose,board='192.168.0.2',bind='192.168.0.3',port=5000,lab_root=legacy_location('C:/BX72_0105_LAB'),out=destination,pixel_format=pixel_format)
    entry.prepare(args)
    return destination/'PLAN.json'

def plan_for_format(plan_path,pixel_format):
    """Create a new plan when transport changes; never edit a reviewed plan."""
    plan_path=Path(plan_path).resolve();plan=read(plan_path)
    sys.path.insert(0,str(HOST));entry=module('_final0108_format',HOST/'engineering_capture.py')
    need(entry.plan_digest(plan)==plan['plan_sha256'],'Old plan changed before format selection')
    need(sha(plan['qualification'])==plan['qualification_sha256'] and sha(plan['mask'])==plan['mask_sha256'],'Plan inputs changed')
    need(type(pixel_format) is int and pixel_format in (49,50),'0108 format must be49 or50')
    if plan['pixel_format']==pixel_format:return plan_path
    target=plan_path.parent/('format'+str(pixel_format)+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+__import__('uuid').uuid4().hex[:8])
    return prepare_native(plan['roi'],Path(plan['mask']),plan['sample'],plan['pose'],target,pixel_format=pixel_format)

def capture(plan_path,cancel,notify=lambda text:None):
    """Only called after a human clicks start and confirms the current physical pose."""
    plan=read(plan_path);sys.path.insert(0,str(HOST));entry=module('_final0108_capture',HOST/'engineering_capture.py')
    need(plan['schema']=='0108-engineering-capture-plan-v1' and entry.plan_digest(plan)==plan['plan_sha256'],'Reviewed plan changed')
    need(sha(plan['qualification'])==plan['qualification_sha256'] and sha(plan['mask'])==plan['mask_sha256'],'Plan inputs changed')
    from qualification import validate
    qualification,_=validate(plan['qualification'])
    need(qualification['candidate_source_commit']==plan['candidate_source_commit'],'Candidate source changed')
    if cancel.is_set():raise InterruptedError('Engineering capture cancelled before board access')
    implementation=module('_final0108_executor',HOST/'engineering_executor.py',QUALIFICATION_PATH=plan['qualification']);sdk=implementation.sdk
    from roi_prepare0108 import executor_class
    from performance import Ledger,profiled_executor
    timing=Ledger();Executor=profiled_executor(implementation,executor_class(implementation),timing)
    root=Path(plan['result_directory']).resolve();need(root.is_relative_to(legacy_location('E:/GuangjianData').resolve()) and not root.exists(),'Use a new engineering output directory onE')
    root.mkdir(parents=True,exist_ok=False);roi=plan['roi'];board=np.frombuffer(Path(plan['mask']).read_bytes(),np.uint8).reshape(roi[3],roi[2]).astype(bool)
    peer=sdk.wire.pinned_module('_final0108_operator_lock',HOST.parents[1]/'auto_exposure_0105_20261015/app_core.py','448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857');engine=peer.load_engine()
    binding=dict(candidate_source_commit=qualification['candidate_source_commit'],bit_path=qualification['bit_path'],bit_sha256=qualification['bit_sha256'])
    executor=None;failure=None;cleanup=None;records=[];preparation_record=None;started=time.monotonic();phase='constructor'
    with contextlib.ExitStack() as owner:
        owner.enter_context(peer.operator_lock(Path(plan['lab_root'])))
        try:
            executor=Executor(group_id=plan['group'],group_digest=bytes.fromhex(plan['digest128']),group_roi=roi,group_board=board,result_directory=root/'fusion',board=plan['board'],port=plan['port'],bind=plan['bind'],ymw_root=engine.root/'ymw',output_root=root/'captures',pixel_format=plan['pixel_format'],mode='strict',evidence_source='real_board',candidate_binding=binding)
            phase='roi_preparation';notify('先拍1张ROI准备帧，使现有0108的执行域与新mask一致；此图不计入正式8帧。')
            frame=executor.acquire_roi_preparation(light_channel=1,brightness=128,exposure_lines=400,gain16=16,roi=roi,board_mask=board.astype(np.uint8).tobytes(),settle_frames=1,discard_frames=3,timeout_s=plan['single_capture_timeout_s'],sample_id=plan['sample'],round_id=plan['pose']+'_ROI_PREPARATION_NOT_FORMAL',cancel=cancel)
            preparation_record=str(frame.record_path);phase='formal_eight';notify('ROI准备完成；开始独立的正式8帧。')
            for slot in range(1,9):
                remaining=plan['whole_round_timeout_s']-(time.monotonic()-started);need(remaining>0,'Whole group deadline exhausted')
                frame=executor.acquire(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=400 if slot%2 else 800,gain16=16,roi=roi,board_mask=board.astype(np.uint8).tobytes(),settle_frames=1,discard_frames=3,timeout_s=min(remaining,plan['single_capture_timeout_s']),sample_id=plan['sample'],round_id=plan['pose'],cancel=cancel)
                records.append(str(frame.record_path));notify('0108已提交 '+str(slot)+'/8')
        except BaseException as exc:failure=dict(type=type(exc).__name__,message=str(exc),code=getattr(exc,'code',None))
        finally:
            if executor is not None:
                try:cleanup=executor.lights_off(timeout_s=3)
                except BaseException as exc:cleanup=dict(acknowledged=False,error=str(exc))
                finally:executor.close()
    status='ENGINEERING_SAME_INPUT_PASSED' if failure is None and len(records)==8 and (root/'fusion/RESULT.json').is_file() and cleanup and cleanup.get('acknowledged') else 'FAILED'
    summary=dict(status=status,error=failure,failed_phase=None if status=='ENGINEERING_SAME_INPUT_PASSED' else phase,cleanup=cleanup,records=records,roi_preparation_record=preparation_record,roi_preparation_in_formal_eight=False,formal_expected_frames=8,total_CAP_limit=9,controller_sha256=sha(__file__),roi_preparation_source_sha256=sha(Path(__file__).with_name('roi_prepare0108.py')),plan_sha256=plan['plan_sha256'],engineering_only=True,release_ready=False,downloaded_bit_sha_readback_verified=False)
    (root/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n','utf-8')
    cache_status=dict(status='NOT_CREATED',reason='Capture incomplete')
    if status=='ENGINEERING_SAME_INPUT_PASSED':
        try:
            from verified_evidence import seal_live
            with timing.span('seal_already_verified_live_evidence'):
                cache=seal_live(executor,plan['qualification'])
            cache_status=dict(status='SEALED',path=str(cache),origin='strict live SDK and same-input engineering audit')
        except Exception as exc:
            # A failed optional optimization cannot erase the completed audit.
            # The analysis worker then uses its original full strict loader.
            cache_status=dict(status='FALL_BACK_TO_FULL_AUDIT',reason=str(exc))
            notify('原采集已核验保存；证据复用未就绪，检测将完整复核：'+str(exc))
    (root/'EVIDENCE_CACHE.json').write_text(json.dumps(cache_status,ensure_ascii=False,indent=2)+'\n','utf-8')
    timing.save(root/'CAPTURE_PERFORMANCE.json',status=status,physical_hardware=getattr(executor,'evidence_source',None)=='real_board',pixel_format=plan['pixel_format'],formal_frames=len(records),preparation_frames=1 if preparation_record else 0,
                group=plan['group'],digest128=plan['digest128'],roi=roi,sample=plan['sample'],records=records,
                capture_to_archive_wall_seconds=time.monotonic()-started,includes_startup_and_cleanup=True,evidence_cache=cache_status,
                caveat='Host wall times and actual SDK counters; not FPGA pure cycles. Positioning and human interaction are outside this capture interval.')
    if status!='ENGINEERING_SAME_INPUT_PASSED':raise RuntimeError('0108阶段 '+phase+' 未完成；正式帧 '+str(len(records))+'/8；记录 '+str(root)+'；'+json.dumps(failure,ensure_ascii=False))
    return root/'fusion'

def prepare_retry(plan_path):
    """Keep the original failed run and exact mask; create a new reviewed plan."""
    plan_path=Path(plan_path).resolve();plan=read(plan_path)
    sys.path.insert(0,str(HOST));entry=module('_final0108_retry_plan',HOST/'engineering_capture.py')
    need(entry.plan_digest(plan)==plan['plan_sha256'],'Old reviewed plan changed')
    need(sha(plan['qualification'])==plan['qualification_sha256'] and sha(plan['mask'])==plan['mask_sha256'],'Old geometry/qualification changed')
    summary=read(Path(plan['result_directory'])/'SUMMARY.json')
    need(summary['status']=='FAILED' and summary['records']==[] and summary.get('roi_preparation_record') is None and summary.get('cleanup',{}).get('acknowledged') is True and summary.get('error',{}).get('message')=='BEGIN status 3; no automatic mutation retry','Only known pre-capture BEGIN rejection can reuse this retry path')
    outcomes=[read(path) for path in (Path(plan['result_directory'])/'captures').glob('*/outcome.json')]
    need(outcomes and sum(r.get('cost',{}).get('capture_requests',0) for r in outcomes)==0,'Only a verified zero-CAP failure can use this retry path')
    output=plan_path.parent/('retry_'+time.strftime('%Y%m%d_%H%M%S')+'_'+__import__('uuid').uuid4().hex[:8])
    new=prepare_native(plan['roi'],Path(plan['mask']),plan['sample'],plan['pose'],output)
    (output/'RETRY_SOURCE.json').write_text(json.dumps(dict(original_plan=str(plan_path),original_plan_sha256=sha(plan_path),original_failed_run=plan['result_directory'],same_roi=True,same_mask=True,mask_sha256=plan['mask_sha256'],no_new_CAP_during_prepare=True,operator_must_confirm_same_pose=True),indent=2)+'\n','utf-8')
    return new
