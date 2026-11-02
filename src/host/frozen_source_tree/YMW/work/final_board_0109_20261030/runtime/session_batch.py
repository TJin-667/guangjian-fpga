"""Experimental same-owner session reuse. Not installed in the stable GUI.

All original SDK transactions, mask CRC/ACK, per-frame verification and FPGA
comparison remain unchanged. Reuse is between fully released groups only.
"""
import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


@dataclass(frozen=True)
class Plan:
    group: int
    digest: bytes
    roi: tuple
    mask: bytes
    sample: str
    pose: str
    pixel_format: int = 49
    low_lines: int = 400
    high_lines: int = 800

    def validate(self, sensor_size):
        need(type(self.group) is int and 0 < self.group < 1 << 64, 'Nonzero uint64 group required')
        need(type(self.digest) is bytes and len(self.digest)==16 and any(self.digest), 'Nonzero digest128 required')
        need(type(self.roi) is tuple and len(self.roi)==4 and all(type(v) is int for v in self.roi), 'Native integer ROI required')
        x,y,w,h = self.roi
        need(min(x,y)>=0 and min(w,h)>=9 and x+w<=sensor_size[0] and y+h<=sensor_size[1], 'ROI outside native sensor')
        need(type(self.mask) is bytes and len(self.mask)==w*h and any(self.mask) and not any(v>1 for v in self.mask), 'Explicit binary native mask required')
        need(type(self.pixel_format) is int and self.pixel_format in (49,50), 'Gray49 or dual50 only')
        need(type(self.low_lines) is int and type(self.high_lines) is int and 1<=self.low_lines<self.high_lines<=1116,'Legal ordered manual exposure pair required')
        need(self.sample.strip() and self.pose.strip(), 'Sample and pose declarations required')

    @property
    def key(self):
        return self.roi,hashlib.sha256(self.mask).hexdigest(),self.pixel_format


