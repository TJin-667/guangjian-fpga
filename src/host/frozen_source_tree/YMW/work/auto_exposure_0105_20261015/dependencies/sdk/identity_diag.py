"""Candidate 0x0105 sidecar codec. Image datagrams remain LGHT wire-v1.

Logical association never implies physically settled lighting or exposure.
"""
import struct
import binascii
import secrets
SESSION_BIND=8;IDENTITY_QUERY=9;MASK_WRITE=10;MASK_SEAL=11;WAIT_POLICY=12;CANCEL_CAPTURE=13
IDENTITY_STATUS=0x85
H1_KEYS=('pixel_count','gray_sum','near_black','near_white','rgb_any_max','board_count','board_gray_sum','board_dark','board_white','board_rgb_any_max')

def fresh_session():
    """Bind a fresh nonzero nonce after every reset/reconnect, never reuse one."""
    value=0
    while not value:value=secrets.randbits(64)
    return value

def crc64_ecma(data):
    """poly=42f0e1eba9ea3693, init=0, refin/refout=false, xorout=0."""
    if not hasattr(crc64_ecma,'table'):
        table=[]
        for b in range(256):
            c=b<<56
            for _ in range(8):c=((c<<1)^(0x42f0e1eba9ea3693 if c>>63 else 0))&0xffffffffffffffff
            table.append(c)
        crc64_ecma.table=table
    c=0
    for b in data:c=((c<<8)&0xffffffffffffffff)^crc64_ecma.table[(c>>56)^b]
    return c

def command(kind,seq,args=0):
    if not 0<=seq<=65535 or not 0<=args<2**64:raise ValueError('integer bounds')
    return struct.pack('!4sBBHHHQ',b'LGHT',1,kind,seq,10,0,args)

def decode_identity(raw):
    if len(raw)!=32:raise ValueError('identity length')
    session,req,cfg,dvp,pub,roi,camera,light,fid=struct.unpack('!Q4I4H',raw)
    return dict(session=session,request_id=req,config_epoch=cfg,dvp_sequence=dvp,publish_sequence=pub,
                roi_generation=roi,camera_generation=camera,light_generation=light,frame_id=fid)

def decode(data):
    if len(data)!=170:raise ValueError('sidecar length')
    magic,v,kind,seq,n=struct.unpack('!4sBBHH',data[:10]);p=data[10:]
    if (magic,v,kind,n)!=(b'LGHT',1,IDENTITY_STATUS,160) or p[0]!=1 or p[1]&240 or p[2]>7 or p[3]!=0 or p[41]!=0 or any(p[144:]):raise ValueError('sidecar schema/reserved fields')
    fw,fid=struct.unpack('!HH',p[4:8]);tag=decode_identity(p[8:40])
    if fw!=0x0105 or fid!=tag['frame_id'] or p[40]>1:raise ValueError('firmware/frame/bank identity')
    exp,gain,mask,brightness,settle,discard=struct.unpack('!HH4B',p[42:50])
    x,y,w,h=struct.unpack('!4H',p[50:58]);values=struct.unpack('!10I',p[58:98])
    wait,drop=struct.unpack('!2B',p[98:100]);stale,reads,counter,strong,weak=struct.unpack('!5I',p[100:120])
    total,residual=struct.unpack('!Qq',p[120:136])
    rgb_crc64=int.from_bytes(p[136:144],'big')
    valid=bool(p[1]&1);bound=bool(p[1]&2);params=bool(p[1]&4);mask_valid=bool(p[1]&8)
    if bound!=(tag['session']!=0):raise ValueError('inconsistent session flag')
    if params and not (1<=exp<=1116 and 16<=gain<=1023 and mask<=15):raise ValueError('readback parameters')
    if valid:
        if p[2]!=0 or not (9<=w<=1920 and 9<=h<=1080 and x+w<=1920 and y+h<=1080) or values[0]!=w*h:raise ValueError('committed geometry/statistics')
        if any(tag[k]==0 for k in ('request_id','config_epoch','dvp_sequence','publish_sequence')):raise ValueError('missing committed identity')
        if values[1]>255*values[0] or values[5]>values[0] or values[6]>255*values[5]:raise ValueError('sum/count bounds')
        if any(values[k]>values[0] for k in (2,3,4)) or any(values[k]>values[5] for k in (7,8,9)):raise ValueError('count bounds')
        if strong>weak or weak>values[0] or total>20655*values[0] or abs(residual)>20400*values[0]:raise ValueError('H2 summary bounds')
    return dict(schema=1,firmware=fw,seq=seq,valid=valid,bound=bound,parameters_valid=params,mask_valid=mask_valid,
        logical_association_available=valid and bound and params,physical_freshness_verified=False,error=p[2],
        identity=tag,bank=p[40],parameters=dict(exposure_lines=exp,gain16=gain,light_mask=mask,brightness=brightness,settle_frames=settle,discard_frames=discard),
        roi=[x,y,w,h],statistics=dict(zip(H1_KEYS,values)),wait_complete_frames=wait,discard_complete_frames=drop,
        stale_drops=stale,fifo_reads=reads,request_counter=counter,rgb_crc64=rgb_crc64,
        features=dict(strong_count=strong,weak_count=weak,sum9_total=total,residual_n_total=residual))

def require_association(meta,session,request_id,frame_id,raw=None,require_mask=True,expected_context=None):
    if not meta['logical_association_available'] or meta['error']!=0:raise ValueError('association unavailable; keep image provisional')
    tag=meta['identity']
    if (tag['session'],tag['request_id'],tag['frame_id'])!=(session,request_id,frame_id):raise ValueError('stale/ambiguous image identity')
    if expected_context is not None and any(tag.get(k)!=v for k,v in expected_context.items()):raise ValueError('requested configuration/ROI identity mismatch')
    if require_mask and not meta['mask_valid']:raise ValueError('board mask not sealed for this saved domain')
    if meta['wait_complete_frames']!=meta['parameters']['settle_frames'] or meta['discard_complete_frames']!=meta['parameters']['discard_frames']:raise ValueError('wait policy incomplete')
    if raw is None or len(raw)!=meta['roi'][2]*meta['roi'][3]*2 or crc64_ecma(raw)!=meta['rgb_crc64']:raise ValueError('image/metadata content binding absent or stale')
    return tag

def mask_commands(mask,width,height,generation,start_seq=0):
    """Yield byte-exact contiguous 32-bit writes and a CRC-bound seal.

    Caller must wait for and validate each ACK, retrying identical bytes/seq.
    This generator alone does not contact hardware.
    """
    if len(mask)!=width*height or not 9<=width<=1920 or not 9<=height<=1080 or not 0<=generation<=65535:raise ValueError('mask dimensions/generation')
    if any(v not in (0,1) for v in mask):raise ValueError('mask must contain 0/1')
    crc=0xffff;seq=start_seq
    for address in range((len(mask)+31)//32):
        bits=0
        for b in range(32):
            index=address*32+b
            if index<len(mask) and mask[index]:bits|=1<<(31-b)
        crc=binascii.crc_hqx(bits.to_bytes(4,'big'),crc);seq=(seq+1)&65535
        yield command(MASK_WRITE,seq,(address<<32)|bits)
    seq=(seq+1)&65535
    yield command(MASK_SEAL,seq,(width<<48)|(height<<32)|(generation<<16)|crc)
