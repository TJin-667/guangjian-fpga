"""Hold one light for manual focus, then save four 1080p illumination views.

The PC schedules commands; FPGA applies UART commands and checks controller
ACKs. Camera exposure/gain remain automatic in this first integration demo.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import uuid
import zipfile

from PIL import Image, ImageDraw
from focus_preview import CameraClient, Cancelled, Preview, rgb565_image, EXPECTED_BIT_SHA256
from protocol import LED_SET


def set_light(client, mask, brightness):
    if not 0 <= mask <= 15 or not 0 <= brightness <= 255:
        raise ValueError('灯光参数超出范围')
    deadline = time.monotonic() + 8
    while True:
        ack, _, _ = client.transact(LED_SET, (mask, brightness, 0, 0))
        if ack['result'] == 0:
            return ack
        if ack['result'] == 1 and time.monotonic() < deadline:
            if client.stop.wait(0.15):
                raise Cancelled()
            continue
        if ack['result'] == 4:
            raise RuntimeError('控制器未确认灯光命令：检查串口接线、控制器电源及模式；未收到成功 $ 或返回 &')
        raise RuntimeError(f'灯光设置被板卡拒绝：{ack}')


def wait_settle(client, seconds):
    if client.stop.wait(seconds):
        raise Cancelled()


def save_record(path, record):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def capture_four(client, out, sample, brightness=128, settle=1.0, on_event=None):
    """Fail closed: never label an image with a light that did not ACK.

    Discard a complete frame after each lighting change, because the producer
    may hold a frame from before that change. Save the following complete frame.
    """
    notify = on_event or (lambda *_: None)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    record = {
        'status': 'RUNNING', 'sample_id': sample,
        'started_at': datetime.now().astimezone().isoformat(),
        'firmware': 258, 'width': 1920, 'height': 1080,
        'candidate_bit_sha256': EXPECTED_BIT_SHA256,
        'bit_identity_note': 'local candidate hash, not FPGA readback',
        'encoding': 'RGB565 big-endian; camera ISP output, not sensor RAW',
        'brightness': brightness, 'settle_seconds': settle,
        'camera_exposure_gain': 'automatic; inherited stable camera configuration',
        'camera_register_readback': 'not implemented',
        'purpose': 'first integration demonstration; not calibrated fusion experiment',
        'channel_direction_mapping': 'not entered; physical directions labelled only by CH1..CH4',
        'freshness_policy': 'discard first complete frame after change, save next',
        'views': [], 'saved_frames': 0, 'total_capture_requests': 0,
        'total_complete_frames_received': 0,
    }
    path = out / 'session.json'
    save_record(path, record)
    try:
        for channel in range(1, 5):
            notify('status', f'CH{channel}：先关灯，再设置亮度 {brightness}/255')
            off_ack = set_light(client, 0, 0)
            on_ack = set_light(client, 1 << (channel - 1), brightness)
            item = {'channel': channel, 'mask': 1 << (channel - 1),
                    'brightness': brightness, 'off_ack': off_ack, 'on_ack': on_ack,
                    'status': 'CAPTURING'}
            record['views'].append(item)
            save_record(path, record)
            wait_settle(client, settle)
            notify('status', f'CH{channel}：丢弃缓存旧帧，再保存新帧')
            record['total_capture_requests'] += 1
            save_record(path, record)
            _, discarded = client.capture(frame_wait=8)
            record['total_complete_frames_received'] += 1
            item['discarded_frame'] = discarded
            save_record(path, record)
            record['total_capture_requests'] += 1
            save_record(path, record)
            raw, meta = client.capture(frame_wait=8)
            record['total_complete_frames_received'] += 1
            base = out / f'CH{channel}_brightness{brightness:03d}'
            base.with_suffix('.rgb565').write_bytes(raw)
            image = rgb565_image(raw)
            image.save(base.with_suffix('.png'))
            item.update(status='COMPLETE', frame=meta, png=base.name+'.png',
                        rgb565=base.name+'.rgb565', bytes=len(raw),
                        sha256_rgb565=hashlib.sha256(raw).hexdigest())
            record['saved_frames'] += 1
            save_record(path, record)
            notify('frame', (raw, {**meta, 'channel': channel}))
        record['status'] = 'PASS'
    except Exception as exc:
        record['status'] = 'CANCELLED' if isinstance(exc, Cancelled) else 'FAIL'
        if record['views'] and record['views'][-1]['status'] == 'CAPTURING':
            record['views'][-1]['status'] = record['status']
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        record['finished_at'] = datetime.now().astimezone().isoformat()
        save_record(path, record)
    return record


def make_overview(out):
    out = Path(out)
    canvas = Image.new('RGB', (960, 588), '#181818')
    draw = ImageDraw.Draw(canvas)
    for i in range(4):
        files = sorted(out.glob(f'CH{i+1}_*.png'))
        if not files:
            continue
        with Image.open(files[0]) as im:
            thumb = im.resize((480, 270), Image.Resampling.LANCZOS)
        x, y = (i % 2) * 480, (i // 2) * 294
        draw.text((x+8, y+6), f'CH{i+1} - preview only', fill='white')
        canvas.paste(thumb, (x, y+24))
    canvas.save(out / 'overview_preview_only.png')


def zip_result(out):
    out = Path(out)
    result = out.with_suffix('.zip')
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in out.rglob('*'):
            if path.is_file():
                z.write(path, path.relative_to(out.parent))
    return result


class Demo(Preview):
    def __init__(self, root, args):
        super().__init__(root, args)
        self.events = queue.Queue(maxsize=32)
        self.closing = False
        self.mode = 'idle'
        self.config = None
        root.title('光鉴 · 单灯调焦与四方向1080p采集（首版联调）')
        self.start_button.config(text='① 单灯调焦预览')
        self.status_text.set('先下载本包新 bit，再手动断开 Cisco VPN。')
        self.light_channel = tk.StringVar(value='1')
        self.light_brightness = tk.StringVar(value='128')
        self.sample = tk.StringVar(value='sample001')
        self.phase = tk.StringVar(value='未运行；首次演示保留自动曝光/增益')
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill='x', before=self.start_button.master)
        ttk.Label(bar, text='调焦通道').pack(side='left')
        self.channel_box = ttk.Combobox(bar, width=3, state='readonly',
                                       values=('1','2','3','4'), textvariable=self.light_channel)
        self.channel_box.pack(side='left', padx=4)
        ttk.Label(bar, text='亮度 0–255').pack(side='left')
        self.brightness_box = ttk.Spinbox(bar, from_=0, to=255, width=5,
                                         textvariable=self.light_brightness)
        self.brightness_box.pack(side='left', padx=4)
        ttk.Label(bar, text='工件编号').pack(side='left')
        self.sample_box = ttk.Entry(bar, width=16, textvariable=self.sample)
        self.sample_box.pack(side='left', padx=4)
        self.stop_button = ttk.Button(bar, text='② 停止预览并关灯', command=self.stop_preview)
        self.stop_button.pack(side='left', padx=6)
        self.batch_button = ttk.Button(bar, text='③ 自动拍四张图', command=self.start_batch)
        self.batch_button.pack(side='left', padx=4)
        ttk.Label(root, textvariable=self.phase, padding=8).pack(fill='x')

    def parameters(self):
        brightness = int(self.light_brightness.get())
        channel = int(self.light_channel.get())
        if not 1 <= channel <= 4 or not 0 <= brightness <= 255:
            raise ValueError('通道应为 1–4，亮度应为 0–255')
        sample = self.sample.get().strip()
        if not sample or not re.fullmatch(r'[\w-]{1,48}', sample):
            raise ValueError('工件编号只能使用文字、数字、下划线或短横线，最长48字')
        return channel, brightness, sample

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def controls(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.start_button.config(state=state)
        self.batch_button.config(state=state)
        self.channel_box.config(state='readonly' if enabled else 'disabled')
        self.brightness_box.config(state=state)
        self.sample_box.config(state=state)

    def start(self):
        if self.running():
            return
        try:
            self.config = self.parameters()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror('参数错误', str(exc));return
        self.mode = 'focus'
        self.reset_best()
        self.controls(False)
        super().start()

    def stop_preview(self):
        if self.running():
            self.stop_event.set()
            self.status_text.set('正在停止；等待当前抓帧结束并发送全关命令…')

    def start_batch(self):
        if self.running():
            messagebox.showinfo('先停止预览', '先点击“停止预览并关灯”，等结束后再拍四张图。');return
        try:
            self.config = self.parameters()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror('参数错误', str(exc));return
        self.mode = 'batch'
        self.stop_event.clear();self.pause_event.clear()
        self.controls(False)
        self.pause_button.config(state='disabled')
        self.worker = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker.start()

    def cleanup_lights(self):
        cleanup = CameraClient(self.args.bind, self.args.board, self.args.port, threading.Event())
        try:
            return set_light(cleanup, 0, 0)
        finally:
            cleanup.close()

    def capture_loop(self):
        client = None
        out = None
        record = None
        failures = []
        try:
            channel, brightness, sample = self.config
            client = CameraClient(self.args.bind, self.args.board, self.args.port, self.stop_event)
            status = client.ready()
            if not status['capabilities'] & 16:
                raise RuntimeError('板上程序没有可确认的灯光控制功能，请下载本包新 bit')
            if self.mode == 'focus':
                set_light(client, 0, 0)
                set_light(client, 1 << (channel-1), brightness)
                wait_settle(client, self.args.settle)
                client.capture(frame_wait=8)  # release a possibly stale frame
                self.post('status', f'CH{channel} 保持常亮；缓慢转镜头，观察右侧1:1细节')
                while not self.stop_event.is_set():
                    if self.pause_event.is_set():
                        self.stop_event.wait(0.1);continue
                    raw, meta = client.capture(frame_wait=8)
                    self.post('frame', (raw, {**meta, 'channel': channel}))
            else:
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                out = Path(__file__).resolve().parents[1] / 'results' / f'BX72_4LIGHT_{sample}_{stamp}_{uuid.uuid4().hex[:6]}'
                out.parent.mkdir(parents=True, exist_ok=True)
                record = capture_four(client, out, sample, brightness, self.args.settle, self.post)
        except Cancelled:
            self.post('status', '采集已停止')
        except Exception as exc:
            failures.append(f'{type(exc).__name__}: {exc}')
            self.post('error', failures[-1])
        finally:
            if client:
                client.close()
            try:
                off_ack = self.cleanup_lights()
                cleanup_status = {'status': 'ACK_CONFIRMED', 'ack': off_ack}
            except Exception as exc:
                cleanup_status = {'status': 'UNCONFIRMED', 'error': str(exc)}
                self.post('error', '关灯未获确认，请用控制器面板关闭灯光：'+str(exc))
            if out and out.exists():
                try:
                    path = out / 'session.json'
                    report = json.loads(path.read_text(encoding='utf-8'))
                    report['final_lights_off'] = cleanup_status
                    if cleanup_status['status'] != 'ACK_CONFIRMED' and report['status'] == 'PASS':
                        report['status'] = 'FAIL';report['error'] = 'final lights-off unconfirmed'
                    save_record(path, report)
                    make_overview(out)
                    zip_path = zip_result(out)
                    self.post('result', (report['status'], str(out), str(zip_path)))
                except Exception as exc:
                    self.post('error', f'结果打包失败：{exc}；已有文件在 {out}')
            self.post('stopped', None)

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'frame':
                    raw, meta = payload
                    self.latest = (raw, rgb565_image(raw), meta)
                    self.save_button.config(state='normal')
                    self.redraw(new_frame=True)
                    self.phase.set(f"当前 CH{meta.get('channel', '?')}；{self.mode}；完整1080p帧 {meta['frame_id']}")
                elif kind == 'status':
                    self.status_text.set(payload)
                elif kind == 'error':
                    self.status_text.set(payload)
                    if not self.closing:messagebox.showerror('联调提示', payload)
                elif kind == 'result':
                    status, directory, zip_path = payload
                    self.phase.set(f'{status}：结果 {directory}')
                    self.status_text.set(f'结果ZIP：{zip_path}')
                    if not self.closing:
                        messagebox.showinfo('四方向结果', f'{status}\n原图目录：{directory}\n发给GPT：{zip_path}')
                elif kind == 'stopped':
                    self.controls(True)
                    self.pause_button.config(state='disabled', text='暂停')
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def close(self):
        self.closing = True
        self.stop_event.set()
        self.status_text.set('正在关灯并退出…')
        def finish():
            if self.running():
                self.root.after(100, finish)
            else:
                self.closed = True
                self.root.destroy()
        finish()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind', default='192.168.0.3')
    p.add_argument('--board', default='192.168.0.2')
    p.add_argument('--port', type=int, default=5000)
    p.add_argument('--settle', type=float, default=1.0)
    args = p.parse_args()
    if not 0.1 <= args.settle <= 10:
        p.error('settle must be between 0.1 and 10 seconds')
    root = tk.Tk()
    Demo(root, args)
    root.mainloop()


if __name__ == '__main__':
    main()
