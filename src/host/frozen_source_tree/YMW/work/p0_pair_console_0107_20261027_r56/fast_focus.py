"""Memory-only full-resolution GRAY8 focus preview; never formal P0 inputs."""
import copy
import ctypes
import io
import json
import threading
import time
from collections import Counter,deque
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import console_workflow as workflow
import focus_tools

sdk=workflow.backend.sdk
HERE=Path(__file__).resolve().parent
DEFAULT_MAX_FRAMES=1000
TARGET_FPS=2.0

class NativeCRC:
    def __init__(self):
        proof=workflow.read(HERE/'CRC_BUILD.json')
        for name,digest in proof['files_sha256'].items():workflow.need(workflow.sha(HERE/name)==digest,'Preview CRC source/binary changed')
        self.library=ctypes.CDLL(str(HERE/'preview_crc64.dll'))
        self.function=self.library.gj_crc64;self.function.argtypes=[ctypes.c_char_p,ctypes.c_size_t];self.function.restype=ctypes.c_uint64
        workflow.need(self(b'123456789')==0x6c40df5f0b497347,'Native CRC64 self check failed')
    def __call__(self,raw):return int(self.function(raw,len(raw)))

class LatestFrame:
    """One pending display frame; slow rendering cannot build a video backlog."""
    def __init__(self):self.lock=threading.Lock();self.value=None;self.pending=False;self.replaced=0
    def put(self,value):
        with self.lock:
            if self.value is not None:self.replaced+=1
            self.value=value;signal=not self.pending;self.pending=True;return signal
    def take(self):
        with self.lock:value=self.value;self.value=None;self.pending=False;return value

