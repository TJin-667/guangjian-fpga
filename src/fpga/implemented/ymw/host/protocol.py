"""Candidate LGHT v0.1 codec and bounded single-frame reassembly."""
import struct,time
MAGIC=b'LGHT';VERSION=1
LED_SET=1;CAPTURE=2;STATUS_QUERY=3;ACK=0x81;STATUS=0x82;FRAME_DATA=0x90
CAMERA_SET=4;CAMERA_GET=5;CAMERA_STATUS=0x83;MANUAL_CAPABILITY=0x20
ROI_SET=6;ROI_GET=7;ROI_STATUS=0x84;ROI_CAPABILITY=0x40
CAMERA_REGISTERS=(0x3503,0x3500,0x3501,0x3502,0x350a,0x350b,
                  0x380c,0x380d,0x380e,0x380f,0x350c,0x350d,0x300a,0x300b)
CHUNK=1380;HEADER=struct.Struct('!4sBBHHHHHHBB')
COLORS=(0xffff,0xffe0,0x07ff,0x07e0,0xf81f,0xf800,0x001f,0)

def command(kind,seq,args=(0,0,0,0)):
    return struct.pack('!4sBBHHBB4H',MAGIC,1,kind,seq,10,0,0,*args)

def control(data):
    if len(data)<10:raise ValueError('short control header')
    magic,version,kind,seq,n=struct.unpack('!4sBBHH',data[:10])
    if magic!=MAGIC or version!=1 or len(data)!=10+n:raise ValueError('bad control envelope')
    if kind==ACK and n==10:
        original,result,frame,busy,caps,reserved=struct.unpack('!BB4H',data[10:])
        if reserved or busy>1 or result>5:raise ValueError('bad ACK')
        return dict(type=kind,seq=seq,original=original,result=result,frame_id=frame,busy=busy,capabilities=caps)
    if kind==STATUS and n==22:
        reserved,firmware,caps,state,error,commands,frames,dropped=struct.unpack('!5H3I',data[10:])
        if reserved:raise ValueError('bad STATUS')
        return dict(type=kind,seq=seq,firmware=firmware,capabilities=caps,state=state,error=error,commands=commands,frames=frames,dropped=dropped)
    if kind==CAMERA_STATUS and n==22:
        payload=data[10:]
        schema,flags,error,reserved=payload[:4]
        if schema!=1 or flags>1 or error>4 or reserved or payload[20:]!=b'\0\0':
            raise ValueError('bad CAMERA_STATUS')
        raw=payload[4:18]
        registers=dict(zip(CAMERA_REGISTERS,raw))
        exposure_raw=((raw[1]&15)<<16)|(raw[2]<<8)|raw[3]
        gain16=((raw[4]&3)<<8)|raw[5]
        hts=(raw[6]<<8)|raw[7];vts=(raw[8]<<8)|raw[9]
        dummy=(raw[10]<<8)|raw[11];chip_id=(raw[12]<<8)|raw[13]
        locked=bool(flags&1)
        if locked and (error or raw[0]!=3 or raw[1]>15 or raw[4]>3 or
                       exposure_raw&15 or not 1<=exposure_raw>>4<=1116 or
                       not 16<=gain16<=1023 or hts!=2500 or vts!=1120 or
                       dummy or chip_id!=0x5640):
            raise ValueError('inconsistent manual lock readback')
        return dict(type=kind,seq=seq,schema=schema,locked=locked,error=error,
                    mode=raw[0],exposure_raw=exposure_raw,exposure_lines=exposure_raw/16,
                    gain16=gain16,gain_x=gain16/16,hts=hts,vts=vts,dummy_lines=dummy,
                    chip_id=chip_id,generation=int.from_bytes(payload[18:20],'big'),
                    raw_registers={f'0x{k:04X}':v for k,v in registers.items()})
    if kind==ROI_STATUS and n==22:
        schema,flags,x,y,w,h,packets,last,generation,pixels,error,reserved=struct.unpack('!BB7HIBB',data[10:])
        if schema!=1 or flags>1 or error or reserved or not w or not h or x+w>1920 or y+h>1080:
            raise ValueError('bad ROI_STATUS')
        expected=(w*h+689)//690
        if pixels!=w*h or packets!=expected or last!=pixels-(expected-1)*690 or (flags and not generation):
            raise ValueError('inconsistent ROI packet geometry')
        return dict(type=kind,seq=seq,valid=bool(flags),roi=[x,y,w,h],packets=packets,
                    last_pixels=last,generation=generation,pixels=pixels)
    if n==10:
        reserved,*args=struct.unpack('!5H',data[10:])
        if reserved:raise ValueError('reserved bits')
        return dict(type=kind,seq=seq,args=args)
    raise ValueError('unsupported control length')

