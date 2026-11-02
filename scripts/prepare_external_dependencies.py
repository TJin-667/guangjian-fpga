"""Verify/restore exact licensed local files; never downloads or republishes them."""
from pathlib import Path
import argparse,hashlib,json,shutil,zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,help='Lawfully obtained full engineering directory or original internal handoff ZIP')
    ap.add_argument('--apply',action='store_true',help='Restore verified bytes for local use; default is check-only')
    a=ap.parse_args()
    rows=json.loads((ROOT/'external_dependencies.json').read_bytes())['files']
    archive=None
    if a.source and a.source.is_file():archive=zipfile.ZipFile(a.source)
    missing=[];different=[];available=0;restored=0
    try:
        for row in rows:
            rel=row['path'];target=(ROOT/rel).resolve()
            if not target.is_relative_to(ROOT):raise ValueError('External path leaves repository')
            raw=None
            if target.is_file():raw=target.read_bytes()
            elif archive:
                for prefix in ('handoff/engineering/guangjian-fpga/','guangjian-fpga/',''):
                    try:raw=archive.read(prefix+rel);break
                    except KeyError:pass
            elif a.source:
                for prefix in ('','engineering/guangjian-fpga','handoff/engineering/guangjian-fpga'):
                    p=(a.source/prefix/rel).resolve()
                    if not p.is_relative_to(a.source.resolve()):raise ValueError('Source path leaves supplied directory')
                    if p.is_file():raw=p.read_bytes();break
            if raw is None:missing.append(rel);continue
            if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
                different.append(rel);continue
            available+=1
            if a.apply and not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);restored+=1
        result=dict(status='LICENSED_DEPENDENCIES_READY' if not missing and not different else 'LICENSED_DEPENDENCIES_REQUIRED',
                    expected=len(rows),available=available,missing=missing,changed=different,restored=restored,
                    applied=a.apply,network_access=False,license_grant_by_this_script=False,
                    note='Files remain under original rights and are ignored by Git. Source provenance checks are not removed.')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if missing or different:raise SystemExit(2)
    finally:
        if archive:archive.close()

if __name__=='__main__':main()
