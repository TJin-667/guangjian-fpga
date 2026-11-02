"""Loopback-only108 transaction model. No sensor, AXI, DDR or FPGA claims."""
import copy,struct,zlib
import numpy as np
from sdk_loader import load,ROOT
from engineering_executor import sdk,references

def make_peer():
    module=load('_off109_transport_peer',ROOT/'derived_sdk/software_transport_peer_0109.py')
    Base,engine=module.make_peer()
    fusion,h2,quality,connect,decode=references()
    class Peer(Base):
        def __init__(self,*args,extension_fault='',**kwargs):
            self.extension_fault=extension_fault;self.off_group=0;self.off_digest=bytes(16);self.off_live=False;self.off_slots=0
            self.off_published=False;self.off_cookie=0;self.off_request=0;self.off_slot=0;self.off_regs=[0]*6+[400,800];self.off_pair=(400,800);self.off_q=[];self.off_sealed=False
            self.off_r=[];self.off_v=[];self.off_gray=[];self.off_data=b'';self.off_last=None;self.off_execution={};self.off_sent=[]
            super().__init__(*args,firmware=0x109,**kwargs)
        def response(self,op,seq,status=0,*,args=0,payload=b''):
            flags=int(self.off_live)<<7|int(self.off_live and not self.busy and self.last['valid'] and self.off_request==self.counter)<<6|int(self.off_published)<<1
            body=bytearray(64);body[:4]=bytes((1,op,status,flags));struct.pack_into('>IIQ',body,4,self.off_cookie,self.off_request,self.off_group);body[20:36]=self.off_digest
            struct.pack_into('>4H',body,36,*self.off_roi)
            struct.pack_into('>4I',body,44,args>>32,len(payload),zlib.crc32(payload) if payload else 0,len(self.off_sent)+1)
            body[60:64]=bytes((self.off_slots,self.off_slot,0,9));packet=struct.pack('>4sBBHH',b'LGHT',1,0x88,seq,64+len(payload))+body+payload
            if ((self.extension_fault=='wrong_stream_crc' and op==23) or (self.extension_fault=='wrong_profile_crc' and op==26)) and payload:packet=packet[:-1]+bytes((packet[-1]^1,))
            return packet
        @property
        def off_roi(self):return self.roi if len(self.roi)==4 else (0,0,*self.sensor_size)
        def _handle(self,data,peer):
            if len(data)!=20 or data[5]<16:
                # Actual group lock catches any accidental reupload/rebind
                # in the reused lifecycle. Manual/light and ROI_GET stay usable.
                if self.off_live and len(data)==20 and data[5] in (8,10,11,12,15,6):
                    self._send(self._ack(data[5],int.from_bytes(data[6:8],'big'),3 if data[5]>=8 else 1),peer);return
                return super()._handle(data,peer)
            op=data[5];seq=int.from_bytes(data[6:8],'big');args=int.from_bytes(data[12:],'big');signature=(seq,op,args)
            if self.off_last and signature==self.off_last[0]:self._send(self.off_last[1],peer);return
            self.off_execution[op]=self.off_execution.get(op,0)+1;status=0;payload=b''
            if op==16:
                index=args>>32
                if self.off_live:status=3
                elif index>=8 or (index>=6 and not 1<=args&0xffffffff<=1116):status=2
                else:self.off_regs[index]=args&0xffffffff
            elif op==17:
                if self.off_live or not self.mask_valid:status=3
                elif not 1<=self.off_regs[6]<self.off_regs[7]<=1116:status=2
                else:
                    self.off_group=(self.off_regs[0]<<32)|self.off_regs[1];self.off_digest=struct.pack('>4I',*self.off_regs[2:6]);self.off_live=True;self.off_slots=0;self.off_pair=tuple(self.off_regs[6:8]);self.off_r=[];self.off_v=[];self.off_gray=[];self.off_cookie=0;self.off_slot=0;self.off_request=0
            elif op==18:
                cookie,slot=args>>32,args&0xffffffff
                if not self.off_live or self.busy or self.off_published:status=3
                elif cookie<=self.off_cookie or slot!=self.off_slots+1 or self.exp!=(self.off_pair[0] if slot%2 else self.off_pair[1]) or self.gain!=16 or self.brightness!=128 or self.mask!=1<<((slot-1)//2) or (self.wait,self.discard)!=(1,3):status=2
                else:self.off_cookie=cookie;self.off_slot=slot;self.off_request=self.counter+1;self.off_q=[];self.off_sealed=False
            elif op==19:pass
            elif op==20:
                index=args>>32
                if self.busy or not self.last['valid'] or self.counter!=self.off_request:status=3
                elif index!=len(self.off_q):status=2
                else:self.off_q.append(args&0xffffffff);self.off_sealed=False
            elif op==21:
                _,_,w,h=self.off_roi;tiles=((w+31)//32)*((h+31)//32);crc=zlib.crc32(b''.join(word.to_bytes(4,'little') for word in self.off_q))
                if args>>32!=tiles or args&0xffffffff!=crc or len(self.off_q)!=(tiles+31)//32:status=2
                else:self.off_sealed=True
            elif op==22:
                if not self.off_sealed or args>>32!=self.off_cookie or args&0xffffffff!=self.off_slot:status=2
                else:
                    _,_,w,h=self.off_roi;gray=sdk.wire.planes_from_payload(self.last_raw,w,h,1)[0]
                    valid=np.zeros((h,w),bool);columns=(w+31)//32
                    for y in range(0,h,32):
                        for x in range(0,w,32):
                            i=(y//32)*columns+x//32;valid[y:y+32,x:x+32]=bool(self.off_q[i//32]>>(i%32)&1)
                    self.off_r.append(h2(gray)['residual_n']);self.off_v.append(valid);self.off_gray.append(gray);self.off_slots+=1;self.off_sealed=False
                    if self.off_slots==8:
                        result=fusion.fuse_two_stage(np.stack(self.off_r),np.stack(self.off_v))['final'];source=result['source_frame'];yy,xx=np.indices(source.shape)
                        selected=np.stack(self.off_gray)[np.maximum(source.astype(int)-1,0),yy,xx];selected[source==0]=0
                        words=result['residual_n'].view('<u2').astype('<u4')|(source.astype('<u4')<<16)|(result['weak'].astype('<u4')<<20)|(result['strong'].astype('<u4')<<21)|(selected.astype('<u4')<<22)
                        self.off_data=words.astype('<u4').tobytes();self.off_published=True
            elif op==23:
                at=(args>>32)*1024
                if not self.off_published or args&0xffffffff!=self.off_group&0xffffffff:status=3
                elif at>=len(self.off_data):status=2
                else:payload=self.off_data[at:at+1024]
            elif op==26:
                stage,cookie=args>>32,args&0xffffffff
                if not self.off_live or self.off_slots!=self.off_slot or self.off_slots==0:status=3
                elif stage>2 or cookie!=self.off_cookie:status=2
                else:
                    _,_,w,h=self.off_roi;pixels=w*h;beats=(pixels+3)//4
                    count0=pixels if stage==0 else (beats if stage==1 or self.off_slots==1 else 2*beats)
                    count1=3 if stage==0 else ((beats+15)//16 if stage==1 else beats)
                    hz=125000000 if stage==0 else 100000000
                    if self.extension_fault=='wrong_profile_clock':hz+=1
                    payload=struct.pack('>4s6I',b'GJP9',stage,hz,10000+pixels*4,count0,count1,3)
            elif op==27:
                lo,hi=self.off_pair if self.off_live else self.off_regs[6:8]
                if self.extension_fault=='wrong_config_echo':lo+=1
                payload=struct.pack('>4sHHHBBHBB',b'GJC9',lo,hi,16,128,3,1116,1,9)
            elif op==24:
                if args!=self.off_group or not self.off_published:status=3
                else:self.off_live=False;self.off_published=False
            else:status=2
            packet=self.response(op,seq,status,args=args,payload=payload);self.off_last=(signature,packet);self.off_sent.append(signature)
            # Lose one ACK AFTER executing the mutation. Retry must retain
            # sequence and obtain immutable cached reply without executing it.
            if self.extension_fault=='lose_first_arm_ack' and op==18 and self.off_cookie==1 and self.off_execution[18]==1:return
            self._send(packet,peer)
    return Peer,engine
