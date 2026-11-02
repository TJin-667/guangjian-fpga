# Derived independent host adapter; source SHA256 55d0dda2bccaa6952b3a53512489ab60387e85e63a1d1ba40eb1ebdcd4f6b87c
"""Cancellable child-process pipeline. GUI process never imports detector/SDK together."""
import json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
from contracts import require_backend,result_version_label,PARAMETER_FREEZE_ID
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n','utf-8')

def run(source,kind,output_base,*,cancel=None,notify=lambda text:None,backend='stable0107_pc',validation_mode='reuse',capture_started=None,allow_fixture=False,cache_base=None,reference=False):
    from bootstrap import verify
    verify()
    if validation_mode not in ('audit','reuse'):raise ValueError('Unknown validation mode')
    if kind=='0109':backend='offload0109_archive'
    else:require_backend(backend)
    if kind not in ('capture','b1','0109'):raise ValueError('UNSUPPORTED_INPUT_KIND')
    source=Path(source).resolve();base=Path(output_base).resolve()
    if not source.exists():raise ValueError('INPUT_NOT_FOUND')
    protected=[source if source.is_dir() else source.parent,HERE]
    if any(base.is_relative_to(p) or p.is_relative_to(base) for p in protected):raise ValueError('OUTPUT_OVERLAPS_INPUT_OR_CODE')
    base.mkdir(parents=True,exist_ok=True);out=base/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir()
    status=dict(status='STARTED',source=str(source),kind=kind,backend=backend,new_captures=0,automatic_pass=False,parameter_freeze_id=PARAMETER_FREEZE_ID,validation_mode=validation_mode)
    write(out/'JOB.json',status);token=cancel or threading.Event();process=None
    try:
        if token.is_set():raise InterruptedError('Analysis cancelled before launch')
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
        with (out/'worker.log').open('w',encoding='utf-8') as log:
            worker_started=time.perf_counter()
            command=[str(executable),'-B','-u',str(HERE/('reference_worker.py' if reference else 'speed_worker.py') if kind=='0109' else HERE.parent/'final_board_0109_20261030/runtime/worker.py'),'--source',str(source),'--kind',kind,'--out',str(out),'--validation-mode',validation_mode]
            if kind=='0109' and allow_fixture:command.append('--allow-fixture')
            if kind=='0109' and cache_base:command.extend(['--cache-base',str(cache_base)])
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def pump():
                for line in process.stdout:log.write(line);log.flush();notify(line.rstrip())
            reader=threading.Thread(target=pump,daemon=True);reader.start()
            while process.poll() is None:
                if token.wait(.1):
                    (out/'CANCEL_REQUESTED').write_text('cancel','ascii')
                    try:process.wait(3)
                    except subprocess.TimeoutExpired:
                        if os.name=='nt':
                            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        else:process.terminate()
                        process.wait(5)
                    reader.join(5);raise InterruptedError('Analysis cancelled; acquired data retained')
            reader.join(5)
        if process.returncode:raise RuntimeError('Offline analysis failed; see '+str(out/'worker.log'))
        result=read(out/'RESULT.json')
        if result['status']!='COMPLETE_REQUIRES_HUMAN_REVIEW':raise ValueError('INCOMPLETE_RESULT')
        result_version_label(result)
        if result.get('parameter_freeze_id')!=PARAMETER_FREEZE_ID:raise ValueError('Worker returned historical algorithm')
        if capture_started is not None:
            seconds=time.perf_counter()-capture_started
            if not 0<=seconds<86400:raise ValueError('Invalid capture interval clock')
            write(out/'END_TO_END.json',dict(scope='capture_task_start_to_analysis_archive_before_UI_display',wall_seconds=seconds,
                                           group_id=result['group_id'],includes_ROI_preparation=True,includes_formal_eight=True,
                                           includes_OFF_and_reference_checks=True,includes_positioning=False,includes_human_interaction=False,
                                           includes_UI_display=False,FPGA_pure_compute_seconds=None))
        from performance import render_report
        render_report(out/'PERFORMANCE.json')
        import hashlib
        seal=read(out/'OUTPUT_MANIFEST.json')
        for name in ('PERFORMANCE.html','END_TO_END.json'):
            path=out/name
            if path.is_file():seal['files_sha256'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
        write(out/'OUTPUT_MANIFEST.json',seal)
        status.update(status='COMPLETE',result='RESULT.json',group_id=result['group_id'],worker_process_wall_seconds=time.perf_counter()-worker_started)
    except BaseException as exc:
        if process is not None and process.poll() is None:process.terminate();process.wait(5)
        status.update(status='CANCELLED' if isinstance(exc,InterruptedError) else 'FAILED',error=str(exc))
    write(out/'JOB.json',status);return out,status
