"""Independent0109 strict host derivatives. Original0108 SDK stays immutable."""
import json,hashlib
from derive_candidate import HERE,original,replace
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=HERE/'derived_sdk';out.mkdir(exist_ok=True)
    names=('host_transport_0108.py','acquisition_executor_0108_base.py','sdk_transport_0108.py','software_transport_peer_0108.py','fixed_eight_0108.py')
    for name in names:
        s=original('derived_sdk/'+name).replace('0108','0109').replace('_offload108','_offload109')
        (out/name.replace('0108','0109')).write_text(s,encoding='utf-8')
    (out/'SOURCE_MANIFEST.json').write_text(json.dumps(dict(schema='0109-isolated-sdk-v1',parent='8771bdf8dafdbeb3799a5526d17e92ae93b74226',derived_sha256={p.name:sha(p) for p in out.glob('*.py')},changes='Strict firmware0109 and isolated module names; numerical references and lifecycle rules retained'),indent=2)+'\n',encoding='utf-8')
    host=HERE/'host';host.mkdir(exist_ok=True)
    s=original('host/offload_wire.py').replace('0108','0109')
    s=replace(s,"25:'ABORT',31:'CAPABILITIES'","25:'ABORT',26:'PROFILE',27:'CONFIG',31:'CAPABILITIES'")
    s=replace(s,'==(1,op,8)','==(1,op,9)')
    s=replace(s,"require(op==23 and body[2]==0 and len(payload)<=1024 and len(payload)%4==0,'0109 unexpected/unaligned payload')",'''require(body[2]==0 and ((op==23 and len(payload)<=1024 and len(payload)%4==0) or (op==26 and len(payload)==28) or (op==27 and len(payload)==16)),'0109 unexpected/unaligned payload')''')
    s=replace(s,'def begin(self,group,digest,roi):','def begin(self,group,digest,roi,*,low=400,high=800):')
    s=replace(s,"        registers=[group>>32,group&0xffffffff,*struct.unpack('>4I',digest)]",'''        require(type(low) is int and type(high) is int and 1<=low<high<=1116,'Legal ordered low/high sensor lines required')
        registers=[group>>32,group&0xffffffff,*struct.unpack('>4I',digest),low,high]''')
    s=replace(s,'        return response\n    def arm(self,cookie,slot):', '''        configuration=self.configuration()
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
    def arm(self,cookie,slot):''')
    (host/'offload_wire.py').write_text(s,encoding='utf-8')
    s=original('host/engineering_executor.py').replace('_off108','_off109')
    s=s.replace('Strict108','Strict109').replace('active108','active109').replace('Failed108','Failed109').replace("'0108_extension'","'0109_extension'").replace('Fixed400/800,1x','Frozen manual low/high,1x')
    s=replace(s,'def __init__(self,*,group_id,group_digest,group_roi,group_board,result_directory,**kwargs):','def __init__(self,*,group_id,group_digest,group_roi,group_board,result_directory,group_low=400,group_high=800,**kwargs):')
    s=replace(s,'        self._off_group_live=False;', '''        if type(group_low) is not int or type(group_high) is not int or not 1<=group_low<group_high<=1116:raise ValueError('Legal ordered low/high sensor lines required')
        self._off_pair=(group_low,group_high)
        self._off_group_live=False;''')
    s=replace(s,'+math.ceil(4*pixels/1024)+32','+math.ceil(4*pixels/1024)+64')
    s=replace(s,'exposure_lines=400 if slot%2 else 800','exposure_lines=self._off_pair[0] if slot%2 else self._off_pair[1]')
    s=replace(s,'self.extension.begin(self._off_group,self._off_digest,self._off_roi);','self.extension.begin(self._off_group,self._off_digest,self._off_roi,low=self._off_pair[0],high=self._off_pair[1]);')
    s=replace(s,"        self._off_slot+=1;self._off_rows.append(dict(capture=capture,gray=gray.copy(),valid=valid.copy(),residual_n=residual.copy()))",'''        self._off_slot+=1
        profiles=[self.extension.profile(stage) for stage in (0,1,2)]
        self._off_rows.append(dict(capture=capture,gray=gray.copy(),valid=valid.copy(),residual_n=residual.copy(),profiles=profiles))''')
    s=replace(s,"actual_parameters=meta['parameters'],cost_through_offload=", "actual_parameters=meta['parameters'],device_profiles=profiles,cost_through_offload=")
    s=s.replace("schema='0108-","schema='0109-")
    s=replace(s,"group=self._off_group,digest128=self._off_digest.hex(),roi=self._off_roi,frames=records,differences=differences,","group=self._off_group,digest128=self._off_digest.hex(),roi=self._off_roi,frames=records,differences=differences,low_lines=self._off_pair[0],high_lines=self._off_pair[1],device_profiles=[r['profiles'] for r in self._off_rows],")
    (host/'engineering_executor.py').write_text(s,encoding='utf-8')
    s=original('host/result_view.py').replace('0108','0109').replace('左低400行、右高800行','左为本组实际低曝光、右为实际高曝光（数值见各图标题）')
    (host/'result_view.py').write_text(s,encoding='utf-8')
    s=original('host/software_offload_peer.py').replace('_off108','_off109').replace('software_transport_peer_0108.py','software_transport_peer_0109.py')
    s=s.replace('firmware=0x108','firmware=0x109').replace('self.off_regs=[0]*6','self.off_regs=[0]*6+[400,800];self.off_pair=(400,800)')
    s=replace(s,'bytes((self.off_slots,self.off_slot,0,8))','bytes((self.off_slots,self.off_slot,0,9))')
    s=replace(s,"if self.extension_fault=='wrong_stream_crc' and payload:","if ((self.extension_fault=='wrong_stream_crc' and op==23) or (self.extension_fault=='wrong_profile_crc' and op==26)) and payload:")
    s=replace(s,'if self.off_live or index>=6:status=3\n                else:self.off_regs[index]=args&0xffffffff', '''if self.off_live:status=3
                elif index>=8 or (index>=6 and not 1<=args&0xffffffff<=1116):status=2
                else:self.off_regs[index]=args&0xffffffff''')
    s=replace(s,'if self.off_live or not self.mask_valid:status=3\n                else:', '''if self.off_live or not self.mask_valid:status=3
                elif not 1<=self.off_regs[6]<self.off_regs[7]<=1116:status=2
                else:''')
    s=replace(s,"self.off_digest=struct.pack('>4I',*self.off_regs[2:]);self.off_live=True;self.off_slots=0", "self.off_digest=struct.pack('>4I',*self.off_regs[2:6]);self.off_live=True;self.off_slots=0;self.off_pair=tuple(self.off_regs[6:8]);self.off_r=[];self.off_v=[];self.off_gray=[];self.off_cookie=0;self.off_slot=0;self.off_request=0")
    s=s.replace('self.exp!=(400 if slot%2 else 800)','self.exp!=(self.off_pair[0] if slot%2 else self.off_pair[1])')
    s=replace(s,'            elif op==24:', '''            elif op==26:
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
            elif op==24:''')
    (host/'software_offload_peer.py').write_text(s,encoding='utf-8')
    print('DERIVED0109_HOST',flush=True)
if __name__=='__main__':main()
