"""Sensor readback codec, real UDP request/retry, and fixed CH1 capture checks."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from manual_camera import (FIRMWARE,FRAME_BYTES,ManualCameraClient,capture_three,
                           same_lock,validate_values)
from protocol import (ACK,CAMERA_GET,CAMERA_SET,CAMERA_STATUS,CAPTURE,LED_SET,
                      STATUS,STATUS_QUERY,control,frame_packets)


def packet(kind,seq,payload):
    return struct.pack('!4sBBHH',b'LGHT',1,kind,seq,len(payload))+payload


def snapshot_payload(exposure=100,gain=16,locked=True,error=0,generation=1):
    encoded=exposure<<4
    raw=bytes((3,(encoded>>16)&15,(encoded>>8)&255,encoded&255,
               gain>>8,gain&255,9,196,4,96,0,0,0x56,0x40))
    return bytes((1,int(locked),error,0))+raw+struct.pack('!HH',generation,0)


class BoardPeer(threading.Thread):
    def __init__(self,firmware=FIRMWARE,lose_readback=False,drift=False):
        super().__init__(daemon=True)
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.1)
        self.port=self.sock.getsockname()[1];self.stop_event=threading.Event()
        self.firmware=firmware;self.lose_readback=lose_readback;self.drift=drift
        self.seen={};self.set_count=0;self.frame_id=0;self.capture_count=0
        self.mask=0;self.brightness=0;self.exposure=100;self.gain=16;self.light_calls=[]
    def run(self):
        while not self.stop_event.is_set():
            try:data,peer=self.sock.recvfrom(128)
            except socket.timeout:continue
            except OSError:return
            kind=data[5];seq=int.from_bytes(data[6:8],'big');args=struct.unpack('!4H',data[12:20])
            key=(peer,seq,kind);new=key not in self.seen;self.seen[key]=self.seen.get(key,0)+1
            if kind==CAMERA_SET and new:self.exposure,self.gain=args[:2];self.set_count+=1
            if kind==LED_SET:self.mask,self.brightness=args[:2];self.light_calls.append(args[:2])
            if kind==CAPTURE:self.frame_id+=1;self.capture_count+=1
            ack=struct.pack('!BB4H',kind,0,self.frame_id,0,63,0)
            self.sock.sendto(packet(ACK,seq,ack),peer)
            if kind==STATUS_QUERY:
                self.sock.sendto(packet(STATUS,seq,struct.pack('!5H3I',0,self.firmware,63,16,0,0,0,0)),peer)
            elif kind in (CAMERA_SET,CAMERA_GET):
                if self.lose_readback and kind==CAMERA_SET and new:continue
                # A stale response is deliberately sent before the correlated one.
                payload=snapshot_payload(self.exposure,self.gain,self.set_count>0,generation=self.set_count)
                if self.drift and kind==CAMERA_GET:
                    payload=snapshot_payload(self.exposure+1,self.gain,False,error=2,generation=self.set_count)
                self.sock.sendto(packet(CAMERA_STATUS,(seq-1)&65535,payload),peer)
                self.sock.sendto(packet(CAMERA_STATUS,seq,payload),peer)
            elif kind==CAPTURE:
                raw=b'\x12\x34'*(FRAME_BYTES//2)
                for i,p in enumerate(frame_packets(raw,1920,1080,self.frame_id)):
                    self.sock.sendto(p,peer)
                    if i%200==199:self.stop_event.wait(.005)
    def close(self):self.stop_event.set();self.join(3);self.sock.close()


class ManualCameraTest(unittest.TestCase):
    def client(self,**kw):
        board=BoardPeer(**kw);board.start()
        client=ManualCameraClient('127.0.0.1','127.0.0.1',board.port,threading.Event())
        self.addCleanup(board.close);self.addCleanup(client.close)
        return client,board
    def test_codec_register_encoding(self):
        item=control(packet(CAMERA_STATUS,9,snapshot_payload(100,16)))
        self.assertEqual((item['mode'],item['exposure_lines'],item['gain_x'],item['hts'],item['vts']),(3,100,1,2500,1120))
        self.assertEqual(item['raw_registers']['0x3501'],6)
        self.assertEqual(item['raw_registers']['0x3502'],0x40)
        self.assertEqual(item['chip_id'],0x5640)
    def test_codec_rejects_false_lock(self):
        for index,value in ((4,0),(7,0x41),(8,4),(12,0),(16,0),(2,1),(0,2),(3,1),(20,1)):
            payload=bytearray(snapshot_payload());payload[index]=value
            with self.subTest(index=index),self.assertRaises(ValueError):control(packet(CAMERA_STATUS,9,payload))
    def test_parameter_limits_are_checked_before_network(self):
        validate_values(1,16,1);validate_values(1116,1023,255)
        for args in ((0,16,1),(1117,16,1),(100,15,1),(100,1024,1),(100,16,0),(100,16,256)):
            with self.subTest(args=args),self.assertRaises(ValueError):validate_values(*args)
    def test_real_udp_set_get_and_correlated_readback(self):
        client,board=self.client();client.ready()
        initial=client.camera();self.assertFalse(initial['locked'])
        applied=client.camera(100,16);self.assertTrue(applied['locked'])
        current=client.camera();self.assertTrue(same_lock(current,applied));self.assertEqual(board.set_count,1)
    def test_lost_readback_retries_same_identity_without_new_set(self):
        client,board=self.client(lose_readback=True);client.ready()
        applied=client.camera(200,16)
        self.assertEqual((applied['exposure_lines'],applied['generation'],board.set_count),(200,1,1))
    def test_old_firmware_cannot_receive_manual_commands(self):
        client,board=self.client(firmware=258)
        with self.assertRaisesRegex(RuntimeError,'0x0104'):client.ready()
        self.assertEqual(board.set_count,0)
    def test_readback_drift_does_not_claim_locked(self):
        client,_=self.client(drift=True);client.ready();client.camera(100,16)
        with self.assertRaisesRegex(RuntimeError,'未确认'):client.camera()
    def test_full_1080p_ch1_three_captures_record_settings_and_final_off(self):
        client,board=self.client()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'three'
            record=capture_three(client,out,'scratch01',100,16,128,settle=0)
            self.assertEqual(record['status'],'CAPTURE_COMPLETE_REVIEW_REQUIRED')
            self.assertEqual((record['total_capture_requests'],record['complete_frames_received'],record['saved_frames']),(6,6,3))
            self.assertEqual(len(record['discarded_frames']),3)
            self.assertEqual(board.light_calls,[(0,0),(1,128),(0,0)])
            self.assertEqual(record['final_off_status'],'CONFIRMED')
            self.assertEqual(board.set_count,1)
            self.assertEqual(record['physical_stability_review'].split(':')[0],'pending')
            for view in record['views']:
                self.assertEqual((out/view['rgb565']).stat().st_size,FRAME_BYTES)
                self.assertEqual((out/view['png']).read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
                self.assertEqual(view['readback_before']['exposure_lines'],100)
                self.assertEqual(view['readback_after']['gain16'],16)
            self.assertTrue(out.with_suffix('.zip').is_file())
    def test_drift_blocks_images_and_still_turns_light_off(self):
        client,board=self.client(drift=True)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'failed'
            with self.assertRaises(RuntimeError):capture_three(client,out,'scratch01',100,16,128,settle=0)
            record=json.loads((out/'session.json').read_text(encoding='utf-8'))
            self.assertEqual((record['status'],record['saved_frames'],board.capture_count),('FAIL',0,0))
            self.assertEqual(board.mask,0)


if __name__=='__main__':unittest.main()
