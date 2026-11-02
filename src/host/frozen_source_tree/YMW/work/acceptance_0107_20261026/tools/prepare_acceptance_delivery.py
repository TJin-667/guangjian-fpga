"""Assemble reviewed 0107 evidence and a single local operator window."""
import argparse,hashlib,json,shutil,subprocess,sys
from pathlib import Path

REPO=Path('C:/bx72_ymw_0105_20261015/repo')
HERE=REPO/'YMW/work/acceptance_0107_20261026'
ROOT=Path('C:/bx72_ymw_0105_20261015')
PYTHON=Path('C:/Users/yue/.codex/.chatgpt-projects/g-p-6aacf33115048191845c3025390bb3cd/output/BX72_FourLight_ROI_20261012/.venv_demo/Scripts/python.exe')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def dump(p,v):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok:raise ValueError(message)
def copy_selected(source,dest):
    allowed={'.json','.csv','.sv','.svh','.bin','.tcl','.rpt','.tsv','.xdc','.log','.txt','.py'}
    for p in sorted(source.rglob('*')):
        if not p.is_file() or any(x in ('xsim.dir','.Xil','__pycache__','ipcopy','project','ymw','ymw_copy') for x in p.relative_to(source).parts):continue
        if p.suffix not in allowed:continue
        if p.stat().st_size>12_000_000:continue
        q=dest/p.relative_to(source);q.parent.mkdir(parents=True,exist_ok=True)
        if q.exists():need(q.read_bytes()==p.read_bytes(),'Evidence would overwrite different bytes: '+str(q))
        else:q.write_bytes(p.read_bytes())

