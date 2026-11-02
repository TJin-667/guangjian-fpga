"""BX72 operator-owned PC exposure loop; the frozen XDL/TJ algorithms stay intact."""
from __future__ import annotations
import contextlib,datetime,hashlib,io,json,os,re,secrets,socket,sys,threading,time,zipfile
from pathlib import Path
import numpy as np

PACKAGE=Path(__file__).resolve().parent
ADAPTER=PACKAGE/'vendor/TJ/work/pc_closed_loop_20261015'
CONTROLLER=PACKAGE/'vendor/XDL/XDL_Software_Controller'
BIT_SHA='f9aa14f03d15e687a905104f1a9a30b615b456bc6b6488df3e841ed7285a29fe'
BIT_SOURCE='142e549f79fb61a48bf278509b43034c2b161941'
SINGLE_TIMEOUT_S=30.0
_engine_lock=threading.Lock()

def sha(value):return hashlib.sha256(value).hexdigest()
def hash_stream(stream):
    h=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def digest(path):
    with Path(path).open('rb') as stream:return hash_stream(stream)
def parse_json(data):
    def bad(v):raise ValueError('Nonfinite JSON: '+v)
    return json.loads(data,parse_constant=bad)
def read_json(path):
    return parse_json(Path(path).read_bytes())
def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def local_now():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))

def verify_vendor():
    manifest=read_json(PACKAGE/'vendor_sources.json')
    for name,row in manifest['files'].items():
        path=(PACKAGE/name).resolve()
        if not path.is_relative_to(PACKAGE) or digest(path)!=row['sha256']:
            raise ValueError('冻结源码校验失败：'+name)
    return manifest

def load_engine(*,include_peer=False):
    # Imports occur in the sole worker, before any UDP endpoint is opened.
    with _engine_lock:
        verify_vendor()
        if str(ADAPTER) not in sys.path:sys.path.insert(0,str(ADAPTER))
        import dependencies
        return dependencies.load_dependencies(PACKAGE/'dependencies',include_peer=include_peer)

def latest_source(lab_root):
    sources=sorted((p for p in (Path(lab_root)/'results').glob('single_full_*') if p.is_dir()),reverse=True)
    if not sources:raise ValueError('未找到完整图。请先运行02，再用03确认裁剪。')
    return sources[0]  # A failed newest run must never silently reuse an old mask.

