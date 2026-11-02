"""UDP loopback acceptance using real, previously captured RGB565 fixtures."""
import json
from pathlib import Path
import struct,tempfile,threading,unittest
import numpy as np
from roi_camera import ROOT,FIRMWARE,RoiCameraClient,capture_group,safe_off,raw_image
from protocol import (ACK,STATUS,STATUS_QUERY,CAMERA_GET,CAMERA_SET,CAMERA_STATUS,
                      LED_SET,CAPTURE,ROI_SET,ROI_GET,ROI_STATUS,control,frame_packets,rgb888)
from test_manual_camera import BoardPeer,packet,snapshot_payload

FIXTURES=ROOT/'sim/fixtures'

def roi_payload(rectangle=(0,0,1920,1080),generation=1,valid=True):
    x,y,w,h=rectangle;pixels=w*h;count=(pixels+689)//690
    return struct.pack('!BB7HIBB',1,int(valid),x,y,w,h,count,pixels-(count-1)*690,generation,pixels,0,0)

class RoiBoardPeer(BoardPeer):
    def __init__(self,caps=127,dark=False,wrong_dimensions=False,missing_packet=False,
                 busy_set=False,lose_roi_readback=False,**kwargs):
        super().__init__(**kwargs)
        self.caps=caps;self.dark=dark;self.wrong_dimensions=wrong_dimensions;self.missing_packet=missing_packet
        self.busy_set=busy_set;self.lose_roi_readback=lose_roi_readback
        self.roi=(0,0,1920,1080);self.generation=0;self.roi_sets=0;self.captures=[];self.errors=[]
        self.frames={ch:(FIXTURES/f'CH{ch}.rgb565').read_bytes() for ch in range(1,5)}
        if dark:self.frames[1]=(FIXTURES/'dark.rgb565').read_bytes()
    def run(self):
        import socket
        while not self.stop_event.is_set():
            try:data,peer=self.sock.recvfrom(128)
            except socket.timeout:continue
            except OSError:return
            try:
                kind=data[5];seq=int.from_bytes(data[6:8],'big');args=struct.unpack('!4H',data[12:20])
                key=(peer,seq,kind);new=key not in self.seen;self.seen[key]=self.seen.get(key,0)+1;result=0
                if kind==CAMERA_SET and new:self.exposure,self.gain=args[:2];self.set_count+=1
                if kind==LED_SET:self.mask,self.brightness=args[:2];self.light_calls.append(args[:2])
                if kind==ROI_SET:
                    if self.busy_set:self.busy_set=False;result=1;self.seen.pop(key)
                    elif new:self.roi=args;self.generation+=1;self.roi_sets+=1
                if kind==CAPTURE:
                    if args[0]==3 and args[3]!=self.generation:result=2
                    else:self.frame_id+=1;self.capture_count+=1;self.captures.append(args)
                self.sock.sendto(packet(ACK,seq,struct.pack('!BB4H',kind,result,self.frame_id,0,self.caps,0)),peer)
                if result:continue
                if kind==STATUS_QUERY:
                    self.sock.sendto(packet(STATUS,seq,struct.pack('!5H3I',0,self.firmware,self.caps,16,0,0,0,0)),peer)
                elif kind in (CAMERA_GET,CAMERA_SET):
                    payload=snapshot_payload(self.exposure,self.gain,self.set_count>0,generation=self.set_count)
                    if self.drift and kind==CAMERA_GET:payload=snapshot_payload(self.exposure+1,self.gain,False,error=2,generation=self.set_count)
                    self.sock.sendto(packet(CAMERA_STATUS,seq,payload),peer)
                elif kind in (ROI_SET,ROI_GET):
                    if self.lose_roi_readback and kind==ROI_SET and new:continue
                    self.sock.sendto(packet(ROI_STATUS,seq,roi_payload(self.roi,self.generation,self.generation>0)),peer)
                elif kind==CAPTURE:
                    channel=self.mask.bit_length() or 1;raw=self.frames[channel]
                    x,y,w,h=self.roi if args[0]==3 else (0,0,1920,1080)
                    pixels=np.frombuffer(raw,dtype='>u2').reshape(1080,1920)
                    if self.wrong_dimensions:w=max(1,w-1)
                    raw=pixels[y:y+h,x:x+w].astype('>u2').tobytes();count=(len(raw)+1379)//1380
                    for i,p in enumerate(frame_packets(raw,w,h,self.frame_id)):
                        if self.missing_packet and i==count-1:continue
                        self.sock.sendto(p,peer)
                        if i%100==99:self.stop_event.wait(.002)
            except Exception as exc:self.errors.append(repr(exc));return

