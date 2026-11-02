# Derived independent host adapter; source SHA256 8a3b9ec52e21f11976496781a9f0127e4b5e3f92faea681f235aa62d35416b21
"""Qualified continuous-session controller for the separate experimental UI."""
from export_paths import legacy_location, data_path, lab_root, network
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from session_batch import Plan,SessionBatch,need,read,sha,write

HERE=legacy_location('C:/bx72_ymw_0105_20261015/repo/YMW/work/final_board_0109_20261030/runtime')
STABLE=HERE
sys.path.insert(0,str(STABLE))
import engineering0109
from performance import Ledger,profiled_executor
from roi_prepare0109 import executor_class


def fresh_plan(template, *, sample,pose,low,high,pixel_format,base=legacy_location('E:/GuangjianData/continuous0109_plans')):
    need(type(low) is int and type(high) is int and 1<=low<high<=1116,'曝光需为1～1116行整数，且低曝光小于高曝光。')
    old=read(template)
    sys.path.insert(0,str(engineering0109.HOST))
    entry=engineering0109.module('_continuous_plan_codec',engineering0109.HOST/'engineering_capture.py')
    need(entry.plan_digest(old)==old['plan_sha256'],'ROI模板计划已变化')
    need(sha(old['mask'])==old['mask_sha256'],'ROI模板mask已变化')
    target=Path(base)/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    return engineering0109.prepare_native(old['roi'],Path(old['mask']),sample,pose,target,pixel_format=pixel_format,low=low,high=high)


class Controller:
    def __init__(self):
        self.batch=None;self.qualification_sha=None;self.ledger=None;self.last_receipt=None

    def close(self):
        if self.batch is not None:
            self.batch.close();self.batch=None

    def _create(self,plan):
        sys.path.insert(0,str(engineering0109.HOST))
        from qualification import validate
        qualification,_=validate(plan['qualification'])
        need(qualification['candidate_source_commit']==plan['candidate_source_commit'],'计划与候选源码版本不同')
        implementation=engineering0109.module('_continuous_executor_'+uuid.uuid4().hex,engineering0109.HOST/'engineering_executor.py',QUALIFICATION_PATH=plan['qualification'])
        sdk=implementation.sdk
        core=sdk.wire.pinned_module('_continuous_operator_lock',engineering0109.HOST.parents[1]/'auto_exposure_0105_20261015/app_core.py','448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
        self.ledger=Ledger()
        def factory(impl):return profiled_executor(impl,executor_class(impl),self.ledger)
        extra={str(p):sha(p) for p in (Path(__file__),HERE/'session_batch.py',HERE/'continuous_app.py',STABLE/'performance.py',STABLE/'roi_prepare0109.py')}
        from bootstrap import candidate_sources
        extra.update(candidate_sources())
        self.batch=SessionBatch(implementation,base=legacy_location('E:/GuangjianData'),board=plan['board'],port=plan['port'],bind=plan['bind'],
            ymw_root=core.load_engine().root/'ymw',physical=True,
            candidate_binding=dict(candidate_source_commit=qualification['candidate_source_commit'],bit_path=qualification['bit_path'],bit_sha256=qualification['bit_sha256']),
            owner_guard=lambda:core.operator_lock(Path(plan['lab_root'])),executor_factory=factory,extra_source_hashes=extra)
        self.qualification_sha=plan['qualification_sha256']

    def capture(self,plan_path,cancel,notify=lambda value:None):
        started=time.perf_counter();requested_bytes=Path(plan_path).read_bytes();plan=json.loads(requested_bytes)
        need(plan.get('schema')=='0109-engineering-capture-plan-v1' and plan.get('gain16')==16 and plan.get('LED')==128,'0109固定增益/灯光计划不符')
        sys.path.insert(0,str(engineering0109.HOST))
        entry=engineering0109.module('_continuous_capture_codec',engineering0109.HOST/'engineering_capture.py')
        need(entry.plan_digest(plan)==plan['plan_sha256'],'新组计划已变化')
        need(sha(plan['qualification'])==plan['qualification_sha256'] and sha(plan['mask'])==plan['mask_sha256'],'新组依赖已变化')
        requested=Plan(plan['group'],bytes.fromhex(plan['digest128']),tuple(plan['roi']),Path(plan['mask']).read_bytes(),plan['sample'],plan['pose'],plan['pixel_format'],plan['low_lines'],plan['high_lines'])
        requested.validate((1920,1080))
        if cancel.is_set():raise InterruptedError('开始前已停止；尚未采集')
        if self.batch is None or self.batch.failed or self.batch.closed or self.qualification_sha!=plan['qualification_sha256']:
            self.close();self._create(plan)
        # The profiled original methods close over this ledger object. Reset
        # only while the session is idle, before any new group IO.
        self.ledger.started=self.ledger.clock();self.ledger.events=[];self.ledger.aggregates={};self.ledger.costs=[]
        try:
            target,receipt=self.batch.capture(requested,cancel=cancel,notify=notify,target=plan['result_directory'])
            need(Path(plan_path).read_bytes()==requested_bytes,'采集期间计划已变化，保留本组原片并停止复用')
            (target/'REQUESTED_PLAN.json').write_bytes(requested_bytes)
            write(target/'REQUESTED_PLAN_SOURCE.json',dict(path=str(Path(plan_path).resolve()),sha256=hashlib.sha256(requested_bytes).hexdigest()))
            cache_status=dict(status='NOT_CREATED')
            try:
                from combined_evidence import seal_live
                with self.ledger.span('seal_already_verified_live_evidence'):
                    cache=seal_live(self.batch.client,plan['qualification'])
                cache_status=dict(status='SEALED',path=str(cache),origin='strict continuous SDK and same-input engineering audit')
            except Exception as exc:
                cache_status=dict(status='FALL_BACK_TO_FULL_AUDIT',reason=str(exc))
                notify('证据复用未就绪，将完整复核：'+str(exc))
            write(target/'EVIDENCE_CACHE.json',cache_status)
            self.ledger.save(target/'CAPTURE_PERFORMANCE.json',status='ENGINEERING_SAME_INPUT_PASSED',physical_hardware=self.batch.physical,
                pixel_format=plan['pixel_format'],formal_frames=8,preparation_frames=1,group=plan['group'],digest128=plan['digest128'],
                roi=plan['roi'],sample=plan['sample'],records=read(target/'SUMMARY.json')['records'],
                capture_to_archive_wall_seconds=time.perf_counter()-started,includes_startup_and_cleanup=True,
                evidence_cache=cache_status,continuous_session=receipt,
                caveat='First group uploads full mask; warm reuse only within a retained SDK session. Host intervals are not FPGA cycles.')
            self.batch.finalize_metadata(target);self.last_receipt=receipt
            notify('同会话复用mask，未再次上传。' if receipt['reuse'] else '本组完整上传mask；后续同ROI可复用。')
            return target/'fusion'
        except (Exception,KeyboardInterrupt):
            self.close();raise
