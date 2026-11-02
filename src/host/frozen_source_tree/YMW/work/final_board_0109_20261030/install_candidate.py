"""Install only a separately named launcher; preserve and hash the old entry."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--desktop',type=Path);a=p.parse_args()
    qualification=Path('E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json')
    sys.path.insert(0,str(HERE/'host'));from qualification import validate
    q,_=validate(qualification)
    old=Path('E:/GuangjianData/software/FinalSystem_20261029')
    preserved={str(p):sha(p) for p in old.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    def launcher(name,target):
        text='@echo off\r\ncall "'+str(target)+'" %*\r\n'
        path=out/name;path.write_bytes(text.encode('utf-8'));return path
    launch=launcher('RUN_0109_SYSTEM.cmd',HERE/'RUN_0109_SYSTEM.cmd')
    launcher('RUN_RESET_0109.cmd',HERE/'RUN_RESET_0109.cmd')
    if a.desktop:
        path=a.desktop/'光鉴0109独立候选入口.cmd'
        if path.exists():raise ValueError('Existing desktop candidate entry retained; choose a new install')
        path.write_bytes(('@echo off\r\ncall "'+str(launch)+'" %*\r\n').encode('utf-8'))
    if not all(sha(p)==h for p,h in preserved.items()):raise ValueError('Original installation changed')
    result=dict(status='SEPARATE_CANDIDATE_ENTRY_INSTALLED',qualification=str(qualification),candidate_source_commit=q['candidate_source_commit'],bit_sha256=q['bit_sha256'],
        old_entry_files_sha256=preserved,old_files_unchanged=True,default_entry_switched=False,board_programmed=False,entry=str(launch),physical_hardware_tested=False)
    (out/'INSTALLATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],entry=str(launch),preserved_old_files=len(preserved)),ensure_ascii=False))
if __name__=='__main__':main()
