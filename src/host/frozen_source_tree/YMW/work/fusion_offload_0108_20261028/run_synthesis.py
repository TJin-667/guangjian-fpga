"""Isolated module resource/timing measurements with immutable source copies."""
import argparse,csv,json,subprocess,time
from pathlib import Path
from run_real_rtl import HERE,sha,dump

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--tops',nargs='+',choices=['fusion_axi_frame','h2_scratch_writer','fusion_group_guard'],default=['fusion_axi_frame','h2_scratch_writer','fusion_group_guard']);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);source=out/'source';source.mkdir()
    for folder in ('rtl','synth'):
        (source/folder).mkdir()
        for f in (HERE/folder).iterdir():
            if f.is_file():(source/folder/f.name).write_bytes(f.read_bytes())
    hashes={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()};dump(out/'INPUTS.json',hashes)
    cmd=['F:/Xilinx/Vivado/2018.3/bin/vivado.bat','-mode','batch','-source',str(source/'synth/build_modules.tcl'),
        '-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',str(source),str(out/'build'),*a.tops]
    start=time.monotonic();print('STANDALONE_SYNTHESIS_STARTED',str(out),flush=True)
    with (out/'console.txt').open('w',encoding='utf-8') as log:r=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    dump(out/'TOOL_RUN.json',dict(tool_returncode=r.returncode,wall_seconds=time.monotonic()-start,command=cmd,
        source_sha256=hashes,bit_generated=False))
    if r.returncode:raise RuntimeError((out/'console.txt').read_text('utf-8',errors='replace')[-6000:])
    reports=[]
    for top in a.tops:
        root=out/'build'/top;row=list(csv.DictReader((root/'status.csv').open()))[0]
        row.update(wns_ns=float(row['wns_ns']),whs_ns=float(row['whs_ns']),timing_met=row['timing_met']=='1')
        reports.append(row)
    assert all(sha(source/f)==d for f,d in hashes.items())
    dump(out/'VERIFICATION.json',dict(status='PASS' if all(x['timing_met'] for x in reports) else 'TIMING_FAILED',
        standalone_OOC_only=True,source_sha256=hashes,reports=reports,wall_seconds=time.monotonic()-start,
        new_board_utilization_measured=False,bit_generated=False,board_commands=0))
    print('STANDALONE_SYNTHESIS_FINISHED',json.dumps(reports),flush=True)
    if not all(x['timing_met'] for x in reports):raise SystemExit(2)

if __name__=='__main__':main()