def test_image(width,height,source=0):
    if width<1 or height<1 or source not in (0,1):raise ValueError('bad image')
    if source==1:return bytes(i&255 for i in range(width*height*2))
    return b''.join(struct.pack('!H',0 if x==0 or y==0 else COLORS[x*8//width]) for y in range(height) for x in range(width))

def frame_packets(raw,width,height,frame_id):
    if not 1<=width<=65535 or not 1<=height<=65535 or len(raw)!=width*height*2:raise ValueError('shape')
    count=(len(raw)+CHUNK-1)//CHUNK
    if count>65535:raise ValueError('too many packets')
    for pid in range(count):
        payload=raw[pid*CHUNK:(pid+1)*CHUNK];flags=(1 if pid==0 else 0)|(2 if pid==count-1 else 0)
        yield HEADER.pack(MAGIC,1,FRAME_DATA,frame_id,pid,count,len(payload),width,height,1,flags)+payload

def parse_frame(data):
    if len(data)<20 or len(data)>1400:raise ValueError('datagram length')
    magic,v,kind,fid,pid,count,n,w,h,fmt,flags=HEADER.unpack(data[:20])
    total=w*h*2;expected=(total+CHUNK-1)//CHUNK
    if magic!=MAGIC or v!=1 or kind!=FRAME_DATA or fmt!=1 or not w or not h:raise ValueError('header')
    if count!=expected or not 0<=pid<count or len(data)!=20+n:raise ValueError('packet numbering/length')
    if n!=min(CHUNK,total-pid*CHUNK):raise ValueError('chunk length')
    if flags!=((1 if pid==0 else 0)|(2 if pid==count-1 else 0)):raise ValueError('flags')
    return fid,pid,count,w,h,data[20:]

class FrameReceiver:
    def __init__(self,timeout=2.0,max_bytes=8*1024*1024):
        if timeout<=0 or max_bytes<2:raise ValueError('limits')
        self.timeout=timeout;self.max_bytes=max_bytes;self.reset()
    def reset(self):self.meta=None;self.parts={};self.start=None;self.duplicates=0;self.complete=False
    def add(self,data,expected_frame=None,now=None):
        now=time.monotonic() if now is None else now
        fid,pid,count,w,h,payload=parse_frame(data)
        if expected_frame is not None and fid!=expected_frame:raise ValueError('stale frame')
        if w*h*2>self.max_bytes:raise ValueError('frame memory bound')
        meta=(fid,count,w,h)
        if self.meta is None:self.meta=meta;self.start=now
        if self.meta!=meta:raise ValueError('inconsistent frame')
        if now-self.start>self.timeout:raise TimeoutError(f'missing {count-len(self.parts)} packets')
        if pid in self.parts:
            if self.parts[pid]!=payload:raise ValueError('conflicting duplicate')
            self.duplicates+=1;return None
        self.parts[pid]=payload
        if len(self.parts)==count:
            self.complete=True
            return b''.join(self.parts[i] for i in range(count))
        return None
    def missing(self):return [] if self.meta is None else [i for i in range(self.meta[1]) if i not in self.parts]

def rgb888(raw):
    if len(raw)%2:raise ValueError('odd RGB565 byte length')
    output=bytearray()
    for (v,) in struct.iter_unpack('!H',raw):
        r=(v>>11)&31;g=(v>>5)&63;b=v&31
        output.extend(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)))
    return bytes(output)

def save_png(path,raw,width,height):
    import zlib,binascii
    if len(raw)!=width*height*2:raise ValueError('shape')
    pixels=rgb888(raw)
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',binascii.crc32(kind+data)&0xffffffff)
    scan=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))