class PreviewTransport(sdk.TransportExecutor):
    def __init__(self,**kwargs):
        workflow.need(kwargs.get('pixel_format')==49,'Focus preview requires existing GRAY8+SAT1 format')
        self.crc=NativeCRC();self.journal=None;self.needs_light=False;self.zero_timing=False
        super().__init__(**kwargs)
    def _prepare(self):
        applied=self._camera(setting=True);readback=self._camera()
        workflow.need((readback['generation'],readback['raw_registers'])==(applied['generation'],applied['raw_registers']),'Preview camera readback changed')
        self._camera_snapshot=readback;self._crop=False;self._roi_snapshot=None;self._roi_generation=0
        workflow.need(self._requested['roi']==[0,0,*self.sensor_size],'Fast focus is full-frame only')
        self._transaction(1,(1,128,0,0))
        self._transaction(12,(self._requested['settle_frames']<<48)|(self._requested['discard_frames']<<32))
        self._event('preview_configuration_confirmed',camera_readback=readback,board_mask_uploaded=False,
            scope='focus image/CRC only; masked H1/H2 unavailable and not required')
    def _publish_verified(self,meta,after,rectangle):
        # The bootstrap reuses the SDK configuration/identity lifecycle, with
        # no PNG encoding, per-frame full archives or duplicate H1/H2 replay.
        frame=self._preview_result(meta)
        self._call.update(status='PREVIEW_ONLY_NOT_P0',strict_verified=False,payload_CRC64_verified=True,
            H1_H2_recomputed=False,training_data=False,identity=meta['identity'],cost=self._cost_record())
        workflow.write(self._directory/'outcome.json',self._call)
        return frame
    def _preview_result(self,meta):
        self._check()
        workflow.need(sdk.wire.decode_metadata(self._metadata_packet,self._metadata_seq)==meta,'Preview metadata bytes changed')
        workflow.need(meta['valid'] and meta['logical_association_available'] and meta['parameters_valid'] and not meta['error'],'Preview not committed')
        workflow.need(meta['pixel_format']==49 and meta['roi']==[0,0,*self.sensor_size],'Preview format/geometry mismatch')
        workflow.need(meta['fifo_reads']==self.sensor_size[0]*self.sensor_size[1],'Preview incomplete DDR drain')
        workflow.need(meta['wait_complete_frames']==self._requested['settle_frames'] and meta['discard_complete_frames']==self._requested['discard_frames'],'Preview settling mismatch')
        raw=self._image_raw
        workflow.need(len(raw)==meta['payload_bytes'] and self.crc(raw)==meta['payload_crc64'],'Preview payload CRC64 mismatch')
        previous=self._last_success
        if previous is not None:
            workflow.need(meta['identity']['session']==previous['session'],'Preview session changed')
            for key in ['request_id','dvp_sequence','publish_sequence']:
                delta=(meta['identity'][key]-previous[key])&0xffffffff
                workflow.need(0<delta<0x80000000,'Stale preview publication')
        gray,_=sdk.wire.planes_from_payload(raw,*self.sensor_size,49)
        frame=SimpleNamespace(image=Image.fromarray(gray),metadata=copy.deepcopy(meta),received_monotonic=time.monotonic(),started_monotonic=self._started,
            cost=self._cost_record(),payload_CRC64_verified=True)
        self._last_success=dict(meta['identity']);self._cap_attempted=False;self._receiver.parts.clear()
        return frame
    def frame(self,cancel,timeout=8):
        if not self._lock.acquire(blocking=False):raise ValueError('Preview endpoint busy')
        trace=io.StringIO()
        try:
            workflow.need(not self._poisoned and self._connected,'Preview connection needs recovery')
            self._trace=trace;self._call=dict(call_id='preview_'+str(self._owned_counter+1))
            self._cost=Counter();self._kinds=Counter();self._cancel=cancel
            self._started=time.monotonic();self._deadline=self._started+timeout
            self._receiver=None;self._buffer=deque();self._cap_attempted=False;self._pending_mutation=False
            workflow.need(len(self._used_sequences)<65536-64,'Preview control space exhausted; stop before any new CAP')
            if self.needs_light:
                self._transaction(1,(1,128,0,0));self._transaction(12,(1<<48)|(3<<32))
                self._requested.update(settle_frames=1,discard_frames=3);self.needs_light=False;self.zero_timing=False
            elif not self.zero_timing:
                self._transaction(12,0);self._requested.update(settle_frames=0,discard_frames=0);self.zero_timing=True
            meta=self._capture(strict=True)
            return self._preview_result(meta)
        except BaseException:
            self._poisoned=not self._retire() or self._pending_mutation
            raise
        finally:
            if self.journal is not None:self.journal.write(trace.getvalue());self.journal.flush()
            self._trace=None;self._call=None;trace.close();self._lock.release()
    def pause(self):
        result=self.lights_off(timeout_s=3);workflow.need(result['acknowledged'],'Preview pause OFF missing ACK')
        self.needs_light=True;return result

def make_transport(runtime,plan,out):
    base=plan['source_contract'];engine=runtime.core.load_engine()
    return PreviewTransport(board=base['board'],bind=base['bind'],port=base['port'],ymw_root=engine.root/'ymw',
        output_root=out/'sdk_calls',mode='strict',pixel_format=49,candidate_binding=plan['candidate']['binding'],
        evidence_source=runtime.evidence_source,command_timeout=1.5,retries=3)

