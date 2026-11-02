"""Responsive operator GUI; opening the window never connects to the board."""
import argparse,io,json,os,queue,threading,time,traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
import app_core as core

STATUS={'LOCKED':'参数已锁定（成像规则）','NEEDS_REVIEW':'需复核','CAPTURE_FAILED':'采集失败',
        'PROGRAM_ERROR':'程序或接口错误','CONTINUE_ADJUST':'继续调整'}
REASONS={'initial_request':'从600行开始','independent_stable_confirmations':'同档独立新帧确认通过',
    'offline_policy_locked':'当前成像规则满足','retry_exhausted':'采集重试耗尽','cancelled':'已请求停止',
    'missing_requested_data':'缺少所请求观测','missing_fresh_confirmation':'缺少新的确认帧',
    'search_exhausted':'可选曝光档已用尽','host_elapsed_budget':'达到整轮时间预算',
    'transport_frame_reservation_budget':'达到实际请求帧预留预算','external_recovery_required':'设备需要人工恢复',
    'too_dark':'暗区过多','insufficient_effective_area':'有效观测面积不足','rgb_risk_warning':'RGB最大码风险提示',
    'rgb_high_risk':'RGB最大码风险过高','near_white_risk':'近白区域过多','dark_and_highlight':'暗区与高光同时存在',
    'confirmation_unstable':'同档新图不够稳定','budget_exhausted':'预算已用尽','fresh_confirmation_required':'需要同档新帧确认',
    'no_qualified_fallback':'没有满足规则的回退参数','fallback_exhausted':'回退确认已用尽'}

