"""Live first-full-frame location followed by FPGA ROI transport.

Acquisition decisions run on the PC; original-pixel selection runs in FPGA.
"""
import argparse
from collections import deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import zipfile
import numpy as np
from manual_camera import ManualCameraClient, FIRMWARE, same_lock, validate_values, write_record
from plate_roi import LocatorConfig, locate_plate, crop_pixels, overlay, write_image
from protocol import CAPTURE, FrameReceiver, FRAME_DATA, ROI_SET, ROI_GET, ROI_STATUS, ROI_CAPABILITY, parse_frame, rgb888, save_png

ROOT=Path(__file__).resolve().parents[1]
DIRECTIONS={1:'上',2:'右',3:'下',4:'左'}


def raw_image(raw,width,height):
    if len(raw)!=width*height*2:raise ValueError('RGB565图像长度与尺寸不一致')
    values=np.frombuffer(raw,dtype='>u2').reshape(height,width)
    result=np.empty((height,width,3),dtype=np.uint8)
    blue=values&31;green=(values>>5)&63;red=(values>>11)&31
    result[...,0]=(blue<<3)|(blue>>2)
    result[...,1]=(green<<2)|(green>>4)
    result[...,2]=(red<<3)|(red>>2)
    return result


class RoiCameraClient(ManualCameraClient):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.roi_state=None

    def ready(self,timeout=20):
        status=super().ready(timeout)
        if not status['capabilities']&ROI_CAPABILITY:
            raise RuntimeError('当前板上程序缺少动态ROI能力，请下载本包ROI bit')
        return status

    def roi(self,rectangle=None):
        kind=ROI_GET if rectangle is None else ROI_SET
        args=(0,0,0,0) if rectangle is None else tuple(rectangle)
        if rectangle is not None:
            x,y,w,h=args
            if any(type(v) is not int for v in args) or min(x,y)<0 or min(w,h)<1 or x+w>1920 or y+h>1080:
                raise ValueError('ROI超出完整1920×1080图像')
        deadline=time.monotonic()+8
        while True:
            ack,snapshot=self.request(kind,args,extra=ROI_STATUS)
            if ack['result']==1 and time.monotonic()<deadline:
                if self.stop.wait(.1):raise RuntimeError('Cancelled')
                continue
            if ack['result'] or snapshot is None:
                raise RuntimeError(f'ROI操作未确认：{ack}')
            if rectangle is not None and (not snapshot['valid'] or snapshot['roi']!=list(rectangle)):
                raise RuntimeError('ROI设置与板端读回不一致')
            self.roi_state=snapshot
            return snapshot

    def capture(self,frame_wait=8,cropped=False,on_progress=None):
        expected_roi=None
        if cropped:
            if not self.roi_state or not self.roi_state['valid']:
                raise RuntimeError('尚未确认本组ROI')
            expected_roi=dict(self.roi_state)
            # Detect another controller changing the group geometry before CAPTURE.
            actual=self.roi()
            if actual['generation']!=expected_roi['generation'] or actual['roi']!=expected_roi['roi']:
                raise RuntimeError('本组ROI已经改变，停止混合采集')
            width,height=actual['roi'][2:]
            args=(3,width,height,actual['generation'])
        else:
            width,height=1920,1080;args=(2,width,height,0)
        started=time.monotonic()
        if on_progress:on_progress(dict(phase='waiting_ack',received_packets=0,expected_packets=(width*height*2+1379)//1380,width=width,height=height))
        ack,buffered,_=self.transact(CAPTURE,args)
        if ack['result']:
            raise RuntimeError(f'抓帧被拒绝，未保存为成功：{ack}')
        packets=(width*height*2+1379)//1380
        receiver=FrameReceiver(frame_wait,max_bytes=width*height*2)
        buffered=deque(buffered);last_progress=0;malformed=stale=0
        deadline=time.monotonic()+frame_wait
        def progress(phase,force=False):
            nonlocal last_progress
            now=time.monotonic()
            item=dict(phase=phase,frame_id=ack['frame_id'],received_packets=len(receiver.parts),
                expected_packets=packets,width=width,height=height,elapsed_s=round(now-started,3),
                malformed_packets=malformed,stale_packets=stale)
            if on_progress and (force or now-last_progress>=.2):on_progress(item);last_progress=now
            return item
        progress('receiving',True)
        while True:
            try:data=buffered.popleft() if buffered else self.receive(deadline)
            except TimeoutError as exc:
                detail=progress('timeout',True)
                raise TimeoutError(f'帧 {ack["frame_id"]} 接收超时：{detail["received_packets"]}/{packets} 包；'
                    f'错误包 {malformed}，其他帧包 {stale}。'+
                    ('板卡没有发来匹配的图像包。' if not receiver.parts else '图像未收齐，未显示为完整帧。')) from exc
            if len(data)<6 or data[5]!=FRAME_DATA:continue
            try:fid,_,_,rw,rh,_=parse_frame(data)
            except ValueError:malformed+=1;progress('receiving');continue
            if fid!=ack['frame_id']:stale+=1;progress('receiving');continue
            if (rw,rh)!=(width,height):raise RuntimeError('板端帧尺寸与本次请求不一致')
            raw=receiver.add(data,fid)
            progress('receiving')
            if raw is not None:
                if len(raw)!=width*height*2 or receiver.meta[1]!=packets:
                    raise RuntimeError('ROI帧字节数或包数不一致')
                progress('complete',True)
                return raw,dict(frame_id=fid,width=width,height=height,packets=packets,
                    duplicates=receiver.duplicates,transport_bytes=len(raw),elapsed_s=round(time.monotonic()-started,4),
                    received_at=datetime.now().astimezone().isoformat(),
                    transport='fpga_roi' if cropped else 'full_frame',roi_readback=expected_roi)


def candidate_bit_hash():
    path=ROOT/'bit/BX72_1080P_4LIGHT_ROI.bit'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def capture_group(client,out,sample,exposure_lines,gain16,brightness,settle=1,margin=16,on_event=None):
    validate_values(exposure_lines,gain16,brightness)
    if settle<0:raise ValueError('等待时间不能为负')
    if type(margin) is not int or margin<4:raise ValueError('外留边须为至少4像素的整数，建议16')
    config=LocatorConfig(margin=margin)
    notify=on_event or (lambda *_:None)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    record=dict(schema_version=2,status='RUNNING',sample_id=sample,group_id=out.name,firmware=FIRMWARE,
        started_at=datetime.now().astimezone().isoformat(),source_width=1920,source_height=1080,
        encoding='RGB565_BE_camera_ISP; not Bayer RAW',requested=dict(exposure_lines=exposure_lines,gain16=gain16,brightness=brightness),
        candidate_bit_sha256=candidate_bit_hash(),bit_identity_note='local file hash; not FPGA bit hash readback',
        directions=DIRECTIONS,saved_frames=0,total_capture_requests=0,total_complete_frames_received=0,
        total_transport_image_bytes=0,discarded_frames=[],views=[],
        freshness_policy='wait after camera SET; discard 3 complete full frames; after later light changes discard 1 complete ROI frame',
        freshness_physically_validated=False,roi_first_frame_only=True)
    path=out/'session.json';seen=set()
    def snapshot(cropped,discard):
        before=client.camera()
        if not same_lock(before,expected):raise RuntimeError('抓帧前曝光/增益锁定改变')
        record['total_capture_requests']+=1;write_record(path,record)
        raw,meta=client.capture(cropped=cropped)
        record['total_complete_frames_received']+=1;record['total_transport_image_bytes']+=len(raw)
        if meta['frame_id'] in seen:raise RuntimeError('重复帧号，不能作为新观察')
        seen.add(meta['frame_id'])
        after=client.camera()
        if not same_lock(after,expected):raise RuntimeError('抓帧后曝光/增益锁定改变')
        meta.update(discarded=discard,camera_before=before,camera_after=after)
        if discard:record['discarded_frames'].append(meta)
        write_record(path,record)
        return raw,meta
    write_record(path,record)
    try:
        record['board_status']=client.ready()
        notify('status','CH1：设置灯光与手动相机参数，读回确认')
        record['initial_off_ack']=client.light(0,0);record['ch1_on_ack']=client.light(1,brightness)
        expected=client.camera(exposure_lines,gain16);record['camera_readback']=expected;write_record(path,record)
        if client.stop.wait(settle):raise RuntimeError('Cancelled')
        for _ in range(3):snapshot(False,True)
        full,first_meta=snapshot(False,False)
        (out/'first_full.rgb565').write_bytes(full);save_png(out/'first_full.png',full,1920,1080)
        first_image=raw_image(full,1920,1080)
        geometry,mask=locate_plate(first_image,config)
        geometry.update(source_frame_id=first_meta['frame_id'],first_image_sha256=hashlib.sha256((out/'first_full.png').read_bytes()).hexdigest(),
                        group_id=out.name,geometry_id=out.name+'_F'+str(first_meta['frame_id']),mask_is_quality_mask=False)
        record['geometry']=geometry
        write_image(out/'first_overlay.png',overlay(first_image,geometry))
        if mask is not None:
            write_image(out/'plate_mask_full.png',mask);write_image(out/'plate_mask_roi.png',crop_pixels(mask,geometry['roi']))
        record['roi_readback']=client.roi(geometry['roi']);write_record(path,record)
        notify('geometry',(first_image,geometry))
        notify('status','本组ROI已读回确认；后续三个方向由FPGA裁剪' if mask is not None else '首帧无法可靠定位；本组保留完整图，标为待复核')
        for channel in range(1,5):
            if channel==1:
                raw=crop_pixels(np.frombuffer(full,dtype='>u2').reshape(1080,1920),geometry['roi']).astype('>u2').tobytes()
                meta=first_meta;on_ack=record['ch1_on_ack'];off_ack=record['initial_off_ack'];method='PC crop from the already captured first full frame'
            else:
                off_ack=client.light(0,0);on_ack=client.light(1<<(channel-1),brightness)
                notify('status',f'CH{channel}（{DIRECTIONS[channel]}）：等待稳定，丢弃过渡帧，保存FPGA ROI')
                if client.stop.wait(settle):raise RuntimeError('Cancelled')
                snapshot(True,True);raw,meta=snapshot(True,False);method='FPGA original-pixel ROI transport'
            w,h=geometry['roi'][2:]
            if len(raw)!=w*h*2:raise RuntimeError('保存ROI数据长度错误')
            base=out/f'CH{channel}_brightness{brightness:03d}'
            base.with_suffix('.rgb565').write_bytes(raw);save_png(base.with_suffix('.png'),raw,w,h)
            item=dict(channel=channel,image_direction=DIRECTIONS[channel],mask=1<<(channel-1),brightness=brightness,
                status='COMPLETE',off_ack=off_ack,on_ack=on_ack,frame=meta,saved_width=w,saved_height=h,
                roi=geometry['roi'],geometry_id=geometry['geometry_id'],roi_generation=record['roi_readback']['generation'],
                png=base.name+'.png',rgb565=base.name+'.rgb565',bytes=len(raw),sha256_rgb565=hashlib.sha256(raw).hexdigest(),
                crop_method=method,exposure_lines=expected['exposure_lines'],gain16=expected['gain16'])
            record['views'].append(item);record['saved_frames']+=1;write_record(path,record)
            notify('frame',(raw,dict(meta,channel=channel,width=w,height=h)))
        record['status']='PASS' if mask is not None else 'REVIEW_REQUIRED'
        record['saved_roi_payload_reduction_fraction']=1-len(raw)/(1920*1080*2)
    except Exception as exc:
        record['status']='CANCELLED' if client.stop.is_set() else 'FAIL';record['error']=str(exc)
        raise
    finally:
        record['finished_at']=datetime.now().astimezone().isoformat();write_record(path,record)
    return record


def safe_off(bind,board,port):
    client=RoiCameraClient(bind,board,port,threading.Event())
    try:return client.light(0,0)
    finally:client.close()


def pack_result(out):
    path=Path(out).with_suffix('.zip')
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
        for file in Path(out).rglob('*'):
            if file.is_file():z.write(file,file.relative_to(Path(out).parent))
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind',default='192.168.0.3');parser.add_argument('--board',default='192.168.0.2');parser.add_argument('--port',type=int,default=5000)
    parser.add_argument('--sample',default='sample001');parser.add_argument('--exposure-lines',type=int,default=100);parser.add_argument('--gain16',type=int,default=16)
    parser.add_argument('--brightness',type=int,default=128);parser.add_argument('--settle',type=float,default=1);parser.add_argument('--margin',type=int,default=16)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();out=args.out or ROOT/'results'/('BX72_ROI_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    client=RoiCameraClient(args.bind,args.board,args.port,threading.Event());record=None
    try:
        record=capture_group(client,out,args.sample,args.exposure_lines,args.gain16,args.brightness,args.settle,args.margin,
                             lambda kind,value:print(value) if kind=='status' else None)
    finally:
        client.close()
        try:off=safe_off(args.bind,args.board,args.port)
        except Exception as exc:
            if out.exists():
                data=json.loads((out/'session.json').read_text(encoding='utf-8'));data.update(final_off_status='FAILED',final_off_error=str(exc));write_record(out/'session.json',data)
            raise
        if out.exists():
            data=json.loads((out/'session.json').read_text(encoding='utf-8'));data.update(final_off_status='ACK_CONFIRMED',final_off_ack=off);write_record(out/'session.json',data)
    print('Saved',out);print('ZIP',pack_result(out))


if __name__=='__main__':main()
