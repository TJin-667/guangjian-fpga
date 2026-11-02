import ast,hashlib,json,shutil,subprocess,sys
from pathlib import Path

REPO=Path('C:/bx72_ymw_0105_20261015/repo')
HERE=REPO/'YMW/work/acceptance_0107_resume_20261026'
BASE=HERE.parent/'acceptance_0107_20261026'
ROOT=Path('C:/bx72_ymw_0105_20261015')
PACKAGE=Path('C:/BX72_0107_ACCEPTANCE/20261026_window01')
PYTHON='C:/Users/yue/.codex/.chatgpt-projects/g-p-6aacf33115048191845c3025390bb3cd/output/BX72_FourLight_ROI_20261012/.venv_demo/Scripts/python.exe'
sys.path.insert(0,str(HERE))
import resume_acceptance as app
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def need(ok,message):
    if not ok:raise ValueError(message)
def dump(p,v):app.write(p,v)

def main():
    tests=read(ROOT/'r107resume_verification02.json')
    need(tests['status']=='PASS' and tests['sources_unchanged'] and tests['tests']==8,'Resume tests not passed')
    for name,digest in tests['source_sha256'].items():need(sha(HERE/name)==digest,'Tested source changed')
    verification=HERE/'verification';verification.mkdir(exist_ok=True)
    for name in ('r107resume_unittest02.txt','r107resume_verification02.json'):(verification/name).write_bytes((ROOT/name).read_bytes())
    runtime,plan,proof=app.prepare();dump(verification/'real_frozen_review.json',proof)
    source=app.SAVED
    target=verification/'real_frozen_01';target.mkdir(exist_ok=True)
    archive=source.with_name(source.name+'.zip')
    for p in (archive,archive.with_name(archive.name+'.sha256'),archive.with_name(archive.name+'.receipt.json'),source/'operator_summary.json',source/'output_manifest.json'):
        (target/p.name).write_bytes(p.read_bytes())
    batch=source.parent/'workflow/acquisition';rows=[]
    for path in sorted((batch/'sdk_calls').glob('*/committed/result.json')):
        frame=app.bridge.load_commit(path);m=frame.metadata
        rows.append(dict(record=str(path),source_record_sha256=sha(path),identity=m['identity'],parameters=m['parameters'],
            raw_sha256=hashlib.sha256(frame.payload).hexdigest(),raw_bytes=len(frame.payload),H1_H2_and_payload_recomputed=True,
            mask_commands=frame.record['cost']['mask_commands'],packet_anomalies={k:frame.record['cost'][k] for k in ('foreign_packets','command_retries','missing_image_packets','duplicate_image_packets')}))
    rows.sort(key=lambda r:r['identity']['request_id'])
    need(len(rows)==5 and [r['identity']['request_id'] for r in rows]==list(range(1,6)),'Unexpected partial-run content')
    dump(verification/'PARTIAL_RUN_REVIEW.json',dict(status='FIVE_STRICT_COMMITS_VERIFIED',rows=rows,
        complete_eight=False,missing_slots=['CH3_high','CH4_low','CH4_high'],
        later_run_started_a_new_session=True,old_partial_frames_preserved=True,additional_CAP=0,
        recovery_policy='Keep one saved frozen proof; rerun strict eight in one fresh session, do not merge the old five into it.',training_data=False))
    # Preserve the exact original229-file package, including native reports/bit.
    old_manifest=read(BASE/'PUBLISH_MANIFEST.json')
    for row in old_manifest['files']:need(sha(REPO/row['path'])==row['sha256'],'Original0107 source/evidence changed')
    backup=PACKAGE/'launcher_backup_e40c960';backup.mkdir(exist_ok=True)
    for name in ('RUN_ACCEPTANCE_0107.cmd','RUN_ACCEPTANCE_0107.ps1','START_HERE.md','CONTENTS.json'):
        p=PACKAGE/name;q=backup/name
        if not q.exists():q.write_bytes(p.read_bytes())
    binding=BASE/'FINAL_BUILD_BINDING.json';bit=PACKAGE/'bx72_0107_acceptance_EXPERIMENTAL_NOT_RELEASED.bit'
    need(sha(bit)=='4d1545266f83a6eb52327e4863658fa465448c04572b595cbe6dbc482850a01b','Bit changed')
    cmd='@echo off\r\nsetlocal\r\necho START: 0107 resume. Progress will be shown. Do not close this window.\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_ACCEPTANCE_0107.ps1"\r\nset "RESULT=%ERRORLEVEL%"\r\necho Exit code: %RESULT%\r\npause\r\nexit /b %RESULT%\r\n'
    (PACKAGE/'RUN_ACCEPTANCE_0107.cmd').write_bytes(cmd.encode('ascii'))
    ps="""param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
Write-Host 'STARTED: 0107 resume entry. Existing frozen proof is reused. No bit download is needed.'
$python='__PYTHON__'
$entry='__ENTRY__'
$binding='__BINDING__'
function FileDigest([string]$Path) {
    $algorithm=[System.Security.Cryptography.SHA256]::Create(); $stream=[System.IO.File]::OpenRead($Path)
    try { return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
if ((FileDigest $binding) -ne '__BINDING_SHA__') { throw 'Original0107 binding changed. Stop.' }
if ((FileDigest $entry) -ne '__ENTRY_SHA__') { throw 'Resume entry changed. Stop.' }
if ($CheckOnly) { & $python -u $entry --check-only; exit $LASTEXITCODE }
$resultRoot=Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Guangjian0107Resume'
$runName=(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,6)
$runFolder=Join-Path $resultRoot $runName
New-Item -ItemType Directory -Path $runFolder -ErrorAction Stop | Out-Null
$captureFolder=Join-Path $runFolder 'acceptance'
$receipt=@{entry=$entry;entry_sha256='__ENTRY_SHA__';status='STARTED';hardware_programmed_by_launcher=$false;started=(Get-Date -Format o)}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runFolder 'launcher_receipt.json') -Encoding UTF8
Write-Host ('RESULT DIRECTORY: '+$runFolder)
Write-Host 'Please keep this window open. The initial mask upload normally takes about45seconds. Progress appears every5seconds.'
$resultCode=2
try {
    & $python -u $entry --out $captureFolder 2>&1 | Tee-Object -FilePath (Join-Path $runFolder 'console.txt')
    $resultCode=$LASTEXITCODE
} catch {
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $runFolder 'console.txt')
    Write-Host $_
} finally {
    $receipt['exit_code']=$resultCode; $receipt['status']='FINISHED'
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runFolder 'launcher_receipt.json') -Encoding UTF8
    Write-Host ('RESULT DIRECTORY: '+$runFolder)
}
exit $resultCode
"""
    for key,value in {'__PYTHON__':PYTHON,'__ENTRY__':str(HERE/'resume_acceptance.py'),'__ENTRY_SHA__':sha(HERE/'resume_acceptance.py'),
                      '__BINDING__':str(binding),'__BINDING_SHA__':sha(binding)}.items():ps=ps.replace(key,value.replace("'","''"))
    (PACKAGE/'RUN_ACCEPTANCE_0107.ps1').write_text(ps,encoding='utf-8-sig',newline='\r\n')
    text='''# 0107入口已修复：继续验收，不重烧bit

原入口没有过程输出，造成“没有反应”的误解。两次同冻结对照已成功，其中一次灰度序列完成前5张后中断；后一次启动重新绑定了会话。原始文件全部保留。

现在同一个RUN_ACCEPTANCE_0107.cmd已更新：启动立即显示STARTED；每5秒显示阶段、已验证张数和mask配置进度。复用已经独立复核的同冻结对照，不再采这一张。为保留原严格校验，八请求需在一个新会话完整执行，不把旧5张拼入。最多新增8张灰度+1张复位小ROI。

1. 保持现有0107和板卡通电，不用再烧bit，不重做02/03，不刻新划痕；关闭其他采集客户端。
2. 临时断开Cisco，双击本目录RUN_ACCEPTANCE_0107.cmd。看到STARTED后保持窗口开启；首次mask上传约45秒，其后仍有校验/导出/归档，请等提示，不要再次启动。
3. 显示8/8、关灯与导出完成后，按一下KEY2，松开等5秒，在窗口输入RESET回车。
4. 等最终PASS或STOPPED、RESULT DIRECTORY和退出码，恢复Cisco，回复“接续检查完成”。助手直接读取Documents/Guangjian0107Resume最新目录，不用手工打包。

本次入口先发关灯请求，不确认ACK就停止。所有新增帧仍是工程验收，非训练样本。现用09未切换；恢复09前需下载LAB原0105bit。

旧启动器已原字节备份到launcher_backup_e40c960；0107bit SHA256仍为4d1545266f83a6eb52327e4863658fa465448c04572b595cbe6dbc482850a01b。
'''
    (PACKAGE/'START_HERE.md').write_text(text,encoding='utf-8-sig')
    dump(PACKAGE/'CONTENTS.json',{p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in PACKAGE.iterdir() if p.is_file() and p.name!='CONTENTS.json'})
    local=HERE/'local_launchers';local.mkdir(exist_ok=True)
    for name in ('RUN_ACCEPTANCE_0107.cmd','RUN_ACCEPTANCE_0107.ps1','START_HERE.md','CONTENTS.json'):(local/name).write_bytes((PACKAGE/name).read_bytes())
    check=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PACKAGE/'RUN_ACCEPTANCE_0107.ps1'),'-CheckOnly'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (verification/'launcher_check.txt').write_text(check.stdout+check.stderr,encoding='utf-8');need(check.returncode==0,'Offline launcher failed')
    dump(verification/'INSTALL.json',dict(status='PASS',local_package=str(PACKAGE),same_CMD_updated=True,
        visible_start_message=True,progress_seconds=5,source_sha256=sha(HERE/'resume_acceptance.py'),tests=8,
        bit_changed=False,bit_sha256=sha(bit),original_package_source_files_unchanged=len(old_manifest['files']),
        launcher_backup={p.name:sha(p) for p in backup.iterdir() if p.is_file()},hardware_contacted=False))
    dump(HERE/'STATUS.json',dict(entry_fixed=True,progress_visible=True,same_frozen_hardware_verified=True,
        gray_and_SAT_mismatches=0,independent_H1_H2_and_CRC_verified=True,strict_gray_commits_existing=5,
        complete_eight_hardware_verified=False,hardware_reset_verified=False,release_ready=False,production09_switched=False,
        bit_unchanged=True,next_maximum_CAP=9,hardware_commands_by_assistant_this_turn=0))
    (HERE/'README.md').write_text('''# 0107入口进度修复与接续

原启动器在采集、mask配置、归档期间没有过程输出；用户看到空窗口，但程序已实际工作。旧原始结果保留，没有把中断写成板卡故障。

现已更新同一处本机CMD：`C:/BX72_0107_ACCEPTANCE/20261026_window01/RUN_ACCEPTANCE_0107.cmd`。启动即显示STARTED，每5秒显示阶段/已提交灰度帧/最新mask字进度，先确认关灯；复用已通过的同冻结对照。无需重烧bit。操作见[更新清单](local_launchers/START_HERE.md)，旧入口已在本机launcher_backup_e40c960备份。

## 已取得的实板证据

- [同冻结独立复核](verification/real_frozen_review.json)：1920×1080共2073600像素，RGB/gray/SAT来自一次冻结读取；灰度及SAT差异0，独立整数H1/H2、原RGB/实际负载CRC、身份、全DDR读数、原OFF ACK和ZIP均通过。[原ZIP](verification/real_frozen_01/same_frozen.zip)按字节保存，不重复上传解压图。
- [灰度部分序列复核](verification/PARTIAL_RUN_REVIEW.json)：同一会话的前5张已COMMITTED，逐帧负载、平面和H1/H2重新计算一致，mask命令64801→0→0→0→0，传输异常为0。第6次停在相机配置后、CAP之前。后一次启动已用新nonce，因此不能沿用旧5张冒充同会话八请求。
- 新入口只重启严格八请求序列并完成KEY2恢复，最多新增9次工程CAP，已经通过的同冻结全幅不再采。旧5张保留为部分序列证据，不拼接/伪造session，不修改原八请求校验器，不用于训练。

## 修复与验证

新resume_acceptance.py调用原0107严格SDK/宿主/导出器，原RTL、bit及229份发布源文件/凭证保持原字节。进度线程只读新输出目录，不发板卡命令，不修改旧capture/committed文件。启动和最终结果目录即时可见，运行前先落STARTED回执；KEY2输入说明完整换行显示。

[8项新回环检查](verification/r107resume_verification02.json)全部通过，覆盖完整接续且不重拍旧冻结帧、八帧仍在单session、篡改拒绝、第五CRC失败停采、OFF丢失不采集、未复位不发恢复CAP、导出失败保留八图、进度读半行/无ACK；只允许127.0.0.1，未做新实拍。首轮缺少binding时错误类型处理已修正，原失败日志和源码见verification/history_test01。

[本机入口自检](verification/INSTALL.json)通过；外部IO/完整八请求实板及KEY2恢复仍待完成，release_ready=false、现用09未切换。本轮助手0实体命令/0CAP/0烧写/0网络改动，未联系XDL/TJ。
''',encoding='utf-8')
    print('RESUME_ENTRY_INSTALLED_AND_OFFLINE_CHECKED',flush=True)

if __name__=='__main__':main()
