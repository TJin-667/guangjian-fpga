"""Independent host audit of actual simulated0108 UDP bytes and DVP source."""
import argparse,csv,hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np
from derive_candidate import HERE,REPO
import struct
ACCEPT=HERE.parent/'acceptance_0107_20261026';KERNEL=HERE.parent/'fusion_offload_0108_20261028'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def audit(out):
    report=json.loads((out/'VERIFICATION.json').read_text('utf-8'))
    if report['status']!='PASS':raise ValueError('Completed RTL receipt required')
    # Firmware substitution is an explicitly labelled validation view for the
    # frozen0107 parser. Original wire bytes must be108; no capture fallback.
    sys.path.insert(0,str(ACCEPT));import host_transport as old
    sys.path.insert(0,str(HERE/'host'));from offload_wire import decode
    sys.path.insert(0,str(KERNEL/'host'));from result_codec import decode_words
    spec=importlib.util.spec_from_file_location('app_common',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
    vendor,_=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from ymw_integer_reference import integer_h2
    from light_inspection.real_baseline import assess_quality,hysteresis_connect
    frames={}
    for line in (out/'board_trace.jsonl').read_text('utf-8').splitlines():
        event=json.loads(line)
        if event['event']=='FRAME_START':
            identity=int(event['identity_hex'],16);frames[(identity>>192,(identity>>160)&0xffffffff)]=event['source_frame']
    raw=(out/'packets.bin').read_bytes();offset=0;images={};verified=[];pairs=[];result_blocks={};extended=[];profiles={}
    for row in csv.DictReader((out/'packets_index.csv').open()):
        n=int(row['length']);packet=raw[offset:offset+n];offset+=n
        if len(packet)!=n:raise ValueError('Truncated UDP trace')
        kind=packet[5];seq=int.from_bytes(packet[6:8],'big')
        if kind==0x90:
            header=old.codec.HEADER.unpack(packet[:20]);frame,pid=header[3:5]
            images.setdefault(frame,{})[pid]=packet
        elif kind==0x86:
            if int.from_bytes(packet[11:13],'big')!=0x109:raise ValueError('Actual capabilities firmware mismatch')
            view=bytearray(packet);view[11:13]=b'\x01\x07';old.decode_capabilities(bytes(view),seq)
        elif kind==0x85:
            if int.from_bytes(packet[14:16],'big')!=0x109:raise ValueError('Actual metadata firmware mismatch')
            view=bytearray(packet);view[14:16]=b'\x01\x07';meta=old.decode_metadata(bytes(view),seq)
            if not meta['valid']:continue
            tag=meta['identity'];x,y,w,h=meta['roi'];frame=tag['frame_id'];source_frame=frames[(tag['session'],tag['request_id'])]
            source=((np.arange(1024,dtype=np.uint32)*13)^(source_frame*271)).astype(np.uint16).reshape(32,32)
            rgb=source[y:y+h,x:x+w].astype('>u2').tobytes();gray,sat=old.planes_from_payload(rgb,w,h,1)
            expected=rgb if meta['pixel_format']==1 else old.codec.encode(gray,sat) if meta['pixel_format']==49 else old.dual_view.encode(rgb,gray,sat)
            payload=b''.join(images[frame][k][20:] for k in sorted(images[frame]))
            if payload!=expected or old.legacy.crc64_ecma(payload)!=meta['payload_crc64']:raise ValueError('Native DVP-to-network/CRC mismatch')
            board=(np.arange(w*h).reshape(h,w)%5<2)
            receiver=old.StrictReceiver(identity={k:tag[k] for k in old.REQUEST_KEYS},parameters=meta['parameters'],roi=meta['roi'],board=board,pixel_format=meta['pixel_format'],started=0,full_frame_pixels=1024)
            for k in reversed(sorted(images[frame])):receiver.add_packet(images[frame][k],now=0)
            result=receiver.finalize(bytes(view),expected_query_seq=seq,now=0)
            if not np.array_equal(result['gray'],gray) or not np.array_equal(result['sat'],sat):raise ValueError('Strict host plane mismatch')
            images.pop(frame);verified.append(dict(identity=tag,format=meta['pixel_format'],sha256=hashlib.sha256(payload).hexdigest()))
            if tag['session']==0x1080abcd12345678:pairs.append((tag,meta['parameters'],gray,board))
        elif kind==0x88:
            response=decode(packet,op=packet[11],sequence=seq)
            extended.append(dict(op=response.op,seq=seq,status=response.status,cookie=response.cookie,request=response.request,slots=response.completed_slots,bytes=len(response.payload)))
            if response.op==26 and response.status==0:
                magic,stage,hz,cycles,count0,count1,blocked=struct.unpack('>4s6I',response.payload)
                slot=response.slot;expected0=1024 if stage==0 else (256 if stage==1 or slot==1 else 512)
                expected1=None if stage==0 else (16 if stage==1 else 256)
                if magic!=b'GJP9' or stage not in (0,1,2) or hz!=(125000000 if stage==0 else 100000000) or not 1<=slot<=8 or response.cookie!=slot or response.request!=slot or response.completed_slots!=slot:
                    raise ValueError('Profile schema/domain/frame binding')
                if cycles<=0 or count0!=expected0 or (expected1 is not None and count1!=expected1) or max(count0,count1,blocked)>cycles:raise ValueError('Profile service/handshake counts')
                if (slot,stage) in profiles:raise ValueError('Repeated profile page')
                profiles[(slot,stage)]=dict(slot=slot,stage=stage,clock_hz=hz,cycles=cycles,count0=count0,count1=count1,blocked=blocked)
            if response.op==23 and response.status==0:
                if response.group!=0x1080abcd00000108 or response.roi!=(0,0,32,32) or response.completed_slots!=8 or not response.published or response.cookie!=8 or response.request!=8:raise ValueError('Result group/frame binding')
                if response.packet in result_blocks:raise ValueError('Unexpected repeated result block')
                result_blocks[response.packet]=response.payload
    if offset!=len(raw) or len(verified)!=17 or len(pairs)!=8 or sorted(result_blocks)!=list(range(4)):raise ValueError('Incomplete capture/result corpus')
    if len(profiles)!=24:raise ValueError('All eight slots and all three stage pages required')
    residuals=[];valid=[]
    for index,(tag,params,gray,board) in enumerate(pairs):
        expected=dict(exposure_lines=report['low'] if index%2==0 else report['high'],gain16=16,brightness=128,light_mask=1<<(index//2),settle_frames=1,discard_frames=3)
        if params!=expected or tag['request_id']!=index+1:raise ValueError('Executed exposure/direction/order mismatch')
        residuals.append(integer_h2(gray)['residual_n']);v=assess_quality(gray)['valid_mask']
        if not v.all():raise ValueError('Simulation quality upload not equal to frozen exact PC map')
        valid.append(v)
    expected=fusion.fuse_two_stage(np.stack(residuals),np.stack(valid),board=pairs[0][3])['final']
    result_raw=b''.join(result_blocks[i] for i in range(4));words=np.frombuffer(result_raw,dtype='<u4').reshape(32,32)
    result,selected_gray=decode_words(words,pairs[0][3],hysteresis_connect)
    difference={key:int(np.count_nonzero(value!=expected[key])) for key,value in result.items()}
    source=expected['source_frame'];yy,xx=np.indices(source.shape);wanted_gray=np.stack([row[2] for row in pairs])[np.maximum(source.astype(int)-1,0),yy,xx];wanted_gray[source==0]=0
    difference['selected_gray']=int(np.count_nonzero(selected_gray!=wanted_gray))
    if any(difference.values()):raise ValueError(difference)
    (out/'actual_result.r32').write_bytes(result_raw)
    receipt=dict(status='PASS',native_capture_frames=len(verified),eight_frame_new_offload=8,extension_replies=len(extended),extended=extended,
        actual_network_firmware='0x0109',legacy_parser_validation_view='Explicit109-to107 substitution only after original firmware check; not a live SDK/fallback',
        full_pipeline='DVP model -> actual capture/control/identity/H2 -> CDC writer -> modeled DDR -> real merger/table guard -> DMA/CDC/UDP -> strict host decode -> frozen B1 connection',
        candidate_differences=difference,device_profiles=list(profiles.values()),profile_scope='RTL model service cycles, not physical benchmark',result_sha256=hashlib.sha256(result_raw).hexdigest(),committed_images=verified,
        inputs_sha256={name:sha(out/name) for name in ('packets.bin','packets_index.csv','board_trace.jsonl','VERIFICATION.json')},
        physical_hardware=False,bit_generated=False)
    dump(out/'PACKET_AUDIT.json',receipt);print('BOARD_WIRE_AND_FINAL_MASK_PASS 17 captures,8 offload frames,0 differences',flush=True)
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);audit(p.parse_args().out)
