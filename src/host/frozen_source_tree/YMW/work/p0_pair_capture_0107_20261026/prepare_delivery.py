"""Install isolated launchers, perform offline checks, protect old artifacts."""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PACKAGE=Path('C:/BX72_P0_PAIRS/20261026')
WORK=Path('C:/bx72_ymw_0105_20261015')
PYTHON='C:/Users/yue/.codex/.chatgpt-projects/g-p-6aacf33115048191845c3025390bb3cd/output/BX72_FourLight_ROI_20261012/.venv_demo/Scripts/python.exe'

def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main(stage=False):
    tests=read(WORK/'p0_pair_verification02.json')
    need(tests['status']=='PASS' and tests['sources_unchanged'] and tests['tests']==7,'P0 tests incomplete')
    for name,digest in tests['source_sha256'].items():need(sha(HERE/name)==digest,'Tested source changed')
    protected={}
    for name in ('acceptance_0107_20261026','acceptance_0107_resume_20261026','gray_transport_0105_20261025','acceptance_0107_hardware_review_20261026'):
        rows=subprocess.check_output(['git','ls-tree','-r','c2234f3af1ffaccd02475ae1dbb9b8ddc4bdf6a6','--','YMW/work/'+name],cwd=REPO).decode().splitlines()
        need(rows,'Protected tree absent')
        for row in rows:
            meta,path=row.split('\t');need(blob((REPO/path).read_bytes())==meta.split()[2],'Prior delivery changed: '+path)
        protected[name]=len(rows)
    old=read(REPO/'YMW/backups/20261025_before_fixed_pair/BACKUP_MANIFEST.json')
    for row in old['files']:need(sha(Path(old['source_root'])/row['path'])==row['sha256'],'Installed09 changed')
    protected['installed_LAB']=len(old['files'])
    backup=Path('C:/Users/yue/Documents/ChatGPT/fpga创新设计大赛 光鉴项目/output/backups/BX72_0105_LAB_before_fixed_pair_20261025_145409/BX72_0105_LAB_before_fixed_pair_20261025_145409.zip')
    need(sha(backup)=='039293195c2c8dfe57604a0bce9e4fd834240fbd54f387fa62e847a431db1b41','Backup ZIP changed')
    for name,expected in [('MODEL_SPEC.md','d9780a6d09c2609d2040d52b694bbf0cb11a3e66'),('NEXT_BATCH.json','75531e8a455e3bb8d076273735c2a1e17167dfdd')]:
        need(blob((HERE/'xdl_snapshot'/name).read_bytes())==expected,'Remote XDL snapshot mismatch')
    batch=read(HERE/'xdl_snapshot/NEXT_BATCH.json')
    need(batch['limits']['mandatory_groups']==2 and batch['limits']['maximum_groups']==3 and batch['frozen_capture_settings']['low_exposure_lines']==400 and batch['frozen_capture_settings']['high_exposure_lines']==800,'Unexpected P0 request')
    verification=HERE/'verification';verification.mkdir(exist_ok=True)
    shutil.copyfile(WORK/'p0_pair_verification02.json',verification/'P0_SOFTWARE.json')
    shutil.copyfile(WORK/'p0_pair_tests02.txt',verification/'P0_SOFTWARE.txt')
    for name in ('p0_pair_verification01.json','p0_pair_tests01.txt'):
        dest=verification/'history'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(WORK/name,dest)
    # Hidden native-window initialization/cancel smoke check; no sockets/CAP.
    gui_code='''import json,sys,tkinter as tk
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import p0_capture as app
original=tk.Tk
def hidden():
    root=original();root.withdraw();root.after(200,root.destroy);return root
tk.Tk=hidden
source=Path(sys.argv[2])
try:app.select_board(source,"sample005","A_v1")
except ValueError as exc:
    assert "cancelled" in str(exc)
    print(json.dumps(dict(status="PASS",hidden_native_window_created=True,cancel_preserved=True,hardware_contacted=False)))
else:raise AssertionError("Cancel did not stop")
'''
    preview=list((WORK/'p0_pair_tests02/01/run/preview/sdk_calls').glob('*/committed/image.png'))
    need(len(preview)==1,'Software preview unavailable')
    gui=subprocess.run([PYTHON,'-c',gui_code,str(HERE),str(preview[0])],capture_output=True,text=True,encoding='utf-8')
    need(gui.returncode==0,'Hidden GUI check failed: '+gui.stderr);write(verification/'GUI_CANCEL.json',json.loads(gui.stdout))
    launchers=HERE/'local_launchers';launchers.mkdir(exist_ok=True);PACKAGE.mkdir(parents=True,exist_ok=True)
    digest=sha(HERE/'p0_capture.py')
    ps=f'''param([ValidateSet('sample005','sample004')][string]$Specimen='sample005',[switch]$CheckOnly)
$ErrorActionPreference='Stop'
Write-Host ('STARTED: P0 '+$Specimen+' A_v1. Existing0107 RGB; no bit programming or KEY2 reset.')
$env:PYTHONIOENCODING='utf-8'
$python='{PYTHON}'
$entry='{(HERE/'p0_capture.py').as_posix()}'
function Digest([string]$Path) {{
    $algorithm=[System.Security.Cryptography.SHA256]::Create(); $stream=[System.IO.File]::OpenRead($Path)
    try {{ return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }}
    finally {{ $stream.Dispose(); $algorithm.Dispose() }}
}}
if ((Digest $entry) -ne '{digest}') {{ throw 'P0 entry changed. Stop.' }}
if ((Digest '{(HERE.parent/'acceptance_0107_20261026/FINAL_BUILD_BINDING.json').as_posix()}') -ne '3fd82a611d44fc398f1dab6ba682211cce0adb2ff0be04d926b0c6b1671fa911') {{ throw '0107 binding changed. Stop.' }}
if ($CheckOnly) {{ & $python -u $entry --specimen $Specimen --check-only; exit $LASTEXITCODE }}
$resultRoot=Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'GuangjianP0Pairs'
$runName=$Specimen+'_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,6)
$runFolder=Join-Path $resultRoot $runName
New-Item -ItemType Directory -Path $runFolder -ErrorAction Stop | Out-Null
$captureFolder=Join-Path $runFolder 'pair'
$receipt=@{{entry=$entry;entry_sha256='{digest}';specimen=$Specimen;variant='A_v1';status='STARTED';hardware_programmed=$false;started=(Get-Date -Format o)}}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runFolder 'launcher_receipt.json') -Encoding UTF8
Write-Host ('RESULT DIRECTORY: '+$runFolder)
Write-Host 'Keep the board/camera fixed. After one preview, select4 inner board corners and confirm the specimen. Then8 automatic frames.'
$code=2
try {{
    & $python -u $entry --specimen $Specimen --out $captureFolder 2>&1 | Tee-Object -FilePath (Join-Path $runFolder 'console.txt')
    $code=$LASTEXITCODE
}} catch {{
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $runFolder 'console.txt')
    Write-Host $_
}} finally {{
    $receipt['exit_code']=$code;$receipt['status']='FINISHED'
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runFolder 'launcher_receipt.json') -Encoding UTF8
    Write-Host ('RESULT DIRECTORY: '+$runFolder)
}}
exit $code
'''
    (launchers/'RUN_P0_PAIR.ps1').write_text(ps,encoding='utf-8-sig')
    for number in ('005','004'):
        (launchers/f'RUN_P0_{number}.cmd').write_bytes((f'@echo off\r\nsetlocal\r\necho START: P0 sample{number} A_v1\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_P0_PAIR.ps1" -Specimen sample{number}\r\nset "RESULT_CODE=%ERRORLEVEL%"\r\necho Exit code: %RESULT_CODE%\r\npause\r\nexit /b %RESULT_CODE%\r\n').encode())
    shutil.copyfile(HERE/'README.md',launchers/'START_HERE.md')
    for path in launchers.iterdir():
        if path.is_file() and path.name!='CONTENTS.json':shutil.copyfile(path,PACKAGE/path.name)
    contents={p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(launchers.iterdir()) if p.is_file() and p.name!='CONTENTS.json'}
    write(launchers/'CONTENTS.json',contents);shutil.copyfile(launchers/'CONTENTS.json',PACKAGE/'CONTENTS.json')
    check=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PACKAGE/'RUN_P0_PAIR.ps1'),'-CheckOnly'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    need(check.returncode==0 and 'OFFLINE_READY' in check.stdout,'Native launcher failed: '+check.stdout+check.stderr)
    (verification/'LAUNCHER_CHECK.txt').write_text(check.stdout+check.stderr,encoding='utf-8')
    write(HERE/'STATUS.json',dict(status='READY_FOR_YMW_P0',software_tests=7,software_tests_passed=True,
        XDL_reader_blob_match=True,paired_model_gate_implemented_by_XDL=False,new_entry_real_capture_completed=False,
        planned_formal_groups=2,planned_formal_images=16,per_group_positioning_CAP=1,per_group_formal_CAP=8,
        firmware='existing0107',pixel_format=1,source_RGB_retained=True,bit_generated=False,
        old_files_unchanged=protected,release_ready=False,production09_switched=False,assistant_hardware_commands=0))
    write(verification/'FINAL_CHECK.json',dict(status='PASS',source_hashes_match_final_tests=True,GUI_hidden_cancel='PASS',
        native_PowerShell5_CheckOnly='PASS',old_files_unchanged=protected,old_backup_ZIP_unchanged=True,
        installed_package=str(PACKAGE),no_old_launcher_overwritten=True,no_bit_or_network_changes=True,physical_CAP=0))
    if stage:
        for p in HERE.rglob('*.py'):
            if '__pycache__' not in p.parts:ast.parse(p.read_bytes())
        need(not subprocess.check_output(['git','diff','--name-only'],cwd=REPO).strip(),'Unexpected tracked modification')
        files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='PUBLISH_MANIFEST.json')
        rows=[dict(path=p.relative_to(REPO).as_posix(),bytes=p.stat().st_size,sha256=sha(p),git_blob_sha=blob(p.read_bytes())) for p in files]
        manifest=HERE/'PUBLISH_MANIFEST.json';write(manifest,dict(files=rows,count=len(rows),bytes=sum(r['bytes'] for r in rows)));files.append(manifest)
        with tempfile.TemporaryDirectory(prefix='p0_paths_') as temporary:
            spec=Path(temporary)/'paths.nul';spec.write_bytes(b'\0'.join(p.relative_to(REPO).as_posix().encode() for p in files)+b'\0')
            subprocess.run(['git','-c','core.autocrlf=false','add','--sparse','-f','--pathspec-from-file='+str(spec),'--pathspec-file-nul'],cwd=REPO,check=True)
        index=subprocess.check_output(['git','ls-files','--stage','--',HERE.relative_to(REPO).as_posix()],cwd=REPO).decode().splitlines()
        need({r.split('\t')[1]:r.split()[1] for r in index}=={p.relative_to(REPO).as_posix():blob(p.read_bytes()) for p in files},'Index byte mismatch')
        changed=subprocess.check_output(['git','diff','--cached','--name-only'],cwd=REPO).decode().splitlines()
        need(set(changed)=={p.relative_to(REPO).as_posix() for p in files},'Unexpected staged path')
        print(json.dumps(dict(status='PUBLISH_INDEX_PASS',files=len(files),bytes=sum(p.stat().st_size for p in files),package=str(PACKAGE))))
    else:print(json.dumps(dict(status='INSTALLED_AND_OFFLINE_CHECKED',package=str(PACKAGE))))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',action='store_true');args=parser.parse_args();main(args.stage)