def load_source(source):
    import cv2
    source=Path(source).resolve()
    # One immutable snapshot is used for approval, display, upload and output.
    session_bytes=(source/'session.json').read_bytes();geometry_bytes=(source/'plate_candidate.json').read_bytes()
    s=parse_json(session_bytes);g=parse_json(geometry_bytes)
    if s.get('status')!='CAPTURED_OPTICAL_REVIEW_REQUIRED' or g.get('status')!='auto_candidate_review_required':
        raise ValueError('这轮完整图或定位候选不完整，请重新运行02。')
    sample=s.get('operator_confirmed_sample_id')
    if type(sample) is not str or not sample.strip():raise ValueError('完整图缺少样件编号。')
    roi=g.get('roi')
    if type(roi) is not list or len(roi)!=4 or any(type(v) is not int for v in roi):raise ValueError('ROI必须为四个整数。')
    x,y,w,h=roi
    if min(x,y)<0 or min(w,h)<9 or x+w>1920 or y+h>1080:raise ValueError('ROI超出1920×1080画面。')
    png_bytes=(source/'first_full.png').read_bytes();mask_bytes=(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy').read_bytes()
    if sha(png_bytes)!=g.get('source_image_sha256'):raise ValueError('完整图SHA与轮廓不匹配。')
    image=cv2.imdecode(np.frombuffer(png_bytes,np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape!=(1080,1920,3):raise ValueError('完整图尺寸或格式错误。')
    m=np.load(io.BytesIO(mask_bytes),allow_pickle=False)
    if m.dtype!=np.uint8 or m.shape!=(h,w) or not np.all((m==0)|(m==1)) or int(m.sum())<10000:
        raise ValueError('板面mask类型、范围、形状或有效面积错误。')
    expected=dict(exposure_lines=600,gain16=16,light_mask=1,brightness=128,settle_frames=1,discard_frames=3)
    if s.get('actual_parameters')!=expected:raise ValueError('定位完整图不是CH1/LED128/600行/1×。')
    polygon=np.asarray(g.get('polygon'),dtype=np.float32)
    if (g.get('image_size')!=[1920,1080] or polygon.shape!=(4,2) or not np.isfinite(polygon).all()
            or not cv2.isContourConvex(polygon) or (polygon[:,0]<x).any() or (polygon[:,0]>=x+w).any()
            or (polygon[:,1]<y).any() or (polygon[:,1]>=y+h).any()):
        raise ValueError('定位多边形无效，或没有完整包含在ROI内。')
    expected_mask=np.zeros((1080,1920),np.uint8)
    cv2.fillConvexPoly(expected_mask,np.rint(polygon).astype(np.int32),1);expected_mask=expected_mask[y:y+h,x:x+w]
    # The saved corners have 0.001px rounding; allow one raster boundary pixel.
    inner=cv2.erode(expected_mask,np.ones((3,3),np.uint8));outer=cv2.dilate(expected_mask,np.ones((3,3),np.uint8))
    if np.any((inner!=0)&(m==0)) or np.any((m!=0)&(outer==0)):
        raise ValueError('板面mask与定位轮廓不一致，请重新运行02。')
    records=list((source/'calls').glob('*/committed/result.json'))
    if len(records)!=1:raise ValueError('来源缺少唯一的已提交完整帧记录。')
    record=records[0].resolve()
    if not record.is_relative_to(source):raise ValueError('来源记录超出本轮目录。')
    record_bytes=record.read_bytes();r=parse_json(record_bytes);d=r.get('diagnostic',{});camera=r.get('camera_readback',{})
    if not (r.get('status')=='COMMITTED' and r.get('strict_verified') is True and r.get('mode')=='strict'
            and r.get('evidence_source')=='real_board' and r.get('firmware')==0x0105 and d.get('firmware')==0x0105
            and d.get('valid') and d.get('bound') and d.get('parameters_valid') and not d.get('error')):
        raise ValueError('定位来源不是通过严格核验的0x0105实拍完整帧。')
    if not (r.get('sample_id')==sample and r.get('actual_parameters')==expected==d.get('parameters')
            and r.get('roi')==[0,0,1920,1080]==d.get('roi') and r.get('identity')==s.get('identity')==d.get('identity')
            and r.get('call_id')==record.parent.parent.name and r.get('bank')==d.get('bank')
            and camera.get('locked') and not camera.get('error') and camera.get('mode')==3
            and camera.get('exposure_lines')==600 and camera.get('exposure_raw')==9600 and camera.get('gain16')==16
            and camera.get('generation')==r['identity'].get('camera_generation')):
        raise ValueError('来源完整图的样件、参数或帧身份不匹配。')
    if not (sha(png_bytes)==r.get('png_sha256')==digest(record.parent/'image.png')
            and digest(source/'first_full.rgb565')==r.get('raw_rgb565_sha256')==s.get('raw_sha256')==digest(record.parent/'image.rgb565')
            and r.get('crc64')==d.get('rgb_crc64')):
        raise ValueError('来源图片与已提交完整帧的SHA或CRC记录不匹配。')
    m=np.frombuffer(m.tobytes(),np.uint8).reshape(h,w)
    return dict(source=source,session=s,geometry=g,mask=m,sample_id=sample,roi=tuple(roi),
        full_png_sha256=sha(png_bytes),source_session_sha256=sha(session_bytes),
        geometry_sha256=sha(geometry_bytes),mask_npy_sha256=sha(mask_bytes),
        mask_raw_sha256=sha(m.tobytes()),mask_pixels=int(m.sum()),full_png_bytes=png_bytes,
        geometry_bytes=geometry_bytes,session_bytes=session_bytes,mask_npy_bytes=mask_bytes,
        result_relative_path=record.relative_to(source).as_posix(),result_bytes=record_bytes,result_sha256=sha(record_bytes))

def source_preview(snapshot):
    """Render the exact approved geometry over the exact snapshot, not an old overlay."""
    import cv2
    image=cv2.imdecode(np.frombuffer(snapshot['full_png_bytes'],np.uint8),cv2.IMREAD_COLOR)
    x,y,w,h=snapshot['roi'];cv2.rectangle(image,(x,y),(x+w-1,y+h-1),(0,255,0),3)
    cv2.polylines(image,[np.rint(snapshot['geometry']['polygon']).astype(np.int32)],True,(0,255,255),3)
    ok,data=cv2.imencode('.png',image)
    if not ok:raise ValueError('无法生成本轮定位预览。')
    return data.tobytes()

def make_plan(lab_root,source=None):
    return prepare_plan(lab_root,source)[0]

def prepare_plan(lab_root,source=None):
    lab=Path(lab_root).resolve();src=load_source(source or latest_source(lab));engine=load_engine()
    provenance=read_json(lab/'runtime_provenance.json')
    if provenance['source_commit']!=BIT_SOURCE or provenance['bit']['sha256']!=BIT_SHA or digest(lab/'bx72_0105_lab.bit')!=BIT_SHA:
        raise ValueError('本地0x0105候选bit来源不匹配；请核对交付文件。')
    for name in ['acquisition_executor.py','acquisition_support.py','identity_diag.py']:
        if digest(lab/'runtime/software'/name)!=digest(PACKAGE/'dependencies/sdk'/name):
            raise ValueError('现用采集接口与冻结依赖不同：'+name)
    config=read_json(CONTROLLER/'config.json');engine.xdl.acquisition_control.ControllerConfig.from_dict(config)
    # The XDL raw-data report uses its frozen inner-board mask, while old
    # 02-05 device reports retain the original un-eroded capture mask. For
    # this NEW capture transaction upload the XDL mask explicitly; the
    # unchanged adapter/auditor then compare native and common in this domain.
    mask=engine.algorithm['board_mask'](src['mask'].shape,src['geometry']['polygon'],src['roi'][:2])
    if np.any(mask & ~src['mask']) or int(mask.sum())<10000:raise ValueError('板内评价区域无效或超出本轮板面。')
    src['controller_native_mask']=np.frombuffer(mask.tobytes(),np.bool_).reshape(mask.shape)
    plan=dict(schema=3,mode='real_board_operator_preflight',lab_root=str(lab),source=str(src['source']),
        sample_id=src['sample_id'],roi=list(src['roi']),mask_pixels=int(mask.sum()),source_mask_pixels=src['mask_pixels'],
        controller_mask_profile='xdl-board-mask-15x15-erode-saved-border4-v1',
        controller_native_mask_sha256=sha(mask.tobytes()),
        controller_mask_function_source_sha256=digest(PACKAGE/'dependencies/algorithm/ymw_integer_reference.py'),
        capture_statistics_domain='new_uploaded_xdl_inner_board_mask_not_original_02_05_native',
        source_full_png_sha256=src['full_png_sha256'],source_session_sha256=src['source_session_sha256'],
        source_geometry_sha256=src['geometry_sha256'],source_mask_npy_sha256=src['mask_npy_sha256'],
        source_mask_raw_sha256=src['mask_raw_sha256'],source_overlay=str(src['source']/'plate_candidate_overlay.png'),
        source_result_relative_path=src['result_relative_path'],source_result_sha256=src['result_sha256'],
        source_preview_mode='render_from_verified_snapshot_geometry',
        board='192.168.0.2',bind='192.168.0.3',port=5000,firmware_required='0x0105/schema1',
        controller_config=config,config_sha256=digest(CONTROLLER/'config.json'),single_timeout_s=SINGLE_TIMEOUT_S,
        settle_frames=1,discard_frames=3,transaction_frames=5,controller_modeled_transaction_frames=4,
        local_candidate_bit_sha256=BIT_SHA,board_bit_sha_readback_verified=False,
        source_setting_is_not_a_live_observation=True,physical_freshness_verified=False,
        settling_calibrated=False,external_io_qualified=False,controller_rules_modified=False)
    return plan,src

@contextlib.contextmanager
def operator_lock(lab_root):
    """OS-owned lock for this program; crashes release it, files are not deleted."""
    import msvcrt
    path=Path(lab_root)/'.auto_exposure.lock';file=path.open('a+b')
    try:
        file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('已有本程序正在运行，请先停止那个窗口。')
        try:
            if os.fstat(file.fileno()).st_size==0:file.write(b'0');file.flush()
            yield
        finally:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
    finally:file.close()

def request_lights_off(executor):
    result=dict(requested=True,acknowledged=False,physical_off_verified=False)
    try:
        v1=executor.v1;seq=executor._next_seq();packet=v1.command(v1.LED_SET,seq,(0,0,0,0))
        for attempt in range(2):
            executor.sock.sendto(packet,executor.endpoint);deadline=time.monotonic()+1.5
            while time.monotonic()<deadline:
                executor.sock.settimeout(max(.001,deadline-time.monotonic()))
                try:data,peer=executor.sock.recvfrom(65535)
                except socket.timeout:break
                if peer!=executor.endpoint:continue
                try:ack=v1.control(data)
                except ValueError:continue
                if ack.get('type')==v1.ACK and ack.get('seq')==seq and ack.get('original')==v1.LED_SET:
                    result.update(ack=ack,acknowledged=ack['result']==0);return result
    except Exception as exc:result['error']=str(exc)
    return result

def observed_loop_class():
    from closed_loop import ClosedLoop,plain
    class ObservedLoop(ClosedLoop):
        def __init__(self,*,notify,**kw):self.notify=notify;super().__init__(**kw)
        def _transition(self,event=None):
            decision=super()._transition(event)
            self.notify('decision',decision=plain(decision),attempts=len(self.ledger))
            return decision
        def _metrics(self,*args):
            frame,metric=super()._metrics(*args)
            self.notify('image',path=str(args[0].png_path),exposure_lines=frame.exposure_lines,
                statistics=plain(metric.controller_statistics),identity=self.observations[-1]['complete_identity'])
            return frame,metric
    return ObservedLoop

def progress_executor_class(engine,notify):
    class ProgressExecutor(engine.sdk.acquisition_executor.AcquisitionExecutor):
        def _event(self,event,**values):
            super()._event(event,**values)
            if event=='call_started':
                self._progress_words=0;self._progress_total=(len(self._mask)+31)//32
                notify('capture',parameters=values['requested'])
            elif event=='mask_upload_start':notify('progress',text='首次上传板面掩码，请等待约15～30秒。')
            elif event=='mask_reused':notify('progress',text='已复用本轮掩码，正在取得新帧。')
            elif event=='command' and values.get('kind')==10:
                self._progress_words+=1
                if self._progress_words%4096==0 or self._progress_words==self._progress_total:
                    notify('progress',text='掩码上传 %d / %d'%(self._progress_words,self._progress_total))
            elif event=='capture_ack':notify('progress',text='采集已响应，等待完整新图。')
            elif event=='image_complete':notify('progress',text='图像接收完成，正在核验并计算指标。')
    return ProgressExecutor

class ArchiveError(OSError):
    def __init__(self,message,output,summary):
        super().__init__(message);self.output=str(output);self.summary=summary

def finalize_output(out,summary):
    archive_started=time.monotonic_ns();out=Path(out)
    archive=out.parent/(out.name+'.zip');checksum=archive.with_suffix('.zip.sha256');receipt=archive.with_suffix('.zip.receipt.json')
    if any(p.exists() for p in (archive,checksum,receipt)):
        raise ArchiveError('结果归档文件已存在，保留原文件：'+str(archive),out,summary)
    partial=archive.with_name(archive.name+'.'+secrets.token_hex(4)+'.part');owned=False
    try:
        write_json(out/'operator_summary.json',summary)
        inventory={p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file() and p!=out/'output_manifest.json'}
        write_json(out/'output_manifest.json',dict(schema=1,files=inventory,archive_sha256_in_manifest=False))
        with partial.open('xb') as file:
            owned=True
            with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                for p in sorted(out.rglob('*')):
                    if p.is_file():z.write(p,p.relative_to(out))
            file.flush();os.fsync(file.fileno())
        # Verify the actual compressed bytes, not only the input directory.
        with zipfile.ZipFile(partial) as z:
            names=z.namelist()
            if len(names)!=len(set(names)) or set(names)!=set(inventory)|{'output_manifest.json'}:
                raise ValueError('归档文件库存不一致。')
            for name,expected in inventory.items():
                with z.open(name) as stream:
                    if hash_stream(stream)!=expected:raise ValueError('归档字节校验失败：'+name)
            if z.read('output_manifest.json')!=(out/'output_manifest.json').read_bytes():raise ValueError('归档清单不一致。')
        archive_sha=digest(partial)
        # Windows rename refuses an existing target; do not overwrite old data.
        if os.name=='nt':os.rename(partial,archive)
        else:os.link(partial,archive);partial.unlink()
    except BaseException as exc:
        if owned:
            try:partial.unlink(missing_ok=True)
            except OSError:pass
        error=dict(type=type(exc).__name__,message=str(exc),original_files_preserved=True,published_zip=False)
        try:write_json(out/'archive_error.json',error)
        except OSError:pass
        raise ArchiveError('归档失败，原始数据保留在 '+str(out)+'；'+str(exc),out,summary) from exc
    end=time.monotonic_ns();warnings=[]
    archive_record=dict(schema=1,archive_name=archive.name,archive_sha256=archive_sha,archive_bytes=archive.stat().st_size,
        inventory_compression_verification_ms=(end-archive_started)/1e6,
        host_elapsed_ms_through_archive=(end-summary['operator_started_monotonic_ns'])/1e6 if 'operator_started_monotonic_ns' in summary else None,
        scope='Host elapsed through verified ZIP publication; checksum/receipt sidecar writes excluded',physical_freshness_verified=False)
    for path,text in [(checksum,archive_sha+'  '+archive.name+'\n'),(receipt,json.dumps(archive_record,ensure_ascii=False,indent=2)+'\n')]:
        try:
            with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)
        except OSError as exc:warnings.append('ZIP已完整保存，但校验附件写入失败：'+str(path)+'；'+str(exc))
    return dict(summary=summary,output=str(out),archive=str(archive),archive_receipt=str(receipt),archive_warnings=warnings)

def run_real(plan,*,confirmed_same_pose,notify=lambda *a,**k:None,cancel=None):
    """Only call after a human starts capture; tests must use the peer runner."""
    if confirmed_same_pose is not True:raise ValueError('请先确认本轮工件、相机、灯位与轮廓仍一致。')
    started=time.monotonic_ns();fresh,source=prepare_plan(plan['lab_root'],plan['source'])
    if fresh!=plan:raise ValueError('输入在确认后发生变化，请重新载入并确认。')
    cancel=cancel or threading.Event();lab=Path(plan['lab_root']);engine=load_engine()
    stamp=local_now();safe_sample=re.sub(r'[^\w.-]','_',plan['sample_id'])[:80]
    out=lab/'results'/('auto_exposure_'+safe_sample+'_'+stamp.strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(3))
    with operator_lock(lab):
        out.mkdir(parents=True,exist_ok=False);write_json(out/'plan.json',plan)
        (out/'native_mask.bin').write_bytes(source['controller_native_mask'].tobytes())
        (out/'source_geometry.json').write_bytes(source['geometry_bytes'])
        (out/'source_full.png').write_bytes(source['full_png_bytes'])
        (out/'source_session.json').write_bytes(source['session_bytes'])
        (out/'source_mask.npy').write_bytes(source['mask_npy_bytes'])
        (out/'source_result.json').write_bytes(source['result_bytes'])
        config=engine.xdl.acquisition_control.ControllerConfig.from_dict(plan['controller_config'])
        summary=dict(status='STARTED',observed_at=stamp.isoformat(),sample_id=plan['sample_id'],
            evidence_source='real_board',operator_same_pose_confirmed=True,source_full_png_sha256=plan['source_full_png_sha256'],
            board_verified=False,physical_freshness_verified=False,external_io_qualified=False,defect_accuracy_validated=False,
            controller_rules_modified=False,source_is_initialization_only=True,lights_off=dict(requested=False,acknowledged=False),
            controller_mask_profile=plan['controller_mask_profile'],original_source_mask_pixels=plan['source_mask_pixels'],
            uploaded_native_mask_pixels=plan['mask_pixels'],uploaded_native_mask_sha256=plan['controller_native_mask_sha256'],
            single_timeout_s=plan['single_timeout_s'],core_source_sha256=digest(Path(__file__)),
            operator_started_monotonic_ns=started,preflight_and_source_snapshot_host_ms=(time.monotonic_ns()-started)/1e6)
        write_json(out/'operator_summary.json',summary)
        try:
            Executor=progress_executor_class(engine,notify)
            with Executor(board=plan['board'],port=plan['port'],bind=plan['bind'],ymw_root=engine.root/'ymw',
                    output_root=out/'captures',mode='strict',evidence_source='real_board',command_timeout=1.5,retries=3) as executor:
                summary['evidence_source']=executor.evidence_source
                summary['operator_same_pose_confirmed']=executor.evidence_source=='real_board'
                try:
                    loop=observed_loop_class()(notify=notify,dependencies=engine,executor=executor,config=config,
                        output=out/'loop',roi=tuple(plan['roi']),mask_provider=lambda i,e:source['controller_native_mask'],
                        sample_id=plan['sample_id'],pose=Path(plan['source']).name,settle_frames=1,
                        timeout_s=plan['single_timeout_s'],cancel=cancel)
                    result=loop.run();summary.update(status=result['controller_status'],attempts=result['attempts'],
                        accepted_observations=result['accepted_observations'],execution_stop_reason=result['execution_stop_reason'],
                        fatal_error=result['fatal_error'],transport_cost=result['transport_cost'])
                    if result['fatal_error']:summary['status']='PROGRAM_ERROR'
                    if summary['status']=='LOCKED' and loop.observations:
                        summary['locked_exposure_lines']=loop.observations[-1]['actual_parameters']['exposure_lines']
                    if loop.transitions:summary['final_reason_codes']=loop.transitions[-1]['decision']['reason_codes']
                finally:
                    notify('progress',text='正在请求关灯并保存结果。')
                    off_started=time.monotonic_ns()
                    summary['lights_off']=request_lights_off(executor)
                    summary['lights_off_host_ms']=(time.monotonic_ns()-off_started)/1e6
            if (out/'loop/receipt.json').is_file():
                from audit_closed_loop import audit
                audit_started=time.monotonic_ns()
                summary['independent_audit']=audit(out/'loop',engine)
                summary['independent_audit_host_ms']=(time.monotonic_ns()-audit_started)/1e6
                if summary['independent_audit']['status']!='PASS':summary['status']='PROGRAM_ERROR'
        except BaseException as exc:
            summary.update(status='PROGRAM_ERROR',error=dict(type=type(exc).__name__,message=str(exc)))
        if summary['status']!='LOCKED':summary.pop('locked_exposure_lines',None)
        summary.update(cancel_requested=cancel.is_set(),finished_at=local_now().isoformat(),
            host_elapsed_ms_before_archive=(time.monotonic_ns()-started)/1e6)
        result=finalize_output(out,summary);notify('finished',**result);return result

def run_peer(out,*,notify=lambda *a,**k:None,cancel=None,image_plan=None,fault_plan=None):
    """Explicit localhost-only verification; never pretends to capture hardware."""
    engine=load_engine(include_peer=True)
    from software_peer import make_peer_class
    from audit_closed_loop import audit
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    Peer=make_peer_class(engine);Executor=progress_executor_class(engine,notify)
    with Peer(image_plan=image_plan,fault_plan=fault_plan) as peer:
        with Executor(board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',ymw_root=engine.root/'ymw',
                output_root=out/'captures',mode='strict',evidence_source='software_udp_peer',sensor_size=(160,160),command_timeout=.05) as executor:
            try:
                mask=np.ones((128,128),bool)
                loop=observed_loop_class()(notify=notify,dependencies=engine,executor=executor,
                    config=engine.xdl.acquisition_control.ControllerConfig(),output=out/'loop',roi=(11,17,128,128),
                    mask_provider=lambda i,e:mask,sample_id='software_peer_only',pose='synthetic',settle_frames=1,timeout_s=3,cancel=cancel)
                result=loop.run()
            finally:off=request_lights_off(executor)
    checked=audit(out/'loop',engine)
    summary=dict(status=result['controller_status'],evidence_source='software_udp_peer',physical_board_used=False,
        physical_freshness_verified=False,board_verified=False,attempts=result['attempts'],accepted_observations=result['accepted_observations'],
        fatal_error=result['fatal_error'],lights_off=off,independent_audit=checked)
    if summary['status']=='LOCKED' and loop.observations:
        summary['locked_exposure_lines']=loop.observations[-1]['actual_parameters']['exposure_lines']
    return finalize_output(out,summary)
