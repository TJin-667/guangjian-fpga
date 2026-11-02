"""Require an exact committed source bundle before emitting a candidate bit."""
import argparse,hashlib,json,subprocess
from pathlib import Path,PurePosixPath
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--git-head',action='store_true');a=p.parse_args()
    binding=HERE/'SOURCE_BINDING.json';r=json.loads(binding.read_text('utf-8'))
    actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file() and p!=binding and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.jou','.dcp','.bit')}
    if actual!=set(r['files_sha256']):raise ValueError('Unbound/missing source members')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip() if a.git_head else None
    for name,digest in r['files_sha256'].items():
        relative=PurePosixPath(name);target=(HERE/name).resolve()
        if relative.is_absolute() or '..' in relative.parts or not target.is_relative_to(HERE) or sha(target)!=digest:raise ValueError('Changed source: '+name)
        if commit and subprocess.check_output(['git','show',commit+':'+target.relative_to(REPO).as_posix()],cwd=REPO)!=target.read_bytes():raise ValueError('Uncommitted source '+name)
    if commit and subprocess.check_output(['git','show',commit+':'+binding.relative_to(REPO).as_posix()],cwd=REPO)!=binding.read_bytes():raise ValueError('Uncommitted binding')
    print('0109_SOURCE_BUNDLE_VERIFIED',len(actual),flush=True)
if __name__=='__main__':main()