class FocusSession:
    def __init__(self,cancel,notify,max_frames=DEFAULT_MAX_FRAMES,max_bytes=None,target_fps=TARGET_FPS):
        workflow.need(0<target_fps<=4,'Focus target must be in (0,4]')
        self.cancel=cancel;self.notify=notify;self.max_frames=max_frames;self.max_bytes=max_bytes;self.target_fps=target_fps
        self.lock=threading.Lock();self.paused=threading.Event();self.roi=None;self.version=0
    def set_roi(self,roi):
        with self.lock:self.roi=tuple(roi);self.version+=1;return self.version
    def get_roi(self):
        with self.lock:return self.roi,self.version
    def toggle_pause(self):
        if self.paused.is_set():self.paused.clear();return False
        self.paused.set();return True
    def run(self,out,specimen,runtime=None,factory=make_transport):
        out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
        runtime=runtime or workflow.Runtime(specimen,'A_v1','fast_focus_'+time.strftime('%Y%m%d_%H%M%S'),self.cancel,self.notify)
        plan,context,_=workflow.backend.plan_for(runtime,preview=True)
        rows=[];client=None;off=dict(acknowledged=False);error=None;status='FOCUS_STOPPED';started=time.monotonic();costs=Counter()
        self.notify('phase',phase='focus_preview');previous_received=None;paused_off=False
        try:
            with runtime.guard():
                workflow.backend.cancelled(runtime);client=factory(runtime,plan,out)
                try:
                    with (out/'preview_transport.jsonl').open('w',encoding='utf-8') as journal:
                        client.journal=journal
                        frame=client.acquire(light_channel=1,brightness=128,exposure_lines=plan.get('preview_lines',600),gain16=16,
                            roi=context.roi,board_mask=context.mask,settle_frames=1,discard_frames=3,
                            timeout_s=300,cancel=self.cancel,sample_id=specimen,round_id='FAST_FOCUS_ONLY_NOT_P0')
                        while True:
                            roi,version=self.get_roi();w,h=runtime.sensor_size
                            roi=roi or ((w-min(w,320))//2,(h-min(h,240))//2,min(w,320),min(h,240))
                            metric=focus_tools.measure(frame.image,roi)
                            interval=None if previous_received is None else frame.received_monotonic-previous_received
                            previous_received=frame.received_monotonic
                            row=dict(identity=frame.metadata['identity'],ROI=list(roi),roi_version=version,metric=metric,
                                parameters=frame.metadata['parameters'],payload_bytes=frame.metadata['payload_bytes'],payload_crc64=frame.metadata['payload_crc64'],
                                payload_CRC64_verified=True,received_monotonic=frame.received_monotonic,
                                actual_receive_fps=None if not interval else 1/interval,cost=frame.cost,training_data=False)
                            rows.append(row)
                            for key,value in frame.cost.items():
                                if type(value) in (int,float):costs[key]+=value
                            self.notify('focus_live_frame',image=frame.image,roi=roi,version=version,metric=metric,parameters=row['parameters'],
                                frame_id=row['identity']['frame_id'],identity=row['identity'],count=len(rows),target_fps=self.target_fps,
                                received_monotonic=frame.received_monotonic,actual_fps=row['actual_receive_fps'],record=None)
                            if self.cancel.is_set():break
                            if len(rows)>=self.max_frames:status='FOCUS_BUDGET_REACHED';break
                            while self.paused.is_set() or self.get_roi()[0] is None:
                                if not paused_off:
                                    off=client.pause();paused_off=True;self.notify('focus_paused',waiting_for_roi=self.get_roi()[0] is None)
                                if self.cancel.wait(.02):break
                            if self.cancel.is_set():break
                            if paused_off:previous_received=None;paused_off=False
                            remaining=frame.started_monotonic+1/self.target_fps-time.monotonic()
                            if remaining>0 and self.cancel.wait(remaining):break
                            frame=client.frame(self.cancel)
                finally:
                    try:off=client.lights_off(timeout_s=3)
                    finally:client.close()
        except BaseException as exc:
            if not self.cancel.is_set():status='FAILED';error=dict(type=type(exc).__name__,message=str(exc))
        if client is not None and not off.get('acknowledged'):status='CLEANUP_REQUIRED'
        self.notify('phase',phase='focus_finishing')
        workflow.write(out/'focus_frames.json',rows)
        workflow.write(out/'preview_cost.json',dict(totals=dict(costs),note='Received frame costs; failed/bootstrap attempts also retained in SDK/transport logs'))
        result=runtime.archive(out,dict(status=status,error=error,scope='FAST_MANUAL_FOCUS_ONLY_NOT_P0',physical_specimen_id=specimen,
            frames=len(rows),lights_off=off,elapsed_s=time.monotonic()-started,target_fps=self.target_fps,
            real_hardware_fps_verified=False,full_resolution=True,preview_pixel_format=49,preview_GRAYSCALE=True,
            per_frame_CRC64_verified=True,H1_H2_recomputed=False,per_frame_images_saved=False,
            max_frames=self.max_frames,training_data=False,counts_as_P0_group=False,release_ready=False))
        return dict(root=str(out),receipt=result['summary'])
