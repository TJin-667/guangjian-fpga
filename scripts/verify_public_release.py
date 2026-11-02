"""Verify the public snapshot while keeping licensed dependencies explicitly separate."""
from pathlib import Path
import argparse,hashlib,json,re
from urllib.parse import urlsplit,unquote
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--for-publication',action='store_true');a=ap.parse_args()
    expected={}
    for line in (ROOT/'file_manifest.sha256').read_text('utf-8').splitlines():
        h,rel=line.split('  ',1)
        p=(ROOT/rel).resolve()
        if not p.is_relative_to(ROOT):raise ValueError('Unsafe manifest path')
        expected[rel]=h
    errors=[]
    for rel,h in expected.items():
        p=ROOT/rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:errors.append('Public file changed: '+rel)
    external=json.loads((ROOT/'external_dependencies.json').read_bytes())['files']
    restored=[]
    for row in external:
        p=ROOT/row['path']
        if p.exists():
            restored.append(row['path'])
            if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:errors.append('External local file changed: '+row['path'])
    if a.for_publication and restored:errors.append('Licensed external files must be absent from the published snapshot')
    permitted=set(expected)|{'file_manifest.sha256'}|set(restored)
    for p in ROOT.rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if any(part in {'.git','.venv','_work','__pycache__'} for part in rel.parts):continue
        if rel.as_posix() not in permitted:errors.append('Unlisted public file: '+rel.as_posix())
    links=0
    for p in ROOT.rglob('*.md'):
        rel=p.relative_to(ROOT).as_posix()
        if rel.startswith(('src/','provenance/','data/','.git/','_work/')):continue
        for raw in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',p.read_text('utf-8-sig')):
            u=urlsplit(raw.strip().strip('<>'))
            if u.scheme or u.netloc or not u.path:continue
            dest=(p.parent/unquote(u.path)).resolve();links+=1
            if not dest.exists():errors.append('Broken document link: '+rel+' -> '+u.path)
    print(json.dumps(dict(status='PUBLIC_SNAPSHOT_VERIFIED' if not errors else 'FAILED',
                         public_files=len(expected),document_links=links,external_files=len(external),
                         external_files_locally_restored=len(restored),errors=errors,
                         hardware_operated=False,full_hardware_build_verified_by_this_check=False),ensure_ascii=False))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
