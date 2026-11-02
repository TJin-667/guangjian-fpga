"""Back up and atomically switch launchers after offline checks; no board IO."""
import hashlib,json,os,shutil,subprocess,uuid
from pathlib import Path
import console_workflow as workflow
import fast_focus

HERE=Path(__file__).resolve().parent;OLD=HERE.with_name('p0_pair_console_0107_20261027_r55');REPO=HERE.parents[2]
PACKAGE=Path('C:/BX72_P0_PAIRS/20261026');TEST=Path('E:/GuangjianData/software_tests/r56_config_04')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def need(ok,msg):
    if not ok:raise ValueError(msg)
def write(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def atomic_copy(source,target):
    temporary=target.with_name(target.name+'.r56_'+uuid.uuid4().hex+'.tmp')
    shutil.copyfile(source,temporary);os.replace(temporary,target)
def protect():
    proof=read(OLD/'PUBLISH_MANIFEST.json')
    for name,item in proof['files'].items():need(sha(OLD/name)==item['sha256'],'Old r55 changed: '+name)
    original=read(REPO/'YMW/backups/20261025_before_fixed_pair/BACKUP_MANIFEST.json')
    for item in original['files']:need(sha(Path(original['source_root'])/item['path'])==item['sha256'],'Old09 changed')
    zips={}
    for sample,digest in {'sample004':'238473a915b051411f3190198748f8437207c9f6f38fdf3b3cc2f08fbe10016b',
                         'sample005':'7f402e4f2ad1f943a628e79276f1e0f1fdc81525ab9a2270fd7516fb0f68a10f'}.items():
        matches=list(workflow.default_result_root().glob('GUI_'+sample+'_*'))
        need(len(matches)==1,'Expected one existing group: '+sample)
        need(sha(matches[0]/'pair.zip')==digest,'Existing data changed: '+sample);zips[sample]=digest
    return dict(r55_files=len(proof['files'])+1,old09_files=len(original['files']),existing_archives_sha256=zips,
        bit_binding_sha256=sha(REPO/'YMW/work/acceptance_0107_20261026/FINAL_BUILD_BINDING.json'))
def main():
    protected=protect();bundle=workflow.verify_bundle();parent=read(OLD/'BUNDLE.json')
    changed=[name for name in parent['files_sha256'] if (HERE/name).read_bytes()!=(OLD/name).read_bytes()]
    need(set(changed)=={'console_app.py','fast_focus.py','capture_backend.py','console_workflow.py'},'Unexpected runtime changes: '+str(changed))
    added=sorted(set(bundle['files_sha256'])-set(parent['files_sha256']))
    need(added==['capture_settings.py','configured_bridge.py','configured_eight.py'],'Unexpected added runtime files')
    need(fast_focus.TARGET_FPS==2 and fast_focus.DEFAULT_MAX_FRAMES==1000,'Preview defaults changed')
    result=read(TEST/'receipt.json');need(result['status']=='PASS' and result['tests']==27,'Tests not passed')
    need(result['runtime_sha256']==bundle['files_sha256'],'Tested runtime differs from install')
    launch=HERE/'local_launchers';launch.mkdir(exist_ok=True)
    script=(OLD/'local_launchers/RUN_P0_CONSOLE.ps1').read_text(encoding='utf-8')
    script=script.replace(OLD.as_posix(),HERE.as_posix()).replace(sha(OLD/'BUNDLE.json'),sha(HERE/'BUNDLE.json'))
    (launch/'RUN_P0_CONSOLE.ps1').write_bytes(script.replace('\n','\r\n').encode('utf-8'))
    shutil.copyfile(OLD/'local_launchers/RUN_P0_CONSOLE.cmd',launch/'RUN_P0_CONSOLE.cmd')
    for name in ['CONSOLE_START_HERE.md','USER_GUIDE_ZH.md','NEXT_OPERATOR_STEPS_ZH.md']:shutil.copyfile(HERE/'README.md',launch/name)
    write(launch/'CONTENTS_CONSOLE.json',dict(version='r5.6',files_sha256={p.name:sha(p) for p in launch.iterdir() if p.is_file() and p.name!='CONTENTS_CONSOLE.json'}))
    backup=PACKAGE/'backups/before_r56';backup.mkdir(parents=True,exist_ok=True);backup_hashes={}
    for p in (OLD/'local_launchers').iterdir():
        if not p.is_file():continue
        need(sha(PACKAGE/p.name)==sha(p),'Installed launcher changed: '+p.name)
        dest=backup/p.name;need(not dest.exists() or sha(dest)==sha(p),'Conflicting backup')
        if not dest.exists():shutil.copyfile(PACKAGE/p.name,dest)
        backup_hashes[p.name]=sha(dest)
    try:
        for p in sorted(launch.iterdir(),key=lambda p:p.name=='RUN_P0_CONSOLE.ps1'):
            if p.is_file():atomic_copy(p,PACKAGE/p.name)
        run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PACKAGE/'RUN_P0_CONSOLE.ps1'),'-CheckOnly'],capture_output=True,text=True,encoding='utf-8')
        need(run.returncode==0 and 'CONSOLE_OFFLINE_READY' in run.stdout,'Native startup failed: '+run.stdout+run.stderr)
        need(protect()==protected,'Protected files changed')
    except BaseException:
        for p in backup.iterdir():
            if p.is_file():atomic_copy(p,PACKAGE/p.name)
        raise
    evidence=HERE/'verification'
    for name in ['receipt.json','tests.txt']:shutil.copyfile(TEST/name,evidence/name)
    for name in ['interaction_replay.json','viewport_bound.json']:shutil.copyfile(TEST/'ui'/name,evidence/name)
    for i in range(1,4):
        first=TEST.with_name('r56_config_%02d'%i)
        shutil.copyfile(first/'receipt.json',evidence/('HISTORY_%02d.json'%i));shutil.copyfile(first/'tests.txt',evidence/('history_tests_%02d.txt'%i))
    write(evidence/'INSTALLATION.json',dict(status='INSTALLED_OFFLINE_CHECK_PASSED',version='r5.6',protected=protected,
        changed_runtime_files=changed,unchanged_runtime_files=[n for n in parent['files_sha256'] if n not in changed],
        added_runtime_files=added,runtime_sha256=bundle['files_sha256'],
        test_source_sha256={n:sha(HERE/n) for n in ('test_preview_responsiveness.py','test_configurable_capture.py')},tests=result,
        backup=str(backup),backup_files_sha256=backup_hashes,launcher_stdout=run.stdout,launcher_stderr=run.stderr,
        hardware_contacted=False,new_physical_CAP=0,new_bit=False,physical_preview_checked=False))
    write(HERE/'STATUS.json',dict(status='R56_CONFIGURABLE_CAPTURE_AND_RESPONSIVE_PREVIEW_INSTALLED',focus_target_fps=2,focus_max_frames=1000,
        viewport_render=True,render_coalesce_ms=25,same_frame_ROI_rescore=True,tests=27,hardware_contacted=False,
        physical_preview_checked=False,formal_strict_SDK_unchanged=True,per_run_settings=True,old09_preserved=True,release_ready=False))
    files={p.relative_to(HERE).as_posix():dict(sha256=sha(p),git_blob=hashlib.sha1(b'blob '+str(p.stat().st_size).encode()+b'\0'+p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
        for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='PUBLISH_MANIFEST.json'}
    write(HERE/'PUBLISH_MANIFEST.json',dict(files=files,expected_count_including_manifest=len(files)+1))
    print(json.dumps(dict(status='INSTALLED',version='r5.6',tests=27,protected=protected,hardware_contacted=False),ensure_ascii=False))
if __name__=='__main__':main()
