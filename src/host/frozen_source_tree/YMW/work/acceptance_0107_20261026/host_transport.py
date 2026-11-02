"""Strict offline experimental 0107 transport adapter; never opens a socket.

Packets remain provisional until a fresh, sequence-bound committed metadata
response, complete trusted request context, CRC and H1/H2 all agree.
"""
import hashlib
import importlib.util
import math
import struct
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]

def pinned_module(name,path,digest):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('changed reference '+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

legacy=pinned_module('transport_legacy_identity',REPO/'TJ/work/fpga_image_pipeline/software/identity_diag.py',
    'd997d95a55759d2ed3fc4f676c123a9c51f7141a8fa8d86327606113760a6a95')
codec=pinned_module('transport_gray_codec',HERE.parent/'gray_sat_0105_20261025/codec.py',
    '2eeb1760dde94f8cae3c2b3cb133c8a5c086efd6a9cf19da6c7c60363041cba4')
reference=pinned_module('transport_integer_reference',HERE.parent/'inspection_console_0105_20261022/vendor/software/ymw_integer_reference.py',
    'caefc8519c355cc7670cf7fb95986f0cc4fd2885ffb618061dc9899ba84186de')
FORMATS=(1,0x31,0x32)
import dual_view
TAG_KEYS=('session','request_id','config_epoch','dvp_sequence','publish_sequence','roi_generation','camera_generation','light_generation','frame_id')
REQUEST_KEYS=tuple(k for k in TAG_KEYS if k not in ('dvp_sequence','publish_sequence'))
PARAM_KEYS=('exposure_lines','gain16','light_mask','brightness','settle_frames','discard_frames')

def payload_size(width,height,fmt):
    n,gray_size=codec.layout(width,height)
    if type(fmt) is not int or fmt not in FORMATS:raise ValueError('unsupported format')
    return n*2 if fmt==1 else 3*n+(n+7)//8 if fmt==50 else gray_size

def decode_capabilities(data,expected_seq):
    if not isinstance(data,bytes) or len(data)!=32:raise ValueError('capability length')
    magic,v,kind,seq,n=struct.unpack('!4sBBHH',data[:10])
    schema,fw,fmt,supported,reserved,chunk,w,h,poly,flags=struct.unpack('!BHBBBHHHQH',data[10:])
    if (magic,v,kind,seq,n,schema,fw,supported,reserved,chunk,w,h,poly,flags)!=(
            b'LGHT',1,0x86,expected_seq,22,1,0x0107,7,0,1380,1920,1080,0x42f0e1eba9ea3693,1) or fmt not in FORMATS:
        raise ValueError('unsupported capability/version/sequence')
    return {'firmware':fw,'format':fmt,'formats':FORMATS,'payload_crc64_required':True}

def decode_metadata(data,expected_seq):
    if not isinstance(data,bytes) or len(data)!=170:raise ValueError('metadata length')
    if data[10]!=2 or int.from_bytes(data[14:16],'big')!=0x0107:raise ValueError('experimental schema/firmware')
    if int.from_bytes(data[6:8],'big')!=expected_seq:raise ValueError('metadata query sequence')
    fmt,reserved1,reserved2,n,crc=struct.unpack('!BBHIQ',data[154:170])
    if fmt not in FORMATS or reserved1 or reserved2:raise ValueError('transport descriptor')
    # Delegate unchanged fields/bounds to the pinned 0105 parser, then restore
    # explicit 0107 identity. This is a validation view, never a fallback mode.
    view=bytearray(data);view[10]=1;view[14:16]=b'\x01\x05';view[154:]=bytes(16)
    meta=legacy.decode(bytes(view));meta.update(schema=2,firmware=0x0107,pixel_format=fmt,payload_bytes=n,payload_crc64=crc)
    if meta['valid']:
        if n!=payload_size(*meta['roi'][2:],fmt):raise ValueError('payload size metadata')
        if fmt==1 and crc!=meta['rgb_crc64']:raise ValueError('RGB CRC semantic mismatch')
    return meta

def planes_from_payload(raw,width,height,fmt):
    if len(raw)!=payload_size(width,height,fmt):raise ValueError('payload size')
    if fmt==50:return dual_view.decode(raw,width,height,codec=codec)[1:]
    if fmt==0x31:return codec.decode(raw,width,height)
    words=np.frombuffer(raw,dtype='>u2').reshape(height,width).astype(np.uint32)
    r,g,b=(words>>11)&31,(words>>5)&63,words&31
    image=np.stack(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)),axis=2).astype(np.uint8)
    return codec.planes(image)

