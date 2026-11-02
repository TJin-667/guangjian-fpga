"""Strict109 eight-frame capture+offload lifecycle, software qualification first.

This does not enable a bit. sdk_loader keeps the real-board constructor blocked
until a separate checked engineering qualification is supplied.
"""
import hashlib,importlib.util,json,math,os,sys,time
from pathlib import Path
import cv2
import numpy as np
from sdk_loader import load_sdk,ROOT
from offload_wire import ExtensionClient,ProtocolError,quality_words
sdk=load_sdk(qualification=globals().get('QUALIFICATION_PATH'))

def references():
    repo=ROOT.parents[2]
    spec=importlib.util.spec_from_file_location('_off109_app_common',repo/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
    vendor,_=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from ymw_integer_reference import integer_h2
    from light_inspection.real_baseline import assess_quality,hysteresis_connect
    spec=importlib.util.spec_from_file_location('_off109_result',ROOT.parent/'fusion_offload_0108_20261028/host/result_codec.py');codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
    return fusion,integer_h2,assess_quality,hysteresis_connect,codec.decode_words

class EngineeringExecutor(sdk.TransportExecutor):
    def __init__(self,*,group_id,group_digest,group_roi,group_board,result_directory,group_low=400,group_high=800,**kwargs):
        if type(group_low) is not int or type(group_high) is not int or not 1<=group_low<group_high<=1116:raise ValueError('Legal ordered low/high sensor lines required')
        self._off_pair=(group_low,group_high)
        self._off_group_live=False;self._off_slot=0;self._off_cookie=0;self._off_rows=[];self._off_failed=False
        self._off_group=group_id;self._off_digest=group_digest;self._off_roi=tuple(group_roi)
        self._off_board=np.asarray(group_board).copy();self._off_output=Path(result_directory).resolve()
        if self._off_output.exists() or self._off_output.with_name(self._off_output.name+'.pending').exists():raise ValueError('New result directory required; preserve previous pending diagnostics')
        if self._off_board.dtype!=np.bool_ or self._off_board.shape!=(self._off_roi[3],self._off_roi[2]) or not self._off_board.any():raise ValueError('Explicit matching nonempty board mask required')
        if type(group_id) is not int or not 0<group_id<1<<64 or type(group_digest) is not bytes or len(group_digest)!=16 or not any(group_digest):raise ValueError('Group/digest required')
        pixels=self._off_board.size;tile_count=math.ceil(self._off_roi[2]/32)*math.ceil(self._off_roi[3]/32)
        reservation=math.ceil(pixels/32)+8*(600+math.ceil(tile_count/32))+math.ceil(4*pixels/1024)+64
        if reservation>=65536:raise ValueError('Dense mask plus complete eight-frame/result transaction exceeds one strict control-sequence space; use a reviewed native ROI')
        self._off_control_reservation=reservation;self._off_mask=self._off_board.astype(np.uint8).tobytes()
        super().__init__(**kwargs)
        self.extension=ExtensionClient(self._extension_transport,self._next_seq,timeout_s=self.command_timeout,trace=self._extension_trace)

    def _rotate_connection(self):
        if self._off_group_live:raise sdk.AcquisitionError('CONTROL_SPACE_EXHAUSTED','Cannot rotate session/socket inside an active109 group',needs_reset=True)
        return super()._rotate_connection()

    def acquire(self,**kwargs):
        if self._off_failed:raise sdk.AcquisitionError('OFFLOAD_GROUP_FAILED','Failed109 group requires explicit retirement/reset before a fresh executor',needs_reset=True)
        slot=self._off_slot+1
        expected=dict(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=self._off_pair[0] if slot%2 else self._off_pair[1],gain16=16,settle_frames=1,discard_frames=3)
        if slot>8 or any(kwargs.get(key)!=value for key,value in expected.items()) or tuple(kwargs.get('roi',()))!=self._off_roi or bytes(kwargs.get('board_mask') or b'')!=self._off_mask:
            raise sdk.AcquisitionError('GROUP_INPUT_INVALID','Frozen manual low/high,1x,LED128,1/3,CH1..4 order and frozen native ROI/mask required')
        try:return super().acquire(**kwargs)
        except BaseException:
            self._off_failed=True;raise

    def _extension_trace(self,request,reply):
        self._event('0109_extension',kind=request[5],seq=int.from_bytes(request[6:8],'big'),
            request_sha256=hashlib.sha256(request).hexdigest(),reply_sha256=hashlib.sha256(reply).hexdigest(),
            reply_status=reply[12],reply_bytes=len(reply))

    def _extension_transport(self,request,sequence,timeout):
        for attempt in range(self.retries):
            self._check();self.sock.sendto(request,self.endpoint)
            self._cost['udp_sent_packets']+=1;self._cost['udp_sent_bytes']+=len(request);self._kinds[str(request[5])]+=1
            if attempt:self._cost['command_retries']+=1
            until=min(self._deadline,time.monotonic()+timeout)
            while True:
                try:reply=self._receive(until)
                except TimeoutError:break
                if len(reply)>=6 and reply[5]==0x90:self._image_packet(reply);continue
                if len(reply)>=10 and reply[:6]==b'LGHT\x01\x88' and int.from_bytes(reply[6:8],'big')==sequence:return reply
                self._cost['stale_control_packets']+=1
        raise sdk.AcquisitionError('OFFLOAD_COMMAND_TIMEOUT',f'108 op{request[5]} uncertain completion; do not allocate a replacement mutation',needs_reset=True)

    def _capture(self,*,strict=True):
        if not self._off_group_live:
            self.extension.begin(self._off_group,self._off_digest,self._off_roi,low=self._off_pair[0],high=self._off_pair[1]);self._off_group_live=True
        self._off_cookie+=1;self.extension.arm(self._off_cookie,self._off_slot+1)
        meta=super()._capture(strict=strict)
        if (meta['identity']['request_id'],meta['identity']['session'])!=(self.extension.request,self.session):raise ProtocolError('108 ARM/CAP actual identity mismatch')
        return meta

    def _publish_verified(self,meta,after,rectangle):
        capture=super()._publish_verified(meta,after,rectangle)
        fusion,h2,quality,connect,decode=references()
        gray=capture.validated['gray'];valid=quality(gray)['valid_mask'];residual=h2(gray)['residual_n']
        self._verify_instance_sources()
        self.extension.wait_scratch(deadline=self._deadline);self.extension.upload_quality(valid)
        self.extension.fuse(self._off_slot+1,deadline=self._deadline)
        self._off_slot+=1
        profiles=[self.extension.profile(stage) for stage in (0,1,2)]
        self._off_rows.append(dict(capture=capture,gray=gray.copy(),valid=valid.copy(),residual_n=residual.copy(),profiles=profiles))
        ledger=dict(schema='0109-frame-offload-v1',status='FRAME_COMMITTED',slot=self._off_slot,cookie=self._off_cookie,identity=meta['identity'],
            group=self._off_group,digest128=self._off_digest.hex(),actual_parameters=meta['parameters'],device_profiles=profiles,cost_through_offload=self._cost_record(),physical_hardware=self.evidence_source=='real_board')
        sdk.support.write_json(self._directory/'offload.json',ledger)
        if self._off_slot==8:
            raw=self.extension.fetch();words=np.frombuffer(raw,dtype='<u4').reshape(self._off_board.shape)
            result,chosen_gray=decode(words,self._off_board,connect)
            reference=fusion.fuse_two_stage(np.stack([r['residual_n'] for r in self._off_rows]),np.stack([r['valid'] for r in self._off_rows]),board=self._off_board)['final']
            differences={key:int(np.count_nonzero(value!=reference[key])) for key,value in result.items()}
            yy,xx=np.indices(self._off_board.shape);source=reference['source_frame'];expected_gray=np.stack([r['gray'] for r in self._off_rows])[np.maximum(source.astype(int)-1,0),yy,xx];expected_gray[source==0]=0
            differences['selected_gray']=int(np.count_nonzero(chosen_gray!=expected_gray))
            # Retain a diagnostic folder even on mismatch, and do not release
            # the published FPGA bank until the complete group is archived.
            pending=self._off_output.with_name(self._off_output.name+'.pending');pending.mkdir(parents=True,exist_ok=False)
            (pending/'fpga_result.r32').write_bytes(raw)
            sdk.support.write_json(pending/'comparison.json',dict(differences=differences,all_equal=not any(differences.values())))
            if any(differences.values()):raise ProtocolError('FPGA/PC same-input mismatch; diagnostic R32 retained and published bank not released')
            np.savez_compressed(pending/'result.npz',**result,selected_gray=chosen_gray,board=self._off_board)
            for name,image in [('mask.png',result['mask'].astype(np.uint8)*255),('selected_gray.png',chosen_gray)]:
                ok,encoded=cv2.imencode('.png',image)
                if not ok:raise OSError('PNG encoding failed '+name)
                (pending/name).write_bytes(encoded.tobytes())
            records=[dict(slot=i+1,record=str(row['capture'].record_path),record_sha256=sdk.support.sha_file(row['capture'].record_path),identity=row['capture'].metadata['identity']) for i,row in enumerate(self._off_rows)]
            sdk.support.write_json(pending/'RESULT.json',dict(schema='0109-engineering-same-input-result-v1',status='SAME_INPUT_EQUAL',
                group=self._off_group,digest128=self._off_digest.hex(),roi=self._off_roi,frames=records,differences=differences,low_lines=self._off_pair[0],high_lines=self._off_pair[1],device_profiles=[r['profiles'] for r in self._off_rows],
                evidence_source=self.evidence_source,physical_hardware=self.evidence_source=='real_board',
                release_ready=False,source_commit=sdk.SOURCE_COMMIT,result_sha256=hashlib.sha256(raw).hexdigest()))
            from result_view import build
            build(pending,self._off_rows,result,chosen_gray,sdk.wire)
            self._verify_instance_sources()
            os.replace(pending,self._off_output)
            self.extension.release();self._off_group_live=False
        return capture
