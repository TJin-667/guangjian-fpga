"""09 光鉴检测台：人工启动的采集、融合和结果查看界面。"""
import argparse
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
import capture_adapter as capture
import workflow
from common import read_json


class InspectionApp:
    def __init__(self, root, lab):
        self.root, self.lab = root, Path(lab).resolve()
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.worker, self.plan, self.result_path = None, None, None
        self.closing, self.photos = False, []
        root.title('光鉴 · BX72 0x0105 采集与四方向融合')
        root.geometry('1180x850')
        root.minsize(940, 700)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.configure('TLabel', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=5)
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='光鉴  /  定位 → 四方向采集 → 融合候选 → 人工复核',
                  font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='LED128 · 增益1× · CH1上 / CH2右 / CH3下 / CH4左；曝光单位：行。正式四图共用曝光。').pack(anchor='w', pady=(4, 8))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x')
        self.setup_buttons = []
        for title, file in [('预览摆放（06）', '06_preview_gui.cmd'), ('完整图定位（02）', '02_single_fullframe.cmd'), ('确认裁剪（03）', '03_single_roi.cmd')]:
            button = ttk.Button(toolbar, text=title, command=lambda f=file: self.launch_setup(f))
            button.pack(side='left', padx=(0, 6))
            self.setup_buttons.append(button)
        self.reload_button = ttk.Button(toolbar, text='重新载入本轮定位', command=self.reload)
        self.reload_button.pack(side='left')
        self.import_button = ttk.Button(toolbar, text='离线查看已有四方向ZIP', command=self.import_zip)
        self.import_button.pack(side='right')
        self.source_label = ttk.Label(outer, text='正在读取定位资料…', wraplength=1100)
        self.source_label.pack(fill='x', pady=8)
        options = ttk.Frame(outer)
        options.pack(fill='x')
        self.mode = tk.StringVar(value='固定600行（先验证此模式）')
        self.mode_box = ttk.Combobox(options, textvariable=self.mode, state='readonly', width=34,
                                   values=['固定600行（先验证此模式）', '本轮自动曝光锁定后再拍四方向'])
        self.mode_box.pack(side='left')
        self.confirm = tk.BooleanVar(value=False)
        self.confirm_button = ttk.Checkbutton(options, text='我已关闭预览，并确认工件/灯位/相机与本轮轮廓一致', variable=self.confirm)
        self.confirm_button.pack(side='left', padx=12)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=8)
        self.start_button = ttk.Button(controls, text='开始本轮检测（实际拍照）', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text='停止并保存', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.open_button = ttk.Button(controls, text='打开本轮结果目录', command=self.open_result, state='disabled')
        self.open_button.pack(side='right')
        self.status = tk.StringVar(value='就绪')
        ttk.Label(outer, textvariable=self.status, foreground='#125A7A', wraplength=1100).pack(fill='x', pady=(0, 5))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(0, 8))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.source_tab = ttk.Frame(self.tabs)
        self.original_tab = ttk.Frame(self.tabs)
        self.b1_tab, self.m1_tab, self.quality_tab = [ttk.Frame(self.tabs) for _ in range(3)]
        self.log_tab = ttk.Frame(self.tabs)
        for tab, label in [(self.source_tab, '定位预览'), (self.original_tab, '四方向原图'), (self.b1_tab, 'B1基线候选'),
                           (self.m1_tab, 'M1质量约束候选'), (self.quality_tab, '观测质量'), (self.log_tab, '过程与统计')]:
            self.tabs.add(tab, text=label)
        self.log = tk.Text(self.log_tab, wrap='word', height=12, font=('Consolas', 10))
        self.log.pack(fill='both', expand=True)
        ttk.Label(outer, text='红色：候选像素；洋红：缺少有效观测；橙色：至少一个方向RGB最大码风险。候选连通区域数不等于划痕条数。',
                  wraplength=1100).pack(anchor='w', pady=(8, 0))
        root.after(80, self.poll)
        root.after(100, self.reload)

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def set_running(self, value):
        state = 'disabled' if value else 'normal'
        for b in self.setup_buttons + [self.reload_button, self.import_button, self.confirm_button]:
            b.configure(state=state)
        self.mode_box.configure(state='disabled' if value else 'readonly')
        self.start_button.configure(state='disabled' if value or self.plan is None else 'normal')
        self.stop_button.configure(state='normal' if value else 'disabled')
        if value:
            self.progress.start(12)
        else:
            self.progress.stop()

    def clear_result(self):
        self.result_path = None
        self.open_button.configure(state='disabled')
        self.confirm.set(False)
        for tab in (self.original_tab, self.b1_tab, self.m1_tab, self.quality_tab):
            for child in tab.winfo_children():
                child.destroy()
        self.photos = []

    def dispatch(self, function):
        if self.busy():
            return
        self.cancel = threading.Event()
        self.set_running(True)
        def task():
            try:
                value = function()
                self.events.put(('done', value))
            except BaseException as exc:
                self.events.put(('error', str(exc)))
        self.worker = threading.Thread(target=task, daemon=False)
        self.worker.start()

    def notify(self, event, **data):
        self.events.put(('notice', (event, data)))

    def reload(self):
        if self.busy():
            return
        self.plan = None
        self.clear_result()
        self.source_label.configure(text='正在读取最新02/03并校验，不连接开发板…')
        self.status.set('读取定位资料')
        def read():
            try:
                plan, snapshot, _ = capture.prepare_plan(self.lab)
                return ('preflight', plan, snapshot, None)
            except Exception as exc:
                # Display the NEWEST full source only; never silently reuse an older sample.
                core = capture.legacy(self.lab).load_core(self.lab)
                try:
                    _, snapshot = core.prepare_plan(self.lab)
                except Exception:
                    snapshot = None
                return ('preflight', None, snapshot, str(exc))
        self.dispatch(read)

    def launch_setup(self, filename):
        if self.busy():
            return
        self.plan = None
        self.clear_result()
        self.status.set('已打开 '+filename+'；请在独立窗口操作并按提示退出，再返回此处。')
        def run():
            core = capture.legacy(self.lab).load_core(self.lab)
            # Original 02/03/06 do not lock themselves. Lock around OUR child to serialize against 07/08/09.
            with workflow.console_lock(self.lab), core.operator_lock(self.lab):
                p = subprocess.Popen([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(self.lab/filename)],
                                     cwd=self.lab, creationflags=subprocess.CREATE_NEW_CONSOLE)
                while p.poll() is None:
                    # Interactive console cancellation must be done there; never kill a running capture.
                    threading.Event().wait(0.2)
            return ('setup', p.returncode)
        self.dispatch(run)

    def start(self):
        if self.busy() or self.plan is None:
            return
        if not self.confirm.get():
            messagebox.showinfo('尚需人工确认', '请先关闭预览，并勾选本轮工件、轮廓和摆放一致。')
            return
        plan, automatic = self.plan, self.mode_box.current() == 1
        self.clear_result()
        self.log.delete('1.0', 'end')
        self.status.set('开始本轮采集，请保持摆放不动…')
        self.dispatch(lambda: ('result', workflow.execute(plan, automatic=automatic, confirmed_same_pose=True,
                                                        cancel=self.cancel, notify=self.notify)))

    def import_zip(self):
        if self.busy():
            return
        path = filedialog.askopenfilename(title='选择08生成的四方向原始ZIP', initialdir=self.lab/'results',
                                          filetypes=[('四方向数据ZIP', '*.zip')])
        if path:
            self.clear_result()
            self.status.set('离线核验中，不会连接开发板…')
            self.dispatch(lambda: ('result', workflow.import_existing(self.lab, path, cancel=self.cancel, notify=self.notify)))

    def image(self, parent, path, title='', limit=(540, 420)):
        frame = ttk.Frame(parent, padding=4)
        frame.pack(side='top', fill='both', expand=True)
        if title:
            ttk.Label(frame, text=title, wraplength=1080).pack(anchor='w')
        with Image.open(path) as source:
            im = source.convert('RGB')
            im.thumbnail(limit)
        photo = ImageTk.PhotoImage(im)
        self.photos.append(photo)
        label = ttk.Label(frame, image=photo, cursor='hand2')
        label.pack(expand=True)
        label.bind('<Button-1>', lambda event: self.full_image(path))

    def full_image(self, path):
        window = tk.Toplevel(self.root)
        window.title(Path(path).name+' · 100%像素，可滚动查看')
        window.geometry('950x750')
        frame = ttk.Frame(window)
        frame.pack(fill='both', expand=True)
        canvas = tk.Canvas(frame, background='#24292f')
        vertical = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=canvas.xview)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        with Image.open(path) as source:
            photo = ImageTk.PhotoImage(source.convert('RGB'))
        window.photo = photo
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.configure(scrollregion=(0, 0, photo.width(), photo.height()))
        return window

    def display_result(self, result):
        self.result_path = Path(result['output'])
        self.open_button.configure(state='normal')
        s = result['summary']
        self.log.insert('end', '\n'+__import__('json').dumps(s, ensure_ascii=False, indent=2)+'\n')
        analysis = self.result_path/'analysis'
        if 'analysis' not in s or not (analysis/'analysis_summary.json').exists():
            self.status.set('本轮未完成：'+s['status']+'；记录已保存，请查看过程与统计。')
            self.tabs.select(self.log_tab)
            return
        data = s['analysis']
        for tab in (self.original_tab, self.b1_tab, self.m1_tab, self.quality_tab):
            for child in tab.winfo_children():
                child.destroy()
        for i in range(2):
            row = ttk.Frame(self.original_tab)
            row.pack(fill='both', expand=True)
            for j in range(2):
                channel = 1+2*i+j
                cell = ttk.Frame(row)
                cell.pack(side='left', fill='both', expand=True)
                self.image(cell, analysis/('CH%d.png'%channel), 'CH%d %s（点击原尺寸查看）'%(channel, ['上','右','下','左'][channel-1]), (480, 235))
        for mode, tab in [('B1', self.b1_tab), ('M1', self.m1_tab)]:
            metrics = data['modes'][mode]
            text = '%s：候选%d像素，%d个连通区域；缺少有效观测%d像素。红色为候选，需人工复核。'%(
                mode, metrics['candidate_pixels'], metrics['candidate_connected_regions'], metrics['unobserved_board_pixels'])
            self.image(tab, analysis/(mode+'_overlay.png'), text, (1030, 490))
        self.image(self.quality_tab, analysis/'M1_quality.png', '洋红：四方向均无有效观测；橙色：至少一方向达到RGB最大码风险。风险像素没有全部直接删除。', (1030, 490))
        context = '离线回放' if s['status'].startswith('OFFLINE') else '本轮实拍'
        status = context+'完成：'+data['sample_id']+'，曝光'+str(data['exposure_lines'])+'行。B1/M1候选待复核，未作合格判定。'
        if s['status'] == 'ANALYZED_LIGHTS_OFF_UNCONFIRMED':
            status += ' 关灯未确认，请检查实际灯光。'
        self.status.set(status)
        self.tabs.select(self.b1_tab)

    def stop(self):
        self.cancel.set()
        self.status.set('正在停止并保存；采集流程会尝试关灯。若是02/03/06独立窗口，请在该窗口按提示退出。')

    def open_result(self):
        if self.result_path:
            os.startfile(str(self.result_path))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'notice':
                    event, data = value
                    if event == 'finished':
                        continue
                    if event == 'frame_saved':
                        # A new verified photo is visible while later directions are being captured.
                        self.image(self.original_tab, data['png'], 'CH%d 已保存 · %d行'%(data['channel'], data['exposure_lines']), (480, 115))
                        self.tabs.select(self.original_tab)
                        continue
                    if event == 'step':
                        text = '正式采集 CH%d / 4'%data['channel']
                    elif event == 'progress':
                        text = data.get('text', str(data))
                    else:
                        text = event+': '+str(data)
                    self.status.set(text)
                    self.log.insert('end', text+'\n')
                    self.log.see('end')
                elif kind == 'error':
                    self.worker = None
                    self.confirm.set(False)
                    self.set_running(False)
                    self.status.set('停止：'+value)
                    self.log.insert('end', '\nERROR: '+value+'\n')
                elif kind == 'done':
                    self.worker = None
                    self.confirm.set(False)
                    if value[0] == 'preflight':
                        _, self.plan, snapshot, error = value
                        for child in self.source_tab.winfo_children():
                            child.destroy()
                        if snapshot:
                            core = capture.legacy(self.lab).load_core(self.lab)
                            preview = core.source_preview(snapshot)
                            import io
                            # source_preview returns PNG bytes, already bound to the verified full source.
                            image_bytes = preview if isinstance(preview, bytes) else preview[0]
                            with Image.open(io.BytesIO(image_bytes)) as source:
                                im = source.convert('RGB')
                                im.thumbnail((1030, 490))
                            photo = ImageTk.PhotoImage(im)
                            self.source_photo = photo
                            ttk.Label(self.source_tab, image=photo).pack(expand=True)
                        if self.plan:
                            self.source_label.configure(text='工件 '+self.plan['sample_id']+'  ROI '+str(self.plan['roi'])+'  来源：'+self.plan['source'])
                            self.status.set('定位与03裁剪记录已匹配；请核对轮廓后勾选确认，再开始。')
                        else:
                            self.source_label.configure(text='尚未准备好：'+str(error))
                            self.status.set('请用02/03完成本轮定位与裁剪确认，再重新载入。')
                    elif value[0] == 'setup':
                        self.root.after(20, self.reload)
                    elif value[0] == 'result':
                        self.display_result(value[1])
                    self.set_running(False)
        except queue.Empty:
            pass
        except Exception as exc:
            # A bad preview/result image must not leave capture enabled or stop queue polling.
            self.plan = None
            self.confirm.set(False)
            self.set_running(self.busy())
            self.status.set('界面显示失败，已禁止开始；请重新载入。'+str(exc))
            self.log.insert('end', '\nDISPLAY ERROR: '+str(exc)+'\n')
        if self.closing and not self.busy():
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def close(self):
        if self.busy():
            self.closing = True
            self.stop()
        else:
            self.root.destroy()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root', type=Path, default=Path('C:/BX72_0105_LAB'))
    a = p.parse_args()
    root = tk.Tk()
    InspectionApp(root, a.lab_root)
    root.mainloop()


if __name__ == '__main__':
    main()
