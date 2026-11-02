"""Strict0107 full-frame focus snapshots; score the host-selected native crop."""
import csv
import threading
import time
from pathlib import Path
from PIL import Image
import console_workflow as workflow
import focus_tools

DEFAULT_MAX_FRAMES=300

class FocusSession:
    def __init__(self,cancel,notify,max_frames=DEFAULT_MAX_FRAMES,max_bytes=None):
        self.cancel=cancel;self.notify=notify;self.max_frames=max_frames;self.max_bytes=max_bytes
        self.lock=threading.Lock();self.paused=threading.Event();self.roi=None;self.version=0
    def set_roi(self,roi):
        with self.lock:self.roi=tuple(roi);self.version+=1;return self.version
    def get_roi(self):
        with self.lock:return self.roi,self.version
    def toggle_pause(self):
        if self.paused.is_set():self.paused.clear();return False
        self.paused.set();return True
    def run(self,out,specimen,runtime=None):
        out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
        runtime=runtime or workflow.Runtime(specimen,'A_v1','focus_only_'+time.strftime('%Y%m%d_%H%M%S'),self.cancel,self.notify)
        plan,context,_=workflow.backend.plan_for(runtime,preview=True)
        rows=[];executor=None;off={'acknowledged':False};error=None;bytes_saved=0;status='FOCUS_STOPPED';started=time.monotonic()
        self.notify('phase',phase='focus_preview')
        try:
            with runtime.guard():
                workflow.backend.cancelled(runtime);executor=runtime.executor(plan,out)
                try:
                    overview=executor.acquire(light_channel=1,brightness=128,exposure_lines=600,gain16=16,
                        roi=context.roi,board_mask=context.mask,settle_frames=1,discard_frames=3,
                        timeout_s=300,cancel=self.cancel,sample_id=specimen,round_id='FOCUS_ONLY_NOT_P0')
                    workflow.backend.bridge.load_commit(overview.record_path,sensor_size=runtime.sensor_size)
                    self.notify('focus_overview',path=str(overview.png_path),size=runtime.sensor_size,record=str(overview.record_path))
                    rows.append(dict(kind='overview',record=overview.record_path.relative_to(out).as_posix(),identity=overview.metadata['identity'],ROI=list(context.roi)))
                    bytes_saved+=sum(p.stat().st_size for p in overview.record_path.parent.parent.rglob('*') if p.is_file())
                    paused_off=False
                    while not self.cancel.is_set() and len(rows)<self.max_frames and (self.max_bytes is None or bytes_saved<self.max_bytes):
                        roi,version=self.get_roi()
                        if self.paused.is_set() or roi is None:
                            if not paused_off:
                                off=executor.lights_off(timeout_s=3);workflow.need(off['acknowledged'],'Focus pause OFF missing ACK');paused_off=True
                                self.notify('focus_paused',waiting_for_roi=roi is None)
                            self.cancel.wait(.15);continue
                        paused_off=False
                        x,y,w,h=roi
                        workflow.need(min(w,h)>=9 and min(x,y)>=0 and x+w<=runtime.sensor_size[0] and y+h<=runtime.sensor_size[1],'Focus ROI outside sensor')
                        result=executor.acquire(light_channel=1,brightness=128,exposure_lines=600,gain16=16,
                            roi=context.roi,board_mask=context.mask,settle_frames=1,discard_frames=3,
                            timeout_s=300,cancel=self.cancel,sample_id=specimen,round_id='FOCUS_ONLY_NOT_P0')
                        workflow.backend.bridge.load_commit(result.record_path,sensor_size=runtime.sensor_size)
                        with Image.open(result.png_path) as image:metric=focus_tools.measure(image,roi)
                        record=dict(kind='focus_full_frame',record=result.record_path.relative_to(out).as_posix(),
                            identity=result.metadata['identity'],ROI=list(roi),capture_ROI=list(context.roi),roi_version=version,metric=metric,
                            parameters=result.metadata['actual_parameters'],SDK_elapsed_s=result.metadata['cost']['host_elapsed_s'])
                        rows.append(record);bytes_saved+=sum(p.stat().st_size for p in result.record_path.parent.parent.rglob('*') if p.is_file())
                        workflow.write(out/'focus_frames.json',rows)
                        self.notify('focus_frame',path=str(result.png_path),record=str(result.record_path),roi=roi,version=version,
                            metric=metric,parameters=record['parameters'],frame_id=result.metadata['identity']['frame_id'],count=len(rows),bytes_saved=bytes_saved,full_frame=True)
                        self.cancel.wait(.1)
                    if not self.cancel.is_set():status='FOCUS_BUDGET_REACHED'
                finally:
                    try:off=executor.lights_off(timeout_s=3)
                    finally:executor.close()
        except BaseException as exc:
            if not self.cancel.is_set():status='FAILED';error=dict(type=type(exc).__name__,message=str(exc))
        if executor is not None and not off.get('acknowledged'):
            status='CLEANUP_REQUIRED';error=error or dict(type='MissingOffACK',message='OFF not acknowledged; inspect physical light state')
        self.notify('phase',phase='focus_finishing')
        workflow.write(out/'focus_frames.json',rows)
        with (out/'focus_scores.csv').open('w',newline='',encoding='utf-8-sig') as stream:
            fields=['frame_id','roi_version','ROI','score','dark_percent','bright_percent'];writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for row in rows:
                if row['kind']=='focus_full_frame':writer.writerow(dict(frame_id=row['identity']['frame_id'],roi_version=row['roi_version'],ROI=row['ROI'],**{k:row['metric'][k] for k in fields[3:]}))
        outcomes=[workflow.read(p) for p in (out/'sdk_calls').glob('*/outcome.json')]
        recorded_CAP=sum(row.get('cost',{}).get('capture_requests',0) for row in outcomes)
        result=runtime.archive(out,dict(status=status,error=error,scope='MANUAL_FOCUS_ONLY_NOT_P0',physical_specimen_id=specimen,
            frames=len(rows),recorded_logical_CAP=recorded_CAP,bytes_saved=bytes_saved,lights_off=off,elapsed_s=time.monotonic()-started,
            gain16=16,brightness=128,exposure_lines=600,light_channel=1,ROI_frames_are_not_full_frames=False,
            full_overview_is_initial_positioning_only=False,live_full_frame_snapshots=True,
            focus_ROI_is_host_crop_of_same_frame=True,training_data=False,counts_as_P0_group=False,
            max_frames=self.max_frames,max_bytes=self.max_bytes,release_ready=False))
        return dict(root=str(out),receipt=result['summary'])
