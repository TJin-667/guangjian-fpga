"""Build the unchanged FPGA inputs in a fresh workspace; never program a board."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,uuid

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado',type=Path,help='Vivado 2018.3 executable or batch launcher; otherwise use PATH')
    parser.add_argument('--check-only',action='store_true',help='Verify packaged inputs, without starting Vivado')
    parser.add_argument('--out',type=Path,help='A new build directory; must not already exist')
    args=parser.parse_args()
    from export_guard import verify
    verify()
    inputs=ROOT/'src/fpga/implemented'
    specification=json.loads((inputs/'INPUTS.json').read_bytes())
    for relative,digest in specification['source_sha256'].items():
        if sha(inputs/'source'/relative)!=digest:raise ValueError('FPGA input changed: '+relative)
    for name in ('sys_pll','wr_ddr3_fifo','rd_ddr3_fifo','mig_7series_0'):
        p=inputs/'prebuilt_ip/ip2018'/name/(name+'.xci')
        if not p.is_file():raise FileNotFoundError(p)
    ready=dict(status='FPGA_BUILD_INPUTS_READY',source_files=len(specification['source_sha256']),
               algorithm_or_RTL_changed=False,hardware_contacted=False,bit_programmed=False)
    if args.check_only:
        print(json.dumps(ready));return
    vivado=args.vivado or (Path(os.environ['VIVADO_BIN']) if os.environ.get('VIVADO_BIN') else None)
    if vivado is None:
        found=shutil.which('vivado') or shutil.which('vivado.bat')
        if found:vivado=Path(found)
    if not vivado or not vivado.is_file():raise FileNotFoundError('Supply --vivado for Vivado 2018.3, or put it on PATH')
    version=subprocess.run([str(vivado),'-version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True).stdout
    if 'v2018.3' not in version:raise ValueError('Pinned inputs require Vivado 2018.3; automatic IP upgrade is disabled')
    default=ROOT/'_work/fpga_build'/('build_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    out=(args.out or default).resolve()
    if out.exists():raise FileExistsError('Use a new output directory: '+str(out))
    out.mkdir(parents=True)
    work=out/'inputs'
    shutil.copytree(inputs,work)
    command=[str(vivado),'-mode','batch','-notrace','-source',str(work/'source/synth/build_board.tcl'),
             '-tclargs',str(work/'ymw'),str(out/'build'),'board']
    record=dict(ready,status='FPGA_REBUILD_RUNNING',vivado_version=version.strip(),
                command=command,input_copy=str(work),output=str(out/'build'),
                bit_generation_requested=False,existing_bit_sha256=sha(ROOT/'board/artifacts/bx72_0109_fusion_EXPERIMENTAL_NOT_RELEASED.bit'))
    receipt=out/'rebuild_receipt.json'
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(status=record['status'],directory=str(out))),flush=True)
    with (out/'vivado_console.log').open('w',encoding='utf8') as log:
        result=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    record['exit_code']=result.returncode
    routed=out/'build/routed.dcp'
    record['status']='FPGA_REBUILD_COMPLETED' if result.returncode==0 and routed.is_file() else 'FPGA_REBUILD_FAILED'
    if routed.is_file():record['rebuilt_checkpoint_sha256']=sha(routed)
    record['rebuild_does_not_requalify_existing_bit']=True
    record['existing_bit_unchanged']=sha(ROOT/'board/artifacts/bx72_0109_fusion_EXPERIMENTAL_NOT_RELEASED.bit')==record['existing_bit_sha256']
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(status=record['status'],receipt=str(receipt))),flush=True)
    if record['status']!='FPGA_REBUILD_COMPLETED' or not record['existing_bit_unchanged']:raise SystemExit(2)
if __name__=='__main__':main()
