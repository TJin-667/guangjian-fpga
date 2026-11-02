"""Manual-focus preview for the existing BX72 1080p DDR3/UDP snapshot bit.

This requests complete frames repeatedly. It does not claim video-rate streaming.
The focus score is useful only for the same scene, ROI, exposure, and illumination.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import secrets
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageFilter, ImageTk

from protocol import ACK, CAPTURE, FRAME_DATA, STATUS, STATUS_QUERY
from protocol import FrameReceiver, command, control, parse_frame


WIDTH = 1920
HEIGHT = 1080
FRAME_BYTES = WIDTH * HEIGHT * 2
FRAME_PACKETS = 3006
EXPECTED_FIRMWARE = 258
EXPECTED_BIT_SHA256 = "F5367A73402B29EC03E477AE3FD7B6312A810DD173AC800698F10B98159B4A98"


class Cancelled(Exception):
    pass


class CameraClient:
    def __init__(self, bind: str, board: str, port: int, stop: threading.Event):
        self.endpoint = (board, port)
        self.stop = stop
        self.seq = secrets.randbelow(65536)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
            self.sock.bind((bind, 0))
        except Exception:
            self.sock.close()
            raise

    def close(self):
        self.sock.close()

    def receive(self, deadline: float) -> bytes:
        while True:
            if self.stop.is_set():
                raise Cancelled()
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise TimeoutError("等待板卡响应超时")
            self.sock.settimeout(min(remain, 0.2))
            try:
                data, peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            if peer == self.endpoint:
                return data

    def transact(self, kind: int, args=(0, 0, 0, 0)):
        self.seq = (self.seq + 1) & 0xFFFF
        request = command(kind, self.seq, args)
        buffered = []
        status = None
        for _ in range(3):
            self.sock.sendto(request, self.endpoint)
            deadline = time.monotonic() + 1.0
            while True:
                try:
                    data = self.receive(deadline)
                except TimeoutError:
                    break
                if len(data) >= 6 and data[5] == FRAME_DATA:
                    if len(buffered) < FRAME_PACKETS:
                        buffered.append(data)
                    continue
                try:
                    reply = control(data)
                except ValueError:
                    continue
                if reply["type"] == STATUS and reply["seq"] == self.seq:
                    status = reply
                if (reply["type"] == ACK and reply["seq"] == self.seq
                        and reply["original"] == kind):
                    return reply, buffered, status
        raise TimeoutError(f"命令 {kind} 没有收到 ACK")

    def ready(self, config_wait: float = 20.0):
        deadline = time.monotonic() + config_wait
        while time.monotonic() < deadline:
            ack, _, status = self.transact(STATUS_QUERY)
            if ack["result"] != 0:
                raise RuntimeError(f"STATUS 查询失败：{ack}")
            if status is None:
                status_deadline = time.monotonic() + 1.0
                while status is None:
                    data = self.receive(status_deadline)
                    try:
                        reply = control(data)
                    except ValueError:
                        continue
                    if reply["type"] == STATUS and reply["seq"] == self.seq:
                        status = reply
            if status["firmware"] != EXPECTED_FIRMWARE:
                raise RuntimeError(
                    f"板上程序版本为 {status['firmware']}，预览工具要求 {EXPECTED_FIRMWARE}；"
                    "请重新下载本包 BX72_1080P_4LIGHT_DEMO.bit。"
                )
            if status["capabilities"] & 8 == 0:
                raise RuntimeError("板上程序没有相机抓拍能力")
            if status["state"] & 16:
                return status
            self.stop.wait(0.5)
        raise TimeoutError("相机配置 20 秒内没有就绪")

    def capture(self, frame_wait: float = 5.0):
        started = time.monotonic()
        ack, buffered, _ = self.transact(CAPTURE, (2, WIDTH, HEIGHT, 0))
        if ack["result"] != 0:
            raise RuntimeError(f"CAPTURE 被拒绝：{ack}")
        frame_id = ack["frame_id"]
        receiver = FrameReceiver(frame_wait, max_bytes=FRAME_BYTES)
        deadline = time.monotonic() + frame_wait
        while True:
            try:
                data = buffered.pop(0) if buffered else self.receive(deadline)
            except TimeoutError as exc:
                missing = receiver.missing()
                raise TimeoutError(
                    f"帧 {frame_id} 未收齐：已收 {FRAME_PACKETS - len(missing) if receiver.meta else 0}"
                    f"/{FRAME_PACKETS} 包"
                ) from exc
            if len(data) < 6 or data[5] != FRAME_DATA:
                continue
            try:
                fid, _, _, width, height, _ = parse_frame(data)
            except ValueError:
                continue
            if fid != frame_id:
                continue
            if (width, height) != (WIDTH, HEIGHT):
                raise RuntimeError(f"收到错误尺寸：{width}×{height}")
            raw = receiver.add(data, frame_id)
            if raw is not None:
                if len(raw) != FRAME_BYTES or receiver.meta[1] != FRAME_PACKETS:
                    raise RuntimeError("完整帧的字节数或包数不符")
                return raw, {
                    "frame_id": frame_id,
                    "packets": receiver.meta[1],
                    "duplicates": receiver.duplicates,
                    "elapsed_s": round(time.monotonic() - started, 3),
                    "received_at": datetime.now().astimezone().isoformat(),
                }


def rgb565_image(raw: bytes) -> Image.Image:
    if len(raw) != FRAME_BYTES:
        raise ValueError(f"RGB565 长度不符：{len(raw)}")
    values = np.frombuffer(raw, dtype=">u2").reshape(HEIGHT, WIDTH)
    rgb = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    red = (values >> 11) & 31
    green = (values >> 5) & 63
    blue = values & 31
    rgb[:, :, 0] = (red << 3) | (red >> 2)
    rgb[:, :, 1] = (green << 2) | (green >> 4)
    rgb[:, :, 2] = (blue << 3) | (blue >> 2)
    return Image.fromarray(rgb, "RGB")


def focus_measure(image: Image.Image, center: tuple[int, int], roi=(320, 240)):
    half_w, half_h = roi[0] // 2, roi[1] // 2
    x = max(0, min(WIDTH - roi[0], center[0] - half_w))
    y = max(0, min(HEIGHT - roi[1], center[1] - half_h))
    crop = image.crop((x, y, x + roi[0], y + roi[1]))
    gray = np.asarray(crop.convert("L").filter(ImageFilter.GaussianBlur(1.0)),
                      dtype=np.float32)
    laplace = 4 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1]
    laplace -= gray[1:-1, :-2] + gray[1:-1, 2:]
    score = float(laplace.var())
    original = np.asarray(crop.convert("L"))
    clipped = float(np.mean((original <= 5) | (original >= 250))) * 100
    return crop, (x, y, x + roi[0], y + roi[1]), score, clipped


class Preview:
    def __init__(self, root: tk.Tk, args):
        self.root = root
        self.args = args
        self.events = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.worker = None
        self.latest = None
        self.focus_center = (WIDTH // 2, HEIGHT // 2)
        self.best_score = None
        self.last_frame_time = None
        self.last_display = None
        self.closed = False
        root.title("BX72 · 1080p 手动调焦预览（完整帧连续抓拍）")
        root.geometry("1400x860")
        root.minsize(1050, 650)
        root.protocol("WM_DELETE_WINDOW", self.close)

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.start_button = ttk.Button(top, text="开始预览", command=self.start)
        self.start_button.pack(side="left", padx=3)
        self.pause_button = ttk.Button(top, text="暂停", command=self.pause,
                                       state="disabled")
        self.pause_button.pack(side="left", padx=3)
        self.save_button = ttk.Button(top, text="保存当前完整帧", command=self.save,
                                      state="disabled")
        self.save_button.pack(side="left", padx=3)
        ttk.Button(top, text="清除最佳分数", command=self.reset_best).pack(
            side="left", padx=3)
        self.status_text = tk.StringVar(value="准备就绪。先断开 Cisco VPN，并确认板上已下载 1080p UDP bit。")
        ttk.Label(top, textvariable=self.status_text).pack(side="left", padx=14)

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.Frame(body)
        right = ttk.Frame(body, width=390)
        body.add(left, weight=3)
        body.add(right, weight=1)
        self.canvas = tk.Canvas(left, bg="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.select_focus)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

        ttk.Label(right, text="调焦区域：点击左侧图像选择", font=("", 12)).pack(
            anchor="w", pady=(4, 8))
        self.crop_label = ttk.Label(right)
        self.crop_label.pack(anchor="w")
        self.score_text = tk.StringVar(value="清晰度分数：等待图像")
        ttk.Label(right, textvariable=self.score_text, font=("", 12)).pack(
            anchor="w", pady=(12, 4))
        self.clip_text = tk.StringVar(value="过暗/过亮像素：—")
        ttk.Label(right, textvariable=self.clip_text).pack(anchor="w")
        self.frame_text = tk.StringVar(value="帧号：—")
        ttk.Label(right, textvariable=self.frame_text).pack(anchor="w", pady=(8, 4))
        ttk.Label(
            right,
            text="每次显示的是完整 1920×1080 抓帧，右侧为原始像素裁切。\n"
                 "固定样品、灯光、曝光后，缓慢旋转镜头；同一区域分数\n"
                 "越高通常越清楚。纹理、噪声、反光也会影响分数。\n"
                 "此工具不控制镜头，也不判断缺陷。",
            justify="left", wraplength=380,
        ).pack(anchor="w", pady=(18, 0))
        self.root.after(80, self.poll)

    def post(self, kind, payload):
        try:
            self.events.put_nowait((kind, payload))
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            self.events.put_nowait((kind, payload))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.start_button.config(state="disabled")
        self.pause_button.config(state="normal", text="暂停")
        self.status_text.set("正在连接板卡…")
        self.worker = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker.start()

    def pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.config(text="暂停")
        else:
            self.pause_event.set()
            self.pause_button.config(text="继续")

    def capture_loop(self):
        client = None
        try:
            client = CameraClient(self.args.bind, self.args.board,
                                  self.args.port, self.stop_event)
            status = client.ready()
            self.post("status", f"相机已就绪；STATUS error={status['error']}，dropped={status['dropped']}")
            failures = 0
            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    self.stop_event.wait(0.1)
                    continue
                try:
                    raw, meta = client.capture()
                    failures = 0
                    self.post("frame", (raw, meta))
                except (TimeoutError, RuntimeError, ValueError) as exc:
                    failures += 1
                    self.post("status", f"抓帧失败 {failures} 次：{exc}")
                    if failures >= 3:
                        raise RuntimeError("连续三次失败；请检查网络/板卡，必要时重新下载 bit")
                    self.stop_event.wait(0.5)
        except Cancelled:
            pass
        except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
            self.post("error", f"{type(exc).__name__}: {exc}")
        finally:
            if client:
                client.close()
            self.post("stopped", None)

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "frame":
                    raw, meta = payload
                    try:
                        self.latest = (raw, rgb565_image(raw), meta)
                        self.save_button.config(state="normal")
                        self.redraw(new_frame=True)
                    except (ValueError, MemoryError) as exc:
                        self.status_text.set(f"图像解码失败：{exc}")
                elif kind == "status":
                    self.status_text.set(payload)
                elif kind == "error":
                    self.status_text.set(payload)
                    messagebox.showerror("预览失败", payload)
                elif kind == "stopped":
                    self.start_button.config(state="normal")
                    self.pause_button.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def redraw(self, new_frame=False):
        if self.latest is None:
            return
        _, image, meta = self.latest
        cw = max(self.canvas.winfo_width(), 2)
        ch = max(self.canvas.winfo_height(), 2)
        scale = min(cw / WIDTH, ch / HEIGHT)
        dw, dh = max(1, int(WIDTH * scale)), max(1, int(HEIGHT * scale))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        display = image.resize((dw, dh), Image.Resampling.BILINEAR)
        self.last_display = ImageTk.PhotoImage(display)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.last_display, anchor="nw")
        crop, bounds, score, clipped = focus_measure(image, self.focus_center)
        self.crop_photo = ImageTk.PhotoImage(crop)
        self.crop_label.config(image=self.crop_photo)
        x1, y1, x2, y2 = bounds
        self.canvas.create_rectangle(ox + x1 * scale, oy + y1 * scale,
                                     ox + x2 * scale, oy + y2 * scale,
                                     outline="#ffdf00", width=2)
        if self.best_score is None or score > self.best_score:
            self.best_score = score
        self.score_text.set(f"清晰度分数：{score:.1f}    本次最佳：{self.best_score:.1f}")
        self.clip_text.set(f"所选区域过暗/过亮像素：{clipped:.1f}%")
        if new_frame:
            now = time.monotonic()
            interval = "—" if self.last_frame_time is None else f"{now - self.last_frame_time:.2f} 秒"
            self.last_frame_time = now
            self.frame_text.set(
                f"帧号：{meta['frame_id']}    收包：{meta['packets']}    重复：{meta['duplicates']}\n"
                f"板卡抓帧耗时：{meta['elapsed_s']:.2f} 秒    画面间隔：{interval}"
            )
            self.status_text.set("预览中：完整抓帧成功")
        self.display_geometry = (ox, oy, scale)

    def select_focus(self, event):
        if self.latest is None or not hasattr(self, "display_geometry"):
            return
        ox, oy, scale = self.display_geometry
        x = int((event.x - ox) / scale)
        y = int((event.y - oy) / scale)
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.focus_center = (x, y)
            self.reset_best()

    def reset_best(self):
        self.best_score = None
        if self.latest is not None:
            self.redraw()

    def save(self):
        if self.latest is None:
            return
        raw, image, meta = self.latest
        directory = filedialog.askdirectory(title="选择保存目录")
        if not directory:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(directory) / f"BX72_focus_{stamp}_frame{meta['frame_id']}"
        image.save(base.with_suffix(".png"))
        base.with_suffix(".rgb565").write_bytes(raw)
        _, bounds, score, clipped = focus_measure(image, self.focus_center)
        record = {
            "scope": "full_1080p_manual_focus_preview_snapshot",
            "width": WIDTH, "height": HEIGHT, "encoding": "RGB565 big-endian",
            "candidate_bit_sha256": EXPECTED_BIT_SHA256,
            "bit_identity_note": "local candidate hash, not independent FPGA readback",
            "frame": meta, "focus_roi_xyxy": bounds,
            "focus_score_laplacian_variance": score,
            "focus_roi_clipped_percent": clipped,
            "focus_score_note": "relative within same ROI, scene, exposure and lighting",
        }
        base.with_suffix(".json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        self.status_text.set(f"已保存完整帧：{base.name}")

    def close(self):
        self.closed = True
        self.stop_event.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="192.168.0.3", help="电脑直连网卡 IPv4")
    parser.add_argument("--board", default="192.168.0.2", help="板卡 IPv4")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    root = tk.Tk()
    Preview(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
