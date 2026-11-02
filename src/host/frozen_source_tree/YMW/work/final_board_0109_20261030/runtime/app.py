"""One-window capture -> frozen detection -> review. Original capture UI is inherited."""
from __future__ import annotations
from export_paths import legacy_location, data_path, lab_root, network
import argparse,hashlib,importlib.util,json,os,queue,sys,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
from contracts import require_backend,DETECTOR_ID,PARAMETER_FREEZE_ID,SYSTEM_VERSION,result_version_label
import pipeline
HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
CAPTURE=WORK/'p0_pair_console_0107_20261027_r56'
sys.path.insert(0,str(CAPTURE))
from console_app import ConsoleApp
import console_workflow as capture_workflow

def verify_dependencies():
    from integrity import verify
    verify()
    capture_workflow.verify_bundle()
    from frozen_algorithm import metadata
    return dict(status='FINAL_SYSTEM_OFFLINE_READY',backend='stable0107_pc',hardware_contacted=False,**metadata(),integration_version=SYSTEM_VERSION,offload0109_enabled=False)

class CaptureEvents(queue.Queue):
    def __init__(self,observer):super().__init__();self.observer=observer
    def get_nowait(self):
        item=super().get_nowait();self.observer(*item);return item

class Viewport(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.source=None;self.photo=None;self.pending=None;self.zoom=1.;self.last_render_pixels=0;self.auto_fit=True
        self.canvas=tk.Canvas(self,bg='#192738',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        self.xbar=ttk.Scrollbar(self,orient='horizontal',command=self.xview);self.xbar.grid(row=1,column=0,sticky='ew')
        self.ybar=ttk.Scrollbar(self,orient='vertical',command=self.yview);self.ybar.grid(row=0,column=1,sticky='ns')
        self.canvas.configure(xscrollcommand=self.xbar.set,yscrollcommand=self.ybar.set);self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        self.item=self.canvas.create_image(0,0,anchor='nw');self.canvas.bind('<Configure>',lambda e:self.fit() if self.auto_fit else self.schedule())
        self.canvas.bind('<MouseWheel>',lambda e:self.set_zoom(self.zoom*(1.2 if e.delta>0 else 1/1.2),e.x,e.y))
        self.canvas.bind('<ButtonPress-1>',lambda e:self.canvas.scan_mark(e.x,e.y));self.canvas.bind('<B1-Motion>',self.pan)
    def load(self,image):self.source=image.convert('RGB');self.fit()
    def fit(self):
        if self.source is None:return
        self.auto_fit=True
        self.zoom=min(max(1,self.canvas.winfo_width())/self.source.width,max(1,self.canvas.winfo_height())/self.source.height,1.)
        self.canvas.configure(scrollregion=(0,0,self.source.width*self.zoom,self.source.height*self.zoom));self.canvas.xview_moveto(0);self.canvas.yview_moveto(0);self.schedule()
    def set_zoom(self,value,x=None,y=None):
        if self.source is None:return
        self.auto_fit=False
        x=self.canvas.winfo_width()/2 if x is None else x;y=self.canvas.winfo_height()/2 if y is None else y
        px=self.canvas.canvasx(x)/self.zoom;py=self.canvas.canvasy(y)/self.zoom;self.zoom=max(.05,min(8.,value));w=self.source.width*self.zoom;h=self.source.height*self.zoom
        self.canvas.configure(scrollregion=(0,0,w,h));self.canvas.xview_moveto(max(0,px*self.zoom-x)/max(w,1));self.canvas.yview_moveto(max(0,py*self.zoom-y)/max(h,1));self.schedule()
    def xview(self,*args):self.canvas.xview(*args);self.schedule()
    def yview(self,*args):self.canvas.yview(*args);self.schedule()
    def pan(self,event):self.canvas.scan_dragto(event.x,event.y,gain=1);self.schedule()
    def schedule(self):
        if self.pending is None:self.pending=self.after(25,self.redraw)
    def redraw(self):
        self.pending=None
        if self.source is None:return
        z=self.zoom;w,h=self.source.size;x=max(0,int(self.canvas.canvasx(0)/z)-2);y=max(0,int(self.canvas.canvasy(0)/z)-2)
        right=min(w,int(self.canvas.canvasx(self.canvas.winfo_width())/z)+3);bottom=min(h,int(self.canvas.canvasy(self.canvas.winfo_height())/z)+3)
        if right<=x or bottom<=y:return
        tile=self.source.crop((x,y,right,bottom)).resize((max(1,round((right-x)*z)),max(1,round((bottom-y)*z))),Image.Resampling.NEAREST if z>=1 else Image.Resampling.LANCZOS)
        self.last_render_pixels=tile.width*tile.height;self.photo=ImageTk.PhotoImage(tile,master=self.canvas);self.canvas.coords(self.item,x*z,y*z);self.canvas.itemconfigure(self.item,image=self.photo)

class UnifiedApp(ConsoleApp):
    def __init__(self,root,*,result_root=None,analysis_root=None,preflight=True,hardware_mode='0107'):
        if hardware_mode not in ('0107','0109'):raise ValueError('Explicit0107/0109 hardware mode required')
        self.hardware_mode=hardware_mode
        self.pipeline_busy=False;self.pipeline_thread=None;self.pipeline_cancel=threading.Event();self.pipeline_events=queue.Queue(maxsize=500);self.auto_after_capture=False;self.capture_handoff=None;self.final_result=None;self.final_path=None;self.location0109_active=False
        self.analysis_root=Path(analysis_root or str(legacy_location('E:/GuangjianData/UnifiedInspection')))
        super().__init__(root,result_root=result_root,preflight=preflight)
        self.events=CaptureEvents(self.observe_capture_event)
        def relabel(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Label):
                    text=str(child.cget('text'))
                    if text.startswith('光鉴  /  定位'):child.configure(text='光鉴 / 调焦定位 → 八帧采集 → 冻结检测 → 局部复检')
                    elif text.startswith('原09保留 · 要求'):child.configure(text=('0109工程后端 · 调焦 → 新定位 → 八帧验收' if self.hardware_mode=='0109' else '0107稳定后端')+' · 默认400/800行 · 固定1倍增益/LED128')
                    elif text.startswith('新入口为开发采集。'):child.configure(text='原片与检测结果均保留；证据分辅助人工复检。停止/关窗会安全结束当前任务并保存记录。')
                relabel(child)
        relabel(root)
        root.title('光鉴 · '+self.hardware_mode+' / 采集 / 检测 / 复检 '+SYSTEM_VERSION+' · '+PARAMETER_FREEZE_ID)
        root.geometry(f'{min(1380,root.winfo_screenwidth()-60)}x{min(960,root.winfo_screenheight()-90)}');root.minsize(1000,650)
        self.auto_check.pack_forget();self.auto_final=tk.BooleanVar(master=root,value=True)
        ttk.Checkbutton(self.analysis_button.master,text='采集成功后自动检测并复检',variable=self.auto_final).pack(side='left',before=self.analysis_button)
        self.analysis_button.configure(text='冻结检测与复检',command=self.run_current)
        self.tabs.hide(self.evidence_tab)
        self.final_tab=ttk.Frame(self.tabs,padding=5);self.tabs.insert(1,self.final_tab,text='最终检测 / 复检')
        self.final_caption=tk.StringVar(master=root,value='冻结组合 '+PARAMETER_FREEZE_ID+' · 检测弱5.2/强12 · 复检原片55%/端点28%；当前模式'+self.hardware_mode)
        top=ttk.Frame(self.final_tab);top.pack(fill='x')
        ttk.Button(top,text='打开已有采集并检测',command=self.choose_capture).pack(side='left')
        ttk.Button(top,text='打开已有B1结果并处理',command=self.choose_b1).pack(side='left',padx=4)
        ttk.Button(top,text='重开一体化结果',command=self.choose_final).pack(side='left')
        ttk.Button(top,text='导入0109实板结果',command=self.choose_0109).pack(side='left',padx=3)
        self.pipeline_stop=ttk.Button(top,text='停止分析',command=self.stop,state='disabled');self.pipeline_stop.pack(side='left',padx=4)
        ttk.Button(top,text='打开结果目录',command=self.open_final_folder).pack(side='right')
        ttk.Button(top,text='详细报告 / 人工复核',command=self.open_report).pack(side='right')
        ttk.Label(self.final_tab,textvariable=self.final_caption,wraplength=1250).pack(fill='x',pady=5)
        self.performance_caption=tk.StringVar(master=root,value='性能分段将在完成处理后显示；沿用冻结算法。')
        ttk.Label(self.final_tab,textvariable=self.performance_caption,wraplength=1250).pack(fill='x',pady=2)
        pane=ttk.Panedwindow(self.final_tab,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane,width=290);right=ttk.Frame(pane);pane.add(left,weight=1);pane.add(right,weight=4)
        self.final_images=tk.Listbox(left,width=36,height=12,exportselection=False);self.final_images.pack(fill='both',expand=True);self.final_images.bind('<<ListboxSelect>>',self.select_final_image)
        ttk.Label(left,text='局部复检：高/中优先级与证据支持分').pack(anchor='w',pady=5)
        self.review_table=ttk.Treeview(left,columns=('priority','score'),show='tree headings',height=5);self.review_table.heading('#0',text='框');self.review_table.column('#0',width=60)
        for name,title in [('priority','优先级'),('score','证据分')]:self.review_table.heading(name,text=title);self.review_table.column(name,width=70)
        self.review_table.pack(fill='x');self.review_table.bind('<<TreeviewSelect>>',self.select_review)
        ttk.Label(left,text='黄色：正式检测\n橙框：疑似漏段，建议人工复检\n分数为规则证据刻度，非正确概率\n无框也不自动判定合格',wraplength=280).pack(fill='x',pady=6)
        bar=ttk.Frame(right);bar.pack(fill='x');self.final_view=Viewport(right)
        ttk.Button(bar,text='适应窗口',command=self.final_view.fit).pack(side='left')
        ttk.Button(bar,text='100%',command=lambda:self.final_view.set_zoom(1)).pack(side='left',padx=4)
        ttk.Label(bar,text='滚轮缩放，左键拖动；查看原尺寸细节').pack(side='left')
        ttk.Button(bar,text='性能分段记录',command=self.open_performance).pack(side='right')
        self.final_view.pack(fill='both',expand=True)
        self.engineering_tab=ttk.Frame(self.tabs,padding=15);self.tabs.add(self.engineering_tab,text='0109工程验收')
        ttk.Label(self.engineering_tab,text='0109独立候选：新增人工曝光配置和器件分段计数；尚待本版实板验收。',wraplength=1050).pack(anchor='w',pady=8)
        ttk.Label(self.engineering_tab,text='新摆放：先用0109拍1张定位图并确认新ROI，再开始正式8帧；保持原摆放时也可复用对应采集组的ROI和mask。',wraplength=1050).pack(anchor='w',pady=6)
        identity=ttk.Frame(self.engineering_tab);identity.pack(fill='x',pady=5)
        ttk.Label(identity,text='本次样品名').pack(side='left');ttk.Entry(identity,textvariable=self.sample,width=24).pack(side='left',padx=5)
        ttk.Label(identity,text='面/阶段').pack(side='left');ttk.Entry(identity,textvariable=self.variant,width=12).pack(side='left',padx=5)
        options=ttk.Frame(self.engineering_tab);options.pack(fill='x',pady=5)
        self.capture_format=tk.StringVar(master=root,value='RGB+灰度审计')
        ttk.Label(options,text='正式帧保存').pack(side='left')
        ttk.Combobox(options,textvariable=self.capture_format,values=('RGB+灰度审计','灰度证据候选'),state='readonly',width=20).pack(side='left',padx=5)
        self.full_evidence_audit=tk.BooleanVar(master=root,value=False)
        ttk.Checkbutton(options,text='采后每次完整重算核验（较慢）',variable=self.full_evidence_audit).pack(side='left',padx=5)
        ttk.Label(self.engineering_tab,text='两种模式都保留八帧gray/SAT证据。正式默认400/800；其他曝光作为开发对照。',wraplength=1050).pack(anchor='w')
        self.position0109_button=ttk.Button(self.engineering_tab,text='新摆放：1张定位并准备计划',command=self.start_position0109);self.position0109_button.pack(anchor='w',pady=8)
        self.focus0109_button=ttk.Button(self.engineering_tab,text='0109实时调焦（2帧/秒，鼠标拖框）',command=self.start_focus0109);self.focus0109_button.pack(anchor='w',pady=5)
        self.engineering_plan=tk.StringVar(master=root)
        line=ttk.Frame(self.engineering_tab);line.pack(fill='x',pady=8)
        ttk.Button(line,text='从当前采集组准备计划',command=self.prepare_0109).pack(side='left')
        ttk.Button(line,text='选择已准备的PLAN.json',command=self.choose_0109_plan).pack(side='left',padx=5)
        ttk.Entry(self.engineering_tab,textvariable=self.engineering_plan).pack(fill='x',pady=5)
        ttk.Button(self.engineering_tab,text='确认已下载0109并开始8帧工程验收',command=self.start_0109_capture).pack(anchor='w',pady=10)
        ttk.Button(self.engineering_tab,text='停止并关灯、保留记录',command=self.stop).pack(anchor='w')
        self.capture_bars=[self.start_button.master,self.low_spin.master,self.margin_spin.master,self.analysis_button.master,self.focus_button.master]
        self.capture_pack_info=[w.pack_info() for w in self.capture_bars]
        self.capture_status_label=next(w for w in self.tabs.master.winfo_children() if isinstance(w,ttk.Label) and str(w.cget('textvariable'))==str(self.status))
        navigation=ttk.Frame(self.tabs.master);navigation.pack(before=self.capture_status_label,fill='x',pady=3)
        ttk.Button(navigation,text='0109操作台：调焦 / 新定位 / 八帧验收',command=lambda:self.tabs.select(self.engineering_tab)).pack(side='left')
        ttk.Button(navigation,text='查看检测与复检结果',command=lambda:self.tabs.select(self.final_tab)).pack(side='left',padx=5)
        self.capture_controls_hidden=False
        self.tabs.bind('<<NotebookTabChanged>>',self.layout_mode,add='+')
        self.status.set('就绪：预览/采集使用原r5.6链路，采后自动运行冻结检测和复检。启动不连接板卡。')
        self.confirm_default_text=str(self.confirm_button.cget('text'))
        if self.hardware_mode=='0109':
            self.start_button.configure(text='0109新定位（1张）');self.focus_button.configure(text='0109手动调焦（鼠标拖框）')
            self.tabs.select(self.engineering_tab);self.layout_mode()
            self.status.set('0109工程入口就绪；先调焦，再单张定位和八帧验收。启动尚未查询板卡。')
    def layout_mode(self,event=None):
        hide=self.tabs.select() in (str(self.final_tab),str(self.engineering_tab))
        if hide==self.capture_controls_hidden:return
        for widget,info in zip(self.capture_bars,self.capture_pack_info):
            if hide:widget.pack_forget()
            else:widget.pack(before=self.capture_status_label,**info)
        self.capture_controls_hidden=hide
    def busy(self):return self.pipeline_busy or self.capture_handoff is not None or super().busy()
    def set_busy(self,value):
        super().set_busy(value)
        if hasattr(self,'pipeline_stop'):self.pipeline_stop.configure(state='normal' if self.pipeline_busy else 'disabled')
    def preflight(self):
        if self.hardware_mode!='0109':return super().preflight()
        def work():
            from archive0109 import HOST,QUALIFICATION
            sys.path.insert(0,str(HOST));from qualification import validate
            validate(QUALIFICATION)
            return ('preflight','0109候选来源核验通过；可在本页调焦、新定位和八帧验收。尚未查询板卡。')
        self.dispatch(work)
    def start(self):
        if self.busy():return
        if self.hardware_mode=='0109':return self.start_position0109()
        self.auto_after_capture=self.auto_final.get();self.auto_analysis.set(False);super().start()
        if self.worker is None:self.auto_after_capture=False
    def start_focus(self):
        if self.hardware_mode=='0109':return self.start_focus0109()
        return super().start_focus()
    def start_focus0109(self):
        if self.busy():return
        settings=self.settings_from_ui()
        if settings is None:return
        from fast_focus import LatestFrame
        self.focus_mailbox=LatestFrame();self.focus_mode=True;self.selection_active=False;self.current_frame=None;self.focus_roi=None;self.focus_tracker.reset();self.focus_last_time=None
        self.focus_latest_data=None;self.focus_remeasure_pending=False;self.focus_display_fps=None
        self.session_root=legacy_location('E:/GuangjianData/final0109_focus')/('FOCUS_'+settings.specimen+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+__import__('uuid').uuid4().hex[:8])
        self.tabs.select(self.image_tab)
        def work():
            import focus0109
            bridge=focus0109.load_bridge();self.focus_session=bridge.FocusSession(self.cancel,self.notify)
            runtime=focus0109.Runtime(settings.specimen,settings.variant,'focus0109_'+self.session_root.name,self.cancel,self.notify,settings=settings)
            return ('focus',self.focus_session.run(self.session_root,settings.specimen,runtime=runtime))
        self.dispatch(work)
    def observe_capture_event(self,kind,value):
        if kind=='error':self.auto_after_capture=False
        if kind!='done' or not value or value[0]!='capture':return
        wanted=self.auto_after_capture;self.auto_after_capture=False;result,data=value[1:]
        if wanted and data and data.get('input_ready') and result['receipt']['status']=='P0_PAIR_READY_FOR_LABEL_REVIEW' and not self.closing:
            self.capture_handoff=self.root.after_idle(lambda:self.start_pipeline(data['root'],'capture'))
    def run_current(self):
        if self.catalogue and self.catalogue.get('input_ready'):self.start_pipeline(self.catalogue['root'],'capture')
    def choose_capture(self):
        if self.busy():return
        source=filedialog.askdirectory(title='选择完整P0采集组、GUI目录或pair目录',initialdir=str(self.result_root))
        if source:self.start_pipeline(source,'capture')
    def choose_b1(self):
        if self.busy():return
        source=filedialog.askdirectory(title='选择含summary.json的完整B1Detection结果',initialdir=str(legacy_location('E:/GuangjianData/B1Detection')))
        if source:self.start_pipeline(source,'b1')
    def choose_0109(self):
        if self.busy():return
        source=filedialog.askdirectory(title='选择0109工程实板验收的fusion目录',initialdir=str(legacy_location('E:/GuangjianData')))
        if source:self.start_pipeline(source,'0109')
    def choose_0109_plan(self):
        if self.busy():return
        path=filedialog.askopenfilename(title='选择已核对的0109工程PLAN.json',initialdir=str(legacy_location('E:/GuangjianData')),filetypes=[('JSON','*.json')])
        if path:self.engineering_plan.set(path)
    def start_position0109(self):
        if self.busy():return
        settings=self.settings_from_ui()
        if settings is None:return
        if not messagebox.askyesno('0109单张定位','请确认已下载0109候选bit，固定本次工件、相机和灯位。此步只拍1张600行定位图并关灯，随后在原图页确认ROI；不会自动拍正式8张。',parent=self.root):return
        self.pipeline_busy=True;self.pipeline_cancel=threading.Event();self.cancel=self.pipeline_cancel;self.location0109_active=True;self.set_busy(True)
        self.confirm_button.configure(text='确认新ROI并生成0109计划（此步不拍8张）')
        self.session_root=legacy_location('E:/GuangjianData/final0109_positioning')/(time.strftime('%Y%m%d_%H%M%S')+'_'+__import__('uuid').uuid4().hex[:8])
        self.status.set('0109单张定位开始；首次全幅mask上传较慢，请等待。')
        sample,variant=settings.specimen,settings.variant;pose=sample+'_'+variant+'_'+self.session_root.name
        def task():
            try:
                from location0109 import capture_preview,prepare_selection
                receipt=capture_preview(self.session_root,sample,pose,self.pipeline_cancel,notify=lambda s:self.pipeline_events.put(('log',s)))
                selection=self.selector(pipeline.read(receipt)['png'],sample,variant)
                plan=prepare_selection(receipt,selection['points'],selection['margin_px'])
                self.pipeline_events.put(('located',str(plan)))
            except BaseException as exc:self.pipeline_events.put(('failed',str(exc)))
        self.pipeline_thread=threading.Thread(target=task,daemon=False);self.pipeline_thread.start()
    def prepare_0109(self):
        if self.busy():return
        if not self.catalogue or not self.catalogue.get('input_ready'):
            self.status.set('请先在定位/原图页离线打开一组完整采集，作为ROI与mask模板。');return
        from engineering0109 import prepare
        try:
            out=legacy_location('E:/GuangjianData/final0109_plans')/(time.strftime('%Y%m%d_%H%M%S')+'_'+__import__('uuid').uuid4().hex[:8])
            path=prepare(self.catalogue,out,pixel_format=self.capture_format_code());self.engineering_plan.set(str(path));self.status.set('0109计划已准备，尚未联系板卡：'+str(path))
        except Exception as exc:self.status.set('计划未准备：'+str(exc))
    def start_0109_capture(self):
        if self.busy():return
        plan=self.engineering_plan.get()
        if not plan or not Path(plan).is_file():self.status.set('先准备或选择PLAN.json');return
        try:
            from engineering0109 import plan_for_format
            plan=plan_for_format(plan,self.capture_format_code());self.engineering_plan.set(str(plan))
        except Exception as exc:self.status.set('采集格式计划未准备：'+str(exc));return
        if not messagebox.askyesno('0109工程实板验收','请确认已下载计划对应的0109候选bit，工件/相机/灯位与ROI模板保持一致，网口可用。先拍1张ROI准备帧（不计正式数据），再独立采8张正式图并关灯，随后自动检测与复检。',parent=self.root):return
        self.pipeline_busy=True;self.pipeline_cancel=threading.Event();self.set_busy(True);self.status.set('0109工程采集：1张ROI准备＋8张正式；保持摆放，停止会请求取消并关灯。')
        capture_started=time.perf_counter();validation_mode='audit' if self.full_evidence_audit.get() else 'reuse'
        def task():
            try:
                from engineering0109 import capture
                archive=capture(plan,self.pipeline_cancel,notify=lambda s:self.pipeline_events.put(('log',s)))
                cache_receipt=Path(archive).parent/'EVIDENCE_CACHE.json'
                effective_mode='audit' if cache_receipt.is_file() and pipeline.read(cache_receipt).get('status')=='FALL_BACK_TO_FULL_AUDIT' else validation_mode
                self.pipeline_events.put(('complete',pipeline.run(archive,'0109',self.analysis_root,cancel=self.pipeline_cancel,notify=lambda s:self.pipeline_events.put(('log',s)),validation_mode=effective_mode,capture_started=capture_started)))
            except BaseException as exc:self.pipeline_events.put(('failed',str(exc)))
        self.pipeline_thread=threading.Thread(target=task,daemon=False);self.pipeline_thread.start()
    def start_pipeline(self,source,kind):
        self.capture_handoff=None
        if self.busy() or self.closing:return
        self.pipeline_busy=True;self.pipeline_cancel=threading.Event();self.set_busy(True);self.tabs.select(self.final_tab);self.status.set('后台处理：输入核验 → 冻结检测 → 局部复检 → 归档')
        validation_mode='audit' if self.full_evidence_audit.get() else 'reuse'
        def task():
            try:self.pipeline_events.put(('complete',pipeline.run(source,kind,self.analysis_root,cancel=self.pipeline_cancel,notify=lambda s:self.pipeline_events.put(('log',s)),validation_mode=validation_mode)))
            except BaseException as exc:self.pipeline_events.put(('failed',str(exc)))
        self.pipeline_thread=threading.Thread(target=task,daemon=False);self.pipeline_thread.start()
    def poll(self):
        if hasattr(self,'pipeline_events'):
            start=time.monotonic()
            while time.monotonic()-start<.01:
                try:kind,value=self.pipeline_events.get_nowait()
                except queue.Empty:break
                if kind=='log':
                    self.status.set(value);self.log.insert('end',value+'\n');self.log.see('end')
                    if int(self.log.index('end-1c').split('.')[0])>350:self.log.delete('1.0','80.0')
                else:
                    self.pipeline_busy=False;self.pipeline_thread=None;self.set_busy(False)
                    if self.location0109_active:
                        self.location0109_active=False;self.confirm_button.configure(text=self.confirm_default_text);self.selection_active=False
                        self.confirm_button.configure(state='disabled');self.clear_button.configure(state='disabled')
                    if kind=='located':
                        self.engineering_plan.set(value);self.tabs.select(self.engineering_tab);self.status.set('新ROI已确认、计划已准备。保持摆放，点击开始8帧工程验收：'+value)
                    elif kind=='complete':
                        out,status=value
                        if status['status']=='COMPLETE':
                            try:self.load_final(out)
                            except Exception as exc:self.status.set('结果读取失败，记录已保留：'+str(exc))
                        else:self.status.set(status['status']+'：'+status.get('error','')+'；原采集保留')
                    else:self.status.set('处理未完成，记录已保留：'+value)
        super().poll()
    def load_final(self,path):
        path=Path(path).resolve();job=pipeline.read(path/'JOB.json')
        if job['status']!='COMPLETE':raise ValueError('Incomplete or cancelled result')
        manifest=pipeline.read(path/'OUTPUT_MANIFEST.json')['files_sha256']
        if hashlib.sha256((path/'RESULT.json').read_bytes()).hexdigest()!=manifest['RESULT.json']:raise ValueError('Final result changed')
        result=pipeline.read(path/'RESULT.json')
        version_label=result_version_label(result)
        self.final_result=result;self.final_path=path;self.final_images.delete(0,'end')
        for image in result['gallery']:self.final_images.insert('end',image['label'])
        self.review_table.delete(*self.review_table.get_children())
        for row in result['review_windows']:self.review_table.insert('','end',iid=str(row['id']),text='R'+str(row['id']),values=('高' if row['review_priority']=='high' else '中',row['evidence_support_score']))
        self.final_caption.set(f"{result['specimen']} | {result['low_lines']}/{result['high_lines']}行 | {version_label} | {len(result['review_windows'])}处复检提示 | {result['group_id']}")
        profile=path/'PERFORMANCE.json'
        if profile.is_file():
            perf=pipeline.read(profile);events=perf.get('events',[]);lookup={e['name']:e['seconds'] for e in events}
            self.performance_caption.set(f"本次处理 {perf['elapsed_seconds']:.2f}秒；输入核验 {lookup.get('native_input_validation',lookup.get('sealed_B1_input_validation_and_PC_fusion',0)):.2f}秒；检测+复检 {lookup.get('frozen_algorithm_compute',0):.2f}秒；"+perf.get('validation_mode','PC路径')+'（非FPGA纯计算时间）')
        else:self.performance_caption.set('历史结果没有性能分段记录。')
        self.status.set('检测与复检已保存：'+str(path));self.tabs.select(self.final_tab);self.final_images.selection_set(0);self.select_final_image()
    def select_final_image(self,event=None):
        if self.final_result is None:return
        selected=self.final_images.curselection()
        if not selected:return
        row=self.final_result['gallery'][selected[0]];p=Path(row['path'])
        try:
            if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Image changed')
            with Image.open(p) as image:self.final_view.load(image)
        except Exception as exc:self.status.set('图像未打开：'+str(exc))
    def select_review(self,event=None):
        selected=self.review_table.selection()
        if not selected or not self.final_result:return
        prefix='复检R'+selected[0]+' / '
        for i,row in enumerate(self.final_result['gallery']):
            if row['label'].startswith(prefix):self.final_images.selection_clear(0,'end');self.final_images.selection_set(i);self.select_final_image();break
    def choose_final(self):
        if self.busy():return
        path=filedialog.askdirectory(title='选择含RESULT.json的一体化结果',initialdir=str(self.analysis_root))
        if path:
            try:self.load_final(path)
            except Exception as exc:messagebox.showerror('光鉴',str(exc),parent=self.root)
    def open_final_folder(self):
        if self.final_path:os.startfile(str(self.final_path))
    def open_report(self):
        if self.final_result:os.startfile(self.final_result['html'])
    def open_performance(self):
        if self.final_path and (self.final_path/'PERFORMANCE.html').is_file():os.startfile(str(self.final_path/'PERFORMANCE.html'))
    def capture_format_code(self):
        return {'RGB+灰度审计':50,'灰度证据候选':49}[self.capture_format.get()]
    def stop(self):self.pipeline_cancel.set();super().stop()
    def destroy_ui(self):
        if self.capture_handoff:
            try:self.root.after_cancel(self.capture_handoff)
            except tk.TclError:pass
        if hasattr(self,'final_view') and self.final_view.pending:
            try:self.final_view.after_cancel(self.final_view.pending)
            except tk.TclError:pass
        super().destroy_ui()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true');parser.add_argument('--open-result',type=Path);parser.add_argument('--engineering-plan',type=Path);parser.add_argument('--hardware-mode',choices=('0107','0109'),default='0107');a=parser.parse_args();report=verify_dependencies();report['selected_hardware_mode']=a.hardware_mode
    if a.check_only:print(json.dumps(report));raise SystemExit(0)
    try:
        if os.name=='nt':
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError,OSError):pass
    root=tk.Tk();application=UnifiedApp(root,hardware_mode=a.hardware_mode)
    if a.engineering_plan:application.engineering_plan.set(str(a.engineering_plan.resolve()))
    if a.open_result:root.after(180,lambda:application.load_final(a.open_result))
    root.mainloop()
