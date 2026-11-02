"""光鉴P0配对控制台；参考09操作结构，保持原09完整不变。"""
import argparse
import json
import math
import os
import queue
import threading
import time
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog,ttk
from PIL import Image,ImageDraw,ImageOps,ImageTk
import console_workflow as workflow
import focus_tools
from fast_focus import FocusSession,DEFAULT_MAX_FRAMES,LatestFrame
import auto_location
import roi_geometry
from capture_settings import CaptureSettings

PHASES={'preview':'正在拍定位预览；首次mask约45秒，请保持摆放',
        'focus_preview':'快速灰度调焦：目标2帧/秒，左右同帧；先确认相机和灯光，无需上传板面mask',
        'focus_finishing':'调焦结束，正在关灯和保存轻量日志；预览不作正式配对图',
        'select_board':'请核对自动板面轮廓；正确则直接确认，不正确可清空后沿内缘点4角',
        'capture_eight':'正在连续采集八张正式RGB图，组内请勿移动',
        'export':'八张已保存并关灯，正在导出/归档，停止不会重拍',
        'compare_eight':'原始八帧已归档，正在生成带实际曝光标签的八张对比文件夹',
        'analysis':'离线生成低/高/等权证据，不连接板卡，可停止并保留八帧'}

class ConsoleApp:
    def __init__(self,root,result_root=None,preflight=True):
        self.root=root;self.result_root=Path(result_root) if result_root is not None else workflow.default_result_root()
        self.events=queue.Queue();self.focus_mailbox=LatestFrame();self.cancel=threading.Event();self.worker=None;self.closing=False
        self.selection_ready=threading.Event();self.selection_active=False;self.selected_points=[];self.selection_answer=None
        self.source_image=None;self.photo=None;self.image_path=None;self.image_origin=(0,0);self.zoom=None;self.scale=1.;self.current_frame=None
        self.render_id=None;self.image_item=None;self.view_geometry=None;self.scroll_fractions={};self.render_count=0;self.render_stats=None
        self.frames={};self.catalogue=None;self.session_root=None;self.analysis_path=None;self.history_paths={}
        self.focus_session=None;self.focus_mode=False;self.focus_roi=None;self.focus_version=0;self.focus_drag_start=None;self.focus_tracker=focus_tools.Tracker();self.focus_photo=None;self.focus_image=None;self.focus_frame_path=None;self.focus_last_time=None
        self.focus_latest_data=None;self.focus_remeasure_pending=False;self.focus_display_fps=None
        root.title('光鉴 · 0107 低/高曝光ROI采集控制台 r5.6');root.geometry('1320x940');root.minsize(1050,780)
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.configure('TLabel',font=('Microsoft YaHei UI',10));style.configure('TButton',font=('Microsoft YaHei UI',10),padding=5)
        outer=ttk.Frame(root,padding=10);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='光鉴  /  定位 → 板面确认 → 四方向低/高8帧 → 原图与离线证据',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
        ttk.Label(outer,text='原09保留 · 要求已加载0107 · 本轮低/高曝光可设置 · 固定1倍增益/LED128 · 未标注，不作合格判定').pack(anchor='w',pady=(4,8))
        top=ttk.Frame(outer);top.pack(fill='x')
        ttk.Label(top,text='样品名').pack(side='left')
        self.sample=tk.StringVar(value='sample004');self.sample_box=ttk.Combobox(top,textvariable=self.sample,values=['sample001','sample002','sample003','sample004','sample005','sample006'],state='normal',width=15);self.sample_box.pack(side='left',padx=4)
        self.start_button=ttk.Button(top,text='定位并采集本组',command=self.start);self.start_button.pack(side='left')
        self.stop_button=ttk.Button(top,text='停止、关灯并保留',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=6)
        self.off_button=ttk.Button(top,text='单独关灯',command=self.lights_off);self.off_button.pack(side='left')
        self.open_button=ttk.Button(top,text='离线打开P0 ZIP/目录',command=self.open_existing);self.open_button.pack(side='right')
        settingsbar=ttk.Frame(outer);settingsbar.pack(fill='x',pady=(5,0))
        ttk.Label(settingsbar,text='面/阶段').pack(side='left');self.variant=tk.StringVar(value='A_v1')
        self.variant_box=ttk.Combobox(settingsbar,textvariable=self.variant,values=['A_v0','A_v1','B_v0','B_v1'],width=8,state='normal');self.variant_box.pack(side='left',padx=4)
        self.low_lines=tk.StringVar(value='400');self.high_lines=tk.StringVar(value='800')
        ttk.Label(settingsbar,text='低曝光（行）').pack(side='left');self.low_spin=ttk.Spinbox(settingsbar,from_=1,to=1116,textvariable=self.low_lines,width=6);self.low_spin.pack(side='left',padx=4)
        ttk.Label(settingsbar,text='高曝光（行）').pack(side='left');self.high_spin=ttk.Spinbox(settingsbar,from_=1,to=1116,textvariable=self.high_lines,width=6);self.high_spin.pack(side='left',padx=4)
        ttk.Label(settingsbar,text='低＜高；1～1116行；定位/调焦取中值。样品名用英文/数字/_/-。').pack(side='left',padx=6)
        marginbar=ttk.Frame(outer);marginbar.pack(fill='x',pady=(4,0))
        ttk.Label(marginbar,text='板外余量（原图像素）').pack(side='left');self.margin=tk.StringVar(value='16')
        self.margin_spin=ttk.Spinbox(marginbar,from_=16,to=256,increment=1,textvariable=self.margin,width=6);self.margin_spin.pack(side='left',padx=5)
        ttk.Label(marginbar,text='16～256，可直接输入；向外对齐分块网格，不旋转、不取正').pack(side='left')
        options=ttk.Frame(outer);options.pack(fill='x',pady=5)
        self.auto_analysis=tk.BooleanVar(value=False);self.auto_check=ttk.Checkbutton(options,text='采后生成三种离线证据（较慢，可稍后做）',variable=self.auto_analysis);self.auto_check.pack(side='left')
        self.analysis_button=ttk.Button(options,text='生成/重做离线证据',command=self.analyze,state='disabled');self.analysis_button.pack(side='left',padx=5)
        self.reexport_button=ttk.Button(options,text='重新导出已有8帧（不重拍）',command=self.reexport,state='disabled');self.reexport_button.pack(side='left')
        self.compare_button=ttk.Button(options,text='查看八张对比',command=self.open_compare,state='disabled');self.compare_button.pack(side='left',padx=5)
        ttk.Button(options,text='打开本轮目录',command=self.open_folder).pack(side='right')
        focusbar=ttk.Frame(outer);focusbar.pack(fill='x',pady=(0,5))
        self.focus_button=ttk.Button(focusbar,text='手动调焦预览（鼠标拖框）',command=self.start_focus);self.focus_button.pack(side='left')
        self.pause_focus_button=ttk.Button(focusbar,text='暂停调焦',command=self.pause_focus,state='disabled');self.pause_focus_button.pack(side='left',padx=5)
        self.focus_text=tk.StringVar(value='清晰度：—   本次最佳：—   同一区域/曝光/光照下作相对比较')
        ttk.Label(focusbar,textvariable=self.focus_text,foreground='#125a7a').pack(side='left',padx=5)
        ttk.Button(focusbar,text='清除最佳',command=self.reset_focus_best).pack(side='right')
        self.status=tk.StringVar(value='就绪；数据目录：'+str(self.result_root)+'。004/005已保留，启动不联系板卡。')
        ttk.Label(outer,textvariable=self.status,wraplength=1250,foreground='#125a7a').pack(fill='x',pady=4)
        self.progress=ttk.Progressbar(outer,maximum=8);self.progress.pack(fill='x',pady=(0,6))
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        self.image_tab=ttk.Frame(self.tabs);self.evidence_tab=ttk.Frame(self.tabs);self.log_tab=ttk.Frame(self.tabs);self.history_tab=ttk.Frame(self.tabs)
        for widget,label in [(self.image_tab,'定位 / 八帧原图与风险'),(self.evidence_tab,'低 / 高 / 等权证据'),(self.log_tab,'过程、错误与读回'),(self.history_tab,'历史结果')]:self.tabs.add(widget,text=label)
        pane=ttk.Panedwindow(self.image_tab,orient='horizontal');pane.pack(fill='both',expand=True)
        sidebar=ttk.Frame(pane,width=350);viewer=ttk.Frame(pane);pane.add(sidebar,weight=1);pane.add(viewer,weight=4)
        sidecanvas=tk.Canvas(sidebar,width=350,highlightthickness=0);sidecanvas.pack(side='left',fill='both',expand=True)
        sidescroll=ttk.Scrollbar(sidebar,orient='vertical',command=sidecanvas.yview);sidescroll.pack(side='right',fill='y');sidecanvas.configure(yscrollcommand=sidescroll.set)
        left=ttk.Frame(sidecanvas);sidewindow=sidecanvas.create_window(0,0,window=left,anchor='nw')
        left.bind('<Configure>',lambda e:sidecanvas.configure(scrollregion=sidecanvas.bbox('all')))
        sidecanvas.bind('<Configure>',lambda e:sidecanvas.itemconfigure(sidewindow,width=e.width))
        self.table=ttk.Treeview(left,columns=('lines','gain','LED','frame'),show='tree headings',height=10)
        self.table.heading('#0',text='方向 / 曝光');self.table.column('#0',width=110)
        for name,label,width in [('lines','行',48),('gain','倍',40),('LED','LED',44),('frame','帧号',58)]:self.table.heading(name,text=label);self.table.column(name,width=width)
        self.table.pack(fill='x');self.table.bind('<<TreeviewSelect>>',self.choose_frame)
        self.frame_info=tk.StringVar(value='尚无正式图；每组1张定位预览＋8张正式图。')
        ttk.Label(left,textvariable=self.frame_info,wraplength=325).pack(fill='x',pady=8)
        self.focus_crop_label=ttk.Label(left,text='调焦局部：开始调焦后在全景定位图拖框');self.focus_crop_label.pack(fill='x',pady=4)
        self.focus_details=tk.StringVar(value='调焦分数不作检测置信度。');ttk.Label(left,textvariable=self.focus_details,wraplength=325).pack(fill='x')
        ttk.Button(left,text='调焦局部100%查看',command=self.focus_detail).pack(fill='x',pady=3)
        self.view=tk.StringVar(value='彩色原图');self.view_box=ttk.Combobox(left,textvariable=self.view,values=['彩色原图','同帧灰度','SAT风险'],state='readonly');self.view_box.pack(fill='x');self.view_box.bind('<<ComboboxSelected>>',lambda e:self.choose_frame())
        self.brighten=tk.BooleanVar(value=False);self.mask_visible=tk.BooleanVar(value=True)
        ttk.Checkbutton(left,text='仅显示提亮（不改原图）',variable=self.brighten,command=self.render).pack(anchor='w')
        ttk.Checkbutton(left,text='显示板面有效边界',variable=self.mask_visible,command=self.render).pack(anchor='w')
        ttk.Label(left,text='优先自动定位板面，请核对黄色轮廓和绿色传输ROI。失败/不正确时清空重选4角，右键撤销；组内不移动。仅定位留全幅，正式8张传ROI原始像素。',wraplength=325).pack(fill='x',pady=8)
        self.roi_info=tk.StringVar(value='板外余量可在确认前调整；工件轻微倾斜如实保留。');ttk.Label(left,textvariable=self.roi_info,wraplength=325).pack(fill='x')
        self.confirm_button=ttk.Button(left,text='确认板号/板面未动，开始8张',command=self.confirm_selection,state='disabled');self.confirm_button.pack(fill='x')
        self.clear_button=ttk.Button(left,text='清空四角重选',command=self.clear_selection,state='disabled');self.clear_button.pack(fill='x',pady=4)
        ttk.Button(left,text='导出读回表CSV',command=self.export_csv).pack(fill='x',pady=4)
        bar=ttk.Frame(viewer);bar.pack(fill='x')
        for label,value in [('适应窗口',None),('100%',1.),('50%',.5),('200%',2.)]:ttk.Button(bar,text=label,command=lambda z=value:self.set_zoom(z)).pack(side='left')
        self.zoom_text=tk.StringVar(value='');ttk.Label(bar,textvariable=self.zoom_text).pack(side='left',padx=5)
        ttk.Button(bar,text='保存当前显示（另存副本）',command=self.save_view).pack(side='right')
        area=ttk.Frame(viewer);area.pack(fill='both',expand=True);area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(area,background='#24292f',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        self.vertical=ttk.Scrollbar(area,orient='vertical',command=self.scroll_y);self.vertical.grid(row=0,column=1,sticky='ns')
        self.horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.scroll_x);self.horizontal.grid(row=1,column=0,sticky='ew')
        self.canvas.configure(xscrollcommand=lambda a,b:self.scrolled('x',a,b),yscrollcommand=lambda a,b:self.scrolled('y',a,b))
        self.canvas.bind('<Button-1>',self.click);self.canvas.bind('<Button-3>',self.undo);self.canvas.bind('<Configure>',lambda e:self.render())
        self.canvas.bind('<B1-Motion>',self.focus_drag);self.canvas.bind('<ButtonRelease-1>',self.finish_focus_drag)
        self.canvas.bind('<MouseWheel>',self.wheel);self.canvas.bind('<Button-4>',self.wheel);self.canvas.bind('<Button-5>',self.wheel)
        self.canvas.bind('<ButtonPress-2>',lambda e:self.canvas.scan_mark(e.x,e.y));self.canvas.bind('<B2-Motion>',self.pan)
        self.canvas.bind('<Motion>',self.pixel);self.pixel_text=tk.StringVar(value='坐标为保存原图像素');ttk.Label(viewer,textvariable=self.pixel_text).pack(anchor='w')
        self.evidence_body=ttk.Frame(self.evidence_tab,padding=8);self.evidence_body.pack(fill='both',expand=True);self.evidence_photos=[]
        ttk.Label(self.evidence_body,text='仅显示低曝光、高曝光、等权的离线证据。没有已训练global/gate，不显示置信概率或合格结论。',wraplength=1150).pack(anchor='w')
        self.log=tk.Text(self.log_tab,wrap='word',font=('Consolas',10));self.log.pack(fill='both',expand=True)
        self.history=ttk.Treeview(self.history_tab,columns=('state',),show='tree headings');self.history.heading('#0',text='结果目录');self.history.heading('state',text='记录状态');self.history.pack(fill='both',expand=True)
        self.history.bind('<Double-1>',self.open_history)
        ttk.Button(self.history_tab,text='刷新历史列表',command=self.refresh_history).pack(anchor='w')
        ttk.Label(outer,text='新入口为开发采集。SAT是源RGB最大码风险；算法证据不是标注真值。停止/关窗会先请求取消、关灯和保存，勿强制杀进程。',wraplength=1250).pack(anchor='w',pady=(6,0))
        self.poll_id=root.after(80,self.poll)
        self.margin.trace_add('write',lambda *args:self.render())
        if preflight:root.after(100,self.preflight)

    def notify(self,event,**details):
        if event=='focus_live_frame':
            if self.focus_mailbox.put(details):self.events.put(('notice',('focus_live_ready',{})))
        else:self.events.put(('notice',(event,details)))
    def busy(self):return self.worker is not None
    def set_busy(self,value):
        for widget in (self.start_button,self.off_button,self.open_button,self.auto_check,self.focus_button):widget.configure(state='disabled' if value else 'normal')
        self.pause_focus_button.configure(state='normal' if value and self.focus_mode else 'disabled')
        self.margin_spin.configure(state='normal' if not value or self.selection_active else 'disabled')
        for widget in (self.sample_box,self.variant_box,self.low_spin,self.high_spin):widget.configure(state='disabled' if value else 'normal')
        self.stop_button.configure(state='normal' if value else 'disabled')
        ready=self.catalogue is not None and self.catalogue['input_ready'];recoverable=self.catalogue is not None and self.catalogue['raw_eight_recoverable']
        self.analysis_button.configure(state='normal' if ready and not value else 'disabled');self.reexport_button.configure(state='normal' if recoverable and not value else 'disabled')
        self.compare_button.configure(state='normal' if ready and not value else 'disabled')
    def dispatch(self,job):
        if self.busy():return
        self.cancel=threading.Event();self.set_busy(True)
        def task():
            try:self.events.put(('done',job()))
            except BaseException as exc:self.events.put(('error',str(exc)))
        self.worker=threading.Thread(target=task,daemon=False);self.worker.start()
    def preflight(self):
        settings=self.settings_from_ui()
        if settings is None:return
        specimen=settings.specimen
        def work():
            workflow.verify_bundle();runtime=workflow.Runtime(specimen,settings.variant,'offline_preflight',self.cancel,self.notify,settings=settings)
            workflow.backend.plan_for(runtime,preview=True)
            return ('preflight','离线来源/固件检查通过；可输入真实样品名、面/阶段和低高曝光。已有004/005保留，尚未查询板卡。')
        self.dispatch(work)
    def settings_from_ui(self):
        try:return CaptureSettings.from_text(self.sample.get(),self.variant.get(),self.low_lines.get(),self.high_lines.get())
        except ValueError as exc:self.status.set('设置未通过，尚未采集：'+str(exc));return None
    def start(self):
        if self.busy():return
        settings=self.settings_from_ui()
        if settings is None:return
        specimen=settings.specimen;automatic=self.auto_analysis.get();self.catalogue=None;self.frames={};self.table.delete(*self.table.get_children());self.progress['value']=0
        self.session_root=self.result_root/('GUI_'+specimen+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        self.status.set(f'开始新组：{specimen} {settings.variant}；{settings.low}/{settings.high}行；保持镜头/板/灯不动。')
        def work():
            result=workflow.run_capture(self.session_root,specimen,self.cancel,self.selector,self.notify,automatic,settings=settings)
            path=self.session_root/'pair';catalogue=workflow.catalog(path,full_verify=False) if (path/'output_manifest.json').exists() else None
            return ('capture',result,catalogue)
        self.dispatch(work)
    def start_focus(self):
        if self.busy():return
        settings=self.settings_from_ui()
        if settings is None:return
        specimen=settings.specimen;self.focus_mailbox=LatestFrame();self.focus_mode=True;self.selection_active=False;self.current_frame=None;self.focus_roi=None;self.focus_tracker.reset();self.focus_last_time=None
        self.focus_latest_data=None;self.focus_remeasure_pending=False;self.focus_display_fps=None
        self.session_root=self.result_root/'focus'/('FOCUS_'+specimen+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        def work():
            self.focus_session=FocusSession(self.cancel,self.notify)
            runtime=workflow.Runtime(specimen,settings.variant,'fast_focus_'+uuid.uuid4().hex[:8],self.cancel,self.notify,settings=settings)
            return ('focus',self.focus_session.run(self.session_root,specimen,runtime=runtime))
        self.dispatch(work)
    def pause_focus(self):
        if self.focus_session is None:return
        paused=self.focus_session.toggle_pause();self.pause_focus_button.configure(text='继续调焦' if paused else '暂停调焦')
        self.status.set('暂停请求：当前帧结束后关灯；可重新拖框。' if paused else '继续同曝光调焦；缓慢转镜头，观察局部及分数。')
    def reset_focus_best(self):
        self.focus_tracker.reset();self.focus_text.set('清晰度：等待下一帧   本次最佳：—')
    def selector(self,png,specimen,variant):
        self.selection_ready.clear();self.selection_answer=None
        candidate=auto_location.propose(png)
        if self.session_root is not None:workflow.write(self.session_root/'auto_location.json',candidate)
        self.notify('selection',png=str(png),specimen=specimen,variant=variant,candidate=candidate)
        while not self.selection_ready.wait(.15):
            if self.cancel.is_set():raise InterruptedError('Operator cancelled before formal capture')
        if self.cancel.is_set() or self.selection_answer is None:raise InterruptedError('Operator cancelled before formal capture')
        return self.selection_answer
    def confirm_selection(self):
        if not self.selection_active or self.source_image is None:return
        try:
            workflow.backend.polygon_mask(self.selected_points,self.source_image.size)
            geometry=roi_geometry.build(self.selected_points,self.source_image.size,int(self.margin.get()))
        except ValueError as exc:self.status.set('请重新选板面：'+str(exc));return
        self.selection_answer=dict(points=list(self.selected_points),margin_px=geometry['requested_margin_px']);self.selection_active=False;self.margin_spin.configure(state='disabled');self.confirm_button.configure(state='disabled');self.clear_button.configure(state='disabled');self.selection_ready.set()
    def clear_selection(self):self.selected_points=[];self.render()
    def click(self,event):
        if self.focus_mode and self.source_image is not None:
            self.focus_drag_start=(self.canvas.canvasx(event.x)/self.scale,self.canvas.canvasy(event.y)/self.scale)
            return
        if not self.selection_active or self.source_image is None or len(self.selected_points)>=4:return
        x=self.canvas.canvasx(event.x)/self.scale;y=self.canvas.canvasy(event.y)/self.scale
        if 0<=x<self.source_image.width and 0<=y<self.source_image.height:self.selected_points.append((x,y));self.render()
    def undo(self,event=None):
        if self.selection_active and self.selected_points:self.selected_points.pop();self.render()
    def set_zoom(self,value):self.zoom=value;self.render()
    def wheel(self,event):
        if self.source_image is None:return 'break'
        delta=1 if getattr(event,'num',None)==4 else -1 if getattr(event,'num',None)==5 else getattr(event,'delta',0)/120
        if not delta:return 'break'
        delta=max(-20,min(20,delta))
        old=self.scale;new=max(.05,min(4.,old*1.2**delta))
        left,top=focus_tools.anchored_scroll(old,new,self.canvas.canvasx(0),self.canvas.canvasy(0),(event.x,event.y),self.source_image.size,(self.canvas.winfo_width(),self.canvas.winfo_height()))
        self.zoom=new;self.render();self.canvas.xview_moveto(left/(self.source_image.width*new));self.canvas.yview_moveto(top/(self.source_image.height*new))
        self.pixel(event);return 'break'
    def focus_drag(self,event):
        if not self.focus_mode or self.focus_drag_start is None:return
        x,y=self.focus_drag_start;self.canvas.delete('focus_drag')
        self.canvas.create_rectangle(x*self.scale,y*self.scale,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y),outline='#ffe000',width=2,tags='focus_drag')
    def finish_focus_drag(self,event):
        if not self.focus_mode or self.focus_drag_start is None or self.source_image is None:return
        try:
            roi=focus_tools.rectangle(self.focus_drag_start,(self.canvas.canvasx(event.x)/self.scale,self.canvas.canvasy(event.y)/self.scale),self.source_image.size)
            self.apply_focus_roi(roi)
        except ValueError as exc:self.status.set(str(exc))
        finally:self.focus_drag_start=None;self.canvas.delete('focus_drag')
    def apply_focus_roi(self,roi):
        self.focus_roi=tuple(roi);self.focus_tracker.reset()
        if self.focus_session:self.focus_version=self.focus_session.set_roi(roi)
        self.focus_text.set(f'选区 {roi[2]}×{roi[3]}，等待新帧；本次最佳已重置')
        self.focus_remeasure_pending=self.focus_latest_data is not None
        self.render()
    def focus_detail(self):
        if self.focus_image is None:return
        window=tk.Toplevel(self.root);window.title('最新调焦局部 · 100%原始像素');window.geometry('800x600')
        canvas=tk.Canvas(window,background='#24292f');canvas.pack(fill='both',expand=True)
        image=ImageTk.PhotoImage(self.focus_image);window.photo=image;canvas.create_image(0,0,image=image,anchor='nw');canvas.configure(scrollregion=(0,0,image.width(),image.height()))
        canvas.bind('<ButtonPress-2>',lambda e:canvas.scan_mark(e.x,e.y));canvas.bind('<B2-Motion>',lambda e:canvas.scan_dragto(e.x,e.y,gain=1))
        ttk.Label(window,text='此窗口为打开时那一帧的100%原始裁切；主窗口继续更新。中键可拖动。').pack()
    def load_image(self,path,origin=(0,0)):
        self.image_path=Path(path)
        self.image_origin=tuple(origin)
        with Image.open(path) as source:self.source_image=source.convert('RGB').copy()
        self.render()
    def update_focus_frame(self,data):
        # Full-frame freshness is independent of the selected ROI version.
        # A drag during acquisition must not freeze the overall placement view.
        full_frame=data.get('full_frame',False)
        if full_frame:
            left=self.canvas.xview()[0];top=self.canvas.yview()[0]
            self.load_image(data['path'])
            self.canvas.xview_moveto(left);self.canvas.yview_moveto(top)
            self.status.set(f"全景已更新：帧{data['frame_id']}；拖框选调焦区域，逐帧更新，请缓慢调整镜头或摆放。")
        if data['version']!=self.focus_version or tuple(data['roi'])!=self.focus_roi:return
        with Image.open(data['path']) as source:
            image=source.convert('RGB')
            if full_frame:
                x,y,w,h=data['roi'];image=image.crop((x,y,x+w,y+h))
            self.focus_image=image.copy()
        self.focus_frame_path=Path(data['path']);thumb=self.focus_image.copy();thumb.thumbnail((320,240));self.focus_photo=ImageTk.PhotoImage(thumb);self.focus_crop_label.configure(image=self.focus_photo,text='')
        key=(tuple(data['roi']),tuple(sorted(data['parameters'].items())))
        best=self.focus_tracker.accept(data['metric'],key,data['record']);metric=data['metric']
        self.focus_text.set(f"清晰度 {metric['score']:.1f}   本次最佳 {best:.1f}")
        now=time.monotonic();interval='—' if self.focus_last_time is None else f'{now-self.focus_last_time:.2f}s';self.focus_last_time=now
        self.focus_details.set(f"ROI {data['roi']}\n本轮{data['count']}/{DEFAULT_MAX_FRAMES}张全景\n全景与局部同为帧{data['frame_id']}，显示间隔{interval}\n600行 / 1倍 / CH1 / LED128\n仅调焦，不计入正式配对。")
    def update_live_focus(self,data):
        if not self.focus_mode:return
        self.focus_latest_data=data;self.focus_remeasure_pending=False
        self.apply_live_focus(data,new_frame=True)
        self.render_viewport()
    def apply_live_focus(self,data,new_frame):
        # Prepare both images and metrics before returning to Tk's paint loop.
        # Full frames allow a freshly changed ROI to be scored without waiting
        # for another network frame; no mix of old crop/new whole/old score.
        if not self.focus_mode:return
        image=data['image']
        if self.focus_roi is None:
            self.zoom=None;self.focus_roi=tuple(data['roi']);self.focus_version=self.focus_session.set_roi(self.focus_roi) if self.focus_session else data['version']
            self.tabs.select(self.image_tab)
        roi=self.focus_roi
        metric=data['metric'] if tuple(data['roi'])==roi and data['version']==self.focus_version else focus_tools.measure(image,roi)
        x,y,w,h=roi;crop=image.crop((x,y,x+w,y+h)).convert('RGB')
        left=self.canvas.xview()[0];top=self.canvas.yview()[0]
        self.source_image=image.convert('RGB');self.image_path=None;self.image_origin=(0,0);self.current_frame=None
        self.focus_image=crop;self.focus_frame_path=None
        thumb=crop.copy();thumb.thumbnail((320,240));self.focus_photo=ImageTk.PhotoImage(thumb)
        self.focus_crop_label.configure(image=self.focus_photo,text='')
        best=self.focus_tracker.accept(metric,(roi,tuple(sorted(data['parameters'].items()))),'frame '+str(data['frame_id']))
        self.focus_text.set(f"清晰度 {metric['score']:.1f}   本次最佳 {best:.1f}   帧{data['frame_id']}")
        now=time.monotonic()
        if new_frame:
            self.focus_display_fps=None if self.focus_last_time is None else 1/max(.000001,now-self.focus_last_time)
            self.focus_last_time=now
        display_fps=self.focus_display_fps
        receive='—' if data['actual_fps'] is None else f"{data['actual_fps']:.2f}"
        display='—' if display_fps is None else f'{display_fps:.2f}'
        parameters=data['parameters']
        self.focus_details.set(f"原生灰度全景／局部／分数：同帧{data['frame_id']}\n目标{data['target_fps']:g}帧/秒；接收{receive}；显示{display}\n到帧至显示 {(now-data['received_monotonic'])*1000:.0f}ms\nROI {roi}；{data['count']}/{DEFAULT_MAX_FRAMES}帧\n{parameters['exposure_lines']}行 / {parameters['gain16']/16:g}倍 / CH1 / LED{parameters['brightness']}\n原始细节，CRC已核对；仅调焦。")
        self.configure_view();self.canvas.xview_moveto(left);self.canvas.yview_moveto(top)
        self.status.set(f"快速灰度调焦 · 帧{data['frame_id']} · 左右及清晰度同步更新；拖框选区，缓慢旋转镜头。")
    def rendered_image(self):
        if self.source_image is None:return None
        image=ImageOps.autocontrast(self.source_image) if self.brighten.get() else self.source_image.copy()
        draw=ImageDraw.Draw(image)
        if self.selection_active and self.selected_points:
            if len(self.selected_points)>1:draw.line(self.selected_points+[self.selected_points[0]] if len(self.selected_points)==4 else self.selected_points,fill='yellow',width=2)
            for x,y in self.selected_points:draw.ellipse((x-4,y-4,x+4,y+4),fill='yellow')
            if len(self.selected_points)==4:
                try:
                    geometry=roi_geometry.build(self.selected_points,image.size,int(self.margin.get()));x,y,w,h=geometry['roi_xywh']
                    draw.rectangle((x,y,x+w-1,y+h-1),outline='#24d26c',width=2)
                    clipped='；余量触及画面边界' if geometry['requested_margin_clipped_by_sensor'] else ''
                    self.roi_info.set(f'FPGA ROI {w}×{h}，原点({x},{y})\n外扩请求{geometry["requested_margin_px"]}像素，向外32网格对齐{clipped}')
                except ValueError:self.roi_info.set('板外余量请输入16～256的整数像素。')
        elif self.mask_visible.get() and self.current_frame:
            import numpy as np,cv2
            row=self.current_frame;mask=np.frombuffer(Path(row['mask']).read_bytes(),np.uint8).reshape(row['height'],row['width'])
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                points=[tuple(map(int,xy)) for xy in contour.reshape(-1,2)]
                if len(points)>1:draw.line(points+[points[0]],fill='#24d26c',width=2)
        if self.focus_roi and self.focus_mode:
            x,y,w,h=self.focus_roi;draw.rectangle((x,y,x+w-1,y+h-1),outline='#ffe000',width=2)
        return image
    def render(self):
        """Coalesce wheel/resize/frame bursts; never allocate a zoomed full frame."""
        if self.source_image is None or self.closing:return
        self.configure_view()
        if self.render_id is None:self.render_id=self.root.after(25,self.render_viewport)
    def configure_view(self):
        image=self.source_image;w=max(100,self.canvas.winfo_width());h=max(100,self.canvas.winfo_height())
        self.scale=self.zoom if self.zoom is not None else min(w/image.width,h/image.height,1.)
        self.zoom_text.set(f'{self.scale*100:.0f}%')
        geometry=(max(1,round(image.width*self.scale)),max(1,round(image.height*self.scale)))
        if geometry!=self.view_geometry:
            self.view_geometry=geometry;self.canvas.configure(scrollregion=(0,0,*geometry))
    def scrolled(self,axis,first,last):
        scrollbar=self.horizontal if axis=='x' else self.vertical
        scrollbar.set(first,last)
        fractions=(first,last)
        if self.scroll_fractions.get(axis)!=fractions:
            self.scroll_fractions[axis]=fractions;self.render()
    def scroll_x(self,*args):self.canvas.xview(*args);self.render()
    def scroll_y(self,*args):self.canvas.yview(*args);self.render()
    def pan(self,event):
        self.canvas.scan_dragto(event.x,event.y,gain=1);self.render();return 'break'
    def render_viewport(self):
        if self.render_id is not None:self.root.after_cancel(self.render_id)
        self.render_id=None
        if self.source_image is None or self.closing:return
        if self.focus_remeasure_pending and self.focus_mode and self.focus_latest_data is not None:
            self.focus_remeasure_pending=False
            # A reselected box uses the latest received native frame without a
            # new CAP; the crop, score and overview commit in this same callback.
            self.apply_live_focus(self.focus_latest_data,new_frame=False)
        started=time.perf_counter();self.configure_view()
        image=self.rendered_image();w=max(100,self.canvas.winfo_width());h=max(100,self.canvas.winfo_height())
        total_w,total_h=self.view_geometry
        left=max(0,math.floor(self.canvas.canvasx(0)));top=max(0,math.floor(self.canvas.canvasy(0)))
        right=min(total_w,left+w+1);bottom=min(total_h,top+h+1)
        if right<=left or bottom<=top:
            if self.image_item is not None:self.canvas.itemconfigure(self.image_item,state='hidden')
            return
        box=(left/self.scale,top/self.scale,min(image.width,right/self.scale),min(image.height,bottom/self.scale))
        shown=image.resize((right-left,bottom-top),Image.Resampling.NEAREST if self.scale>=1 else Image.Resampling.LANCZOS,box=box)
        photo=ImageTk.PhotoImage(shown,master=self.canvas)
        if self.image_item is None:
            self.image_item=self.canvas.create_image(left,top,image=photo,anchor='nw',tags='viewport_image')
        else:
            self.canvas.coords(self.image_item,left,top);self.canvas.itemconfigure(self.image_item,image=photo,state='normal')
        self.photo=photo;self.canvas.tag_lower(self.image_item)
        self.render_count+=1;self.render_stats=dict(raster_size=list(shown.size),virtual_size=list(self.view_geometry),
            source_box=list(box),scale=self.scale,elapsed_ms=(time.perf_counter()-started)*1000)
    def pixel(self,event):
        if self.source_image is None:return
        x=int(self.canvas.canvasx(event.x)/self.scale);y=int(self.canvas.canvasy(event.y)/self.scale)
        if 0<=x<self.source_image.width and 0<=y<self.source_image.height:
            origin=self.image_origin
            self.pixel_text.set(f'ROI局部 x={x}, y={y}；全图 x={x+origin[0]}, y={y+origin[1]}；像素={self.source_image.getpixel((x,y))}；缩放仅影响显示')
    def frame_from_record(self,slot,record):
        record=Path(record);r=workflow.read(record);m=r['diagnostic'];folder=record.parent
        return dict(slot=slot,record=str(record),color=str(folder/r['png_file']),gray=str(folder/'image.gray.png'),sat=str(folder/'image.sat.png'),mask=str(folder/'board_mask.bin'),
            width=m['roi'][2],height=m['roi'][3],exposure=m['parameters']['exposure_lines'],gain16=m['parameters']['gain16'],LED=m['parameters']['brightness'],frame_id=m['identity']['frame_id'],
            session=str(m['identity']['session']),board_pixels=m['statistics']['board_count'],board_SAT=m['statistics']['board_rgb_any_max'],roi_xywh=list(m['roi']))
    def add_frame(self,row):
        slot=row['slot'];self.frames[slot]=row;values=(row['exposure'],row['gain16']/16,row['LED'],row['frame_id'])
        if self.table.exists(slot):self.table.item(slot,values=values)
        else:self.table.insert('', 'end',iid=slot,text=slot,values=values)
    def choose_frame(self,event=None):
        selected=self.table.selection()
        if not selected or selected[0] not in self.frames or self.selection_active or self.focus_mode:return
        row=self.frames[selected[0]];self.current_frame=row;key={'彩色原图':'color','同帧灰度':'gray','SAT风险':'sat'}[self.view.get()]
        self.load_image(row[key],origin=row.get('roi_xywh',[0,0])[:2]);self.frame_info.set(f"{row['slot']}\n实际{row['exposure']}行 / {row['gain16']/16:g}倍 / LED{row['LED']}\nframe={row['frame_id']}\n原图ROI {row.get('roi_xywh',[0,0,row['width'],row['height']])}\n有效板面{row['board_pixels']}像素\n其中RGB最大码风险{row['board_SAT']}像素\n原始像素；未取正/插值，身份与CRC严格核验。")
    def display_catalogue(self,data):
        self.catalogue=data;self.frames={};self.table.delete(*self.table.get_children())
        for row in data['frames']:self.add_frame(row)
        if self.frames:self.table.selection_set(next(iter(self.frames)));self.choose_frame()
        self.progress.stop();self.progress.configure(mode='determinate',maximum=8,value=len(self.frames));self.set_busy(self.busy())
    def show_analysis(self,path):
        self.analysis_path=Path(path)
        for child in self.evidence_body.winfo_children():child.destroy()
        self.evidence_photos=[]
        ttk.Label(self.evidence_body,text='低/高/等权同一显示尺度；仅算法证据，没有已训练权重、置信概率或合格结论。先看原图独立标注，再查看证据。',wraplength=1150).pack(anchor='w')
        image_path=self.analysis_path/'comparison_shared_scale.png'
        if image_path.exists():
            with Image.open(image_path) as source:image=source.convert('RGB');image.thumbnail((1180,650))
            photo=ImageTk.PhotoImage(image);self.evidence_photos.append(photo);ttk.Label(self.evidence_body,image=photo).pack()
        info=workflow.read(self.analysis_path/'console_analysis.json')
        for item in info['views']:
            ttk.Button(self.evidence_body,text=item['mode']+' 原尺寸',command=lambda name=item['image']:self.show_evidence(name)).pack(side='left',padx=4)
    def show_evidence(self,name):
        if self.busy():return
        origin=self.catalogue['frames'][0].get('roi_xywh',[0,0])[:2] if self.catalogue and self.catalogue['frames'] else (0,0)
        self.current_frame=None;self.selection_active=False;self.load_image(self.analysis_path/name,origin=origin);self.tabs.select(self.image_tab)
    def open_existing(self,path=None):
        if self.busy():return
        if path is None:
            path=filedialog.askopenfilename(title='选择P0 pair.zip；取消后可选择目录',initialdir=self.result_root,filetypes=[('P0 ZIP','*.zip')])
            if not path:path=filedialog.askdirectory(title='选择P0结果目录',initialdir=self.result_root)
        if not path:return
        self.status.set('离线核验来源、身份、CRC和同帧派生，不连接板卡。')
        def work():
            source=Path(path)
            if source.is_file():
                target=self.result_root/('offline_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);source=workflow.extract_zip(source,target)
            data=workflow.catalog(source,self.cancel);return ('opened',data)
        self.dispatch(work)
    def analyze(self):
        if self.busy() or not self.catalogue or not self.catalogue['input_ready']:return
        source=Path(self.catalogue['root'])/'XDL_manifest.json';out=self.result_root/('analysis_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        self.dispatch(lambda:('analysis',workflow.run_analysis(source,out,self.cancel,self.notify),str(out)))
    def reexport(self):
        if self.busy() or not self.catalogue or not self.catalogue['raw_eight_recoverable']:return
        data=self.catalogue;out=self.result_root/('reexport_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);self.status.set('重新整理已有八帧；不发CAP、不当成新增样本。')
        def work():workflow.reexport(data,out);return ('opened',workflow.catalog(out,self.cancel))
        self.dispatch(work)
    def open_compare(self):
        if self.busy() or not self.catalogue or not self.catalogue['input_ready']:return
        pair=Path(self.catalogue['root']);self.status.set('正在准备本组八张原片对比；离线整理，不重新拍摄。')
        self.dispatch(lambda:('compared',workflow.make_eight_compare(pair,self.notify)))
    def lights_off(self):
        specimen='lights_off'
        def work():
            runtime=workflow.Runtime(specimen,'A_v1','lights_off_only',self.cancel,self.notify);plan,_,_=workflow.backend.plan_for(runtime,preview=True)
            folder=self.result_root/('OFF_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True,exist_ok=False)
            with runtime.guard():
                executor=runtime.executor(plan,folder)
                try:result=executor.lights_off(timeout_s=3)
                finally:executor.close()
            workflow.write(folder/'OFF.json',result);return ('off',result)
        self.dispatch(work)
    def stop(self):
        self.cancel.set();self.selection_ready.set();self.selection_active=False;self.confirm_button.configure(state='disabled');self.clear_button.configure(state='disabled');self.status.set('正在停止、尝试关灯并保留记录；等待完成，不强制杀进程。')
    def open_folder(self):
        target=self.session_root or (Path(self.catalogue['root']) if self.catalogue else self.result_root)
        target.mkdir(parents=True,exist_ok=True);os.startfile(str(target))
    def export_csv(self):
        if not self.frames:return
        path=filedialog.asksaveasfilename(title='保存实际读回CSV',defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:workflow.write_readbacks(list(self.frames.values()),path)
            except (ValueError,OSError) as exc:self.status.set('CSV未保存：'+str(exc))
    def save_view(self):
        if self.source_image is None:return
        path=filedialog.asksaveasfilename(title='保存显示副本，原始数据不变',defaultextension='.png',initialfile='display_only.png',filetypes=[('PNG','*.png')])
        if path:
            try:
                target=workflow.new_display_output(path);receipt=target.with_suffix('.view.json');workflow.new_display_output(receipt)
                self.rendered_image().save(target);workflow.write(receipt,dict(display_only=True,source=str(self.image_path) if self.image_path else 'memory_only_focus_preview',source_sha256=workflow.sha(self.image_path) if self.image_path else None,brightened=self.brighten.get(),mask_overlay=self.mask_visible.get(),source_origin_xy=list(self.image_origin)))
            except (ValueError,OSError) as exc:self.status.set('显示副本未保存：'+str(exc))
    def refresh_history(self):
        self.history.delete(*self.history.get_children());self.history_paths={}
        if not self.result_root.exists():return
        for path in sorted(self.result_root.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)[:60]:
            if not path.is_dir():continue
            receipt=path/'console_session.json';summary=path/'pair/operator_summary.json'
            try:state=workflow.read(receipt)['status'] if receipt.exists() else workflow.read(summary)['status'] if summary.exists() else '离线/辅助结果'
            except (ValueError,OSError):state='不完整，记录保留'
            key=self.history.insert('','end',text=path.name,values=(state,));self.history_paths[key]=path
    def open_history(self,event=None):
        if self.busy():return
        selected=self.history.selection()
        if selected:
            path=self.history_paths[selected[0]]
            if (path/'console_analysis.json').exists():self.show_analysis(path);self.tabs.select(self.evidence_tab)
            elif (path/'pair/operator_summary.json').exists() or (path/'operator_summary.json').exists():self.open_existing(path)
            else:self.session_root=path;self.open_folder()
    def poll(self):
        deadline=time.monotonic()+.012
        try:
            for _ in range(32):
                if time.monotonic()>=deadline:break
                kind,value=self.events.get_nowait()
                if kind=='notice':
                    event,data=value
                    if event=='log':self.log.insert('end',data['text']+'\n');self.log.see('end')
                    elif event=='phase':
                        self.status.set(PHASES[data['phase']]);self.progress.stop();self.progress.configure(mode='determinate' if data['phase']=='capture_eight' else 'indeterminate')
                        if data['phase']!='capture_eight':self.progress.start(15)
                    elif event=='selection':
                        self.selection_active=True;self.selected_points=list(data.get('candidate',{}).get('points',[]));self.current_frame=None;self.zoom=None;self.view.set('彩色原图');self.load_image(data['png']);self.tabs.select(self.image_tab)
                        message=PHASES['select_board'] if self.selected_points else '自动定位未通过，请沿板面内缘依次点4角；本轮原图已保留'
                        self.status.set(data['specimen']+' '+data['variant']+'：'+message);self.margin_spin.configure(state='normal');self.confirm_button.configure(state='normal');self.clear_button.configure(state='normal')
                    elif event=='frame':
                        self.add_frame(self.frame_from_record(data['slot'],data['record']));self.progress.configure(mode='determinate',value=data['count']);self.table.selection_set(data['slot']);self.choose_frame()
                    elif event=='analysis':self.show_analysis(data['path'])
                    elif event=='focus_overview':
                        self.current_frame=None;self.zoom=None;self.load_image(data['path']);self.tabs.select(self.image_tab)
                        w,h=data['size'];fw=min(320,w);fh=min(240,h);self.apply_focus_roi(((w-fw)//2,(h-fh)//2,fw,fh))
                        self.status.set('全景和框选局部将随新帧共同更新；拖框改变调焦区域，缓慢调整镜头或摆放。')
                    elif event=='focus_paused':
                        if data['waiting_for_roi']:self.status.set('调焦灯光已关闭；等待拖框选区。')
                    elif event=='focus_frame':
                        self.update_focus_frame(data)
                    elif event=='focus_live_ready':
                        data=self.focus_mailbox.take()
                        if data is not None:self.update_live_focus(data)
                elif kind=='done':
                    self.worker=None;self.selection_active=False;self.confirm_button.configure(state='disabled');self.clear_button.configure(state='disabled');self.progress.stop()
                    if value[0]=='preflight':self.status.set(value[1]);self.refresh_history()
                    elif value[0]=='capture':
                        result,data=value[1:]
                        if data:self.display_catalogue(data)
                        receipt=result['receipt'];self.status.set(receipt['status']+'；目录 '+result['root']+'。原图未标注，待TJ/YMW复核。')
                        gallery=receipt.get('eight_compare',{})
                        if gallery.get('status')=='READY':self.status.set(self.status.get()+' 八张对比已生成，可点“查看八张对比”。')
                        elif gallery:self.status.set(self.status.get()+' 对比副本未完成，可稍后离线重试。')
                        self.refresh_history()
                    elif value[0]=='opened':self.display_catalogue(value[1]);self.status.set('离线校验完成：'+str(len(self.frames))+'张已提交帧；未连接板卡。');self.refresh_history()
                    elif value[0]=='compared':
                        gallery=value[1]
                        if gallery.get('status')=='READY':
                            self.status.set('本组八张对比：'+gallery['directory']);os.startfile(gallery['index'])
                        else:self.status.set('对比副本未生成，原始八帧保留；'+gallery['error']['message'])
                    elif value[0]=='analysis':self.status.set(value[1]);self.show_analysis(value[2]) if value[1]=='OFFLINE_EVIDENCE_COMPLETE_NOT_DETECTION' else None
                    elif value[0]=='off':self.status.set('关灯命令已应答（不是实测熄灯）。' if value[1]['acknowledged'] else '关灯未应答，请检查实物灯光；记录保留。')
                    elif value[0]=='focus':
                        self.focus_mode=False;self.focus_session=None;self.pause_focus_button.configure(text='暂停调焦',state='disabled');self.status.set(value[1]['receipt']['status']+'：调焦数据已单独保存，不作配对组。调焦结束后再开始正式采集。')
                    self.set_busy(False)
                elif kind=='error':
                    self.worker=None;self.progress.stop();self.selection_active=False;self.focus_mode=False;self.focus_session=None
                    self.pause_focus_button.configure(text='暂停调焦',state='disabled');self.confirm_button.configure(state='disabled');self.clear_button.configure(state='disabled');self.set_busy(False);self.status.set('停止，原记录保留：'+value);self.log.insert('end','ERROR: '+value+'\n')
        except queue.Empty:pass
        except Exception as exc:
            self.status.set('界面显示异常，采集记录保留：'+str(exc));self.log.insert('end','DISPLAY ERROR: '+str(exc)+'\n')
            if self.busy():self.stop()
        if self.closing and not self.busy():self.destroy_ui();return
        self.poll_id=self.root.after(20,self.poll)
    def close(self):
        if self.busy():self.closing=True;self.stop()
        else:self.destroy_ui()
    def destroy_ui(self):
        self.closing=True
        for callback in (self.render_id,self.poll_id):
            if callback is not None:
                try:self.root.after_cancel(callback)
                except tk.TclError:pass
        self.render_id=None;self.root.destroy()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
    workflow.verify_bundle()
    if args.check_only:
        runtime=workflow.Runtime('sample005','A_v1','offline_check',threading.Event(),lambda *a,**k:None);workflow.backend.plan_for(runtime,preview=True)
        print(json.dumps(dict(status='CONSOLE_OFFLINE_READY',hardware_contacted=False)));raise SystemExit(0)
    root=tk.Tk();ConsoleApp(root);root.mainloop()
