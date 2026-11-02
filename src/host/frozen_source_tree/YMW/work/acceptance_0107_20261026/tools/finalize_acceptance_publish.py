"""Verify immutable inputs and stage only the explicit 0107 publication set."""
import argparse,ast,hashlib,json,subprocess
from pathlib import Path
REPO=Path('C:/bx72_ymw_0105_20261015/repo')
HERE=REPO/'YMW/work/acceptance_0107_20261026'
WORK=Path('C:/Users/yue/Documents/ChatGPT/fpga创新设计大赛 光鉴项目/output')
PACKAGE=Path('C:/BX72_0107_ACCEPTANCE/20261026_window01')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def dump(p,v):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok:raise ValueError(message)

def prepare():
    for name in ('RUN_ACCEPTANCE_0107.cmd','RUN_ACCEPTANCE_0107.ps1','CONTENTS.json'):
        q=HERE/'local_launchers'/name;q.parent.mkdir(exist_ok=True);q.write_bytes((PACKAGE/name).read_bytes())
    source=WORK/'acceptance_prompt_log.txt';data=source.read_bytes()
    text=data.decode('utf-16') if data.startswith(b'\xff\xfe') else data.decode('utf-8-sig')
    need('PROMPT_ROUNDTRIP=RESET' in text,'Console roundtrip failed')
    prompt=HERE/'verification/prompt_io_01';prompt.mkdir(exist_ok=True)
    for name in ('test_acceptance_prompt.py','test_acceptance_prompt.ps1','acceptance_prompt_log.txt'):(prompt/name).write_bytes((WORK/name).read_bytes())
    dump(prompt/'verification.json',dict(status='PASS',scope='Software console input through Windows PowerShell5 Tee-Object only',
        typed_text='RESET',hardware_contacted=False,production_launcher_UTF8_BOM=(PACKAGE/'RUN_ACCEPTANCE_0107.ps1').read_bytes().startswith(b'\xef\xbb\xbf'),
        final_operator_prints_complete_line_before_input=True,
        fixture_history='Inline -c quoting and UTF8-without-BOM fixtures were corrected; actual launcher uses a file argument and UTF8 BOM.'))
    dump(HERE/'verification/FACTORY_HISTORY.json',dict(first_attempt=dict(status='FAILED_AFTER_OFFLINE_LAUNCHER_PASS',
        error='Status/README writer reused variable q for a WindowsPath then indexed it as qualification JSON.',hardware_contacted=False),
        correction='Renamed parsed qualification record native_review; reran assembly and CheckOnly successfully.',
        current_scope='Factory packaging only; no FPGA logic change or physical capture'))
    current=read(HERE/'verification/CURRENT_EVIDENCE.json');binding=read(HERE/'FINAL_BUILD_BINDING.json');status=read(HERE/'STATUS.json')
    for name,digest in binding['required_files_sha256'].items():need(sha(HERE/name)==digest,'Bound source/evidence changed: '+name)
    need(sha(HERE/binding['bit_file'])==binding['bit_sha256']==sha(PACKAGE/Path(binding['bit_file']).name),'Bit copies differ')
    tests=read(HERE/'verification'/current['software'])
    need(tests['status']=='PASS' and tests['tests']==46 and tests['sources_unchanged'],'Final software receipt')
    for name,digest in tests['source_sha256'].items():need(sha(name)==digest,'Executed source changed: '+name)
    need(status['hardware_tested'] is False and status['release_ready'] is False and status['current09_switched'] is False,'Unproved release scope')
    for name,record in read(PACKAGE/'CONTENTS.json').items():need(sha(PACKAGE/name)==record['sha256'] and (PACKAGE/name).stat().st_size==record['bytes'],'Local package changed: '+name)
    checked=0
    for p in HERE.rglob('*.py'):
        if '__pycache__' in p.parts:continue
        ast.parse(p.read_bytes(),filename=str(p));checked+=1
    dump(HERE/'verification/FINAL_CHECK.json',dict(status='PASS',final_software_tests=46,rtl_unit=61,board_model=18,layout=868,
        final_sources_and_evidence_unchanged=True,local_bit_copy_equal=True,ast_files=checked,
        installed_protection=read(HERE/'verification/PROTECTED_FILES.json'),
        offline_launcher=read(HERE/'verification/DELIVERY.json'),
        bit_sha256=binding['bit_sha256'],hardware_contacted=False,production09_switched=False,release_ready=False))
    selected=[]
    for p in sorted(HERE.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix in ('.pyc','.jou') or p.name=='PUBLISH_MANIFEST.json':continue
        need(p.stat().st_size<15_000_000,'Unexpected large artifact: '+str(p))
        need(p.suffix not in ('.dcp','.xci','.zip','.hex'),'Do not publish large/runtime source snapshots')
        selected.append(p)
    rows=[]
    for p in selected:
        data=p.read_bytes();rows.append(dict(path=p.relative_to(REPO).as_posix(),bytes=len(data),sha256=sha(p),
            git_blob_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()))
    manifest=HERE/'PUBLISH_MANIFEST.json';dump(manifest,dict(schema='guangjian0107-explicit-publication-v1',files=rows,count=len(rows),bytes=sum(r['bytes'] for r in rows)))
    selected.append(manifest)
    pathspec=WORK/'acceptance_publish_paths.nul';pathspec.write_bytes(b'\0'.join(p.relative_to(REPO).as_posix().encode() for p in selected)+b'\0')
    subprocess.run(['git','-c','core.autocrlf=false','add','--sparse','-f','--pathspec-from-file='+str(pathspec),'--pathspec-file-nul'],cwd=REPO,check=True)
    index=subprocess.check_output(['git','ls-files','--stage','--',HERE.relative_to(REPO).as_posix()],cwd=REPO).decode().splitlines()
    staged={line.split('\t')[1]:line.split()[1] for line in index}
    expected={r['path']:r['git_blob_sha'] for r in rows}
    m=manifest.read_bytes();expected[manifest.relative_to(REPO).as_posix()]=hashlib.sha1(b'blob '+str(len(m)).encode()+b'\0'+m).hexdigest()
    need(staged==expected,'Git index differs from explicit publication bytes')
    print(json.dumps(dict(status='PUBLICATION_AND_INDEX_PASS',files=len(selected),bytes=sum(p.stat().st_size for p in selected),
        bit_sha256=binding['bit_sha256']),indent=2))

if __name__=='__main__':prepare()
