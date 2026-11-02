"""Worker-side capture, strict offline browsing/re-export, and CPU analysis."""
import contextlib
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import capture_backend as backend
import xdl_crop_adapter
import eight_compare
from capture_settings import CaptureSettings,for_runtime

HERE=Path(__file__).resolve().parent
read,sha,need,write=backend.read,backend.sha,backend.need,backend.write

def default_result_root():
    return Path(os.environ.get('GUANGJIAN_RESULT_ROOT','E:/GuangjianData/P0Pairs'))

def verify_bundle():
    bundle=read(HERE/'BUNDLE.json')
    for name,digest in bundle['files_sha256'].items():
        need(Path(name).name==name and sha(HERE/name)==digest,'Console source changed: '+name)
    need(sha(HERE.parent/'p0_pair_capture_0107_20261026/p0_capture.py')==bundle['parent_P0_sha256'],'Original P0 source changed')
    return bundle

class Runtime(backend.Runtime):
    def __init__(self,specimen,variant,pose,cancel,notify,settings=None):
        super().__init__(specimen,variant,pose,settings=settings)
        self.cancel_event=cancel;self.notify=notify
    def candidate(self):
        bundle=verify_bundle();candidate,files,hashes=super().candidate()
        hashes.update({str(HERE/name):digest for name,digest in bundle['files_sha256'].items()})
        hashes[str(HERE/'BUNDLE.json')]=sha(HERE/'BUNDLE.json')
        files['candidate_evidence/CONSOLE_BINDING.json']=(HERE/'BUNDLE.json').read_bytes()
        return candidate,files,hashes

class LogWriter:
    def __init__(self,path,notify):self.stream=Path(path).open('w',encoding='utf-8');self.notify=notify;self.lock=threading.Lock();self.pending=''
    def write(self,text):
        with self.lock:
            self.stream.write(text);self.stream.flush();self.pending+=text
            while '\n' in self.pending:
                line,self.pending=self.pending.split('\n',1)
                self.notify('log',text=line)
        return len(text)
    def flush(self):self.stream.flush()
    def close(self):self.stream.close()

def run_capture(root,specimen,cancel,selector,notify,automatic_analysis=True,runtime=None,settings=None):
    settings=settings or (for_runtime(runtime) if runtime is not None else CaptureSettings(specimen))
    need(settings.specimen==specimen,'Frozen sample name mismatch')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    pose=specimen+'_'+settings.variant+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    runtime=runtime or Runtime(specimen,settings.variant,pose,cancel,notify,settings=settings)
    need(for_runtime(runtime)==settings,'Runtime settings do not match frozen run')
    write(root/'capture_settings.json',settings.document())
    writer=LogWriter(root/'console.log',notify)
    receipt=dict(status='STARTED',sample=specimen,raw_pair=None,analysis_status='NOT_RUN',release_ready=False,
                 production09_switched=False,source='new_P0_console',created=time.strftime('%Y-%m-%d %H:%M:%S'),
                 capture_settings=settings.document())
    write(root/'console_session.json',receipt)
    try:
        with contextlib.redirect_stdout(writer):result=backend.run(root/'pair',runtime,selector=selector)
        receipt.update(status=result['summary']['status'],raw_pair=str(root/'pair'),raw_archive=result['archive'])
        if result.get('archive'):receipt['raw_archive_sha256']=sha(Path(result['archive']))
        if receipt['status']=='P0_PAIR_READY_FOR_LABEL_REVIEW':
            receipt['eight_compare']=make_eight_compare(root/'pair',notify)
        if receipt['status']=='P0_PAIR_READY_FOR_LABEL_REVIEW' and automatic_analysis:
            receipt['analysis_status']=run_analysis(root/'pair/XDL_manifest.json',root/'analysis',cancel,notify)
        elif cancel.is_set():receipt['analysis_status']='CANCELLED_OR_NOT_REQUESTED'
    except BaseException as exc:receipt.update(status='FAILED',error=dict(type=type(exc).__name__,message=str(exc)))
    finally:
        writer.close();write(root/'console_session.json',receipt)
    return dict(root=str(root),receipt=receipt)

