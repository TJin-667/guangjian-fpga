"""Small operator UI for the fixed CH1 manual experiment (standard library)."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from manual_camera import ManualCameraClient,capture_three,validate_values


class ManualPanel:
    def __init__(self,root,args):
        self.root=root;self.args=args;self.events=queue.Queue();self.stop=threading.Event()
        self.worker=None;self.closing=False;self.image=None
        root.title('光鉴 · CH1 手动曝光与增益读回');root.geometry('980x720')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.exposure=tk.StringVar(value='100');self.brightness=tk.StringVar(value='128')
        self.sample=tk.StringVar(value='sample001');self.status=tk.StringVar(value='默认100行、1×增益；先下载本包0x0104 ROI候选bit。')
        bar=ttk.Frame(root,padding=10);bar.pack(fill='x')
        ttk.Label(bar,text='曝光（行）').pack(side='left')
        self.exposure_box=ttk.Spinbox(bar,from_=1,to=1116,increment=25,width=7,textvariable=self.exposure)
        self.exposure_box.pack(side='left',padx=5)
        ttk.Label(bar,text='增益固定1×（gain16=16）   CH1亮度').pack(side='left',padx=8)
        self.brightness_box=ttk.Spinbox(bar,from_=1,to=255,width=5,textvariable=self.brightness)
        self.brightness_box.pack(side='left',padx=5)
        ttk.Label(bar,text='工件编号').pack(side='left',padx=5)
        self.sample_box=ttk.Entry(bar,textvariable=self.sample,width=16);self.sample_box.pack(side='left')
        actions=ttk.Frame(root,padding=10);actions.pack(fill='x')
        self.buttons=[]
        for label,kind in (('读取当前寄存器','read'),('应用曝光并读回（CH1保持亮）','set'),
                           ('保存CH1同条件三张','three'),('关灯','off')):
            b=ttk.Button(actions,text=label,command=lambda k=kind:self.launch(k));b.pack(side='left',padx=4);self.buttons.append(b)
        ttk.Label(root,textvariable=self.status,wraplength=950,padding=10).pack(fill='x')
        self.photo=ttk.Label(root,text='保存三张后显示最后一张缩略图；原图保留1920×1080。');self.photo.pack(fill='both',expand=True)
        self.details=tk.Text(root,height=10,wrap='word');self.details.pack(fill='x',padx=10,pady=10)
        root.after(100,self.poll)
    def launch(self,kind):
        if self.worker and self.worker.is_alive():return
        try:
            exposure,brightness=100,128
            if kind in ('set','three'):
                exposure=int(self.exposure.get());brightness=int(self.brightness.get())
                validate_values(exposure,16,brightness)
        except ValueError as exc:messagebox.showerror('参数错误',str(exc));return
        self.stop.clear();self.status.set('正在与板卡通信，请等待读回确认。')
        for item in self.buttons+[self.exposure_box,self.brightness_box,self.sample_box]:item.config(state='disabled')
        self.worker=threading.Thread(target=self.run,args=(kind,exposure,brightness,self.sample.get()),daemon=False)
        self.worker.start()
    def run(self,kind,exposure,brightness,sample):
        client=None;successful=False
        try:
            client=ManualCameraClient(self.args.bind,self.args.board,self.args.port,self.stop)
            # Off remains available even when camera initialization has failed.
            if kind=='off':result={'off_ack':client.light(0,0)}
            elif kind=='three':
                out=self.args.results/('CH1_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                result=capture_three(client,out,sample,exposure,16,brightness)
                result['output_directory']=str(out.resolve())
            else:
                client.ready()
                if kind=='set':
                    client.light(0,0);client.light(1,brightness)
                    result=client.camera(exposure,16)
                else:result=client.camera()
            successful=True;self.events.put(('result',kind,result))
        except Exception as exc:self.events.put(('error',kind,str(exc)))
        finally:
            if client is not None:
                if self.closing or (kind=='set' and not successful):
                    self.stop.clear()
                    try:client.light(0,0)
                    except Exception as exc:self.events.put(('off_error',kind,str(exc)))
                client.close()
            self.events.put(('done',kind,None))
    def poll(self):
        while True:
            try:kind,action,result=self.events.get_nowait()
            except queue.Empty:break
            if kind=='result':
                self.details.delete('1.0','end');self.details.insert('end',json.dumps(result,ensure_ascii=False,indent=2))
                if action=='three':
                    out=Path(result['output_directory']);self.image=tk.PhotoImage(file=str(out/'CH1_repeat03.png')).subsample(3)
                    self.photo.config(image=self.image,text='')
                    self.status.set(f'三张完整照片已保存，关灯已确认；请检查划痕、白斑、暗区稳定性。目录：{out}')
                elif action=='off':self.status.set('关灯命令已收到控制器确认；现场核对灯已灭。')
                elif result['locked']:
                    self.status.set(f'传感器读回：曝光{result["exposure_lines"]:g}行、增益{result["gain_x"]:g}×、0x3503=0x{result["mode"]:02X}。')
                else:self.status.set('已读到寄存器，但尚无有效的用户设置锁定；请应用曝光并读回。')
            elif kind in ('error','off_error'):
                self.status.set(('关灯未确认，请手动关灯：' if kind=='off_error' else '操作失败，不能视为参数已生效：')+str(result))
                self.details.insert('end','\n'+str(result))
                if self.closing:messagebox.showerror('关闭前检查',self.status.get())
            elif kind=='done':
                if self.closing:self.root.destroy();return
                for item in self.buttons+[self.exposure_box,self.brightness_box,self.sample_box]:item.config(state='normal')
        self.root.after(100,self.poll)
    def close(self):
        self.closing=True
        if self.worker and self.worker.is_alive():
            self.stop.set();self.status.set('正在取消操作并尝试确认关灯，请等待。')
        else:self.launch('off')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bind',default='192.168.0.3');ap.add_argument('--board',default='192.168.0.2')
    ap.add_argument('--port',type=int,default=6000);ap.add_argument('--results',type=Path,default=Path('results_manual'))
    args=ap.parse_args();root=tk.Tk();ManualPanel(root,args);root.mainloop()


if __name__=='__main__':main()
