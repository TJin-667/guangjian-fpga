"""Inventory the exact routed checkpoint without altering implementation."""
import argparse,hashlib,json,subprocess,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
CHECKPOINT_SHA='175d82b777469cc1e94d4123ace9935ea25f8d47902476ee6f926ca47c30c947'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--vivado',type=Path,default=Path('F:/Xilinx/Vivado/2018.3/bin/vivado.bat'));args=p.parse_args()
    checkpoint=args.checkpoint.resolve();out=args.out.resolve();script=HERE/'audit_io_cdc.tcl'
    if sha(checkpoint)!=CHECKPOINT_SHA:raise ValueError('Not the exact reviewed routed checkpoint')
    out.mkdir(parents=True,exist_ok=False);script_sha=sha(script)
    (out/'audit_script.tcl').write_bytes(script.read_bytes())
    command=[str(args.vivado),'-mode','batch','-source',str(script),'-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',str(checkpoint),str(out/'reports')]
    record=dict(checkpoint=str(checkpoint),checkpoint_sha256=CHECKPOINT_SHA,script_sha256=script_sha,runner_sha256=sha(Path(__file__)),command=command,
        implementation_modified=False,new_bit=False,hardware_contacted=False)
    (out/'input_manifest.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    started=time.monotonic()
    with (out/'console.txt').open('w',encoding='utf-8') as f:result=subprocess.run(command,cwd=out,stdout=f,stderr=subprocess.STDOUT)
    if sha(checkpoint)!=CHECKPOINT_SHA or sha(script)!=script_sha:raise ValueError('Audit input changed')
    record.update(returncode=result.returncode,completed=(out/'reports/audit_complete.txt').is_file(),wall_seconds=round(time.monotonic()-started,3),
        reports_sha256={p.name:sha(p) for p in sorted((out/'reports').glob('*')) if p.is_file()})
    (out/'verification.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');print(json.dumps(record,indent=2))
    if result.returncode or not record['completed']:raise SystemExit(1)

if __name__=='__main__':main()
