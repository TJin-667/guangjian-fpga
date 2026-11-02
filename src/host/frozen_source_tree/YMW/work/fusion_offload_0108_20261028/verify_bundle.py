"""Verify this independent candidate bundle; never modify an old installation."""
import argparse,hashlib,json,subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent;BINDING=HERE/'SOURCE_BINDING.json'
def members():
    return {p.relative_to(HERE).as_posix():p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and
            p!=BINDING and (p.suffix in {'.py','.v','.sv','.svh','.tcl','.md','.json','.txt'} or p.name in {'.gitignore','.gitattributes'})}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--git-head',action='store_true');a=p.parse_args();files=members()
    if a.write:
        if BINDING.exists():raise FileExistsError('Binding already exists; review changes before updating it')
        with BINDING.open('w',encoding='utf-8',newline='\n') as f:
            f.write(json.dumps(dict(schema='0108-independent-candidate-source-v1',files_sha256={k:sha(v) for k,v in sorted(files.items())}),indent=2)+'\n')
    expected=json.loads(BINDING.read_text('utf-8'))['files_sha256']
    if set(expected)!=set(files):raise ValueError('Bundle members differ')
    for name,digest in expected.items():
        if sha(files[name])!=digest:raise ValueError('Bundle changed: '+name)
    if a.git_head:
        repo=HERE.parents[2]
        for name,path in (files|{'SOURCE_BINDING.json':BINDING}).items():
            raw=subprocess.check_output(['git','show','HEAD:'+path.relative_to(repo).as_posix()],cwd=repo)
            if hashlib.sha256(raw).hexdigest()!=sha(path):raise ValueError('Git blob differs from working bytes '+name)
        print('GIT_BLOBS_BYTE_VERIFIED',len(files)+1)
    print('BUNDLE_BYTE_VERIFIED',len(files))

if __name__=='__main__':main()
