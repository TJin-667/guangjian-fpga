"""Separate candidate UI. Stable v1.5 files and launcher remain unchanged."""
from export_paths import legacy_location, data_path, lab_root, network
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk

HERE=Path(__file__).resolve().parent
STABLE=HERE
sys.path.insert(0,str(STABLE))
import app as stable_app
import pipeline
from continuous_capture import Controller,fresh_plan


def latest_roi_template(root=legacy_location('E:/GuangjianData/UnifiedInspection')):
    """A template pointer only; never silently pick an older successful job."""
    try:
        directories=sorted(p for p in Path(root).iterdir() if p.is_dir())
        if not directories:return None
        latest=directories[-1]
        job=json.loads((latest/'JOB.json').read_text(encoding='utf-8-sig'))
        result=json.loads((latest/'RESULT.json').read_text(encoding='utf-8-sig'))
        if job['status']!='COMPLETE' or result.get('physical_hardware') is not True or result.get('backend')!='offload0109_archive':return None
        plan=Path(result['input_source']).parent.parent/'PLAN.json'
        return plan if plan.is_file() else None
    except (OSError,ValueError,KeyError,TypeError):return None


def verify_candidate():
    result=stable_app.verify_dependencies()
    from archive0109 import HOST,QUALIFICATION
    sys.path.insert(0,str(HOST))
    from qualification import validate
    validate(QUALIFICATION)
    return result


