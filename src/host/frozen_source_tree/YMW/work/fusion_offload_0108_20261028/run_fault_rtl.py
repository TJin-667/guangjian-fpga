"""Directed control/DDR fault injection in real RTL, with a boundary AXI model."""
import argparse,json,os,time
from pathlib import Path
from run_real_rtl import simulate,dump,sha,HERE

def main():
    p=argparse.ArgumentParser();p.add_argument('--vectors',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    for path in a.vectors.glob('c0_s*.hex'):os.link(path,out/path.name)
    original=HERE/'sim/tb_fusion_axi.sv';text=original.read_text('utf-8').replace('localparam DEPTH=186624;','localparam DEPTH=2048;')
    begin=text.index('    initial begin\n        receipt=$fopen(')
    end=text.index('    initial begin #10000000000;',begin)
    text=text[:begin]+'''    initial begin
        receipt=$fopen("rtl_real_receipt.csv","w");$fwrite(receipt,"case,status\\n");
        repeat(5)tick();reset=0;
    end
    `include "faults.svh"
'''+text[end:]
    tb=out/'tb_fusion_axi.sv';tb.write_text(text,'utf-8');(out/'faults.svh').write_bytes((HERE/'sim/faults.svh').read_bytes())
    hashes=simulate(out,'tb_fusion_axi',[HERE/'rtl'/n for n in ('maxabs8_pixel.v','fusion_axi_frame.v','fusion_group_guard.v')]+[tb],
                    'FUSION_FAULTS_ALL_PASS',timeout=300)
    log=(out/'2_tool.txt').read_text('utf-8');passes=[line.removeprefix('FAULT_PASS ') for line in log.splitlines() if line.startswith('FAULT_PASS ')]
    assert len(passes)>=14,passes
    dump(out/'VERIFICATION.json',dict(status='PASS',checks=passes,source_sha256=hashes,
        original_testbench_sha256=sha(original),fault_include_sha256=sha(HERE/'sim/faults.svh'),
        wall_seconds=time.monotonic()-start,physical_MIG=False,bit_generated=False,board_commands=0))
    print('FAULT_RTL_PASS',len(passes),flush=True)

if __name__=='__main__':main()
