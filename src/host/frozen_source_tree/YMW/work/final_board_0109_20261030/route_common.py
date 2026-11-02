"""Immutable 0107 board sources plus the verified first-stage 0108 kernels."""
import hashlib,json,subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
PIN='ef02414acc1d5f55561de2ce1af1bd5e61ffc53f'
KERNEL=REPO/'YMW/work/fusion_offload_0108_20261028'
TJ=REPO/'TJ/work/fpga_image_pipeline'
ACCEPT=REPO/'YMW/work/acceptance_0107_20261026'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='\n') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')
def pinned(relative):
    path=REPO/relative;raw=subprocess.check_output(['git','show',PIN+':'+relative],cwd=REPO)
    if path.read_bytes()!=raw:raise ValueError('Frozen source changed '+relative)
    return raw
def verify_kernels():
    binding=json.loads((KERNEL/'SOURCE_BINDING.json').read_text('utf-8'))
    for name,digest in binding['files_sha256'].items():
        if sha(KERNEL/name)!=digest:raise ValueError('0108 phase1 changed '+name)
def replace(text,old,new,count=1):
    if text.count(old)!=count:raise ValueError('Source anchor changed: '+old)
    return text.replace(old,new)
def simulate(out,top,sources,marker):
    sys.path.insert(0,str(KERNEL));from run_real_rtl import simulate as run
    return run(out,top,sources,marker)
