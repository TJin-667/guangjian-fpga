import tempfile
import unittest
import socket
import struct
import threading
from pathlib import Path
from protocol import ACK, CAPTURE, FRAME_DATA, STATUS, STATUS_QUERY, frame_packets
from diagnose_camera import attempt
from udp_client import CameraClient


class Client:
    def __init__(self, packets):self.packets=packets;self.seq=0
    def transact(self,kind,args=(0,0,0,0)):
        self.seq+=1
        ack={'type':ACK,'seq':self.seq,'original':kind,'result':0,'frame_id':10}
        if kind==STATUS_QUERY:
            return ack,[],{'type':STATUS,'seq':self.seq,'firmware':258,
                'capabilities':31,'state':48,'error':0x105,'commands':3,'frames':1,'dropped':0}
        return ack,list(self.packets),None
    def receive(self,deadline):raise TimeoutError('test ended')


class TestDiagnostic(unittest.TestCase):
    def test_stdlib_udp_client_buffers_frame_and_accepts_matching_ack(self):
        server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        server.bind(('127.0.0.1',0));server.settimeout(2)
        stop=threading.Event()
        client=CameraClient('127.0.0.1','127.0.0.1',server.getsockname()[1],stop)
        errors=[]
        frame=list(frame_packets(b'\0'*128,8,8,10))[0]
        def respond():
            try:
                request,peer=server.recvfrom(256)
                seq=int.from_bytes(request[6:8],'big')
                kind=request[5]
                def packet(typ,sequence,payload):
                    return struct.pack('!4sBBHH',b'LGHT',1,typ,sequence,len(payload))+payload
                ack=struct.pack('!BB4H',kind,0,10,0,31,0)
                server.sendto(packet(ACK,(seq+1)&65535,ack),peer)
                server.sendto(frame,peer)
                status=struct.pack('!5H3I',0,258,31,16,0,1,0,0)
                server.sendto(packet(STATUS,seq,status),peer)
                server.sendto(packet(ACK,seq,ack),peer)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=respond);worker.start()
        try:
            ack,buffered,status=client.transact(STATUS_QUERY)
            self.assertEqual(ack['seq'],client.seq)
            self.assertEqual(buffered,[frame])
            self.assertEqual(status['firmware'],258)
        finally:
            client.close();worker.join(3);server.close()
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)

    def test_separates_wrong_id_and_malformed_packets_from_no_udp(self):
        stale=list(frame_packets(b'\0'*128,8,8,9))[0]
        malformed=b'LGHT'+bytes((1,FRAME_DATA))+b'bad'
        with tempfile.TemporaryDirectory() as temp:
            result=attempt(Client([stale,malformed]),Path(temp),'camera',2,8,8,.01)
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['frame_datagrams'],2)
        self.assertEqual(result['wrong_frame_id_packets'],1)
        self.assertEqual(result['parse_errors'],1)
        self.assertEqual(result['unique_packets'],0)
        self.assertEqual(result['status_after']['decoded']['source_reason_code'],1)
        self.assertTrue(result['status_after']['decoded']['ddr_source_failed'])

    def test_complete_pattern_saved_without_camera(self):
        raw=b'\xf8\0'*64
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            result=attempt(Client(list(frame_packets(raw,8,8,10))),out,'pattern',0,8,8)
            self.assertEqual(result['status'],'PASS')
            self.assertEqual((out/'pattern.rgb565').read_bytes(),raw)
            self.assertTrue((out/'pattern.png').is_file())


if __name__=='__main__':unittest.main()
