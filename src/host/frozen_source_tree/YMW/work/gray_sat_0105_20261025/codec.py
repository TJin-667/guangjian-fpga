"""Experimental GRAY8+SAT1 contract. Offline codec, not a board driver."""
import hashlib
import math
import struct
import numpy as np

FORMAT = 0x31  # Experimental allocation; no deployed firmware advertises it.
HEADER = struct.Struct('!4sBBHHHHHHBB')
CHUNK = 1380
MAX_PIXELS = 1920 * 1080


def layout(width, height):
    if type(width) is not int or type(height) is not int or not 1 <= width <= 1920 or not 1 <= height <= 1080:
        raise ValueError('dimensions')
    n = width * height
    return n, n + (n + 7) // 8


def planes(bgr):
    if not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError('BGR uint8 required')
    layout(bgr.shape[1], bgr.shape[0])
    a = bgr.astype(np.uint32)
    gray = ((9798*a[:,:,2] + 19235*a[:,:,1] + 3735*a[:,:,0] + 16384) >> 15).astype(np.uint8)
    return gray, (bgr == 255).any(axis=2)


def encode(gray, sat):
    if not isinstance(gray, np.ndarray) or gray.dtype != np.uint8 or gray.ndim != 2:
        raise ValueError('gray8 required')
    if not isinstance(sat, np.ndarray) or sat.dtype != np.bool_ or sat.shape != gray.shape:
        raise ValueError('SAT1 shape/type')
    n, _ = layout(gray.shape[1], gray.shape[0])
    g, s = gray.reshape(-1), sat.reshape(-1)
    groups = (n + 7) // 8
    padded_g = np.zeros(groups*8, np.uint8); padded_g[:n] = g
    padded_s = np.zeros(groups*8, np.uint8); padded_s[:n] = s
    records = np.empty((groups, 9), np.uint8)
    records[:, :8] = padded_g.reshape(-1, 8)
    records[:, 8] = np.packbits(padded_s.reshape(-1, 8), axis=1, bitorder='big')[:,0]
    tail = n % 8
    if not tail:
        return records.tobytes()
    return records[:-1].tobytes() + records[-1,:tail].tobytes() + bytes([records[-1,8]])


def decode(raw, width, height):
    n, size = layout(width, height)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('payload length')
    groups, tail = divmod(n, 8)
    block = np.frombuffer(raw[:groups*9], np.uint8).reshape(groups, 9)
    gray = np.empty(n, np.uint8); sat = np.empty(n, np.bool_)
    gray[:groups*8] = block[:,:8].reshape(-1)
    sat[:groups*8] = np.unpackbits(block[:,8,None], axis=1, bitorder='big').reshape(-1).astype(bool)
    if tail:
        last = raw[groups*9:]
        if last[-1] & ((1 << (8-tail))-1): raise ValueError('nonzero tail padding')
        gray[groups*8:] = np.frombuffer(last[:tail], np.uint8)
        sat[groups*8:] = np.unpackbits(np.array([last[-1]], np.uint8), bitorder='big')[:tail].astype(bool)
    return gray.reshape(height,width), sat.reshape(height,width)


def packets(raw, width, height, frame_id):
    _, size = layout(width, height)
    if len(raw) != size or type(frame_id) is not int or not 0 <= frame_id <= 65535:
        raise ValueError('frame')
    count = math.ceil(size/CHUNK)
    for pid in range(count):
        part = raw[pid*CHUNK:(pid+1)*CHUNK]
        flags = int(pid==0) | (int(pid==count-1)<<1)
        yield HEADER.pack(b'LGHT',1,0x90,frame_id,pid,count,len(part),width,height,FORMAT,flags)+part


class Receiver:
    """Bounded offline reassembly. Final digest is required before publication.

    Live acquisition must ALSO bind trusted request/session/frame and camera/ROI
    receipts. A 16-bit wire frame ID plus hash is not a full provenance contract.
    """
    def __init__(self, width, height, frame_id, expected_sha256, *, started, timeout=10):
        _, self.size = layout(width,height)
        if type(frame_id) is not int or not 0 <= frame_id <= 65535: raise ValueError('frame ID')
        if not isinstance(expected_sha256,str) or len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
            raise ValueError('digest')
        if not math.isfinite(started) or not math.isfinite(timeout) or timeout <= 0: raise ValueError('deadline')
        self.width,self.height,self.fid = width,height,frame_id
        self.digest,self.started,self.timeout = expected_sha256,started,timeout
        self.count=math.ceil(self.size/CHUNK); self.parts={}; self.duplicates=0; self.done=False; self.failed=False

    def add(self, data, *, now):
        if self.failed or self.done: raise ValueError('terminal receiver')
        try:
            if not math.isfinite(now) or now<self.started or now-self.started>self.timeout: raise TimeoutError('deadline')
            if not isinstance(data,bytes) or not 20 <= len(data) <= 1400: raise ValueError('datagram')
            magic,v,kind,fid,pid,count,n,w,h,fmt,flags=HEADER.unpack(data[:20])
            if (magic,v,kind,fid,count,w,h,fmt)!=(b'LGHT',1,0x90,self.fid,self.count,self.width,self.height,FORMAT):
                raise ValueError('format/identity/geometry')
            if not 0<=pid<count or n!=min(CHUNK,self.size-pid*CHUNK) or len(data)!=20+n:
                raise ValueError('packet length/index')
            if flags!=(int(pid==0)|(int(pid==count-1)<<1)): raise ValueError('flags')
            part=data[20:]
            if pid in self.parts:
                if self.parts[pid]!=part: raise ValueError('conflicting duplicate')
                self.duplicates+=1; return None
            self.parts[pid]=part
            if len(self.parts)==self.count:
                raw=b''.join(self.parts[i] for i in range(self.count))
                if hashlib.sha256(raw).hexdigest()!=self.digest: raise ValueError('content digest')
                result=decode(raw,self.width,self.height)
                self.done=True; return result
            return None
        except Exception:
            self.failed=True; self.parts.clear(); raise


def tile_quality_gray(gray,sat,board,tile_size=32,rgb_penalty=4,dark_penalty=4):
    if gray.dtype!=np.uint8 or gray.ndim!=2 or sat.dtype!=np.bool_ or sat.shape!=gray.shape:
        raise ValueError('planes')
    if board.dtype!=np.bool_ or board.shape!=gray.shape or not board.any(): raise ValueError('board')
    if type(tile_size)!=int or tile_size<2 or any(type(p)!=int or p<0 for p in (rgb_penalty,dark_penalty)):
        raise ValueError('quality configuration')
    q=np.zeros(gray.shape,np.uint16); rows=[]
    for y in range(0,gray.shape[0],tile_size):
        for x in range(0,gray.shape[1],tile_size):
            sl=np.s_[y:y+tile_size,x:x+tile_size]; m=board[sl]; n=int(m.sum())
            clipped=int((sat[sl]&m).sum()); dark=int(((gray[sl]<=10)&m).sum())
            weight=256*n//(n+rgb_penalty*clipped+dark_penalty*dark) if n else 0
            q[sl]=weight
            rows.append(dict(x=x,y=y,width=m.shape[1],height=m.shape[0],board_pixels=n,
                rgb_max_pixels=clipped,dark_pixels=dark,rgb_max_fraction=clipped/n if n else None,
                dark_fraction=dark/n if n else None,quality_q8=weight))
    return dict(quality_q8=q,tiles=rows)