class App:
    def __init__(self,root,lab_root,*,runner=core.run_real,autoload=True):
        self.root=root;self.lab=Path(lab_root).resolve();self.runner=runner;self.events=queue.Queue()
        self.plan=None;self.state='idle';self.cancel=threading.Event();self.closing=False;self.last_result=None;self.photo=None
        self.preview_ready=False;self.boot_job=None
        root.title('BX72 自动曝光实验 · 0x0105');root.geometry('1160x850');root.minsize(900,680)
        self.source=tk.StringVar();self.sample=tk.StringVar(value='尚未载入');self.roi=tk.StringVar(value='—')
        self.confirm=tk.BooleanVar(value=False);self.status=tk.StringVar(value='请载入本轮完整图，确认轮廓后开始。')
        self.detail=tk.StringVar(value='固定CH1（上） · LED128 · 增益1× · 曝光400/500/600/700行 · 从600行开始')
        self.quality=tk.StringVar(value='尚未取得新的评价图');self.result_text=tk.StringVar(value='参数锁定表示成像规则满足，缺陷检测结果需另行评价。')
        top=ttk.Frame(root,padding=10);top.pack(fill='x')
        ttk.Label(top,text='完整图来源').grid(row=0,column=0,sticky='w')
        self.source_entry=ttk.Entry(top,textvariable=self.source,state='readonly');self.source_entry.grid(row=0,column=1,columnspan=3,sticky='ew',padx=8)
        self.choose_button=ttk.Button(top,text='选择完整图目录',command=self.choose);self.choose_button.grid(row=0,column=4,padx=3)
        self.refresh_button=ttk.Button(top,text='载入最新02结果',command=self.refresh);self.refresh_button.grid(row=0,column=5,padx=3)
        ttk.Label(top,text='样件编号').grid(row=1,column=0,sticky='w',pady=8)
        ttk.Label(top,textvariable=self.sample,font=('Microsoft YaHei UI',11,'bold')).grid(row=1,column=1,sticky='w')
        ttk.Label(top,text='ROI').grid(row=1,column=2,sticky='w');ttk.Label(top,textvariable=self.roi).grid(row=1,column=3,columnspan=3,sticky='w')
        ttk.Label(top,textvariable=self.detail).grid(row=2,column=0,columnspan=6,sticky='w',pady=4)
        self.confirm_box=ttk.Checkbutton(top,text='已检查轮廓正确，且工件、相机和灯位与这张完整图一致',variable=self.confirm)
        self.confirm_box.grid(row=3,column=0,columnspan=6,sticky='w',pady=5)
        ttk.Label(top,text='采集前请关闭预览及其他采集窗口；VPN由你手动断开。').grid(row=4,column=0,columnspan=6,sticky='w')
        top.columnconfigure(1,weight=1);top.columnconfigure(3,weight=1)
        buttons=ttk.Frame(root,padding=(10,0));buttons.pack(fill='x')
        self.start_button=ttk.Button(buttons,text='开始自动曝光',command=self.start,state='disabled');self.start_button.pack(side='left',padx=(0,8))
        self.stop_button=ttk.Button(buttons,text='停止并关灯',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=8)
        self.open_button=ttk.Button(buttons,text='打开本轮结果',command=self.open_result,state='disabled');self.open_button.pack(side='right')
        ttk.Label(root,textvariable=self.status,padding=(10,8),font=('Microsoft YaHei UI',11,'bold')).pack(fill='x')
        content=ttk.Panedwindow(root,orient='horizontal');content.pack(fill='both',expand=True,padx=10)
        self.preview=ttk.Label(content,anchor='center',text='完整图轮廓 / 本次新图');content.add(self.preview,weight=3)
        right=ttk.Frame(content);content.add(right,weight=2)
        ttk.Label(right,text='本次观测',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
        ttk.Label(right,textvariable=self.quality,wraplength=390,justify='left').pack(anchor='w',fill='x',pady=8)
        ttk.Label(right,textvariable=self.result_text,wraplength=390,justify='left').pack(anchor='w',fill='x',pady=8)
        self.log=tk.Text(right,height=15,width=45,wrap='word',state='disabled');self.log.pack(fill='both',expand=True)
        ttk.Label(root,text='本程序运行在电脑上。当前仅调曝光；不改固件、网卡或VPN。',padding=10).pack(fill='x')
        self.confirm.trace_add('write',lambda *args:self.update_controls())
        root.protocol('WM_DELETE_WINDOW',self.close);self.poll_job=root.after(80,self.poll)
        if autoload:self.boot_job=root.after(120,self.refresh)

    def write_log(self,text):
        self.log.config(state='normal');self.log.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n');self.log.see('end');self.log.config(state='disabled')
    def notify(self,event,**values):self.events.put((event,values))
    def update_controls(self):
        idle=self.state=='idle'
        self.start_button.config(state='normal' if idle and self.plan and self.preview_ready and self.confirm.get() else 'disabled')
        self.stop_button.config(state='normal' if self.state=='running' and not self.cancel.is_set() else 'disabled')
        for b in [self.choose_button,self.refresh_button,self.confirm_box]:b.config(state='normal' if idle else 'disabled')
        self.open_button.config(state='normal' if idle and self.last_result else 'disabled')
    def choose(self):
        source=filedialog.askdirectory(title='选择02生成的single_full目录',initialdir=self.lab/'results')
        if source:self.refresh(source)
    def refresh(self,source=None):
        if self.boot_job is not None:self.root.after_cancel(self.boot_job)
        self.boot_job=None
        if self.state!='idle':return
        self.plan=None;self.preview_ready=False;self.last_result=None;self.confirm.set(False)
        self.source.set('');self.sample.set('尚未载入');self.roi.set('—');self.photo=None
        self.preview.config(image='',text='正在载入定位图')
        self.quality.set('尚未取得本轮新的评价图');self.result_text.set('参数锁定表示成像规则满足，缺陷检测结果需另行评价。')
        self.state='loading';self.status.set('正在校验本轮来源和程序依赖……');self.update_controls()
        def worker():
            try:
                plan,snapshot=core.prepare_plan(self.lab,source)
                self.notify('plan',plan=plan,preview_png=core.source_preview(snapshot))
            except BaseException as exc:self.notify('load_error',message=str(exc))
        threading.Thread(target=worker,name='BX72-local-preflight',daemon=False).start()
    def accept_plan(self,plan,preview_png=None):
        self.confirm.set(False);self.preview_ready=False;self.last_result=None
        self.quality.set('尚未取得本轮新的评价图');self.result_text.set('请先确认定位图；旧轮次指标不参与本次运行。')
        self.plan=plan;self.source.set(plan['source']);self.sample.set(plan['sample_id']);self.roi.set(str(plan['roi'])+'；板内评价%s像素'%plan['mask_pixels'])
        self.state='idle';self.status.set('请检查轮廓和样件编号，再勾选确认并开始。')
        if preview_png is None:
            snapshot=core.load_source(plan['source'])
            if snapshot['geometry_sha256']!=plan['source_geometry_sha256'] or snapshot['full_png_sha256']!=plan['source_full_png_sha256']:
                raise ValueError('定位来源已变化，请重新载入。')
            preview_png=core.source_preview(snapshot)
        self.preview_ready=self.show_image(preview_png)
        if not self.preview_ready:self.status.set('定位预览显示失败，请重新载入；尚未连接板卡。')
        self.write_log('已载入 '+plan['sample_id']+'；此步骤仅检查本地文件，没有访问板卡。');self.update_controls()
    def show_image(self,path):
        try:
            with Image.open(io.BytesIO(path) if isinstance(path,bytes) else path) as source:im=source.convert('RGB')
            width=max(350,self.preview.winfo_width()-10);height=max(300,self.preview.winfo_height()-10)
            im.thumbnail((width,height));self.photo=ImageTk.PhotoImage(im);self.preview.config(image=self.photo,text='')
            return True
        except Exception as exc:
            self.photo=None;self.preview.config(image='',text='当前图像无法显示，请查看日志');self.write_log('图像显示失败：'+str(exc));return False
    def start(self):
        if self.state!='idle' or not self.plan or not self.preview_ready or not self.confirm.get():return
        plan=self.plan;self.state='running';self.cancel=threading.Event();self.last_result=None
        self.status.set('开始本轮自动曝光；请保持摆放不动。');self.result_text.set('正在运行；可点击停止并关灯。')
        self.quality.set('正在等待本轮新图；当前显示仅用于定位。')
        self.write_log('请求连接板卡 '+plan['board']+'，每次采集超时30秒，整轮预算仍按XDL配置。');self.update_controls()
        def worker():
            try:
                result=self.runner(plan,confirmed_same_pose=True,notify=self.notify,cancel=self.cancel)
                self.notify('done',**result)
            except BaseException as exc:self.notify('run_error',message=str(exc),trace=traceback.format_exc(),output=getattr(exc,'output',None))
        threading.Thread(target=worker,name='BX72-exposure-worker',daemon=False).start()
    def stop(self):
        if self.state=='running':
            self.cancel.set();self.status.set('正在停止当前请求，随后请求关灯并归档……');self.update_controls()
    def close(self):
        if self.state in ('running','loading'):
            self.closing=True;self.stop();self.status.set('正在结束当前任务并保存，请稍候……')
        else:self.destroy()
    def destroy(self):
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job);self.poll_job=None
        if self.boot_job is not None:
            self.root.after_cancel(self.boot_job);self.boot_job=None
        self.root.destroy()
    def open_result(self):
        if self.last_result:os.startfile(self.last_result['output'])
    def finish(self,data):
        self.state='idle';self.confirm.set(False);self.last_result=data
        s=data['summary'];label=STATUS.get(s['status'],s['status']);self.status.set(label)
        exposure=s.get('locked_exposure_lines');off=s.get('lights_off',{}).get('acknowledged',False)
        reasons='、'.join(REASONS.get(r,r) for r in s.get('final_reason_codes',[]))
        self.result_text.set((('锁定曝光：%s行\n'%exposure) if exposure is not None else '')+
            '接受观测：%s张\n'%s.get('accepted_observations',0)+'关灯指令：'+('已收到ACK' if off else '未确认，请查看灯具')+
            (('\n原因：'+reasons) if reasons else '')+
            (('\n本轮耗时（归档前）：%.2f秒'%(s['host_elapsed_ms_before_archive']/1000)) if 'host_elapsed_ms_before_archive' in s else '')+
            '\n结果ZIP：'+data['archive'])
        for warning in data.get('archive_warnings',[]):self.write_log(warning)
        self.write_log('本轮结束：'+label+'；'+data['archive']);self.update_controls()
    def poll(self):
        self.poll_job=None
        try:
            for _ in range(100):
                event,d=self.events.get_nowait()
                if event=='plan':self.accept_plan(d['plan'],d.get('preview_png'))
                elif event=='load_error':
                    self.state='idle';self.status.set(d['message']);self.write_log(d['message']);self.update_controls()
                elif event=='capture':
                    e=d['parameters']['exposure_lines'];self.status.set('正在采集 %d 行的新图……'%e);self.write_log('请求曝光%d行'%e)
                elif event=='progress':self.status.set(d['text']);self.write_log(d['text'])
                elif event=='decision':
                    decision=d['decision'];reasons='、'.join(REASONS.get(r,r) for r in decision['reason_codes'])
                    self.write_log(STATUS.get(decision['status'],decision['status'])+'；'+reasons+
                        ('；下一次%d行'%decision['next_exposure_lines'] if decision['next_exposure_lines'] is not None else ''))
                elif event=='image':
                    self.show_image(d['path']);s=d['statistics'];n=s['n'];ratio=lambda k:'%.3f%%'%(100*s[k]/n) if n else '不可用'
                    self.quality.set('曝光：%d行\n评价像素：%d\n平均灰度：%s\n暗区：%s\n灰度近白：%s\nRGB最大码风险：%s\n有效观测面积：%s\n帧编号：%s'%(
                        d['exposure_lines'],n,'%.3f'%(s['gray_sum']/n) if n else '不可用',ratio('dark_count'),ratio('near_white_count'),
                        ratio('rgb_max_count'),ratio('effective_count'),d['identity']['frame_id']))
                elif event=='done':self.finish(d)
                elif event=='run_error':
                    self.state='idle';self.confirm.set(False);self.status.set('程序未完成：'+d['message'])
                    if d.get('output'):self.last_result=dict(output=d['output'],archive=None)
                    self.write_log(d['trace']);self.update_controls()
                # 'finished' is a durable core event. 'done' arrives after its return.
        except queue.Empty:pass
        except Exception as exc:
            self.write_log('界面消息处理失败：'+str(exc))
            if self.state=='running':self.stop()
            else:
                self.preview_ready=False;self.confirm.set(False);self.state='idle';self.update_controls()
            self.status.set('界面显示异常，已保留日志；正在处理停止或后续结果。')
        if self.closing and self.state=='idle':self.destroy();return
        self.poll_job=self.root.after(80,self.poll)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'))
    p.add_argument('--source',type=Path);p.add_argument('--plan-only',action='store_true')
    p.add_argument('--software-peer',action='store_true');p.add_argument('--out',type=Path)
    args=p.parse_args()
    if args.plan_only:print(json.dumps(core.make_plan(args.lab_root,args.source),ensure_ascii=False,indent=2));return 0
    if args.software_peer:
        if args.out is None:p.error('--software-peer requires --out')
        result=core.run_peer(args.out);print(json.dumps(result['summary'],ensure_ascii=False,indent=2));return 0 if result['summary']['independent_audit']['status']=='PASS' else 2
    root=tk.Tk();app=App(root,args.lab_root,autoload=args.source is None)
    if args.source:app.boot_job=root.after(120,lambda:app.refresh(args.source))
    root.mainloop();return 0
if __name__=='__main__':raise SystemExit(main())
