"""Snapshot the qualified0108 board/IP inputs and implement independent0109.

No board connection, no original project mutation, no automatic bit emission.
"""
import argparse,hashlib,json,shutil,subprocess,time
from pathlib import Path
from derive_candidate import HERE,main as derive
PREVIOUS=Path('E:/GuangjianData/fpga_0108_board_20261028/board_build_05')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,o):Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();derive()
    previous=json.loads((PREVIOUS/'INPUTS.json').read_text(encoding='utf-8-sig'))
    for name,digest in previous['source_sha256'].items():
        if sha(PREVIOUS/'source'/name)!=digest:raise ValueError('Qualified board snapshot changed '+name)
    for name,row in previous['reused_IP_products']['checkpoints'].items():
        if sha(PREVIOUS/f'prebuilt_ip/ip2018/{name}/{name}.xci')!=row['xci_sha256'] or sha(PREVIOUS/f'prebuilt_ip/ip2018/{name}/{name}.dcp')!=row['dcp_sha256']:
            raise ValueError('Qualified IP product changed '+name)
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for name in ('source','ymw','prebuilt_ip'):shutil.copytree(PREVIOUS/name,out/name)
    for item in (HERE/'generated').rglob('*.v'):
        target=out/'source'/item.relative_to(HERE/'generated');target.write_bytes(item.read_bytes())
    shutil.copyfile(HERE/'rtl/stage_cycle_meter.v',out/'source/rtl/stage_cycle_meter.v')
    script=out/'source/synth/build_board.tcl';text=script.read_text(encoding='utf-8-sig')
    if text.count('fusion_net_service.v fusion_ui_backend.v')!=1:raise ValueError('Pinned source list changed')
    text=text.replace('fusion_net_service.v fusion_ui_backend.v','fusion_net_service.v fusion_ui_backend.v stage_cycle_meter.v')
    # Retain exact synthesis, clock and IO constraints. Reuse the proven bounded
    # mailbox route checks, without opening or modifying any old checkpoint.
    route=(HERE.parent/'fusion_board_0108_20261028/route_preserved_mailboxes.tcl').read_text(encoding='utf-8-sig')
    text=text[:text.index('\nopt_design\n')+1]+route[route.index('set instances '):]
    script.write_text(text,encoding='utf-8')
    inputs={p.relative_to(out/'source').as_posix():sha(p) for p in sorted((out/'source').rglob('*')) if p.is_file()}
    candidate={str(p.resolve()):sha(p) for p in [*(HERE/'generated').rglob('*.v'),HERE/'rtl/stage_cycle_meter.v',Path(__file__).resolve()]}
    write(out/'INPUTS.json',dict(parent_build=str(PREVIOUS),parent_manifest_sha256=sha(PREVIOUS/'INPUTS.json'),source_sha256=inputs,candidate_source_sha256=candidate,IP_reused_byte_exact=True,clock_or_external_IO_constraints_changed=False,bit_generated=False))
    cmd=['F:/Xilinx/Vivado/2018.3/bin/vivado.bat','-mode','batch','-source',str(script),'-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',str(out/'ymw'),str(out/'build'),'board']
    print('0109_FULL_BOARD_IMPLEMENTATION_STARTED',str(out),flush=True);started=time.monotonic()
    with (out/'console.txt').open('w',encoding='utf-8') as log:result=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    for rel,digest in inputs.items():
        if sha(out/'source'/rel)!=digest:raise ValueError('Implementation source snapshot changed '+rel)
    for rel,digest in candidate.items():
        if sha(rel)!=digest:raise ValueError('Candidate RTL changed while implementing '+rel)
    write(out/'TOOL_RUN.json',dict(returncode=result.returncode,wall_seconds=time.monotonic()-started,source_unchanged=True,bit_generated=False,command=cmd))
    print('0109_IMPLEMENTATION_EXIT',result.returncode,flush=True)
    if result.returncode:raise SystemExit(result.returncode)

if __name__=='__main__':main()
