"""Keep image processing off Tk and retain only the latest display thumbnails."""
import json,os,queue,re,threading,time,uuid
from datetime import datetime
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from manual_camera import write_record,validate_values
from roi_camera import ROOT,RoiCameraClient,capture_group,raw_image,safe_off,pack_result,DIRECTIONS
from plate_roi import overlay

def thumbnail(image,size):
    picture=Image.fromarray(image[...,::-1])
    picture.thumbnail(size,Image.Resampling.LANCZOS)
    return picture

class DisplayMailbox:
    def __init__(self):
        self.lock=threading.Lock();self.main=None;self.cards={};self.status=None
    def put(self,main=None,channel=None,card=None,meta=None):
        with self.lock:
            if main is not None:self.main=main
            if card is not None:self.cards[channel]=(card,meta)
    def set_status(self,value):
        with self.lock:self.status=value
    def take(self):
        with self.lock:
            result=(self.main,self.cards,self.status)
            self.main=None;self.cards={};self.status=None
            return result

class LiveApp:
    def __init__(self,root,args):
        self.root=root;self.args=args;self.events=queue.Queue();self.display=DisplayMailbox()
        self.worker=None;self.stop=threading.Event();self.last_out=None;self.last_log=None
        self.images={};self.closing=False;self.mode=None;self.operation_error=False;self.inputs=[]
        self.displayed_frames=0;self.last_frame_id=None
        root.title('BX72 四方向首帧定位与FPGA裁剪');root.geometry('1220x900')
        controls=ttk.Frame(root,padding=12);controls.pack(fill='x')
        self.sample=tk.StringVar(value='sample001');self.exposure=tk.StringVar(value='100');self.gain=tk.StringVar(value='16')
        self.brightness=tk.StringVar(value='128');self.channel=tk.StringVar(value='1');self.margin=tk.StringVar(value='16')
        for col,(label,var,width) in enumerate([('工件编号',self.sample,16),('曝光行数',self.exposure,8),('增益编码 16=1×',self.gain,8),('LED亮度 1–255',self.brightness,8),('外留边像素',self.margin,6)]):
            ttk.Label(controls,text=label).grid(row=0,column=2*col,sticky='w',padx=(0,6))
            entry=ttk.Entry(controls,textvariable=var,width=width);entry.grid(row=0,column=2*col+1,padx=(0,15));self.inputs.append(entry)
        row=ttk.Frame(root,padding=(12,0));row.pack(fill='x');self.buttons=[]
        ttk.Label(row,text='预览通道').pack(side='left')
        self.channel_input=ttk.Combobox(row,textvariable=self.channel,values=('1','2','3','4'),state='readonly',width=3);self.channel_input.pack(side='left',padx=8)
        for label,mode in [('设置并读回曝光/增益','set'),('① 单灯预览','preview'),('③ 四方向定位裁剪','group')]:
            button=ttk.Button(row,text=label,command=lambda value=mode:self.start(value));button.pack(side='left',padx=5);self.buttons.append(button)
        ttk.Button(row,text='② 停止并关灯',command=self.cancel).pack(side='left',padx=5)
        ttk.Button(row,text='打开最近结果',command=self.open_result).pack(side='right')
        self.status=tk.StringVar(value='先设置并读回曝光/增益；单灯预览会显示收包进度与过渡帧。')
        self.readback=tk.StringVar(value='相机读回尚未确认；增益编码16代表1×。')
        ttk.Label(root,textvariable=self.status,padding=(12,8),wraplength=1180).pack(fill='x')
        ttk.Label(root,textvariable=self.readback,padding=(12,0),wraplength=1180).pack(fill='x')
        self.main=ttk.Label(root,anchor='center',text='等待图像…');self.main.pack(fill='both',expand=True,padx=12,pady=8)
        self.cards=[];frames=ttk.Frame(root,padding=(12,0,12,12));frames.pack(fill='x')
        for channel in range(1,5):
            box=ttk.LabelFrame(frames,text=f'CH{channel}（{DIRECTIONS[channel]}）',padding=5);box.pack(side='left',fill='both',expand=True,padx=4)
            card=ttk.Label(box,anchor='center',text='待采集');card.pack();self.cards.append(card)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(40,self.poll)

    def values(self):
        exposure,gain,brightness=int(self.exposure.get()),int(self.gain.get()),int(self.brightness.get())
        validate_values(exposure,gain,brightness);margin=int(self.margin.get())
        if margin<4:raise ValueError('外留边至少4像素，建议16')
        sample=self.sample.get().strip()
        if not sample:raise ValueError('请填写工件编号')
        return exposure,gain,brightness,margin,sample,int(self.channel.get())

    def start(self,mode):
        if self.worker and self.worker.is_alive():return
        try:values=self.values()
        except Exception as exc:messagebox.showerror('参数错误',str(exc));return
        self.stop=threading.Event();self.mode=mode;self.operation_error=False;self.display.take()
        for item in self.buttons+self.inputs+[self.channel_input]:item.config(state='disabled')
        self.status.set('正在连接板卡，等待状态与参数读回…')
        if mode in ('preview','group'):
            for i,card in enumerate(self.cards):card.config(image='',text='待采集');self.images.pop('card'+str(i+1),None)
            self.main.config(image='',text='正在等待完整图像…');self.images.pop('main',None)
        self.worker=threading.Thread(target=self.run,args=(mode,values),daemon=True);self.worker.start()

    def run(self,mode,values):
        exposure,gain,brightness,margin,sample,channel=values
        client=None;out=None;error=None
        logs=ROOT/'logs';logs.mkdir(exist_ok=True)
        log_path=logs/('GUI_'+mode+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]+'.jsonl')
        self.last_log=log_path
        def log(kind,value):
            with log_path.open('a',encoding='utf-8') as file:
                file.write(json.dumps(dict(time=datetime.now().astimezone().isoformat(),event=kind,value=value),ensure_ascii=False,default=str)+'\n')
        def notify(kind,value):
            if kind=='status':self.display.set_status(value);log(kind,value)
            elif kind=='frame':
                raw,meta=value;image=raw_image(raw,meta['width'],meta['height'])
                self.display.put(main=thumbnail(image,(1080,510)) if mode=='preview' else None,
                    channel=meta['channel'],card=thumbnail(image,(265,210)),meta=meta)
                log('frame',meta)
            elif kind=='geometry':
                image,geometry=value;self.display.put(main=thumbnail(overlay(image,geometry),(1080,510)));log(kind,geometry)
            else:self.events.put((kind,value));log(kind,value)
        def preview_capture(label):
            def progress(item):
                if item['phase']=='waiting_ack':text=f'CH{channel}：{label}，等待抓帧ACK…'
                else:text=f'CH{channel}：{label}，帧 {item["frame_id"]} 已收 {item["received_packets"]}/{item["expected_packets"]} 包'
                self.display.set_status(text);log('transfer_progress',item)
            raw,meta=client.capture(on_progress=progress)
            notify('frame',(raw,dict(meta,channel=channel,preview_label=label)))
        try:
            log('start',dict(mode=mode,parameters=values,bind=self.args.bind,board=self.args.board,port=self.args.port))
            client=RoiCameraClient(self.args.bind,self.args.board,self.args.port,self.stop)
            if mode=='group':
                safe_sample=re.sub(r'[^\w.-]','_',sample)
                out=ROOT/'results'/('BX72_ROI_'+safe_sample+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
                result=capture_group(client,out,sample,exposure,gain,brightness,1,margin,notify)
                notify('status',f'完成：保存{result["saved_frames"]}张，快照请求{result["total_capture_requests"]}次；{result["status"]}')
                notify('readback',result['camera_readback'])
            else:
                status=client.ready();log('board_status',status);snapshot=client.camera(exposure,gain);notify('readback',snapshot)
                if mode=='set':notify('status','曝光和增益设置完成，传感器读回一致。')
                else:
                    client.light(0,0);client.light(1<<(channel-1),brightness)
                    notify('status',f'CH{channel}灯光已确认；等待稳定1秒…')
                    if self.stop.wait(1):raise RuntimeError('Cancelled')
                    for index in range(3):preview_capture(f'过渡帧 {index+1}/3，仅预览、不保存')
                    while not self.stop.is_set():
                        preview_capture('稳定预览，不保存')
                        if self.stop.wait(.15):break
        except Exception as exc:
            if not self.stop.is_set():
                error=str(exc);notify('error',error);notify('status','采集失败，正在确认关灯；详情记录在 '+log_path.name)
        finally:
            if client:client.close()
            try:
                off=safe_off(self.args.bind,self.args.board,self.args.port);log('final_off',dict(status='ACK_CONFIRMED',ack=off))
                if out and (out/'session.json').exists():
                    record=json.loads((out/'session.json').read_text(encoding='utf-8'));record.update(final_off_status='ACK_CONFIRMED',final_off_ack=off);write_record(out/'session.json',record)
            except Exception as exc:
                error=(error+'；' if error else '')+'未确认关灯：'+str(exc);notify('error',error)
                if out and (out/'session.json').exists():
                    record=json.loads((out/'session.json').read_text(encoding='utf-8'));record.update(final_off_status='FAILED',final_off_error=str(exc));write_record(out/'session.json',record)
            if out and out.exists():
                try:pack_result(out)
                except Exception as exc:error=(error+'；' if error else '')+'打包失败：'+str(exc);notify('error',error)
                notify('result',out)
            notify('done',dict(mode=mode,failed=bool(error),error=error,log=str(log_path)))

    def show(self,widget,picture,key):
        photo=ImageTk.PhotoImage(picture);self.images[key]=photo;widget.config(image=photo,text='')

    def poll(self):
        # A finite amount of work per tick is essential: Tk must return to its event loop.
        deadline=time.perf_counter()+.008
        for _ in range(16):
            if time.perf_counter()>deadline:break
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='readback':self.readback.set(f'传感器读回：曝光 {value["exposure_lines"]:g} 行；增益 {value["gain_x"]:g}×；锁定={value["locked"]}；配置代数 {value["generation"]}')
            elif kind=='result':self.last_out=value
            elif kind=='error':
                self.operation_error=True;self.status.set('操作失败：'+value)
                if 'main' not in self.images:self.main.config(text='未收到完整图像：'+value,wraplength=1000)
            elif kind=='done':
                for item in self.buttons+self.inputs:item.config(state='normal')
                self.channel_input.config(state='readonly')
                if self.stop.is_set() and not value['failed']:self.status.set('已停止，关灯ACK已确认。')
                if value['failed']:self.status.set('操作失败：'+str(value['error'])+'；日志 '+str(value['log']))
                if self.closing:self.root.destroy();return
        main,cards,status=self.display.take()
        if status and not self.stop.is_set() and not self.operation_error:self.status.set(status)
        if main is not None:self.show(self.main,main,'main')
        for channel,(card,meta) in cards.items():
            self.show(self.cards[channel-1],card,'card'+str(channel));self.displayed_frames+=1;self.last_frame_id=meta.get('frame_id')
        self.root.after(40,self.poll)

    def cancel(self):self.stop.set();self.status.set('正在停止并确认关灯…')
    def open_result(self):
        if self.last_out:os.startfile(str(self.last_out))
    def close(self):
        if self.worker and self.worker.is_alive():self.closing=True;self.cancel()
        else:self.root.destroy()
