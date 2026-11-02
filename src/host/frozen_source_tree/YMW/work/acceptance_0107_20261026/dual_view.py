"""Independent host diagnostic for the same frozen RGB/gray/SAT stream."""
import numpy as np

def encode(rgb,gray,sat):
    words=np.frombuffer(rgb,'>u2');g=gray.reshape(-1);s=sat.reshape(-1)
    if len(words)!=len(g) or len(s)!=len(g):raise ValueError('Plane size')
    out=bytearray()
    for start in range(0,len(g),8):
        k=min(8,len(g)-start)
        out.extend(rgb[2*start:2*(start+k)]);out.extend(g[start:start+k].tobytes())
        out.append(sum(int(s[start+i])<<(7-i) for i in range(k)))
    return bytes(out)

def decode(raw,width,height,*,codec):
    n=width*height
    if len(raw)!=3*n+(n+7)//8:raise ValueError('Dual-view length')
    complete=n//8;tail=n%8;at=complete*25
    groups=np.frombuffer(raw[:at],np.uint8).reshape(complete,25)
    rgb=bytearray(groups[:,:16].copy().tobytes())
    g=groups[:,16:24].copy().reshape(-1)
    sat=np.unpackbits(groups[:,24],bitorder='big')
    if tail:
        rgb.extend(raw[at:at+2*tail]);g=np.concatenate((g,np.frombuffer(raw[at+2*tail:at+3*tail],np.uint8)))
        value=raw[-1]
        if value&((1<<(8-tail))-1):raise ValueError('SAT tail padding')
        sat=np.concatenate((sat,np.unpackbits(np.array([value],np.uint8),bitorder='big')[:tail]))
    gray=g.reshape(height,width);sat=sat.astype(bool).reshape(height,width)
    words=np.frombuffer(rgb,'>u2').reshape(height,width).astype(np.uint32)
    r,g,b=(words>>11)&31,(words>>5)&63,words&31
    bgr=np.stack(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)),axis=2).astype(np.uint8)
    expected_g,expected_s=codec.planes(bgr)
    if not np.array_equal(gray,expected_g) or not np.array_equal(sat,expected_s):raise ValueError('Same frozen RGB/gray/SAT mismatch')
    return bytes(rgb),gray,sat
