"""Snapshot real IP/RTL and implement the candidate; never emit a bitstream."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from generate_candidate import generate,HERE,REPO,PIN,TJ,replace
from report_implementation import resources

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--ymw-root',type=Path,default=Path('C:/bx72_ymw_0105_20261015/board_2018_r5/ymw'))
    ap.add_argument('--vivado-bin',type=Path,default=Path('F:/Xilinx/Vivado/2018.3/bin'))
    ap.add_argument('--mode',choices=['core','board'],default='board');args=ap.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);generate()
    source=out/'source';source.mkdir();inputs={}
    for folder in ('rtl','integration','constraints'):
        (source/folder).mkdir()
        for p in sorted((REPO/TJ/folder).glob('*')):
            if p.is_file() and p.suffix in ('.v','.tcl','.xdc','.json'):
                q=source/folder/p.name;q.write_bytes(p.read_bytes())
    for p in (HERE/'derived').glob('*.v'):
        q=source/('integration' if p.name in ('bx72_ddr_identity_top.v','lght_core_camera_identity.v') else 'rtl')/p.name
        q.write_bytes(p.read_bytes())
    for p in [HERE/'transport_packet_store.v',HERE/'transport_layout.v',HERE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v']:
        (source/'rtl'/p.name).write_bytes(p.read_bytes())
    (source/'synth').mkdir()
    tcl=(REPO/TJ/'synth/build_ddr_frame_identity_ooc.tcl').read_text(encoding='utf-8')
    tcl=replace(tcl,'frozen_frame_owner.v saved_packet_store.v tj_frozen_packet_source.v','frozen_frame_owner.v gray_sat_encoder.v transport_packet_store.v transport_layout.v tj_frozen_packet_source.v')
    (source/'synth/build_ddr_frame_identity_ooc.tcl').write_text(tcl,encoding='utf-8',newline='\n')
    peer=out/'ymw';peer.mkdir()
    manifest=json.loads((args.ymw_root/'pinned_manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        p=args.ymw_root/entry['path']
        if sha(p)!=entry['sha256']:raise ValueError('modified pinned YMW file: '+str(p))
        q=peer/entry['path'];q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    (peer/'pinned_manifest.json').write_bytes((args.ymw_root/'pinned_manifest.json').read_bytes())
    pins=(peer/'bx72_1080p_udp.xdc').read_text(encoding='utf-8')
    pins=re.sub(r'set_clock_groups -asynchronous[^#]*?(?=\n\n)','',pins)
    pins=re.sub(r'^set_false_path .*light_uart[^\n]*\n','',pins,flags=re.M)
    (source/'constraints/pinned_board_pins.xdc').write_text(pins,encoding='utf-8',newline='\n')
    for p in source.rglob('*'):
        if p.is_file():inputs[p.relative_to(source).as_posix()]=sha(p)
    dump(out/'input_manifest.json',{'base_commit':PIN,'mode':args.mode,'source_sha256':inputs,'ymw':manifest,'builder_sha256':sha(Path(__file__)),'emit_bit_supported':False})
    command=[(args.vivado_bin/'vivado.bat').as_posix(),'-mode','batch','-source',(source/'synth/build_ddr_frame_identity_ooc.tcl').as_posix(),'-log',(out/'vivado.log').as_posix(),'-journal',(out/'vivado.jou').as_posix(),'-tclargs',peer.as_posix(),(out/'build').as_posix(),args.mode]
    dump(out/'command.json',command);started=time.monotonic();print('REAL_CANDIDATE_IMPLEMENTATION',args.mode,str(out),flush=True)
    with (out/'console.txt').open('w',encoding='utf-8') as log:result=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    for relative,digest in inputs.items():
        if sha(source/relative)!=digest:raise ValueError('source snapshot changed during build')
    summary={'mode':args.mode,'tool_returncode':result.returncode,'routed':(out/'build/routed.dcp').exists(),'timing_met':False,'bram_budget_met':None,'hardware_tested':False,'bit_generated':False,'wall_seconds':round(time.monotonic()-started,3),'source_manifest_sha256':sha(out/'input_manifest.json')}
    status=out/'build/build_status.csv'
    if status.exists():
        rows=list(csv.DictReader(status.open()));assert len(rows)==1
        summary.update(wns_ns=float(rows[0]['wns_ns']),whs_ns=float(rows[0]['whs_ns']),timing_met=rows[0]['timing_met']=='1')
    report=out/'build/reports/utilization_routed.rpt'
    if report.exists():
        resource_values=resources(report)
        summary['resources']=resource_values;summary['bram_budget_met']=resource_values['BRAM_36K_equivalent']<=108
    summary['resource_and_timing_gate_passed']=summary['routed'] and summary['timing_met'] and summary['bram_budget_met'] is True
    summary['release_ready']=False
    summary['limits']=['No bitstream or physical operation.','Original external IO qualification gaps are retained; internal timing/resource PASS alone is not a board release.']
    summary['report_sha256']={p.name:sha(p) for p in (out/'build/reports').glob('*.rpt')}
    dump(out/'build_verification.json',summary);print(json.dumps(summary,indent=2),flush=True)
    if result.returncode or not summary['resource_and_timing_gate_passed']:raise SystemExit(result.returncode or 2)

if __name__=='__main__':main()
