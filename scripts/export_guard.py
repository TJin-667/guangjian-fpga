"""Verify current export bytes and byte-pinned upstream Git membership proofs.

Original source bindings remain unchanged. Portability-only derivatives have
separate identities; they are never described as byte-identical upstream code.
"""
import base64,hashlib,json
from pathlib import Path
from export_paths import PACKAGE_ROOT,SOURCE_ROOT
from export_seal import MANIFEST_SHA256

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def need(ok,message):
    if not ok:raise ValueError(message)
def inside(relative):
    need(isinstance(relative,str) and '\\' not in relative,'Invalid export relative path')
    p=(PACKAGE_ROOT/relative).resolve()
    need(p.is_relative_to(PACKAGE_ROOT),'Export path escapes package')
    return p
def git_hash(kind,raw):return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def tree_entries(raw):
    result={};pos=0
    while pos<len(raw):
        space=raw.index(b' ',pos);end=raw.index(b'\0',space)
        mode=raw[pos:space].decode('ascii');name=raw[space+1:end].decode('utf-8')
        oid=raw[end+1:end+21].hex();need(len(oid)==40,'Truncated upstream tree')
        result[name]=(mode,oid);pos=end+21
    return result
def proof_objects():
    p=read(PACKAGE_ROOT/'provenance/upstream_git_proofs.json');result={}
    for oid,row in p['objects'].items():
        raw=base64.b64decode(row['base64'],validate=True)
        need(git_hash(row['kind'],raw)==oid,'Upstream proof object changed')
        result[oid]=(row['kind'],raw)
    return p,result
def upstream_blob_id(commit,path,proof=None):
    spec,objects=proof or proof_objects()
    need(commit in spec['pinned_commits'],'Unexpected upstream source commit')
    kind,raw=objects[commit];need(kind=='commit','Invalid upstream commit object')
    line=raw.split(b'\n',1)[0];need(line.startswith(b'tree '),'Missing upstream root tree')
    oid=line[5:].decode('ascii')
    for part in Path(path).as_posix().split('/'):
        kind,raw=objects[oid];need(kind=='tree','Non-tree upstream path')
        entries=tree_entries(raw);need(part in entries,'Upstream source path missing')
        _,oid=entries[part]
    return oid
def manifest():
    p=PACKAGE_ROOT/'provenance/export_manifest.json'
    need(sha(p)==MANIFEST_SHA256,'Export manifest differs from release seal')
    return read(p)
def relative(path):
    p=Path(path).resolve();need(p.is_relative_to(PACKAGE_ROOT),'File outside export package')
    return p.relative_to(PACKAGE_ROOT).as_posix()
def matches_origin(path,expected_original):
    row=manifest()['files'].get(relative(path))
    return bool(row and row.get('upstream_sha256')==expected_original and sha(path)==row['sha256'])
def verify():
    m=manifest();files=m['files']
    for name,row in files.items():
        p=inside(name)
        need(p.is_file() and sha(p)==row['sha256'],'Export file missing/changed: '+name)
        if row.get('original_file'):
            original=inside(row['original_file']).read_bytes()
            need(hashlib.sha256(original).hexdigest()==row['upstream_sha256'],'Original source proof SHA changed: '+name)
            need(git_hash('blob',original)==row['upstream_git_blob'],'Original source proof Git identity changed: '+name)
    for prefix in m['exact_inventory_roots']:
        root=inside(prefix)
        actual={p.relative_to(PACKAGE_ROOT).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')}
        expected={p for p in files if p.startswith(prefix+'/')}
        need(actual==expected,'Unbound or missing export members: '+prefix)
    proof=proof_objects()
    for row in m['upstream_pins']:
        raw=inside(row['original_file']).read_bytes()
        need(git_hash('blob',raw)==upstream_blob_id(row['commit'],row['source_path'],proof),'Upstream pinned blob differs: '+row['source_path'])
    return m
def candidate_sources():
    m=verify()
    return {str(inside(p)):row['sha256'] for p,row in m['files'].items() if p.startswith('src/host/') or p.startswith('scripts/')}
