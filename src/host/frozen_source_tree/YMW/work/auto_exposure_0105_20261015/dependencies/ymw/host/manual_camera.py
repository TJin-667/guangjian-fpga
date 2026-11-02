"""Explicit manual exposure/gain and CH1 three-frame review. No automatic tuning.

Uses only the Python standard library; no NumPy/Pillow dependency is required.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import zipfile

from protocol import (ACK, CAPTURE, CAMERA_GET, CAMERA_SET, CAMERA_STATUS,
                      FRAME_DATA, FrameReceiver, LED_SET, MANUAL_CAPABILITY,
                      STATUS, STATUS_QUERY, command, control, parse_frame, save_png)
from udp_client import CameraClient

FIRMWARE=0x0104
WIDTH,HEIGHT=1920,1080
FRAME_BYTES=WIDTH*HEIGHT*2


def validate_values(exposure_lines, gain16, brightness):
    if not isinstance(exposure_lines,int) or not 1<=exposure_lines<=1116:
        raise ValueError('曝光须为1–1116个整行周期（本1080p配置VTS=1120）')
    if not isinstance(gain16,int) or not 16<=gain16<=1023:
        raise ValueError('增益寄存器值gain16须为16–1023；16代表1倍，32代表2倍')
    if not isinstance(brightness,int) or not 1<=brightness<=255:
        raise ValueError('CH1亮度须为1–255')


class ManualCameraClient(CameraClient):
    def request(self, kind, args=(0,0,0,0), extra=None):
        self.seq=(self.seq+1)&65535
        request=command(kind,self.seq,args)
        ack=reply=None
        # Retry the same request identity. The RTL caches the completed snapshot.
        for _ in range(3):
            self.sock.sendto(request,self.endpoint)
            deadline=time.monotonic()+1.5
            while True:
                try:data=self.receive(deadline)
                except TimeoutError:break
                try:item=control(data)
                except ValueError:continue
                if item['seq']!=self.seq:continue
                if item['type']==ACK and item['original']==kind:ack=item
                elif extra is not None and item['type']==extra:reply=item
                if ack is not None:
                    if ack['result'] not in (0,5) or extra is None:return ack,reply
                    if reply is not None:return ack,reply
        raise TimeoutError(f'命令{kind}未收到完整ACK/读回响应；不能视为设置成功')

    def ready(self, timeout=20):
        deadline=time.monotonic()+timeout
        while True:
            ack,status=self.request(STATUS_QUERY,extra=STATUS)
            if ack['result'] or status is None:raise RuntimeError(f'STATUS失败：{ack}')
            if status['firmware']!=FIRMWARE or not status['capabilities']&MANUAL_CAPABILITY:
                raise RuntimeError(f'当前固件{status["firmware"]}不支持本手动读回协议；需要0x0104 ROI候选，旧0x0102不能使用')
            if status['state']&16:return status
            if time.monotonic()>=deadline:raise TimeoutError('相机/DDR初始化未就绪')
            if self.stop.wait(.2):raise RuntimeError('Cancelled')

    def camera(self, exposure_lines=None, gain16=None):
        kind=CAMERA_GET if exposure_lines is None else CAMERA_SET
        args=(0,0,0,0) if kind==CAMERA_GET else (exposure_lines,gain16,0,0)
        if kind==CAMERA_SET:validate_values(exposure_lines,gain16,1)
        deadline=time.monotonic()+8
        while True:
            ack,snapshot=self.request(kind,args,extra=CAMERA_STATUS)
            if ack['result']==1 and time.monotonic()<deadline:
                if self.stop.wait(.1):raise RuntimeError('Cancelled')
                continue
            if ack['result'] or snapshot is None or snapshot['error']:
                raise RuntimeError(f'相机操作失败，参数未确认：ACK={ack}，读回={snapshot}')
            if kind==CAMERA_SET and (not snapshot['locked'] or
                    snapshot['exposure_lines']!=exposure_lines or snapshot['gain16']!=gain16):
                raise RuntimeError(f'请求参数与传感器读回不一致：{snapshot}')
            return snapshot

    def light(self, mask, brightness):
        deadline=time.monotonic()+8
        while True:
            ack,_=self.request(LED_SET,(mask,brightness,0,0))
            if ack['result']==0:return ack
            if ack['result']==1 and time.monotonic()<deadline:
                if self.stop.wait(.1):raise RuntimeError('Cancelled')
                continue
            raise RuntimeError(f'灯控未确认：{ack}')

    def capture(self, frame_wait=8):
        # Capture sends no new camera setting and never changes illumination.
        ack,buffered,_=self.transact(CAPTURE,(2,WIDTH,HEIGHT,0))
        if ack['result']:raise RuntimeError(f'CAPTURE被拒绝：{ack}')
        receiver=FrameReceiver(frame_wait,max_bytes=FRAME_BYTES)
        deadline=time.monotonic()+frame_wait
        while True:
            data=buffered.pop(0) if buffered else self.receive(deadline)
            if len(data)<6 or data[5]!=FRAME_DATA:continue
            try:fid,_,_,width,height,_=parse_frame(data)
            except ValueError:continue
            if fid!=ack['frame_id']:continue
            if (width,height)!=(WIDTH,HEIGHT):raise RuntimeError('图像尺寸不符')
            raw=receiver.add(data,fid)
            if raw is not None:
                if len(raw)!=FRAME_BYTES or receiver.meta[1]!=3006:raise RuntimeError('帧长度/包数不符')
                return raw,dict(frame_id=fid,packets=3006,duplicates=receiver.duplicates,
                                received_at=datetime.now().astimezone().isoformat())


def same_lock(snapshot, expected):
    return (snapshot['locked'] and snapshot['error']==0 and
            snapshot['generation']==expected['generation'] and
            snapshot['raw_registers']==expected['raw_registers'])


def write_record(path, record):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def capture_three(client, out, sample, exposure_lines, gain16, brightness, settle=1):
    validate_values(exposure_lines,gain16,brightness)
    if settle<0:raise ValueError('等待时间不能为负')
    out=Path(out)
    if out.with_suffix('.zip').exists():raise ValueError('对应结果ZIP已经存在，请使用新的输出目录')
    out.mkdir(parents=True,exist_ok=False)
    record=dict(status='RUNNING',sample_id=sample,firmware=FIRMWARE,
        requested=dict(exposure_lines=exposure_lines,gain16=gain16,brightness=brightness,light_mask=1),
        started_at=datetime.now().astimezone().isoformat(),width=WIDTH,height=HEIGHT,
        encoding='RGB565_BE_camera_ISP',saved_frames=0,total_capture_requests=0,
        complete_frames_received=0,discarded_frames=[],views=[],
        physical_stability_review='pending: inspect scratches, white spots, dark areas and brightness',
        bit_identity_note='firmware version response; not an FPGA bit hash readback',
        freshness_policy='wait after SET, discard three complete frames, save three; read before/after each',
        stage='CH1 fixed-condition manual exposure/gain review; no four-direction sweep')
    path=out/'session.json';write_record(path,record)
    failure=None;last_id=None
    try:
        record['board_status']=client.ready()
        record['off_ack']=client.light(0,0)
        record['ch1_ack']=client.light(1,brightness)
        record['initial_readback']=expected=client.camera(exposure_lines,gain16)
        write_record(path,record)
        if client.stop.wait(settle):raise RuntimeError('Cancelled')
        for i in range(6):
            before=client.camera()
            if not same_lock(before,expected):raise RuntimeError('抓帧前曝光/增益读回改变或锁定失效')
            record['total_capture_requests']+=1;write_record(path,record)
            raw,meta=client.capture()
            record['complete_frames_received']+=1
            if last_id is not None and meta['frame_id']==last_id:raise RuntimeError('重复帧身份，不能作为新照片')
            last_id=meta['frame_id']
            after=client.camera()
            if not same_lock(after,expected):raise RuntimeError('抓帧后曝光/增益读回改变或锁定失效')
            item=dict(frame=meta,readback_before=before,readback_after=after)
            if i<3:record['discarded_frames'].append(item)
            else:
                base=out/f'CH1_repeat{i-2:02d}'
                base.with_suffix('.rgb565').write_bytes(raw)
                save_png(base.with_suffix('.png'),raw,WIDTH,HEIGHT)
                item.update(png=base.name+'.png',rgb565=base.name+'.rgb565',bytes=len(raw),
                            sha256_rgb565=hashlib.sha256(raw).hexdigest())
                record['views'].append(item);record['saved_frames']+=1
            write_record(path,record)
        record['status']='CAPTURE_COMPLETE_REVIEW_REQUIRED'
    except (Exception,KeyboardInterrupt) as exc:
        failure=exc;record['status']='CANCELLED' if isinstance(exc,KeyboardInterrupt) else 'FAIL'
        record['error']=f'{type(exc).__name__}: {exc}'
    finally:
        # Cancellation must not prevent the final attempt to turn the lights off.
        stop_was_set=client.stop.is_set();client.stop.clear()
        try:record['final_off_ack']=client.light(0,0);record['final_off_status']='CONFIRMED'
        except Exception as exc:
            record['final_off_status']='UNCONFIRMED';record['final_off_error']=str(exc)
            record['status']='FAIL';failure=failure or exc
        finally:
            if stop_was_set:client.stop.set()
        record['finished_at']=datetime.now().astimezone().isoformat();write_record(path,record)
        with zipfile.ZipFile(out.with_suffix('.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(out.glob('*')):
                if file.is_file():archive.write(file,file.relative_to(out.parent))
    if failure is not None:raise failure
    return record


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('status','set','verify-three'))
    ap.add_argument('--bind',default='192.168.0.3');ap.add_argument('--board',default='192.168.0.2')
    ap.add_argument('--port',type=int,default=6000)
    ap.add_argument('--exposure-lines',type=int,default=100);ap.add_argument('--gain16',type=int,default=16)
    ap.add_argument('--brightness',type=int,default=128);ap.add_argument('--sample',default='sample001')
    ap.add_argument('--settle',type=float,default=1);ap.add_argument('--out',type=Path)
    args=ap.parse_args()
    if args.action!='status':
        try:validate_values(args.exposure_lines,args.gain16,args.brightness)
        except ValueError as exc:ap.error(str(exc))
    if args.action=='verify-three' and args.out is None:ap.error('verify-three需要新的--out目录')
    stop=threading.Event();client=ManualCameraClient(args.bind,args.board,args.port,stop)
    try:
        if args.action=='verify-three':result=capture_three(client,args.out,args.sample,args.exposure_lines,args.gain16,args.brightness,args.settle)
        else:
            client.ready();result=client.camera(args.exposure_lines,args.gain16) if args.action=='set' else client.camera()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except KeyboardInterrupt:
        stop.set();raise SystemExit('操作已中断；核对灯具是否关闭')
    finally:client.close()


if __name__=='__main__':main()