def recompute(gray,sat,board):
    n=gray.size;count=int(board.sum())
    statistics=dict(pixel_count=n,gray_sum=int(gray.sum(dtype=np.uint64)),near_black=int((gray<=5).sum()),
        near_white=int((gray>=250).sum()),rgb_any_max=int(sat.sum()),board_count=count,
        board_gray_sum=int(gray[board].sum(dtype=np.uint64)),board_dark=int(((gray<=10)&board).sum()),
        board_white=int(((gray>=250)&board).sum()),board_rgb_any_max=int((sat&board).sum()))
    h2=reference.integer_h2(gray);absolute=np.abs(h2['residual_n'].astype(np.int32))
    features=dict(strong_count=int((absolute>1620).sum()),weak_count=int((absolute>648).sum()),
        sum9_total=int(h2['sum9'].sum(dtype=np.uint64)),residual_n_total=int(h2['residual_n'].sum(dtype=np.int64)))
    return statistics,features

class StrictReceiver:
    def __init__(self,*,identity,parameters,roi,board,pixel_format,started,timeout=30,full_frame_pixels=1920*1080):
        if set(identity)!=set(REQUEST_KEYS) or any(type(v) is not int or v<0 for v in identity.values()):raise ValueError('complete trusted request identity required')
        if not 0<identity['session']<2**64 or not 0<identity['request_id']<2**32:raise ValueError('session/request')
        for k in REQUEST_KEYS:
            if identity[k]>=(2**32 if k in ('request_id','config_epoch') else 2**64 if k=='session' else 2**16):raise ValueError('identity bounds')
        if identity['config_epoch']==0:raise ValueError('configuration epoch')
        if set(parameters)!=set(PARAM_KEYS) or any(type(v) is not int for v in parameters.values()):raise ValueError('trusted executed parameters required')
        if not (1<=parameters['exposure_lines']<=1116 and 16<=parameters['gain16']<=1023 and 1<=parameters['light_mask']<=15 and 0<=parameters['brightness']<=255 and all(0<=parameters[k]<=255 for k in ('settle_frames','discard_frames'))):raise ValueError('parameter bounds')
        if not isinstance(roi,(list,tuple)) or len(roi)!=4 or any(type(v) is not int for v in roi):raise ValueError('ROI')
        x,y,w,h=roi
        if min(x,y)<0 or min(w,h)<9 or x+w>1920 or y+h>1080:raise ValueError('ROI bounds')
        if not isinstance(board,np.ndarray) or board.dtype!=np.bool_ or board.shape!=(h,w) or not board.any():raise ValueError('trusted nonempty sealed board mask')
        if type(full_frame_pixels) is not int or not w*h<=full_frame_pixels<=1920*1080:raise ValueError('full-frame drain size')
        if not math.isfinite(started) or not math.isfinite(timeout) or timeout<=0:raise ValueError('deadline')
        self.identity=dict(identity);self.parameters=dict(parameters);self.roi=list(roi);self.board=board.copy();self.fmt=pixel_format
        self.size=payload_size(w,h,pixel_format);self.count=(self.size+1379)//1380
        self.started=started;self.timeout=timeout;self.full_pixels=full_frame_pixels
        self.parts={};self.duplicates=0;self.failed=False;self.committed=False

    def check_time(self,now):
        if self.failed or self.committed:raise ValueError('terminal receiver')
        if not math.isfinite(now) or now<self.started or now-self.started>self.timeout:raise TimeoutError('deadline')

    def reject(self):
        if not self.committed:self.failed=True;self.parts.clear()

    def cancel(self):
        """Discard provisional bytes; the live caller must also cancel/off/ACK."""
        self.reject()

    def add_packet(self,data,*,now):
        try:
            self.check_time(now)
            if not isinstance(data,bytes) or not 20<=len(data)<=1400:raise ValueError('packet length')
            magic,v,kind,fid,pid,count,n,w,h,fmt,flags=codec.HEADER.unpack(data[:20])
            if (magic,v,kind,fid,count,w,h,fmt)!=(b'LGHT',1,0x90,self.identity['frame_id'],self.count,self.roi[2],self.roi[3],self.fmt):raise ValueError('packet identity/format/geometry')
            if not 0<=pid<count or n!=min(1380,self.size-pid*1380) or len(data)!=20+n or flags!=(int(pid==0)|(int(pid==count-1)<<1)):raise ValueError('packet index/length/flags')
            part=data[20:]
            if pid in self.parts:
                if self.parts[pid]!=part:raise ValueError('conflicting duplicate')
                self.duplicates+=1
            else:self.parts[pid]=part
            # Even the complete packet set remains provisional.
            return None
        except Exception:self.reject();raise

    def finalize(self,metadata,*,expected_query_seq,now,previous_publication=None):
        try:
            self.check_time(now)
            if len(self.parts)!=self.count:raise ValueError('missing packet')
            meta=decode_metadata(metadata,expected_query_seq)
            if not meta['logical_association_available'] or not meta['mask_valid'] or meta['error'] or meta['pixel_format']!=self.fmt:raise ValueError('not committed/format/mask')
            if any(meta['identity'][k]!=v for k,v in self.identity.items()) or meta['parameters']!=self.parameters or meta['roi']!=self.roi:raise ValueError('request/executor binding')
            if meta['request_counter']!=self.identity['request_id'] or meta['fifo_reads']!=self.full_pixels:raise ValueError('request counter/full DDR drain')
            if meta['wait_complete_frames']!=self.parameters['settle_frames'] or meta['discard_complete_frames']!=self.parameters['discard_frames']:raise ValueError('incomplete waits')
            if previous_publication is not None:
                if set(previous_publication)!=set(TAG_KEYS) or any(type(v) is not int or v<0 for v in previous_publication.values()) or previous_publication['session']!=self.identity['session']:raise ValueError('previous publication context')
                if meta['identity']['request_id']<=previous_publication['request_id']:raise ValueError('request counter cannot wrap in a session')
                for k in ('request_id','dvp_sequence','publish_sequence'):
                    delta=(meta['identity'][k]-previous_publication[k])&0xffffffff
                    if not 0<delta<0x80000000:raise ValueError('stale publication')
            raw=b''.join(self.parts[k] for k in range(self.count))
            if len(raw)!=meta['payload_bytes'] or legacy.crc64_ecma(raw)!=meta['payload_crc64']:raise ValueError('payload CRC64')
            gray,sat=planes_from_payload(raw,*self.roi[2:],self.fmt)
            if self.fmt==50:
                rgb,_,_=dual_view.decode(raw,*self.roi[2:],codec=codec)
                if legacy.crc64_ecma(rgb)!=meta['rgb_crc64']:raise ValueError('Original frozen RGB CRC64')
            statistics,features=recompute(gray,sat,self.board)
            if statistics!=meta['statistics'] or features!=meta['features']:raise ValueError('H1/H2 content mismatch')
            self.committed=True;self.parts.clear()
            return {'gray':gray,'sat':sat,'metadata':meta,'payload':raw,'metadata_packet':metadata,
                    'board_mask_sha256':hashlib.sha256(self.board.astype(np.uint8).tobytes()).hexdigest(),
                    'payload_sha256':hashlib.sha256(raw).hexdigest(),
                    'physical_freshness_verified':False,'hardware_tested':False}
        except Exception:self.reject();raise
