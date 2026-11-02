"""Independent strict 0107 UDP SDK. No socket opens on import.

Original 0105 SDK and installed applications remain untouched. A real-board
constructor requires an explicit local candidate-bit/source binding; software
tests use a labelled loopback peer and never supply that binding.
"""
import copy,importlib.util,json,math,os,sys,threading,time,uuid
from collections import Counter,deque
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
import host_transport as wire
from generate_sdk_base import derive

HERE=Path(__file__).resolve().parent
SDK=HERE.parent/'auto_exposure_0105_20261015/dependencies/sdk'
SOURCE_COMMIT=json.loads((HERE/'SOURCE_PIN.json').read_bytes())['candidate_source_commit']

def load_file(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

support=wire.pinned_module('_gray_sdk_support',SDK/'acquisition_support.py',
    'dc47f6c7f9d746d5a4e8fa0aeb2d7a79e9a8b4947e866eca4485e821ea95c11a')
publication=wire.pinned_module('_gray_sdk_publication',HERE.parent/'auto_exposure_0105_20261015/vendor/TJ/work/pc_closed_loop_20261015/publication.py',
    '45964fdb893646ebbb6e045948b95d3bfe947d7c850f148c55b78dce969b978c')
derived,BASE_MANIFEST=derive()
BASE_PATH=HERE/'derived_sdk/acquisition_executor_0107_base.py'
if BASE_PATH.read_bytes()!=derived:raise ValueError('Regenerate/review 0107 lifecycle base')
previous={k:sys.modules.get(k) for k in ('identity_diag','acquisition_support')}
try:
    sys.modules.update(identity_diag=wire.legacy,acquisition_support=support)
    base=load_file('_gray_sdk_lifecycle',BASE_PATH)
finally:
    for name,value in previous.items():
        if value is None:sys.modules.pop(name,None)
        else:sys.modules[name]=value
AcquisitionError=base.AcquisitionError
STABLE_KEYS=('identity','bank','parameters','roi','statistics','features','rgb_crc64','valid','error',
             'mask_valid','parameters_valid','wait_complete_frames','discard_complete_frames','fifo_reads',
             'pixel_format','payload_bytes','payload_crc64')
SOURCE_SNAPSHOT={str(p):support.sha_file(p) for p in [Path(__file__),Path(wire.__file__),BASE_PATH,
    HERE/'SOURCE_PIN.json',HERE/'dual_view.py',Path(wire.codec.__file__),Path(wire.reference.__file__),Path(wire.legacy.__file__),
    SDK/'acquisition_executor.py',SDK/'acquisition_support.py',HERE/'generate_sdk_base.py',Path(publication.__file__)]}

def verify_sources():
    for name,digest in SOURCE_SNAPSHOT.items():
        try:matches=support.sha_file(name)==digest
        except OSError:matches=False
        if not matches:raise AcquisitionError('SOURCE_CHANGED','executable source changed: '+name)

@dataclass(frozen=True)
class CaptureResult:
    raw_payload:bytes
    png_path:Path
    gray_path:Path
    sat_path:Path
    record_path:Path
    metadata:dict
    validated:dict

class Receiver(wire.StrictReceiver):
    def missing(self):return [pid for pid in range(self.count) if pid not in self.parts]

class TransportExecutor(base.AcquisitionExecutor):
    def __init__(self,*,pixel_format=0x31,candidate_binding=None,**kwargs):
        verify_sources()
        if type(pixel_format) is not int or pixel_format not in wire.FORMATS or kwargs.get('mode','strict')!='strict':
            raise ValueError('0107 exact format and strict mode required')
        binding=copy.deepcopy(candidate_binding)
        if kwargs.get('evidence_source','real_board')=='real_board':
            if not isinstance(binding,dict) or binding.get('candidate_source_commit')!=SOURCE_COMMIT:
                raise ValueError('Explicit candidate source/bit binding required before any real socket')
            path=Path(binding.get('bit_path',''))
            if not path.is_file() or support.sha_file(path)!=binding.get('bit_sha256'):
                raise ValueError('Candidate bit file/SHA mismatch')
            binding['bit_path']=str(path.resolve())
        self._format=pixel_format;self._candidate_binding=binding
        self._last_success=None;self._cleanup_active=False;self._trace=None;self._owned_counter=0
        super().__init__(**kwargs)
        self._protocol_path=self.ymw_root/'host/protocol.py'
        entries=json.loads((self.ymw_root/'pinned_manifest.json').read_bytes())['files']
        self._protocol_sha=next(row['sha256'] for row in entries if row['path']=='host/protocol.py')
        try:self._verify_instance_sources()
        except BaseException:
            self.close();raise

    @property
    def pixel_format(self):return self._format

    def acquire(self,**kwargs):
        try:mask=bytes(kwargs.get('board_mask') or b'')
        except (TypeError,ValueError) as exc:raise AcquisitionError('INPUT_INVALID','explicit nonempty binary mask required') from exc
        if not mask or not any(mask) or any(value not in (0,1) for value in mask) or kwargs.get('light_mask')==0:
            raise AcquisitionError('INPUT_INVALID','nonempty binary board and nonzero inspection light required')
        return super().acquire(**kwargs)

    def _verify_instance_sources(self):
        verify_sources()
        try:matches=support.sha_file(self._protocol_path)==self._protocol_sha
        except OSError:matches=False
        if not matches:raise AcquisitionError('SOURCE_CHANGED','loaded wire protocol source changed')
        if self._candidate_binding is not None and self.evidence_source=='real_board':
            try:matches=support.sha_file(self._candidate_binding['bit_path'])==self._candidate_binding['bit_sha256']
            except OSError:matches=False
            if not matches:raise AcquisitionError('SOURCE_CHANGED','candidate bit binding changed')

    def _transaction(self,kind,args=(0,0,0,0),*,extra=None,allow_cancel=False):
        seq=self._next_seq()
        packet=wire.legacy.command(kind,seq,args) if kind>=8 else self.v1.command(kind,seq,args)
        started=time.monotonic_ns();ack=response=None;transmissions=0;finished=False
        mutating=kind in (1,4,6,8,10,11,12,15)
        if mutating:self._pending_mutation=True
        try:
            for attempt in range(self.retries):
                self._check(allow_cancel=allow_cancel);self.sock.sendto(packet,self.endpoint)
                if attempt:self._cost['command_retries']+=1
                transmissions+=1;self._cost['udp_sent_packets']+=1;self._cost['udp_sent_bytes']+=len(packet);self._kinds[str(kind)]+=1
                if kind==2:self._cost['capture_command_transmissions']+=1
                end=min(self._deadline,time.monotonic()+self.command_timeout)
                while True:
                    try:data=self._receive(end,allow_cancel=allow_cancel)
                    except TimeoutError:break
                    if len(data)>=6 and data[5]==0x90:self._image_packet(data);continue
                    if len(data)<10 or data[:4]!=b'LGHT' or int.from_bytes(data[6:8],'big')!=seq:
                        self._cost['stale_control_packets']+=1;continue
                    try:
                        if kind==9 and data[5]==0x85:
                            item=wire.decode_metadata(data,seq)
                            self._metadata_packet=data;self._metadata_seq=seq
                            response=item;finished=True;return item
                        if kind==14 and data[5]==0x86:
                            item=wire.decode_capabilities(data,seq)
                            self._capabilities.append({'seq':seq,'packet_hex':data.hex(),'decoded':item})
                            response=item;finished=True;return item
                        item=self.v1.control(data)
                    except ValueError as exc:raise AcquisitionError('PROTOCOL_INVALID',str(exc)) from exc
                    if item.get('type')==self.v1.ACK and item.get('original')==kind:
                        if item['result'] in ((3,) if kind>=8 else (1,)):
                            self._cost['busy_replies']+=1;break
                        if item['result']:
                            finished=True;raise AcquisitionError('COMMAND_REJECTED',f'command {kind} result {item["result"]}')
                        if ack is not None and ack!=item:raise AcquisitionError('RESPONSE_CONFLICT','inconsistent ACK')
                        ack=item
                    elif extra is not None and item.get('type')==extra:
                        if response is not None and response!=item:raise AcquisitionError('RESPONSE_CONFLICT','inconsistent readback')
                        response=item
                    else:self._cost['stale_control_packets']+=1
                    if ack is not None and (extra is None or response is not None):
                        finished=True;return (ack,response) if extra is not None else ack
                if attempt+1<self.retries:time.sleep(min(.01,max(0,self._deadline-time.monotonic())))
            raise AcquisitionError('COMMAND_TIMEOUT',f'command {kind} missing response',needs_reset=kind in (1,2,4,6,8,10,11,12,15))
        finally:
            if mutating and finished:self._pending_mutation=False
            self._event('command',kind=kind,seq=seq,args=list(args) if kind<8 else f'{args:016x}',
                local_port=self.sock.getsockname()[1],request_sha256=support.sha_bytes(packet),transmissions=transmissions,
                started_monotonic_ns=started,ended_monotonic_ns=time.monotonic_ns(),ack=ack,response=response)

    def _status(self,allow_cancel=False):
        _,status=self._transaction(3,extra=self.v1.STATUS,allow_cancel=allow_cancel)
        if status['firmware']!=0x0107 or status['capabilities']&0x60!=0x60:
            raise AcquisitionError('UNSUPPORTED_FIRMWARE','0107 manual camera/ROI and transport capability required')
        return status

    def _ready(self):
        self._verify_instance_sources()
        self._capabilities=[]
        status=self._status()
        while not status['state']&16 or status['state']&3:
            self._check();time.sleep(.01);status=self._status()
        self._firmware=0x0107
        if not self._connected:
            self.session=self._session_factory()
            if type(self.session) is not int or not 0<self.session<2**64 or self.session in self._used_nonces:
                raise AcquisitionError('SESSION_INVALID','fresh nonzero nonce required')
            self._used_nonces.add(self.session);self._transaction(8,self.session)
            bound=self._transaction(9,0)
            # Actual RTL retains the previous invalid snapshot after BIND.
            # ACK + counter reset are observed here; the new nonce is verified
            # against the accepted CAP identity, never invented as an echo.
            if bound['request_counter'] or bound['valid']:
                raise AcquisitionError('SESSION_INVALID','new session did not invalidate/reset counter',needs_reset=True)
            capability=self._transaction(14,0)
            if capability['format']!=1:raise AcquisitionError('FORMAT_RESET_INVALID','fresh session did not restore RGB',needs_reset=True)
            if self.pixel_format!=1:self._transaction(15,self.pixel_format)
            self._last_success=None;self._owned_counter=0
            self._event('session_bind_acknowledged',session=self.session,local_port=self.sock.getsockname()[1],nonce_echo_verified=False)
        verified=self._transaction(14,0)
        if verified['format']!=self.pixel_format:raise AcquisitionError('FORMAT_MISMATCH','selected format differs',needs_reset=True)
        self._connected=True;self._call.update(firmware=0x0107,session=self.session)

    def _metadata_context(self,meta):
        super()._metadata_context(meta)
        if meta['pixel_format']!=self.pixel_format:
            raise AcquisitionError('FORMAT_MISMATCH','capture format changed',needs_reset=True)

    def _image_packet(self,data):
        if self._cleanup_active:self._cost['stale_image_packets']+=1;return
        if not 20<=len(data)<=1400 or data[:6]!=b'LGHT\x01\x90':
            raise AcquisitionError('IMAGE_INVALID','invalid provisional image envelope/size')
        if self._receiver is None:
            limit=2*math.ceil(self.sensor_size[0]*self.sensor_size[1]*3.125/1380)+64
            if len(self._buffer)>=limit:raise AcquisitionError('BUFFER_BOUND','pre-context image bound',needs_reset=True)
            self._buffer.append(data);return
        try:
            if len(data)<20:raise ValueError('short image header')
            fields=wire.codec.HEADER.unpack(data[:20])
            if fields[3]!=self._frame_id:self._cost['stale_image_packets']+=1;return
            self._receiver.add_packet(data,now=time.monotonic());self._cost['image_packets_seen']+=1
            if len(self._receiver.parts)==self._receiver.count:
                self._image_raw=b''.join(self._receiver.parts[k] for k in range(self._receiver.count))
        except (ValueError,TimeoutError) as exc:raise AcquisitionError('IMAGE_INVALID',str(exc)) from exc

    def _capture(self,*,strict=True):
        if not strict:raise AcquisitionError('MODE_MISMATCH','No compatibility path')
        self._receiver=None;self._buffer.clear();self._image_raw=None
        self._capture_context=self._publication=None
        capability=self._transaction(14,0)
        if capability['format']!=self.pixel_format:raise AcquisitionError('FORMAT_MISMATCH','format changed after configuration',needs_reset=True)
        baseline=self._transaction(9,0)
        if baseline['request_counter']!=self._owned_counter or (self._owned_counter and baseline['identity']['session']!=self.session):
            raise AcquisitionError('SESSION_INVALID','session/counter changed outside this executor',needs_reset=True)
        if baseline['request_counter']==0xffffffff:raise AcquisitionError('COUNTER_EXHAUSTED','fresh session required',needs_reset=True)
        self._request_id=baseline['request_counter']+1;self._call['expected_request_id']=self._request_id
        self._owned_counter=self._request_id
        self._cap_attempted=True;self._cost['capture_requests']+=1
        self._event('capture_requested',session=self.session,request_id=self._request_id)
        args=(3,self._requested['roi'][2],self._requested['roi'][3],self._roi_generation) if self._crop else (2,0,0,0)
        ack=self._transaction(2,args);self._frame_id=ack['frame_id'];self._call['wire_frame_id']=self._frame_id
        self._event('capture_ack',frame_id=self._frame_id,request_id=self._request_id,busy=ack['busy'])
        self._metadata_context(self._transaction(9,0))
        self._receiver=Receiver(identity=self._capture_context,parameters={k:self._requested[k] for k in wire.PARAM_KEYS},
            roi=self._requested['roi'],board=np.frombuffer(self._mask,np.uint8).reshape(self._requested['roi'][3],self._requested['roi'][2]).astype(bool),
            pixel_format=self.pixel_format,started=self._started,timeout=self._deadline-self._started,
            full_frame_pixels=self.sensor_size[0]*self.sensor_size[1])
        while self._buffer:self._image_packet(self._buffer.popleft())
        while self._image_raw is None:
            try:data=self._receive(min(self._deadline,time.monotonic()+.1))
            except TimeoutError:
                meta=self._transaction(9,0);self._metadata_context(meta)
                if meta['error']:raise AcquisitionError('DEVICE_ERROR',f'device error {meta["error"]}',needs_reset=meta['error']!=3)
                continue
            if len(data)>=6 and data[5]==0x90:self._image_packet(data)
            else:self._cost['stale_control_packets']+=1
        self._cost['complete_images_received']+=1;self._cost['duplicate_image_packets']+=self._receiver.duplicates
        self._event('image_complete',frame_id=self._frame_id,packets=self._receiver.count,bytes=len(self._image_raw),raw_sha256=support.sha_bytes(self._image_raw))
        while True:
            meta=self._transaction(9,0);self._metadata_context(meta)
            if meta['error']:raise AcquisitionError('DEVICE_ERROR',f'device error {meta["error"]}',needs_reset=meta['error']!=3)
            if meta['valid']:break
            self._check();time.sleep(.01)
        final=self._transaction(9,0);self._metadata_context(final)
        if any(final[k]!=meta[k] for k in STABLE_KEYS):raise AcquisitionError('DIAGNOSTIC_CHANGED','committed snapshot changed',needs_reset=True)
        self._event('release_confirmed',identity=final['identity'],bank=final['bank'],observation_source='valid snapshot after release')
        return final

    def _publish_verified(self,meta,after,rectangle):
        self._verify_instance_sources()
        if wire.decode_metadata(self._metadata_packet,self._metadata_seq)!=meta:
            raise AcquisitionError('DIAGNOSTIC_CHANGED','final bytes/object/query differ',needs_reset=True)
        try:
            validated=self._receiver.finalize(self._metadata_packet,expected_query_seq=self._metadata_seq,
                now=time.monotonic(),previous_publication=self._last_success)
        except (ValueError,TimeoutError) as exc:raise AcquisitionError('ASSOCIATION_FAILED',str(exc)) from exc
        if validated['payload']!=self._image_raw:raise AcquisitionError('PAYLOAD_CHANGED','provisional bytes changed')
        self._cap_attempted=False;self._cost['saved_images']=1
        pending=self._directory/'pending';pending.mkdir(exist_ok=False)
        raw_name='image.rgb565' if self.pixel_format==1 else 'image.dual_view' if self.pixel_format==50 else 'image.gray_sat'
        (pending/raw_name).write_bytes(self._image_raw)
        if self.pixel_format==50:
            rgb,_,_=wire.dual_view.decode(self._image_raw,*rectangle[2:],codec=wire.codec)
            (pending/'same_frame.rgb565').write_bytes(rgb)
        gray=validated['gray'];sat=validated['sat']
        (pending/'image.gray8').write_bytes(gray.tobytes())
        (pending/'image.sat1').write_bytes(np.packbits(sat.reshape(-1),bitorder='big').tobytes())
        for name,plane in [('image.gray.png',gray),('image.sat.png',sat.astype(np.uint8)*255)]:
            ok,encoded=cv2.imencode('.png',plane)
            if not ok:raise OSError('PNG encoding failed')
            (pending/name).write_bytes(encoded.tobytes())
        png_name='image.gray.png'
        if self.pixel_format==1:
            png_name='image.png';self.v1.save_png(pending/png_name,self._image_raw,rectangle[2],rectangle[3])
        (pending/'metadata_packet.bin').write_bytes(self._metadata_packet)
        (pending/'board_mask.bin').write_bytes(self._mask)
        support.write_json(pending/'transport_capabilities.json',self._capabilities)
        self._call.update(status='COMMITTED',strict_verified=True,identity=meta['identity'],bank=meta['bank'],
            actual_parameters=meta['parameters'],camera_readback=after,roi=rectangle,roi_generation=self._roi_generation,
            frame_id=self._frame_id,statistics=meta['statistics'],features=meta['features'],diagnostic=meta,
            pixel_format=self.pixel_format,payload_bytes=len(self._image_raw),payload_crc64=meta['payload_crc64'],
            rgb_crc64=meta['rgb_crc64'],raw_payload_sha256=support.sha_bytes(self._image_raw),raw_payload_file=raw_name,
            metadata_query_seq=self._metadata_seq,metadata_packet_sha256=support.sha_bytes(self._metadata_packet),
            png_file=png_name,png_sha256=support.sha_file(pending/png_name),
            gray_sha256=support.sha_file(pending/'image.gray8'),sat1_sha256=support.sha_file(pending/'image.sat1'),
            sat1_layout='whole-plane row-major packed bits, bit7 first, zero low tail padding; wire grouping unchanged',
            complete_packets=self._receiver.count,expected_packets=math.ceil(len(self._image_raw)/1380),
            device_reported_settle_frames=meta['wait_complete_frames'],device_reported_discard_frames=meta['discard_complete_frames'],
            candidate_binding=self._candidate_binding,downloaded_bit_identity_verified=False,
            candidate_source_commit=SOURCE_COMMIT,SDK_executable_source_sha256=SOURCE_SNAPSHOT,
            loaded_protocol_source_sha256={str(self._protocol_path):self._protocol_sha},
            SDK_source_manifest=BASE_MANIFEST,transport_source_sha256=support.sha_file(Path(__file__)),
            quality_or_confidence='NOT_EVALUATED',hardware_tested=False,needs_reset=False)
        self._event('result_verified',identity=meta['identity'],bank=meta['bank'],status='COMMITTED')
        inventory={p.name:support.sha_file(p) for p in pending.iterdir() if p.is_file()}
        self._call['archived_file_sha256']=inventory;self._call['cost']=self._cost_record()
        support.write_json(pending/'result.json',self._call);self._check()
        destination=self._directory/'committed'
        publication.atomic_publish(pending,destination,check=self._check,event=self._event)
        self._published_path=destination
        self._event('result_published',identity=meta['identity'],bank=meta['bank'],status='COMMITTED')
        support.write_json(self._directory/'outcome.json',self._call)
        self._check();self._verify_instance_sources();self._last_success=dict(meta['identity'])
        return CaptureResult(self._image_raw,destination/png_name,destination/'image.gray8',destination/'image.sat1',
                             destination/'result.json',copy.deepcopy(self._call),validated)

    def lights_off(self,timeout_s=3):
        if not isinstance(timeout_s,(int,float)) or not math.isfinite(timeout_s) or timeout_s<=0:raise ValueError('cleanup deadline')
        if not self._lock.acquire(blocking=False):raise AcquisitionError('BUSY','cannot clean up active executor')
        poisoned=self._poisoned;folder=None
        try:
            self._cleanup_active=True;self._call={'call_id':'cleanup_'+uuid.uuid4().hex}
            folder=self.output_root/self._call['call_id'];folder.mkdir(parents=True,exist_ok=False)
            self._trace=(folder/'frame_trace.jsonl').open('w',encoding='utf-8',newline='\n')
            self._cost=Counter();self._kinds=Counter();self._started=time.monotonic();self._deadline=self._started+timeout_s
            self._cancel=None;self._receiver=None;self._buffer=deque()
            result={'requested':True,'acknowledged':False,'physical_off_verified':False}
            try:
                result['ack']=self._transaction(1,(0,0,0,0),allow_cancel=True);result['acknowledged']=True
            except Exception as exc:
                result.update(error=str(exc),needs_reset=getattr(exc,'needs_reset',False));self._poisoned=True
            result['cost']=self._cost_record();support.write_json(folder/'outcome.json',result);return result
        finally:
            self._poisoned=self._poisoned or poisoned
            if self._trace is not None:self._trace.close()
            self._trace=None;self._call=None;self._cleanup_active=False;self._lock.release()
