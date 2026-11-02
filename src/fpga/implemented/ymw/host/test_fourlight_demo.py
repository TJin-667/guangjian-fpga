"""Offline full-size UDP tests: freshness, four saved views, and light failure."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from PIL import Image
from focus_preview import CameraClient, FRAME_BYTES
from fourlight_demo import capture_four, make_overview, zip_result
from protocol import ACK, CAPTURE, LED_SET, STATUS, STATUS_QUERY, frame_packets


def control_packet(kind, seq, payload):
    return struct.pack('!4sBBHH', b'LGHT', 1, kind, seq, len(payload)) + payload


class FakeBoard(threading.Thread):
    def __init__(self, reject_light=False):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0));self.sock.settimeout(.1)
        self.port = self.sock.getsockname()[1]
        self.stop_event = threading.Event()
        self.reject_light = reject_light
        self.mask = 0;self.frame_id = 0
        self.cached_mask = 0;self.captures = 0
        self.light_commands = []
        self.colors = {0:0, 1:0xf800, 2:0x07e0, 4:0x001f, 8:0xffff}

    def run(self):
        while not self.stop_event.is_set():
            try:data,peer=self.sock.recvfrom(256)
            except socket.timeout:continue
            except OSError:return
            kind=data[5];seq=int.from_bytes(data[6:8], 'big')
            result=0
            if kind==LED_SET:
                mask,brightness,_,_=struct.unpack('!4H',data[12:20])
                result=4 if self.reject_light else 0
                if result==0:self.mask=mask
                self.light_commands.append((mask,brightness))
            if kind==CAPTURE:
                self.frame_id+=1;self.captures+=1
            payload=struct.pack('!BB4H',kind,result,self.frame_id,0,31,0)
            self.sock.sendto(control_packet(ACK,seq,payload),peer)
            if kind==STATUS_QUERY:
                payload=struct.pack('!5H3I',0,258,31,16,0,0,0,0)
                self.sock.sendto(control_packet(STATUS,seq,payload),peer)
            elif kind==CAPTURE:
                # Emulate the producer holding a pre-change frame until release.
                raw=struct.pack('!H',self.colors[self.cached_mask])*(FRAME_BYTES//2)
                self.cached_mask=self.mask
                for packet in frame_packets(raw,1920,1080,self.frame_id):
                    self.sock.sendto(packet,peer)

    def close(self):
        self.stop_event.set();self.join(2);self.sock.close()


class DemoTest(unittest.TestCase):
    def test_full_size_four_views_discard_old_and_save_new(self):
        board=FakeBoard();board.start()
        client=CameraClient('127.0.0.1','127.0.0.1',board.port,threading.Event())
        try:
            self.assertEqual(client.ready()['firmware'],258)
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'four'
                result=capture_four(client,out,'washer01',128,0)
                self.assertEqual(result['status'],'PASS')
                self.assertEqual(board.captures,8)
                self.assertEqual(result['saved_frames'],4)
                self.assertEqual(result['total_capture_requests'],8)
                self.assertEqual(result['total_complete_frames_received'],8)
                self.assertEqual(board.light_commands,[(0,0),(1,128),(0,0),(2,128),(0,0),(4,128),(0,0),(8,128)])
                for channel,color in enumerate((0xf800,0x07e0,0x001f,0xffff),1):
                    raw=(out/f'CH{channel}_brightness128.rgb565').read_bytes()
                    self.assertEqual(len(raw),FRAME_BYTES)
                    self.assertEqual(raw,struct.pack('!H',color)*(FRAME_BYTES//2))
                    with Image.open(out/f'CH{channel}_brightness128.png') as im:
                        self.assertEqual(im.size,(1920,1080))
                make_overview(out)
                self.assertTrue(zip_result(out).is_file())
        finally:client.close();board.close()

    def test_no_capture_after_light_rejection(self):
        board=FakeBoard(reject_light=True);board.start()
        client=CameraClient('127.0.0.1','127.0.0.1',board.port,threading.Event())
        try:
            client.ready()
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'fail'
                with self.assertRaisesRegex(RuntimeError,'控制器未确认'):
                    capture_four(client,out,'washer01',128,0)
                result=json.loads((out/'session.json').read_text(encoding='utf-8'))
                self.assertEqual(result['status'],'FAIL')
                self.assertEqual(result['saved_frames'],0)
                self.assertEqual(result['total_capture_requests'],0)
                self.assertEqual(result['total_complete_frames_received'],0)
                self.assertEqual(board.captures,0)
                self.assertFalse(list(out.glob('CH*.png')))
        finally:client.close();board.close()


if __name__=='__main__':unittest.main()