def assemble(a):
    build=a.build.resolve();finished=a.finished.resolve();software=a.software.resolve()
    b=read(build/'build_verification.json');f=read(finished/'verification.json');s=read(software/'verification.json')
    qualification=ROOT/'acceptance0107_qualification01';native_review=read(qualification/'verification.json')
    need(native_review['review_checks_passed'] and native_review['IO']['external_IO_qualified'] is False,'Native qualification inventory not reviewed')
    unit=read(ROOT/'acceptance0107_checks02/verification.json');board=read(ROOT/'acceptance0107_board02/verification.json')
    need(b['resource_and_timing_gate_passed'] and f['status']=='PASS' and s['status']=='PASS' and s['sources_unchanged'],'Review gates failed')
    need(unit['status']=='PASS' and unit['cases']==61 and board['status']=='PASS' and board['board_cases']==18 and board['layout_cases']==868,'RTL scope differs')
    for name,digest in s['source_sha256'].items():need(sha(name)==digest,'Tested source changed: '+name)
    build_manifest=read(build/'input_manifest.json');build_sources=build_manifest['source_sha256']
    ymw_sources={r['path']:r['sha256'] for r in build_manifest['ymw']['files']}
    for receipt_key in ('source_sha256',):
        for name,digest in unit[receipt_key].items():
            if Path(name).suffix=='.v':
                need(sha(name)==digest and build_sources['rtl/'+Path(name).name]==digest,'Unit-tested RTL differs from build: '+name)
    for name,digest in board['board_source_sha256'].items():
        if Path(name).suffix=='.v':
            folder='integration' if Path(name).name in ('bx72_ddr_identity_top.v','lght_core_camera_identity.v') else 'rtl'
            built_digest=build_sources.get(folder+'/'+Path(name).name,ymw_sources.get('src/'+Path(name).name))
            need(sha(name)==digest and built_digest==digest,'Board-tested RTL differs from build: '+name)
    verification=HERE/'verification'
    software_dir='software_'+software.name
    copy_selected(qualification,verification/'qualification_01')
    for directory,src in [('rtl_unit_01',ROOT/'acceptance0107_checks02'),('rtl_board_01',ROOT/'acceptance0107_board02'),
        (software_dir,software),('implementation_01',build),('checkpoint_01',finished),
        ('history_board_01',ROOT/'acceptance0107_board01')]:
        # Implementation source/IP/DCP stay local; only logs/reports/manifests.
        if directory=='implementation_01':
            for name in ('input_manifest.json','build_verification.json','command.json','console.txt','vivado.log'):
                q=verification/directory/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((src/name).read_bytes())
            copy_selected(src/'build/reports',verification/directory/'reports')
        elif directory==software_dir:
            for name in ('verification.json','unittest.txt','test_inherited_sdk.py'):
                q=verification/directory/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((src/name).read_bytes())
            copy_selected(src/'executed_sources',verification/directory/'executed_sources')
        else:copy_selected(src,verification/directory)
    history=[]
    for index,note in [(1,'41 tests passed before button-reset stage was added.'),
        (2,'43 tests, reset-failure status incorrectly remained RESET_PENDING; source fixed to FAILED.'),
        (3,'46 tests, same reset-status regression; original failed evidence retained.'),
        (4,'46 tests passed with source snapshots, before final source pin and CLI CAP-count correction.'),
        (5,'46 tests passed after source pin; CLI preflight maximum_CAP corrected from9 to10 afterwards.'),
        (6,'46 tests passed with all final engine logic; final CLI prompt changed to a newline before input for Tee-Object visibility.')]:
        root=ROOT/f'a107sw{index:02d}'
        if not root.exists():continue
        target=verification/f'history_sw_{index:02d}';target.mkdir(parents=True,exist_ok=True)
        for name in ('verification.json','unittest.txt','test_inherited_sdk.py'):
            if (root/name).exists():(target/name).write_bytes((root/name).read_bytes())
        history.append(dict(directory=target.relative_to(HERE).as_posix(),note=note,final_current_source_evidence=False))
    dump(verification/'HISTORY.json',dict(software=history,board_01='Fixture expected wrong post-reset rejection code2; real priority is unconfigured-camera code4. No RTL change for that correction.',
        board_02='PASS; DVP test pattern source-frame identity explicitly logged across common reset.',
        vector_prepare_01='Initial test fixture used an invalid one-row dimension for65536 pixels; corrected factorization before simulation.'))
    protected=read(REPO/'YMW/backups/20261025_before_fixed_pair/BACKUP_MANIFEST.json');root=Path(protected['source_root'])
    for row in protected['files']:
        p=root/row['path'];need(p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'Installed file changed: '+row['path'])
    backup=REPO/'YMW/backups/20261025_before_fixed_pair/BX72_0105_LAB_before_fixed_pair_20261025_145409.zip'
    need(sha(backup)=='039293195c2c8dfe57604a0bce9e4fd834240fbd54f387fa62e847a431db1b41','Backup ZIP changed')
    # Bind old0106 package to its original commit, independently of new sources.
    old=REPO/'YMW/work/gray_transport_0105_20261025';old_files=subprocess.check_output(['git','ls-tree','-r','2000d04','--',old.relative_to(REPO).as_posix()],cwd=REPO).decode().splitlines()
    for row in old_files:
        description,name=row.split('\t',1);expected=description.split()[2];data=(REPO/name).read_bytes()
        need(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==expected,'Original0106 package modified: '+name)
    dump(verification/'PROTECTED_FILES.json',dict(status='PASS',installed_files=len(protected['files']),
        original0106_files=len(old_files),original0106_commit='2000d04ecba10e707bf24ef0151a30e383268c23',installed_changed=0,original0106_changed=0,
        backup_zip_sha256=sha(backup),hardware_contacted=False))
    bit=HERE/'artifact'/f['bit_file'];bit.parent.mkdir(exist_ok=True);bit.write_bytes((finished/'emit_reports'/f['bit_file']).read_bytes())
    need(sha(bit)==f['bit_sha256'],'Copied bit mismatch')
    required={p.relative_to(HERE).as_posix():sha(p) for p in HERE.glob('*.py')}
    for folder in ('derived','derived_sdk'):
        required.update({p.relative_to(HERE).as_posix():sha(p) for p in (HERE/folder).iterdir() if p.is_file()})
    required.update({p.relative_to(HERE).as_posix():sha(p) for p in HERE.glob('*.v')})
    for p in [HERE/'SOURCE_PIN.json',verification/'rtl_unit_01/verification.json',verification/'rtl_board_01/verification.json',
              verification/software_dir/'verification.json',verification/'implementation_01/build_verification.json',verification/'checkpoint_01/verification.json']:
        required[p.relative_to(HERE).as_posix()]=sha(p)
    required['verification/qualification_01/verification.json']=sha(verification/'qualification_01/verification.json')
    dump(verification/'CURRENT_EVIDENCE.json',dict(software=software_dir+'/verification.json',rtl_unit='rtl_unit_01/verification.json',
        board='rtl_board_01/verification.json',implementation='implementation_01/build_verification.json',checkpoint='checkpoint_01/verification.json',qualification='qualification_01/verification.json'))
    binding=dict(schema='guangjian-0107-engineering-binding-v1',firmware=263,candidate_source_commit=f['candidate_source_commit'],
        bit_file=bit.relative_to(HERE).as_posix(),bit_sha256=sha(bit),implementation_timing_passed=True,
        BRAM_36K_equivalent=f['resources']['BRAM_36K_equivalent'],rtl_verified=True,software_verified=True,
        required_files_sha256=required,release_ready=False,external_IO_qualified=False)
    dump(HERE/'FINAL_BUILD_BINDING.json',binding)
    package=Path('C:/BX72_0107_ACCEPTANCE/20261026_window01');package.mkdir(parents=True,exist_ok=True)
    localbit=package/bit.name;localbit.write_bytes(bit.read_bytes())
    command='@echo off\r\nsetlocal\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_ACCEPTANCE_0107.ps1"\r\nset "RESULT=%ERRORLEVEL%"\r\necho Exit code: %RESULT%\r\npause\r\nexit /b %RESULT%\r\n'
    (package/'RUN_ACCEPTANCE_0107.cmd').write_bytes(command.encode('ascii'))
    ps="""param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
$python='__PYTHON__'
$entry='__ENTRY__'
$binding='__BINDING__'
$expectedBinding='__BINDING_SHA__'
function FileDigest([string]$Path) {
    $algorithm=[System.Security.Cryptography.SHA256]::Create()
    $stream=[System.IO.File]::OpenRead($Path)
    try { return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
if ((FileDigest $binding) -ne $expectedBinding) { throw 'Acceptance binding changed. Stop.' }
$resultRoot=Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Guangjian0107Acceptance'
if ($CheckOnly) { & $python -u $entry --check-only; exit $LASTEXITCODE }
$runName=(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,6)
$runFolder=Join-Path $resultRoot $runName
New-Item -ItemType Directory -Path $runFolder -ErrorAction Stop | Out-Null
$captureFolder=Join-Path $runFolder 'acceptance'
$receipt=@{entry=$entry;binding_sha256=$expectedBinding;hardware_programmed_by_launcher=$false;started=(Get-Date -Format o)}
try {
    & $python -u $entry --out $captureFolder 2>&1 | Tee-Object -FilePath (Join-Path $runFolder 'console.txt')
    $resultCode=$LASTEXITCODE
} catch {
    $_ | Out-String | Add-Content -LiteralPath (Join-Path $runFolder 'console.txt')
    $resultCode=2
} finally {
    $receipt['exit_code']=$resultCode
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runFolder 'launcher_receipt.json') -Encoding UTF8
    Write-Host ('RESULT DIRECTORY: '+$runFolder)
}
exit $resultCode
"""
    for key,value in {'__PYTHON__':str(PYTHON),'__ENTRY__':str(HERE/'acceptance_operator.py'),
                      '__BINDING__':str(HERE/'FINAL_BUILD_BINDING.json'),'__BINDING_SHA__':sha(HERE/'FINAL_BUILD_BINDING.json')}.items():ps=ps.replace(key,value.replace("'","''"))
    (package/'RUN_ACCEPTANCE_0107.ps1').write_text(ps,encoding='utf-8-sig',newline='\r\n')
    instructions=f'''# 0107一次完整工程验收（保留09）

1. 关闭09、预览和其他采集客户端。通电后在Vivado的Program Device中下载同目录 `{bit.name}`，只写RAM，不写Flash。新版本应为0107。
2. 保持物体、相机和灯位不动即可，不用重做02/03、不用制作新划痕。可以继续用现有开发工件，不用007～010和背面。
3. 临时断开Cisco，双击 `RUN_ACCEPTANCE_0107.cmd`。脚本不改VPN、路由、防火墙，也不依赖在线助手。
4. 自动完成全幅同冻结RGB/灰度/SAT对照一张、CH1～4的400/800行灰度八张、关灯和模型输入导出。全幅mask配置可能等待约一分钟，以实际运行计时为准。请等脚本提示后再操作板卡。
5. 提示出现后按一下板上KEY2复位键，松开并等5秒，在窗口输入 `RESET` 回车。脚本先读复位空状态，再用一张81×21小ROI确认重新配置和采集恢复。
6. 出现RESULT DIRECTORY和退出码后恢复Cisco，回复“0107完整验收完成”。助手直接读取 Documents/Guangjian0107Acceptance 最新目录，不用手工打包。

最多10次工程CAP，所有文件标记非训练/未评价，不表示曝光最优、置信度或发布资格。失败会停止并保留结果；不自行反复重跑。若不方便完成按键步骤，输入STOP保留此前结果。

0107期间不要打开旧09。恢复原采集时，Program Device下载 `C:/BX72_0105_LAB/bx72_0105_lab.bit` 后再开09。原0105/0106bit和备份均未改。

新bit SHA256：`{sha(bit)}`。BRAM：{f['resources']['BRAM_36K_equivalent']}/135；setup/hold：{f['wns_ns']:+.3f}/{f['whs_ns']:+.3f}ns。外部IO预算仍待核，工程验收不等于生产切换。
'''
    (package/'START_HERE.md').write_text(instructions,encoding='utf-8-sig');(HERE/'MINIMUM_BOARD_WINDOW.md').write_text(instructions,encoding='utf-8')
    dump(package/'CONTENTS.json',{p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in package.iterdir() if p.is_file() and p.name!='CONTENTS.json'})
    check=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(package/'RUN_ACCEPTANCE_0107.ps1'),'-CheckOnly'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (verification/'launcher_check.txt').write_text(check.stdout+check.stderr,encoding='utf-8');need(check.returncode==0,'CheckOnly failed')
    dump(verification/'DELIVERY.json',dict(status='PASS',local_package=str(package),local_bit_sha256=sha(localbit),bit=bit.relative_to(HERE).as_posix(),
        binding_sha256=sha(HERE/'FINAL_BUILD_BINDING.json'),launcher_offline_check_passed=True,programming_performed=False,hardware_contacted=False))
    dump(HERE/'STATUS.json',dict(firmware='0x0107 acceptance only',candidate_source_commit=f['candidate_source_commit'],
        bit_generated=True,resources=f['resources'],wns_ns=f['wns_ns'],whs_ns=f['whs_ns'],
        rtl_unit_cases=61,board_model_cases=18,layout_cases=868,software_tests=s['tests'],
        complete_entry_software_verified=True,same_frozen_hardware_verified=False,complete_entry_hardware_verified=False,
        hardware_button_reset_verified=False,hardware_tested=False,external_IO_qualified=False,release_ready=False,
        native_IO_CDC_DRC_inventory_reviewed=True,CDC_entries=native_review['CDC']['entries'],CDC_changed=0,DRC_entries=native_review['DRC']['entries'],
        current09_switched=False,installed_files_unchanged=len(protected['files']),physical_commands_this_turn=0,
        local_package=str(package)))
    overview=f'''# 0107：完整入口与同冻结输入的独立工程验收

已准备工程候选与单窗口入口，**尚未实板验收，现用09未切换，release_ready=false**。此轮不扩大FPGA图像算法；灰度转换器原源码和0106均保留。新版本只为补齐同一次冻结读取的RGB/灰度/SAT证据和完整入口验收。

- [一次最小实板操作单](MINIMUM_BOARD_WINDOW.md)：本机 `{package.as_posix()}`，下载一次0107、运行一个CMD、按提示一次KEY2；最多10次工程CAP，不重做02/03、不计训练组。
- [候选bit](artifact/{bit.name})；SHA256 `{sha(bit)}`；固定RTL `{f['candidate_source_commit']}`，来源清单见[新旧源码差异](derived/SOURCE_MANIFEST.json)、[软件派生](SOFTWARE_DERIVATION.json)和[运行绑定](FINAL_BUILD_BINDING.json)。
- [接口/复位资格边界](QUALIFICATION.md)、[真正缺失的厂家依据](INTERFACE_EVIDENCE_REQUEST.md)、[当前机器状态](STATUS.json)。

## 核验结果

| 项目 | 结果/边界 |
|---|---|
| BRAM | {f['resources']['BRAM_36K_equivalent']}/135 = {f['resources']['BRAM_36K_equivalent']/135*100:.2f}%，小于80%；原0106为81.5 |
| LUT / FF / DSP | {f['resources']['LUT']} / {f['resources']['FF']} / {f['resources']['DSP']} |
| 新精确DCP setup / hold | {f['wns_ns']:+.3f} / {f['whs_ns']:+.3f}ns，内部约束通过；不代表外部IO预算已闭合 |
| RTL | 61项编码/分包/背压/复位，868项布局长度，18项板级模型及9个提交帧逐像素检查 |
| 完整软件入口 | {s['tests']}项通过；实际严格SDK、关灯/ZIP、八图、导出、复位读回与重新配置；全部127.0.0.1，非实板 |
| 新DCP审查 | CDC {native_review['CDC']['entries']}条，规则/源/目的/depth/严重性/exception变化0；完整DRC {native_review['DRC']['entries']}条及106引脚一致；[详细凭证](verification/qualification_01/verification.json)保留外部资格缺口 |
| 实板 | 本轮0命令/0采集/0下载；原0106已通过的小ROI及全幅四帧证据沿用 |
| 原软件/bit | 638个现用文件、原0106整个发布目录及备份ZIP均未改，见[保护核验](verification/PROTECTED_FILES.json) |

最终证据：[RTL](verification/rtl_unit_01/verification.json)、[板级/布局](verification/rtl_board_01/verification.json)、[软件](verification/{software_dir}/verification.json)、[实现](verification/implementation_01/build_verification.json)、[DCP审查/bit](verification/checkpoint_01/verification.json)、[离线入口](verification/DELIVERY.json)。模型、DDR、PHY等模拟边界已分别标明；没有把软件回环称为实物采集。

## 入口与失败行为

`acceptance_operator.py`调用隔离的严格宿主/SDK，原09和0106生产gate没有放开。工程Runtime只接精确bit、源码和通过凭证，标记engineering_acceptance_only。全幅mask为全1诊断域，不冒充板面分割；所有导出training_data=false。

第一步0x32在一次CAP的一次冻结DDR读取中携带原RGB及灰度/SAT，逐像素对照并复算原RGB CRC、实际负载CRC及H1/H2；随后0x31跑四方向固定400/800行八请求、同session/mask复用、关灯和可搬移XDL输入。400/800仅工程配置，不是最优曝光。最后按KEY2；BIND前先用3/14/9读取空状态，新的nonce和mask重新配置后仅一张81×21恢复帧。

CRC失败立即停采；导出失败保留八张及ZIP，不自动重拍；OFF无ACK不导出；未真正复位不发恢复CAP。sw02/03发现复位失败状态仍为RESET_PENDING，已修正为FAILED，最终轮复核通过。[原失败/修正记录](verification/HISTORY.json)保留。当前实板、光学质量、置信度、外部IO及生产发布标志均未提前置true。

完整第三方硬件PDF、实现IP缓存/DCP、大型可再生向量和软件回环原图不重复上传。复现工具在本目录与tools；原0106/原实拍数据继续原位保留。XDL负责后续融合训练/置信度和正式采集单，YMW采集、TJ协助标注；007～010及背面仍保留。
'''
    (HERE/'README.md').write_text(overview,encoding='utf-8')
    print(json.dumps(dict(status='DELIVERY_PREPARED',local_package=str(package),bit_sha256=sha(bit)),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--finished',type=Path,required=True);p.add_argument('--software',type=Path,required=True)
    assemble(p.parse_args())
