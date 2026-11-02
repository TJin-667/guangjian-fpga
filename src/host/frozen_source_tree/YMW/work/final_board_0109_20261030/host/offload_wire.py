"""Strict0109 extension codec/client. Importing this module never opens a socket.

The caller supplies a shared transport and sequence allocator. Legacy capture
and extension traffic MUST use that same socket/allocator, under one owner.
This layer does not enable the unqualified bit or replace an installed SDK.
"""
from dataclasses import dataclass
import math,struct,time,zlib
import numpy as np

HEADER=struct.Struct('>4sBBHH')
OPERATIONS={16:'REG',17:'BEGIN',18:'ARM',19:'STATUS',20:'QWORD',21:'QSEAL',22:'FUSE',23:'FETCH',24:'RELEASE',25:'ABORT',26:'PROFILE',27:'CONFIG',31:'CAPABILITIES'}

class ProtocolError(ValueError):pass
class BoardRejected(ProtocolError):
    def __init__(self,response):
        self.response=response;super().__init__(f'{OPERATIONS[response.op]} status {response.status}; no automatic mutation retry')

def require(condition,message):
    if not condition:raise ProtocolError(message)
def uint(value,bits,name):
    require(type(value) is int and 0<=value<(1<<bits),f'{name} must be uint{bits}');return value

def command(op,args,sequence):
    require(op in OPERATIONS,'Unsupported0109 operation')
    return HEADER.pack(b'LGHT',1,uint(op,8,'operation'),uint(sequence,16,'sequence'),10)+b'\0\0'+uint(args,64,'arguments').to_bytes(8,'big')

@dataclass(frozen=True)
class Response:
    op:int;sequence:int;status:int;flags:int;cookie:int;request:int;group:int;digest:bytes;roi:tuple
    packet:int;payload:bytes;crc32:int;ticket:int;completed_slots:int;slot:int;association_error:bool;scratch_error:int;wire:bytes
    @property
    def published(self):return bool(self.flags&2)
    @property
    def fatal(self):return bool(self.flags&1)
    @property
    def scratch_ready(self):return bool(self.flags&64)
    @property
    def job_busy(self):return bool(self.flags&4)

def decode(data,*,op,sequence):
    require(type(data) is bytes and 74<=len(data)<=1098,'0109 response length')
    magic,version,kind,seq,length=HEADER.unpack_from(data)
    require((magic,version,kind,seq)==(b'LGHT',1,0x88,sequence),'0109 response header/sequence')
    require(length==len(data)-10,'0109 response body length')
    body=data[10:];require((body[0],body[1],body[63])==(1,op,9),'0109 response schema/op/revision')
    require(body[2]<=7 and body[60]<=8 and body[61]<=8 and body[62]&0x70==0,'0109 invalid status/slot/reserved bits')
    payload=body[64:];count=int.from_bytes(body[48:52],'big');crc=int.from_bytes(body[52:56],'big')
    require(count==len(payload),'0109 payload count')
    if payload:
        require(body[2]==0 and ((op==23 and len(payload)<=1024 and len(payload)%4==0) or (op==26 and len(payload)==28) or (op==27 and len(payload)==16)),'0109 unexpected/unaligned payload')
        require(zlib.crc32(payload)==crc,'0109 result payload CRC32')
    else:require(crc==0,'0109 empty response CRC must be zero')
    return Response(op,seq,body[2],body[3],int.from_bytes(body[4:8],'big'),int.from_bytes(body[8:12],'big'),int.from_bytes(body[12:20],'big'),
        body[20:36],struct.unpack_from('>4H',body,36),int.from_bytes(body[44:48],'big'),payload,crc,int.from_bytes(body[56:60],'big'),
        body[60],body[61],bool(body[62]&128),body[62]&15,data)

def quality_words(valid):
    """Pack an exact frozen PC valid_mask; partial native-ROI edge tiles count."""
    valid=np.asarray(valid);require(valid.ndim==2 and valid.dtype==np.bool_,'Boolean native ROI quality map required')
    h,w=valid.shape;require(9<=w<=1920 and 9<=h<=1080,'Unsupported native ROI')
    tiles=[]
    for y in range(0,h,32):
        for x in range(0,w,32):
            tile=valid[y:y+32,x:x+32];require(np.all(tile==tile[0,0]),'Quality map must use exact ROI-anchored32x32 tiles')
            tiles.append(bool(tile[0,0]))
    require(len(tiles)<=2048,'Quality RAM capacity')
    words=[sum(int(v)<<(i%32) for i,v in enumerate(tiles[start:start+32])) for start in range(0,len(tiles),32)]
    raw=b''.join(word.to_bytes(4,'little') for word in words)
    return words,len(tiles),zlib.crc32(raw)

