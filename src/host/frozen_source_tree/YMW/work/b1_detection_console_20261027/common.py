"""Small shared contracts for the separate, offline B1 detection application."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path,PurePosixPath

HERE=Path(__file__).resolve().parent
DEFAULT_INPUT=Path('E:/GuangjianData/P0Pairs')
DEFAULT_OUTPUT=Path('E:/GuangjianData/B1Detection')
ORDER=tuple(f'CH{i}_{role}' for i in range(1,5) for role in ('low','high'))

def need(ok,message):
    if not ok:raise ValueError(message)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def inside(root,name):
    need(isinstance(name,str) and '\\' not in name and ':' not in name,'Unsafe artifact path')
    p=PurePosixPath(name);need(not p.is_absolute() and '..' not in p.parts and bool(p.parts),'Path escapes input root')
    result=(Path(root)/str(p)).resolve();need(result.is_relative_to(Path(root).resolve()),'Resolved artifact escapes root')
    return result

def verify_vendor():
    binding=read(HERE/'VENDOR_BINDING.json');from export_paths import vendor_root;root=vendor_root().resolve()
    for name,digest in binding['files_sha256'].items():need(sha(inside(root,name))==digest,'XDL package file changed: '+name)
    for pin in read(root/'dual_exposure_b1/frozen_reference_manifest.json'):
        need(sha(root/'dual_exposure_b1'/pin['frozen_path'])==pin['sha256'],'Frozen algorithm differs: '+pin['frozen_path'])
    return root,binding

def verify_app():
    for name,digest in read(HERE/'APP_BINDING.json')['files_sha256'].items():
        from export_guard import matches_origin
        need(matches_origin(inside(HERE,name),digest),'Detection application source changed: '+name)

def resolve_manifest(source):
    p=Path(source).resolve()
    if p.is_file():need(p.name=='XDL_manifest.json','Select a P0 group directory, XDL_manifest.json, or supported ZIP');return p
    for relative in ['XDL_manifest.json','pair/XDL_manifest.json']:
        if (p/relative).is_file():return p/relative
    raise ValueError('No complete P0 group manifest in selected directory')

def describe(source):
    source=Path(source).resolve()
    if source.suffix.lower()=='.zip':return dict(source=str(source),label=source.name+' [ZIP，运行时校验]',group_id=None)
    manifest=resolve_manifest(source);d=read(manifest);need(len(d.get('groups',[]))==1,'One group per selected input')
    g=d['groups'][0];observations=g['observations'];low={x['exposure_lines'] for x in observations if x['exposure_role']=='low'};high={x['exposure_lines'] for x in observations if x['exposure_role']=='high'}
    need(len(observations)==8 and len(low)==len(high)==1,'Not a complete eight-frame exposure pair')
    return dict(source=str(manifest),group_id=g['group_id'],specimen=g['specimen_id'],low=next(iter(low)),high=next(iter(high)),label=f"{g['specimen_id']}  {next(iter(low))}/{next(iter(high))}行  {g['group_id']}")

def discover(source):
    p=Path(source).resolve()
    if p.is_file() or (p/'XDL_manifest.json').exists() or (p/'pair/XDL_manifest.json').exists():return [describe(p)]
    candidates=sorted(p.glob('*/pair/XDL_manifest.json'))+sorted(p.glob('*/XDL_manifest.json'))
    result=[];seen=set()
    for path in candidates:
        try:row=describe(path)
        except (ValueError,KeyError,json.JSONDecodeError,OSError):continue
        if row['group_id'] not in seen:result.append(row);seen.add(row['group_id'])
    need(result,'No complete paired groups found here')
    return result