class ContinuousApp(stable_app.UnifiedApp):
    def __init__(self,root,**kwargs):
        self.continuous=Controller();self.new_plan_pending=None
        super().__init__(root,hardware_mode='0109',**kwargs)
        root.title('光鉴 · 0109独立候选入口 v1.7 · 冻结检测f09eb5885e1d')
        self.lease_caption=tk.StringVar(master=root,value='尚未建立会话；首次完整上传mask。工件移动时请重新定位。')
        ttk.Label(self.engineering_tab,textvariable=self.lease_caption,wraplength=1050).pack(anchor='w',pady=5)
        self.release_button=ttk.Button(self.engineering_tab,text='结束连续会话，释放板卡',command=self.release_session)
        self.release_button.pack(anchor='w',pady=5)
        exposure_bar=ttk.Frame(self.engineering_tab);exposure_bar.pack(anchor='w',pady=5)
        ttk.Label(exposure_bar,text='下一组低曝光（行）').pack(side='left')
        self.continuous_low=ttk.Spinbox(exposure_bar,from_=1,to=1116,textvariable=self.low_lines,width=7);self.continuous_low.pack(side='left',padx=5)
        ttk.Label(exposure_bar,text='高曝光（行）').pack(side='left')
        self.continuous_high=ttk.Spinbox(exposure_bar,from_=1,to=1116,textvariable=self.high_lines,width=7);self.continuous_high.pack(side='left',padx=5)
        ttk.Label(self.engineering_tab,text='默认400/800行；可人工设置下一组曝光。组内锁定，逐帧核对实际写入与读回。',wraplength=1050).pack(anchor='w')
        for child in self.engineering_tab.winfo_children():
            if isinstance(child,ttk.Button) and '开始8帧工程验收' in str(child.cget('text')):
                child.configure(text='采集下一组（复用当前ROI/mask）')
        self.position0109_button.configure(text='重新定位（仅需要时使用）')
        self.start_button.configure(text='采集下一组（复用ROI）')
        self.status.set('实验入口就绪。选择已确认PLAN作为ROI模板，或需要时重新定位；每组单独归档。')

    def release_session(self):
        if self.busy():return
        self.continuous.close();self.lease_caption.set('会话已结束，板卡已释放；下一组需要完整配置。')

    def start(self):return self.start_0109_capture()

    def start_focus(self):
        if self.busy():return
        self.release_session();return super().start_focus()

    def start_focus0109(self):
        if self.busy():return
        self.release_session();return super().start_focus0109()

    def start_position0109(self):
        if self.busy():return
        self.release_session();return super().start_position0109()

    def lights_off(self):
        if self.busy():return
        self.release_session();return super().lights_off()

    def set_busy(self,value):
        super().set_busy(value)
        if hasattr(self,'release_button'):self.release_button.configure(state='disabled' if value else 'normal')
        for name in ('continuous_low','continuous_high'):
            if hasattr(self,name):getattr(self,name).configure(state='disabled' if value else 'normal')

    def start_0109_capture(self):
        if self.busy():return
        template=self.engineering_plan.get()
        if not template or not Path(template).is_file():
            self.status.set('先选择已确认的PLAN作为ROI模板；工件移动时再点“重新定位”。');return
        settings=self.settings_from_ui()
        if settings is None:return
        if not 1<=settings.low<settings.high<=1116:
            self.status.set('低、高曝光须为1～1116行整数，且低值小于高值。');return
        fmt=self.capture_format_code()
        self.pipeline_busy=True;self.pipeline_cancel=threading.Event();self.set_busy(True)
        self.status.set('使用当前ROI/mask准备新组；不重新定位。请保持实物摆放。')
        capture_started=time.perf_counter();mode='audit' if self.full_evidence_audit.get() else 'reuse'
        def task():
            try:
                plan=fresh_plan(template,sample=settings.specimen,pose=settings.variant,low=settings.low,high=settings.high,pixel_format=fmt)
                self.new_plan_pending=str(plan)
                archive=self.continuous.capture(plan,self.pipeline_cancel,notify=lambda s:self.pipeline_events.put(('log',s)))
                cache=Path(archive).parent/'EVIDENCE_CACHE.json'
                effective='audit' if cache.is_file() and pipeline.read(cache).get('status')=='FALL_BACK_TO_FULL_AUDIT' else mode
                self.pipeline_events.put(('complete',pipeline.run(archive,'0109',self.analysis_root,cancel=self.pipeline_cancel,
                    notify=lambda s:self.pipeline_events.put(('log',s)),validation_mode=effective,capture_started=capture_started)))
            except (Exception,KeyboardInterrupt) as exc:
                self.continuous.close();self.pipeline_events.put(('failed',str(exc)))
        self.pipeline_thread=threading.Thread(target=task,daemon=False);self.pipeline_thread.start()

    def poll(self):
        super().poll()
        if hasattr(self,'lease_caption') and not self.closing:
            if self.new_plan_pending:
                self.engineering_plan.set(self.new_plan_pending);self.new_plan_pending=None
            receipt=self.continuous.last_receipt
            if self.continuous.batch is None:
                self.lease_caption.set('无保留会话；调焦/定位/结束会话后，下一组完整配置。')
            elif receipt:
                self.lease_caption.set('会话已保留；上一组mask命令 '+str(receipt['mask_commands'])+'。同ROI/mask可直接改组信息拍下一组；移动工件请重新定位。')

    def destroy_ui(self):
        self.continuous.close();super().destroy_ui()


def main():
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--plan',type=Path)
    a=p.parse_args();verify_candidate()
    if a.check_only:
        print(json.dumps(dict(status='CONTINUOUS_UI_OFFLINE_READY',physical_continuous_session_verified=False,
            default_exposure=[400,800],manual_exposure_range=[1,1116],device_service_cycles_enabled=True,frozen_algorithm='f09eb5885e1d',default_entry_changed=False)));return
    if os.name=='nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError,OSError):pass
    root=tk.Tk();application=ContinuousApp(root)
    template=a.plan or latest_roi_template()
    if template:
        application.engineering_plan.set(str(template.resolve()))
        try:
            old=json.loads(template.read_text(encoding='utf-8-sig'));application.sample.set(old['sample'])
            stage=re.search(r'[AB]_v\d+',old.get('pose',''))
            if stage:application.variant.set(stage.group(0))
        except (OSError,ValueError,KeyError):pass
        application.status.set('已加载上次完整采集的ROI模板。工件未动可改组信息后直接下一组；已移动请点“重新定位”。')
    root.mainloop()


if __name__=='__main__':main()
