import ast,hashlib,json,subprocess
from pathlib import Path
REPO=Path('C:/bx72_ymw_0105_20261015/repo')
HERE=REPO/'YMW/work/acceptance_0107_resume_20261026'
BASE=HERE.parent/'acceptance_0107_20261026'
WORK=Path('C:/Users/yue/Documents/ChatGPT/fpga创新设计大赛 光鉴项目/output')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok:raise ValueError(message)

verification=HERE/'verification';tests=read(verification/'r107resume_verification02.json')
need(tests['status']=='PASS' and tests['sources_unchanged'],'Final tests incomplete')
for name,digest in tests['source_sha256'].items():need(sha(HERE/name)==digest,'Tested code changed')
proof=read(verification/'real_frozen_review.json');need(proof['status']=='PASS' and proof['hardware_verified'] and proof['gray_mismatches']==proof['sat_mismatches']==0,'Real proof missing')
latest=Path('C:/Users/yue/Documents/Guangjian0107Acceptance/20261026_113042_c40e31/acceptance/same_frozen/sdk_calls/db182169b327411084d2d794d489d18e/frame_trace.jsonl')
sixth=Path('C:/Users/yue/Documents/Guangjian0107Acceptance/20261026_112752_60c452/acceptance/workflow/acquisition/sdk_calls/6c7e7a2aeb07418b808620bd7199cae4/frame_trace.jsonl')
rows=[json.loads(line) for line in latest.read_text().splitlines()];six=[json.loads(line) for line in sixth.read_text().splitlines()]
bind=[r for r in rows if r.get('event')=='session_bind_acknowledged'];mask=[r for r in rows if r.get('event')=='command' and r.get('kind')==10]
need(bind and not any(r.get('event')=='capture_requested' for r in rows+six),'Unexpected CAP in interrupted traces')
dump(verification/'INTERRUPTION_EVIDENCE.json',dict(latest_trace_sha256=sha(latest),latest_new_session=bind[0]['session'],
    old_gray_session=10464228756609493938,latest_mask_words_ACKed=(int(mask[-1]['args'],16)>>32)+1,
    latest_source=str(latest),sixth_source=str(sixth),sixth_trace_sha256=sha(sixth),sixth_CAP_requested=False,
    latest_CAP_requested=False,OS_termination_cause='NOT_DETERMINED',physical_query_performed=False))
old=read(BASE/'PUBLISH_MANIFEST.json')
manifest_bytes=subprocess.check_output(['git','show','e40c960d4691bb5ac6e1d6fa31b563e9d09f5695:'+ (BASE/'PUBLISH_MANIFEST.json').relative_to(REPO).as_posix()],cwd=REPO)
need((BASE/'PUBLISH_MANIFEST.json').read_bytes()==manifest_bytes,'Original manifest changed')
for row in old['files']:need(sha(REPO/row['path'])==row['sha256'],'Original0107 artifact changed')
protected=read(REPO/'YMW/backups/20261025_before_fixed_pair/BACKUP_MANIFEST.json')
for row in protected['files']:need(sha(Path(protected['source_root'])/row['path'])==row['sha256'],'Installed09/old software changed')
package=Path('C:/BX72_0107_ACCEPTANCE/20261026_window01');contents=read(package/'CONTENTS.json')
for name,rec in contents.items():need(sha(package/name)==rec['sha256'],'Local package changed')
for p in HERE.rglob('*.py'):
    if '__pycache__' not in p.parts:ast.parse(p.read_bytes())
dump(verification/'FINAL_CHECK.json',dict(status='PASS',software_tests=8,real_frozen_input_independent_review='PASS',
    existing_gray_strict_commits_verified=5,original0107_files_unchanged=len(old['files'])+1,installed_files_unchanged=len(protected['files']),
    bit_unchanged=True,visible_launcher_check='PASS',same_CMD_updated=True,hardware_contacted_by_assistant=False,
    completed_eight_hardware=False,completed_reset_hardware=False,release_ready=False))
selected=[p for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='PUBLISH_MANIFEST.json']
records=[]
for p in selected:
    data=p.read_bytes();records.append(dict(path=p.relative_to(REPO).as_posix(),bytes=len(data),sha256=sha(p),git_blob_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()))
manifest=HERE/'PUBLISH_MANIFEST.json';dump(manifest,dict(files=records,count=len(records),bytes=sum(r['bytes'] for r in records)))
selected.append(manifest);pathspec=WORK/'resume_publish_paths.nul';pathspec.write_bytes(b'\0'.join(p.relative_to(REPO).as_posix().encode() for p in selected)+b'\0')
subprocess.run(['git','-c','core.autocrlf=false','add','--sparse','-f','--pathspec-from-file='+str(pathspec),'--pathspec-file-nul'],cwd=REPO,check=True)
index=subprocess.check_output(['git','ls-files','--stage','--',HERE.relative_to(REPO).as_posix()],cwd=REPO).decode().splitlines()
indexed={line.split('\t')[1]:line.split()[1] for line in index};expected={r['path']:r['git_blob_sha'] for r in records}
data=manifest.read_bytes();expected[manifest.relative_to(REPO).as_posix()]=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
need(indexed==expected,'Index byte mismatch')
print(json.dumps(dict(status='PUBLISH_AND_INDEX_PASS',files=len(selected),bytes=sum(p.stat().st_size for p in selected))))