class SessionBatch:
    def __init__(self, implementation, *, base, board, port, bind, ymw_root, physical,
                 candidate_binding=None, sensor_size=(1920,1080), initial_seq=None, owner_guard=None,
                 executor_factory=None,extra_source_hashes=None):
        # A live GUI must additionally own its ordinary operator lock. This
        # prototype has no CLI/network adapter changes and does not start IO here.
        self.impl=implementation;self.base=Path(base).resolve();self.endpoint=board,port;self.bind=bind
        self.ymw_root=Path(ymw_root);self.physical=bool(physical);self.binding=candidate_binding
        self.sensor_size=tuple(sensor_size);self.initial_seq=initial_seq
        self.owner_guard=owner_guard;self.owner_lease=None
        self.executor_factory=executor_factory
        self.client=None;self.key=None;self.failed=False;self.closed=False;self.last_group=0
        self.previous_root=None;self.previous_seal={};self.lock=threading.Lock()
        self.source_sha256=sha(__file__)
        self.source_snapshot=dict(implementation.sdk.SOURCE_SNAPSHOT)
        self.source_snapshot.update(extra_source_hashes or {})
        need(not self.physical or self.binding is not None,'Actual candidate binding required for real board')
        need(not self.physical or callable(owner_guard),'Real session must have the ordinary exclusive board-owner guard')

    def _sources(self):
        need(sha(__file__)==self.source_sha256,'Session adapter changed')
        need(all(sha(p)==h for p,h in self.source_snapshot.items()),'Original SDK/candidate changed')

    def _dispose(self, release_owner=False):
        if self.client is not None:
            self.client.close()
            self.client=None
        self.key=None
        if release_owner and self.owner_lease is not None:
            lease=self.owner_lease;self.owner_lease=None;lease.__exit__(None,None,None)

    def close(self):
        need(self.lock.acquire(blocking=False),'Session is busy; cancel the current group first')
        try:
            self._dispose(release_owner=True);self.closed=True
        finally:
            self.lock.release()

    def _new(self, plan, target):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from roi_prepare0109 import executor_class
        Executor=self.executor_factory(self.impl) if self.executor_factory else executor_class(self.impl)
        kwargs=dict(group_id=plan.group,group_digest=plan.digest,group_roi=plan.roi,group_low=plan.low_lines,group_high=plan.high_lines,
            group_board=np.frombuffer(plan.mask,np.uint8).reshape(plan.roi[3],plan.roi[2]).astype(bool),
            result_directory=target/'fusion',board=self.endpoint[0],port=self.endpoint[1],bind=self.bind,
            ymw_root=self.ymw_root,output_root=target/'captures',pixel_format=plan.pixel_format,
            mode='strict',evidence_source='real_board' if self.physical else 'software_udp_peer',
            sensor_size=self.sensor_size,candidate_binding=self.binding,command_timeout=1.5 if self.physical else .15,retries=2)
        if self.initial_seq is not None:
            kwargs['initial_seq']=self.initial_seq
        self.client=Executor(**kwargs);self.key=plan.key

    def _adopt(self, plan, target):
        e=self.client
        need(not e._off_group_live and e._off_slot==8 and e.extension.group is None,'Previous FPGA group not fully RELEASED')
        need(not e._off_failed and not e._poisoned,'Previous group is not reusable')
        # Rebind only group-local state. Session, mask key, owned request count,
        # nonce history, used sequence space and last successful frame stay intact.
        e._off_pair=(plan.low_lines,plan.high_lines)
        e._off_group=plan.group;e._off_digest=plan.digest;e._off_roi=plan.roi
        e._off_board=np.frombuffer(plan.mask,np.uint8).reshape(plan.roi[3],plan.roi[2]).astype(bool)
        e._off_mask=plan.mask;e._off_output=target/'fusion';e.output_root=target/'captures'
        e._off_slot=0;e._off_cookie=0;e._off_rows=[];e._off_failed=False

    def capture(self, plan, *, cancel=None, notify=lambda value:None, target=None):
        need(self.lock.acquire(blocking=False),'Concurrent group refused')
        try:
            need(not self.closed and not self.failed,'Closed/failed batch cannot silently reconnect')
            plan.validate(self.sensor_size)
            need(plan.group>self.last_group,'Group identifiers must increase; no stale plan replay')
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Cancelled before IO')
            try:
                self._sources()
                if self.previous_root is not None:
                    need(all(sha(self.previous_root/p)==h for p,h in self.previous_seal.items()),'Previous archived result changed')
            except (Exception,KeyboardInterrupt):
                self.failed=True;self._dispose(release_owner=True);raise
            target=(self.base/('group_'+str(plan.group))) if target is None else Path(target).resolve()
            need(target.is_relative_to(self.base),'Group target outside batch output root')
            need(not target.exists() and not target.with_name(target.name+'.pending').exists(),'New group directory required')
            same=self.client is not None and plan.key==self.key
            reason='same_session_same_ROI_mask_format' if same else 'first_group_or_changed_contract'
            if same:
                # Retain the original conservative reservation. Do not push the
                #16-bit allocator farther just to improve warm-run statistics.
                if 65536-len(self.client._used_sequences)<self.client._off_control_reservation:
                    same=False;reason='control_space_requires_new_session'
            if not same:
                self._dispose()
            target.mkdir(parents=True)
            records=[];costs=[];preparation=None;cleanup=None
            try:
                if self.owner_lease is None and self.owner_guard is not None:
                    lease=self.owner_guard();lease.__enter__();self.owner_lease=lease
                if same:
                    self._adopt(plan,target)
                else:
                    self._new(plan,target)
                e=self.client
                before_session=e.session
                def args(slot):
                    return dict(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=plan.low_lines if slot%2 else plan.high_lines,gain16=16,
                        roi=plan.roi,board_mask=plan.mask,settle_frames=1,discard_frames=3,
                        timeout_s=180 if self.physical else 12,sample_id=plan.sample,round_id=plan.pose,cancel=cancel)
                preparation=e.acquire_roi_preparation(**args(1));costs.append(e._cost_record())
                for slot in range(1,9):
                    frame=e.acquire(**args(slot));records.append(str(frame.record_path));costs.append(e._cost_record())
                    notify('Batch group '+str(plan.group)+' '+str(slot)+'/8')
            except (Exception,KeyboardInterrupt) as exc:
                self.failed=True
                write(target/'FAILURE.json',dict(status='FAILED',message=str(exc),type=type(exc).__name__,formal_frames=len(records),
                    reason=reason,old_result_preserved=True,automatic_reconnect=False))
                raise
            finally:
                if self.client is not None:
                    try:
                        cleanup=self.client.lights_off(timeout_s=3)
                        costs.append(cleanup.get('cost',{}));write(target/'OFF.json',cleanup)
                    except (Exception,KeyboardInterrupt) as exc:
                        self.failed=True
                        write(target/'OFF.json',dict(acknowledged=False,error=str(exc)))
                        raise
                    finally:
                        if self.failed:
                            self._dispose(release_owner=True)
            try:
                need(len(records)==8 and cleanup and cleanup.get('acknowledged'),'Incomplete group/OFF')
                actual=read(target/'fusion/RESULT.json')
                need(actual['group']==plan.group and not any(actual['differences'].values()),'Same-input FPGA/PC comparison failed')
                need(self.client.extension.group is None and not self.client._off_group_live,'Published result not released')
                current_session=self.client.session
                mask_commands=sum(c.get('mask_commands',0) for c in costs)
                if same:
                    need(current_session==before_session and mask_commands==0,'Claimed warm reuse unexpectedly rebound/uploaded mask')
                self._sources()
                summary=dict(status='ENGINEERING_SAME_INPUT_PASSED',cleanup=cleanup,records=records,
                    roi_preparation_record=str(preparation.record_path),roi_preparation_in_formal_eight=False,
                    formal_expected_frames=8,total_CAP_limit=9,engineering_only=True,release_ready=False,training_data=False,
                    scope='Experimental batch performance, not added to the deployed GUI',controller_sha256=self.source_sha256)
                write(target/'SUMMARY.json',summary)
                receipt=dict(status='GROUP_ARCHIVED_AND_RELEASED',group=plan.group,session=current_session,
                    reuse=same,reason=reason,mask_commands=mask_commands,
                    capture_requests=sum(c.get('capture_requests',0) for c in costs),saved_images=sum(c.get('saved_images',0) for c in costs),
                    formal_frames=8,preparation_frames=1,physical_hardware=self.physical,
                    SDK_costs=costs,device_profiles=actual['device_profiles'],FPGA_core_speedup=None,release_ready=False)
                write(target/'BATCH_RECEIPT.json',receipt)
                write(target/'SOURCE_INDEX.json',dict(files_sha256={**self.source_snapshot,str(Path(__file__).resolve()):self.source_sha256}))
                seal={p.relative_to(target).as_posix():sha(p) for p in sorted(target.rglob('*')) if p.is_file()}
                write(target/'OUTPUT_MANIFEST.json',dict(files_sha256=seal))
                self.previous_root=target;self.previous_seal=seal;self.last_group=plan.group
                return target,receipt
            except (Exception,KeyboardInterrupt):
                self.failed=True;self._dispose(release_owner=True);raise
        finally:
            self.lock.release()

    def finalize_metadata(self,target):
        """Seal newly added timing/cache receipts without accepting changed raw data."""
        need(self.lock.acquire(blocking=False),'Session busy')
        try:
            target=Path(target).resolve()
            need(target==self.previous_root and not self.failed,'Only latest complete group may be extended')
            need(all(sha(target/p)==h for p,h in self.previous_seal.items()),'Original group changed before metadata finalization')
            seal={p.relative_to(target).as_posix():sha(p) for p in sorted(target.rglob('*')) if p.is_file() and p!=target/'OUTPUT_MANIFEST.json'}
            write(target/'OUTPUT_MANIFEST.json',dict(files_sha256=seal));self.previous_seal=seal
        finally:self.lock.release()
