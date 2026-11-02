"""0106 loopback software device; not an electrical/sensor/FPGA model."""
import copy,heapq,struct
from pathlib import Path
import numpy as np
import host_transport as wire

HERE=Path(__file__).resolve().parent

def make_peer():
    core=wire.pinned_module('_gray_peer_core',HERE.parent/'auto_exposure_0105_20261015/app_core.py',
        '448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
    engine=core.load_engine(include_peer=True)
    old=engine.sdk.acquisition_test_peer

    class TransportPeer(old.UdpPeer):
        def __init__(self,ymw_root,*,fault='',sensor_size=(96,32),firmware=0x0106):
            self.pixel_format=1;self.captured=[];self.valid_query_count=0
            super().__init__(ymw_root,fault=fault,firmware=firmware,sensor_size=sensor_size)

        def _empty_meta(self):
            meta=super()._empty_meta();meta.update(pixel_format=self.pixel_format,payload_bytes=0,payload_crc64=0)
            return meta

        def _camera(self,seq):
            if self.fault=='camera_changed_after' and self.counter:
                original=self.fault;self.fault='readback'
                try:return super()._camera(seq)
                finally:self.fault=original
            return super()._camera(seq)

        def _handle(self,data,peer):
            if len(data)!=20:return super()._handle(data,peer)
            kind,seq=data[5],int.from_bytes(data[6:8],'big');args=int.from_bytes(data[12:],'big')
            if kind in (9,14,15):
                self.commands+=1;self.received.append({'kind':kind,'seq':seq,'args':args,'request_hex':data.hex()})
            if kind==14:
                payload=struct.pack('!BHBBBHHHQH',1,self.firmware,self.pixel_format,3,0,1380,1920,1080,0x42f0e1eba9ea3693,1)
                packet=old.envelope(0x86,seq,payload)
                if self.fault=='bad_capability':packet=packet[:-2]+b'\0\0'
                if self.fault=='wrong_capability_seq':packet=packet[:6]+((seq-1)&65535).to_bytes(2,'big')+packet[8:]
                self._send(packet,peer);return
            if kind==15:
                if self.busy:result=3
                elif args not in (1,49) or not self.session:result=2
                else:
                    result=0
                    if self.fault!='ignored_format_set' and self.pixel_format!=args:
                        self.pixel_format=args;self.last['valid']=False
                        self.cache={key:value for key,value in self.cache.items() if key[0]!=2}
                if self.fault!='format_set_ack_lost':self._send(self._ack(kind,seq,result),peer)
                return
            if kind==9:
                meta=copy.deepcopy(self.last);meta['request_counter']=self.counter
                if self.counter:self._mutate_metadata(meta)
                if meta['valid']:
                    self.valid_query_count+=1
                    if self.fault=='descriptor_changed_second' and self.valid_query_count>=2:meta['payload_crc64']^=1
                    if self.fault=='descriptor_changed_third' and self.valid_query_count>=3:meta['payload_crc64']^=1
                    if self.fault=='wrong_payload_crc':meta['payload_crc64']^=1
                    if self.fault=='wrong_H1':meta['statistics']['gray_sum']+=1
                    if self.fault=='wrong_H2':meta['features']['sum9_total']+=1
                    if self.fault=='wrong_format':meta['pixel_format']=1 if self.pixel_format==49 else 49
                    if self.fault=='wrong_session':meta['identity']['session']^=1
                packet=bytearray(old.encode_metadata(seq,meta));packet[10]=2;packet[14:16]=self.firmware.to_bytes(2,'big')
                packet[154:170]=struct.pack('!BBHIQ',meta['pixel_format'],0,0,meta['payload_bytes'],meta['payload_crc64'])
                if self.fault=='wrong_query_seq' and self.counter:packet[6:8]=((seq-1)&65535).to_bytes(2,'big')
                self._send(bytes(packet),peer);return
            before=self.session
            super()._handle(data,peer)
            if kind==8 and self.session!=before:
                self.pixel_format=1
                # Match real RTL: counter resets while previous INVALID
                # snapshot/tag may still be present, not a new nonce echo.
                self.last['valid']=False
            if kind==1 and args==0 and self.fault=='off_ack_lost':
                self.tasks=[task for task in self.tasks if task[2] is None or task[2][5]!=0x81]
                heapq.heapify(self.tasks)

        def _start_capture(self,peer,args):
            x,y,w,h=self.roi if args[0]==3 else [0,0,*self.sensor_size]
            generation=self.roi_generation if args[0]==3 else 0
            tag=dict(session=self.session,request_id=self.counter,config_epoch=self.config_epoch,dvp_sequence=0,publish_sequence=0,
                roi_generation=generation,camera_generation=self.camera_generation,light_generation=self.light_generation,frame_id=self.fid)
            parameters=dict(exposure_lines=self.exp,gain16=self.gain,light_mask=self.mask,brightness=self.brightness,settle_frames=self.wait,discard_frames=self.discard)
            self.last=self._empty_meta();self.last.update(identity=tag.copy(),parameters=parameters,roi=[x,y,w,h],request_counter=self.counter)
            self._meta_valid_queries=0;self.valid_query_count=0
            # Fixed synthetic saved words permit cross-format software parity;
            # actual new DVP frames are not assumed to repeat these pixels.
            values=((np.arange(w*h,dtype=np.uint32)*7919+31)&65535).astype(np.uint16).reshape(h,w)
            rgb=values.astype('>u2').tobytes()
            mask=np.array([(self.mask_words.get(i//32,0)>>(31-i%32))&1 for i in range(w*h)],np.uint8).reshape(h,w)
            arrays=engine.sdk.run_xdl_revision2.synthetic_arrays(values,mask)
            gray,sat=arrays['gray'],arrays['rgb_any_max']
            if self.pixel_format==1:raw=rgb
            else:
                # Independent byte packing, rather than using SDK codec.encode.
                out=bytearray();g=gray.reshape(-1);s=sat.reshape(-1)
                for first in range(0,g.size,8):
                    group=g[first:first+8];out.extend(group.tobytes())
                    out.append(sum(int(s[first+i])<<(7-i) for i in range(len(group))))
                raw=bytes(out)
            self.dvp=(self.dvp+self.wait+self.discard+1)&0xffffffff;self.pub=(self.pub+1)&0xffffffff
            tag.update(dvp_sequence=self.dvp,publish_sequence=self.pub)
            residual=np.abs(arrays['residual_n'].astype(np.int32))
            meta=copy.deepcopy(self.last);meta.update(valid=True,parameters_valid=True,
                mask_valid=self.mask_valid and self.mask_domain==(w,h,generation),identity=tag.copy(),bank=(self.pub-1)&1,
                statistics=dict(zip(wire.legacy.H1_KEYS,engine.sdk.run_xdl_revision2.stats(gray,mask,sat))),
                fifo_reads=self.sensor_size[0]*self.sensor_size[1],wait_complete_frames=self.wait,discard_complete_frames=self.discard,
                features=dict(strong_count=int((residual>1620).sum()),weak_count=int((residual>648).sum()),
                    sum9_total=int(arrays['sum9'].sum(dtype=np.uint64)),residual_n_total=int(arrays['residual_n'].sum(dtype=np.int64))),
                rgb_crc64=wire.legacy.crc64_ecma(rgb),pixel_format=self.pixel_format,payload_bytes=len(raw),payload_crc64=wire.legacy.crc64_ecma(raw))
            self.last.update(identity=tag.copy(),parameters_valid=True,mask_valid=meta['mask_valid'],bank=meta['bank'])
            self.last_raw=rgb;self.captured.append({'identity':tag.copy(),'parameters':parameters.copy(),'pixel_format':self.pixel_format})
            count=(len(raw)+1379)//1380;packets=[]
            for pid in range(count):
                part=raw[pid*1380:(pid+1)*1380]
                packets.append(wire.codec.HEADER.pack(b'LGHT',1,0x90,self.fid,pid,count,len(part),w,h,self.pixel_format,int(pid==0)|(int(pid==count-1)<<1))+part)
            if self.fault in ('old_image','payload_corrupt'):
                damaged=bytearray(packets[0]);damaged[20]^=1;packets[0]=bytes(damaged)
            if self.fault=='missing_packet':packets=packets[:-1]
            if self.fault=='out_of_order':packets.reverse()
            if self.fault=='duplicate':packets=packets[:1]+packets
            if self.fault=='conflict':
                bad=bytearray(packets[0]);bad[-1]^=1;packets=[packets[0],bytes(bad)]+packets[1:]
            if self.fault=='wrong_packet_format':
                bad=bytearray(packets[0]);bad[18]=1 if self.pixel_format==49 else 49;packets[0]=bytes(bad)
            if self.fault=='oversized_provisional_packet':self._send(packets[0][:20]+bytes(2000),peer,0,(self.session,self.counter))
            if self.fault=='reset':self._send(None,peer,.008,callback=self._reset)
            if self.fault=='unknown_retirement':return
            delay=.22 if self.fault in ('cancel','slow_capture') else .025
            token=(self.session,self.counter)
            for index,packet in enumerate(packets):self._send(packet,peer,delay+index*.00002,token)
            def publish():self.last=meta;self.busy=False
            self._send(None,peer,delay+len(packets)*.00002+.001,token,publish)
    return TransportPeer,engine
