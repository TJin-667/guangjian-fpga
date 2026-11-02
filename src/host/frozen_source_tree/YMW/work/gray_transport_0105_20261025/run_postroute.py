"""Optimize an exact checkpoint in new output; never alter IO/CDC exceptions."""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from report_implementation import audit

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--vivado-bin',type=Path,default=Path('F:/Xilinx/Vivado/2018.3/bin'));a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);checkpoint=a.checkpoint.resolve()
    tcl=Path(__file__).resolve().with_name('optimize_routed.tcl')
    input_digest=sha(checkpoint);script_digest=sha(tcl)
    command=[(a.vivado_bin/'vivado.bat').as_posix(),'-mode','batch','-source',tcl.as_posix(),'-log',(out/'vivado.log').as_posix(),'-journal',(out/'vivado.jou').as_posix(),'-tclargs',checkpoint.as_posix(),(out/'implementation').as_posix()]
    dump(out/'input_manifest.json',{'source_checkpoint':str(checkpoint),'source_checkpoint_sha256':input_digest,'optimization_script_sha256':script_digest,'command':command,'new_logic_sources':False,'new_timing_exceptions':False,'bitstream':False})
    start=time.monotonic();print('POSTROUTE_OPTIMIZATION',str(out),flush=True)
    with (out/'console.txt').open('w',encoding='utf-8') as log:r=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    if sha(checkpoint)!=input_digest or sha(tcl)!=script_digest:raise ValueError('input changed during optimization')
    report=audit(out/'implementation',tool_returncode=r.returncode)
    report.update(wall_seconds=round(time.monotonic()-start,3),source_checkpoint_sha256=input_digest,physical_optimization_only=True,source_constraints_preserved=True)
    dump(out/'verification.json',report);print(json.dumps(report,indent=2),flush=True)
    if r.returncode or not report['resource_and_timing_gate_passed']:raise SystemExit(r.returncode or 2)

if __name__=='__main__':main()