def run_analysis(manifest,out,cancel,notify):
    verify_bundle()
    out=Path(out).resolve();need(not out.exists(),'Use a new analysis directory')
    log=out.with_name(out.name+'_worker.log');out.parent.mkdir(parents=True,exist_ok=True)
    notify('phase',phase='analysis')
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen([sys.executable,'-B',str(HERE/'analysis_worker.py'),'--manifest',str(manifest),'--out',str(out)],
            stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        while process.poll() is None:
            if cancel.wait(.15):
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                notify('log',text='离线对照已停止；原始八帧和ZIP保持完整。')
                return 'CANCELLED_RAW_PRESERVED'
    if process.returncode:
        notify('log',text='离线对照失败，原始八帧保留。详见 '+str(log));return 'FAILED_RAW_PRESERVED'
    notify('analysis',path=str(out));return 'OFFLINE_EVIDENCE_COMPLETE_NOT_DETECTION'

def inside(root,name):return backend.bridge.inside(root,name)

def make_eight_compare(pair,notify=lambda *a,**k:None):
    try:
        verify_bundle()
        notify('phase',phase='compare_eight')
        result=eight_compare.create(pair)
        notify('log',text='八张原片对比已保存：'+result['directory'])
        return result
    except Exception as exc:
        notify('log',text='八张对比副本生成失败，原始八帧和ZIP保留，可离线重试：'+str(exc))
        return dict(status='FAILED_RAW_PRESERVED',error=dict(type=type(exc).__name__,message=str(exc)))

def extract_zip(archive,destination):
    archive=Path(archive).resolve();destination=Path(destination).resolve();need(not destination.exists(),'New extraction directory required')
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        need(names and len(names)==len({n.casefold() for n in names}),'Empty/duplicate ZIP members')
        targets=[inside(destination,n) for n in names]
        need(sum(r.file_size for r in z.infolist())<2*1024**3,'Archive exceeds console extraction budget')
        # Validate all paths before writing even one member.
        destination.mkdir(parents=True)
        for name,target in zip(names,targets):
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    receipt=archive.with_name(archive.name+'.receipt.json')
    if receipt.exists():need(sha(archive)==read(receipt)['archive_sha256'],'Original ZIP receipt mismatch')
    return destination

def verify_inventory(root,cancel=None):
    root=Path(root).resolve();inventory=read(root/'output_manifest.json')['files']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual==set(inventory)|{'output_manifest.json'},'Archive directory inventory differs')
    for name,digest in inventory.items():
        if cancel and cancel.is_set():raise InterruptedError('Offline verification cancelled')
        need(sha(inside(root,name))==digest,'Archive member SHA differs: '+name)
    return len(inventory)