class RoiCameraTest(unittest.TestCase):
    def test_vector_decode_matches_all_65536_pixel_values(self):
        raw=np.arange(65536,dtype='>u2').tobytes()
        self.assertEqual(raw_image(raw,256,256)[...,::-1].tobytes(),rgb888(raw))
    def test_vector_decode_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):raw_image(b'\x00\x00',2,1)
    def client(self,**kwargs):
        board=RoiBoardPeer(**kwargs);board.start()
        client=RoiCameraClient('127.0.0.1','127.0.0.1',board.port,threading.Event())
        self.addCleanup(board.close);self.addCleanup(client.close)
        return client,board
    def test_readback_geometry_codec(self):
        data=control(packet(ROI_STATUS,42,roi_payload((605,162,831,833),7)))
        self.assertEqual((data['roi'],data['generation'],data['packets'],data['last_pixels']),([605,162,831,833],7,1004,153))
    def test_bad_geometry_codec_rejected(self):
        good=bytearray(roi_payload())
        for index,value in ((0,2),(1,2),(2,255),(6,0),(15,0),(20,1),(21,1)):
            bad=bytearray(good);bad[index]=value
            with self.subTest(index=index),self.assertRaises(ValueError):control(packet(ROI_STATUS,1,bad))
    def test_invalid_roi_is_rejected_before_network(self):
        client,board=self.client()
        for rectangle in ((-1,0,1,1),(1919,0,2,1),(0,0,0,1),(0,1079,1,2),(0,0,1.5,2)):
            with self.subTest(rectangle=rectangle),self.assertRaises(ValueError):client.roi(rectangle)
        self.assertEqual(board.roi_sets,0)
    def test_missing_roi_capability_blocks(self):
        client,board=self.client(caps=63)
        with self.assertRaisesRegex(RuntimeError,'ROI'):client.ready()
        self.assertEqual(board.roi_sets,0)
    def test_old_firmware_blocks(self):
        client,board=self.client(firmware=0x0103)
        with self.assertRaisesRegex(RuntimeError,'0x0104'):client.ready()
        self.assertEqual(board.roi_sets,0)
    def test_busy_roi_retried_without_false_success(self):
        client,board=self.client(busy_set=True);client.ready()
        result=client.roi((605,162,831,833));self.assertTrue(result['valid']);self.assertEqual(board.roi_sets,1)
    def test_lost_roi_readback_same_identity(self):
        client,board=self.client(lose_roi_readback=True);client.ready()
        result=client.roi((605,162,831,833));self.assertEqual((result['generation'],board.roi_sets),(1,1))
    def test_generation_change_blocks_capture(self):
        client,board=self.client();client.ready();client.roi((605,162,831,833));board.generation+=1
        with self.assertRaisesRegex(RuntimeError,'已经改变'):client.capture(cropped=True)
        self.assertEqual(board.capture_count,0)
    def test_wrong_frame_dimensions_block(self):
        client,_=self.client(wrong_dimensions=True);client.roi((605,162,23,17))
        with self.assertRaisesRegex(RuntimeError,'尺寸'):client.capture(cropped=True)
    def test_missing_packet_times_out(self):
        client,_=self.client(missing_packet=True);client.roi((605,162,23,17))
        with self.assertRaises(TimeoutError):client.capture(frame_wait=.3,cropped=True)
    def test_transfer_progress_reports_completed_frame(self):
        client,_=self.client();client.roi((605,162,23,17));updates=[]
        raw,meta=client.capture(cropped=True,on_progress=updates.append)
        self.assertEqual(len(raw),23*17*2)
        self.assertEqual((updates[-1]['phase'],updates[-1]['received_packets'],updates[-1]['expected_packets']),('complete',1,1))
        self.assertEqual(updates[-1]['frame_id'],meta['frame_id'])
    def test_transfer_timeout_reports_received_packet_count(self):
        client,_=self.client(missing_packet=True);client.roi((605,162,23,31));updates=[]
        with self.assertRaisesRegex(TimeoutError,'1/2'):
            client.capture(frame_wait=.3,cropped=True,on_progress=updates.append)
        self.assertEqual((updates[-1]['phase'],updates[-1]['received_packets'],updates[-1]['expected_packets']),('timeout',1,2))
    def test_existing_real_four_views_are_exact_and_frozen(self):
        client,board=self.client()
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'valid';record=capture_group(client,out,'replayed_existing_sample',100,16,16,settle=0)
            self.assertEqual((record['status'],record['saved_frames'],record['total_capture_requests']),('PASS',4,10))
            self.assertEqual(len(record['discarded_frames']),6)
            self.assertEqual(record['geometry']['roi'],[605,162,831,833])
            self.assertEqual(board.captures[:4],[(2,1920,1080,0)]*4)
            self.assertEqual(board.captures[4:],[(3,831,833,1)]*6)
            x,y,w,h=record['geometry']['roi']
            self.assertEqual(record['total_transport_image_bytes'],4*1920*1080*2+6*w*h*2)
            self.assertEqual((board.set_count,board.roi_sets),(1,1))
            for view in record['views']:
                raw=(out/view['rgb565']).read_bytes();original=np.frombuffer(board.frames[view['channel']],dtype='>u2').reshape(1080,1920)
                self.assertEqual(raw,original[y:y+h,x:x+w].astype('>u2').tobytes())
                self.assertEqual((view['roi_generation'],view['exposure_lines'],view['gain16']),(1,100,16))
            self.assertEqual(record['views'][0]['frame']['transport'],'full_frame')
            self.assertTrue(all(v['frame']['transport']=='fpga_roi' for v in record['views'][1:]))
        safe_off('127.0.0.1','127.0.0.1',board.port);self.assertEqual(board.mask,0)
    def test_dark_first_frame_keeps_full_and_requires_review(self):
        client,board=self.client(dark=True)
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'dark';record=capture_group(client,out,'dark_replay',100,16,4,settle=0)
            self.assertEqual((record['status'],record['geometry']['roi']),('REVIEW_REQUIRED',[0,0,1920,1080]))
            self.assertFalse((out/'plate_mask_roi.png').exists())
            self.assertTrue(all(v['bytes']==1920*1080*2 for v in record['views']))
        safe_off('127.0.0.1','127.0.0.1',board.port);self.assertEqual(board.mask,0)
    def test_sensor_drift_fails_group_before_first_capture(self):
        client,board=self.client(drift=True)
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'failed'
            with self.assertRaises(RuntimeError):capture_group(client,out,'drift',100,16,16,settle=0)
            record=json.loads((out/'session.json').read_text(encoding='utf-8'))
            self.assertEqual((record['status'],record['saved_frames'],board.capture_count),('FAIL',0,0))
        safe_off('127.0.0.1','127.0.0.1',board.port);self.assertEqual(board.mask,0)

if __name__=='__main__':unittest.main()
