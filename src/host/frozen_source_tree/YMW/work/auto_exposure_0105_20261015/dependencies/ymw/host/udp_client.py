"""Standard-library-only control client for offline BX72 diagnostics."""
import secrets
import socket
import time
from protocol import ACK, FRAME_DATA, STATUS, command, control

# Local candidate identifier, not an FPGA hash readback.
EXPECTED_BIT_SHA256 = 'F5367A73402B29EC03E477AE3FD7B6312A810DD173AC800698F10B98159B4A98'


class CameraClient:
    def __init__(self, bind, board, port, stop):
        self.endpoint = (board, port)
        self.stop = stop
        self.seq = secrets.randbelow(65536)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16*1024*1024)
            self.sock.bind((bind, 0))
        except Exception:
            self.sock.close()
            raise

    def close(self):self.sock.close()

    def receive(self, deadline):
        while True:
            if self.stop.is_set():
                raise RuntimeError('Diagnostic cancelled')
            remain = deadline-time.monotonic()
            if remain <= 0:
                raise TimeoutError('Timed out waiting for board response')
            self.sock.settimeout(min(remain,.2))
            try:
                data,peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            if peer==self.endpoint:return data

    def transact(self, kind, args=(0,0,0,0)):
        self.seq = (self.seq+1)&65535
        request = command(kind,self.seq,args)
        buffered = []
        status = None
        for _ in range(3):
            self.sock.sendto(request,self.endpoint)
            deadline = time.monotonic()+1
            while True:
                try:data = self.receive(deadline)
                except TimeoutError:break
                if len(data)>=6 and data[5]==FRAME_DATA:
                    if len(buffered)<3006:buffered.append(data)
                    continue
                try:reply = control(data)
                except ValueError:continue
                if reply['type']==STATUS and reply['seq']==self.seq:
                    status = reply
                if (reply['type']==ACK and reply['seq']==self.seq
                        and reply['original']==kind):
                    return reply,buffered,status
        raise TimeoutError(f'No ACK for command {kind}')