def catalog(path,cancel=None,full_verify=True):
    root=Path(path).resolve()
    if (root/'pair/operator_summary.json').exists():root=root/'pair'
    need((root/'operator_summary.json').is_file(),'Select a new P0 pair ZIP/directory; legacy09 archives remain available in09')
    summary=read(root/'operator_summary.json');count=verify_inventory(root,cancel) if full_verify else None
    need(summary.get('XDL_request_commit')==backend.XDL_COMMIT,'Only the new P0 paired archives are supported; open legacy09 archives in09')
    entries=read(root/'acquisition/observations.json') if (root/'acquisition/observations.json').exists() else []
    frames=[]
    for entry in entries:
        if cancel and cancel.is_set():raise InterruptedError('Offline verification cancelled')
        record=inside(root/'acquisition',entry['record']);r=read(record);m=r['diagnostic']
        if full_verify:
            sensor=summary.get('sensor_size', [1920,1080] if r['evidence_source']=='real_board' else m['roi'][2:])
            frame=backend.bridge.load_commit(record,sensor_size=tuple(sensor))
            need(frame.metadata['identity']==entry['identity'],'Offline frame identity differs')
        need(r['status']=='COMMITTED' and r['strict_verified'],'Not a committed frame')
        frames.append(dict(slot=entry['observation_id'],record=str(record),color=str(record.parent/r['png_file']),
            gray=str(record.parent/'image.gray.png'),sat=str(record.parent/'image.sat.png'),
            mask=str(record.parent/'board_mask.bin'),width=m['roi'][2],height=m['roi'][3],
            exposure=m['parameters']['exposure_lines'],gain16=m['parameters']['gain16'],LED=m['parameters']['brightness'],
            frame_id=m['identity']['frame_id'],session=str(m['identity']['session']),
            board_pixels=m['statistics']['board_count'],board_SAT=m['statistics']['board_rgb_any_max'],roi_xywh=list(m['roi'])))
    ready=False;manifest=root/'XDL_manifest.json'
    if manifest.exists() and len(frames)==8:
        if full_verify:
            runner=xdl_crop_adapter.load();doc=read(manifest)
            for group in doc['groups']:
                for item in group['observations']:
                    for key in ('source_path','gray8_path','sat1_path','valid_mask_path'):inside(root,item[key])
                    runner._load_observation(item,root)
        ready=True
    acquisition=read(root/'acquisition/operator_summary.json') if (root/'acquisition/operator_summary.json').exists() else {}
    return dict(root=str(root),summary=summary,frames=frames,input_ready=ready,comparison_directory=str(eight_compare.default_output(root)),
        raw_eight_recoverable=len(frames)==8 and acquisition.get('status')=='ACQUIRED_EIGHT_REVIEW_REQUIRED',inventory_files=count)

def reexport(catalogue,destination):
    need(catalogue['raw_eight_recoverable'],'A complete strict eight with OFF ACK is required')
    source=Path(catalogue['root']);destination=Path(destination).resolve();need(not destination.exists(),'New recovery output required')
    destination.mkdir(parents=True)
    shutil.copytree(source/'acquisition',destination/'acquisition')
    geometry=source/'crop_geometry.json'
    if not geometry.exists():geometry=source/'acquisition/crop_geometry.json'
    if geometry.exists():shutil.copyfile(geometry,destination/'crop_geometry.json')
    summary=read(source/'acquisition/operator_summary.json');width=catalogue['frames'][0]['width'];height=catalogue['frames'][0]['height']
    runtime=SimpleNamespace(specimen=summary['physical_specimen_id'],variant=summary['specimen_variant'],pose=summary['pose_id'],sensor_size=tuple(summary.get('sensor_size',(width,height))))
    backend.export_xdl(destination,runtime)
    core=backend.original.Runtime().core
    result=core.finalize_output(destination,dict(status='P0_PAIR_READY_FOR_LABEL_REVIEW',XDL_request_commit=backend.XDL_COMMIT,
        physical_specimen_id=runtime.specimen,specimen_variant=runtime.variant,pose_id=runtime.pose,
        evidence_source=summary['evidence_source'],reused_raw_from=str(source),new_physical_CAP=0,
        original_group_id_preserved=True,training_data=False,labels='UNLABELED',release_ready=False,sensor_size=list(runtime.sensor_size),
        warning='Re-export of existing captures, never count this copy as an additional paired group'))
    make_eight_compare(destination)
    return result

def write_readbacks(frames,path):
    new_display_output(path)
    with Path(path).open('w',newline='',encoding='utf-8-sig') as stream:
        fields=['slot','exposure','gain16','LED','frame_id','session','board_pixels','board_SAT']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in frames:writer.writerow({key:row[key] for key in fields})

def new_display_output(path):
    path=Path(path).resolve();need(not path.exists(),'Please use a new output filename')
    for parent in path.parents:
        need(not (parent/'output_manifest.json').exists(),'Save display/CSV outside sealed raw data directories')
    return path