class ExtensionClient:
    """Transport(request_bytes,sequence,timeout_s)->reply_bytes, same live owner.

    For an actual UDP retry, transport must resend the IDENTICAL command and
    sequence; never manufacture a fresh sequence after an uncertain mutation.
    A returned BUSY is terminal for that command. A later poll uses a new seq.
    """
    def __init__(self,transport,next_sequence,*,timeout_s=2,trace=None):
        require(callable(transport) and callable(next_sequence),'Shared transport/sequence callbacks required')
        require(type(timeout_s) in (int,float) and math.isfinite(timeout_s) and timeout_s>0,'Finite timeout required')
        self.transport=transport;self.next_sequence=next_sequence;self.timeout=timeout_s;self.trace=trace
        self.group=None;self.digest=None;self.roi=None;self.cookie=0;self.slot=0;self.request=0
    def rpc(self,op,args=0):
        sequence=self.next_sequence();request=command(op,args,sequence)
        reply=decode(self.transport(request,sequence,self.timeout),op=op,sequence=sequence)
        if self.trace:self.trace(request,reply.wire)
        if reply.status:raise BoardRejected(reply)
        require(not reply.fatal,'Board quarantined; coherent reset required')
        return reply
    def bound(self,response):
        require((response.group,response.digest,response.roi)==(self.group,self.digest,self.roi),'Group/digest/native ROI mismatch')
        require(not response.association_error,'Captured frame association mismatch')
        return response
    def begin(self,group,digest,roi,*,low=400,high=800):
        uint(group,64,'group');require(group>0 and type(digest) is bytes and len(digest)==16 and any(digest),'Nonzero group/digest required')
        roi=tuple(roi);require(len(roi)==4 and all(type(v) is int and 0<=v<=65535 for v in roi),'Integer ROI required')
        x,y,w,h=roi;require(9<=w<=1920 and 9<=h<=1080 and x+w<=1920 and y+h<=1080,'Native sensor ROI bounds')
        require(self.group is None,'Release the previous result before BEGIN')
        require(type(low) is int and type(high) is int and 1<=low<high<=1116,'Legal ordered low/high sensor lines required')
        registers=[group>>32,group&0xffffffff,*struct.unpack('>4I',digest),low,high]
        for index,value in enumerate(registers):self.rpc(16,(index<<32)|value)
        response=self.rpc(17);require((response.group,response.digest,response.roi)==(group,digest,roi),'BEGIN snapshot differs from reviewed configuration')
        require(response.completed_slots==0 and not response.published,'BEGIN did not clear old result')
        self.group,self.digest,self.roi=group,digest,roi;self.cookie=self.slot=self.request=0
        configuration=self.configuration()
        require((configuration['low'],configuration['high'])==(low,high),'Board frozen exposure differs from requested pair')
        return response
    def configuration(self):
        response=self.rpc(27)
        if self.group is not None:self.bound(response)
        magic,low,high,gain,LED,features,maximum,schema,revision=struct.unpack('>4sHHHBBHBB',response.payload)
        require(magic==b'GJC9' and (gain,LED,features,maximum,schema,revision)==(16,128,3,1116,1,9) and 1<=low<high<=maximum,'Malformed or unsupported0109 configuration echo')
        return dict(low=low,high=high,gain16=gain,LED=LED,features=features,maximum_lines=maximum)
    def profile(self,stage):
        require(type(stage) is int and stage in (0,1,2) and self.group is not None and self.slot>0,'Completed bound frame and valid stage required')
        response=self.bound(self.rpc(26,(stage<<32)|self.cookie))
        require((response.cookie,response.request,response.slot,response.completed_slots)==(self.cookie,self.request,self.slot,self.slot),'Profile frame identity mismatch')
        magic,actual_stage,frequency,cycles,count0,count1,blocked=struct.unpack('>4s6I',response.payload)
        require(magic==b'GJP9' and actual_stage==stage and frequency==(125000000 if stage==0 else 100000000),'Profile schema/stage/frequency mismatch')
        require(cycles>0 and count0<=cycles and count1<=cycles and blocked<=cycles,'Impossible stage cycle counts')
        pixels=self.roi[2]*self.roi[3];beats=(pixels+3)//4
        expected=(pixels,None) if stage==0 else ((beats,(beats+15)//16) if stage==1 else (beats*(1 if self.slot==1 else 2),beats))
        require(count0==expected[0] and (expected[1] is None or count1==expected[1]),'Stage completed-handshake counts differ from frame size')
        labels=(('H2 output pixels','H2 output backpressure cycles'),('scratch W beats','scratch B responses'),('fusion R beats','fusion W beats'))[stage]
        return dict(stage=stage,clock_hz=frequency,service_cycles=cycles,service_seconds=cycles/frequency,count0=count0,count1=count1,count0_meaning=labels[0],count1_meaning=labels[1],blocked_cycles=blocked,
            group=self.group,cookie=self.cookie,request=self.request,slot=self.slot,scope='Same-domain inclusive service, includes memory/CDC/backpressure waits; not arithmetic-only cycles',raw_response_hex=response.wire.hex())
    def arm(self,cookie,slot):
        require(self.group is not None,'BEGIN required');uint(cookie,32,'cookie');uint(slot,4,'slot')
        require(cookie>self.cookie and slot==self.slot+1 and slot<=8,'Monotonic cookie/slot required')
        response=self.bound(self.rpc(18,(cookie<<32)|slot))
        require(response.cookie==cookie and response.slot==slot and response.request>0,'ARM frame binding')
        self.cookie,self.request=cookie,response.request;return response
    def wait_scratch(self,*,deadline):
        while time.monotonic()<deadline:
            response=self.bound(self.rpc(19))
            require((response.cookie,response.request)==(self.cookie,self.request),'Scratch frame identity changed')
            if response.scratch_error:raise ProtocolError(f'Scratch writer error{response.scratch_error}; discard the failed frame')
            if response.scratch_ready:return response
            time.sleep(.02)
        raise TimeoutError('Durable scratch completion deadline; frame not fused')
    def upload_quality(self,valid):
        require(self.roi is not None and np.shape(valid)==(self.roi[3],self.roi[2]),'Quality map native dimensions mismatch')
        words,tiles,crc=quality_words(valid)
        for index,value in enumerate(words):
            response=self.bound(self.rpc(20,(index<<32)|value))
            require((response.cookie,response.request)==(self.cookie,self.request),'Quality upload frame binding')
        return self.bound(self.rpc(21,(tiles<<32)|crc))
    def fuse(self,slot,*,deadline):
        require(slot==self.slot+1 and 1<=slot<=8,'Out-of-order FUSE')
        response=self.bound(self.rpc(22,(self.cookie<<32)|slot))
        require((response.cookie,response.request)==(self.cookie,self.request),'FUSE accepted wrong frame')
        while time.monotonic()<deadline:
            response=self.bound(self.rpc(19))
            require((response.cookie,response.request)==(self.cookie,self.request),'FUSE completion identity changed')
            if response.scratch_error:raise ProtocolError(f'Fusion DMA error{response.scratch_error}; old bank remains committed')
            if response.completed_slots==slot and not response.job_busy:
                require(response.published==(slot==8),'Premature/missing group publication');self.slot=slot;return response
            time.sleep(.02)
        raise TimeoutError('Fusion completion deadline; do not start next frame')
    def fetch(self):
        require(self.slot==8,'Eight committed frames required');total=self.roi[2]*self.roi[3]*4;chunks=[]
        for index in range((total+1023)//1024):
            response=self.bound(self.rpc(23,(index<<32)|(self.group&0xffffffff)))
            require(response.completed_slots==8 and response.published,'Result is no longer published')
            require(response.packet==index and len(response.payload)==min(1024,total-index*1024),'Wrong/missing result block')
            require((response.cookie,response.request)==(self.cookie,self.request),'Result frame-eight binding changed')
            chunks.append(response.payload)
        raw=b''.join(chunks);require(len(raw)==total,'Incomplete result');return raw
    def release(self):
        require(self.group is not None,'No active group');response=self.bound(self.rpc(24,self.group));require(not response.published,'Release failed')
        self.group=self.digest=self.roi=None;self.cookie=self.slot=self.request=0;return response
