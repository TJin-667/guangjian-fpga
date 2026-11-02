"""Bind reviewed route to an independently named engineering bit and source.

Never downloads a bit or changes a hardware target. Ordinary IO/DRC warnings
remain in the read-only reports; engineering success is not production release.
"""
import argparse,csv,hashlib,json,re,subprocess,sys,time
from pathlib import Path
from route_common import HERE,REPO,sha,dump,pinned,verify_kernels
def verify_route(build,audit):
    inputs=json.loads((build/'INPUTS.json').read_text('utf-8'));cp=build/'build/routed.dcp';digest=sha(cp)
    for name,value in inputs['source_sha256'].items():
        if sha(build/'source'/name)!=value:raise ValueError('Build snapshot changed '+name)
    for path in [*(HERE/'generated/rtl').glob('*.v'),*(HERE/'generated/integration').glob('*.v'),*(HERE/'rtl').glob('*.v')]:
        folder='integration' if path.parent.name=='integration' else 'rtl'
        if sha(path)!=sha(build/'source'/folder/path.name):raise ValueError('Current RTL differs from actual route '+path.name)
    run=json.loads((build/'TOOL_RUN.json').read_text('utf-8'))
    if run['returncode']!=0 or run['source_unchanged'] is not True:raise ValueError('Incomplete implementation')
    for name,source_digest in inputs['candidate_source_sha256'].items():
        if sha(name)!=source_digest:raise ValueError('Implementation source changed '+name)
    proof=json.loads((audit/'INPUTS.json').read_text('utf-8'));tool=json.loads((audit/'TOOL_RUN.json').read_text('utf-8'))
    if proof['checkpoint_sha256']!=digest or tool['tool_returncode']!=0 or not tool['checkpoint_unchanged']:raise ValueError('Read-only checkpoint audit failed')
    gate=list(csv.DictReader((audit/'reports/audit_gate.csv').open()))[0]
    route=(audit/'reports/route_status.rpt').read_text('utf-8');errors=re.search(r'# of nets with routing errors[.\s]*:\s*(\d+)',route)
    report=(audit/'reports/utilization.rpt').read_text('utf-8')
    bram=float(re.search(r'\| Block RAM Tile\s*\|\s*([\d.]+)',report)[1])
    timing=(audit/'reports/check_timing.rpt').read_text('utf-8')
    unconstrained=re.search(r'There are (\d+) pins that are not constrained for maximum delay\.',timing)
    no_clock=re.search(r'There are (\d+) register/latch pins with no clock\.',timing)
    loops=re.search(r'There are (\d+) combinational loops in the design\.',timing)
    bundles=list(csv.DictReader((audit/'reports/bundle_paths.tsv').open(),delimiter='\t'))
    bundles_ok=len(bundles)==12 and all(float(r['slack_ns'])>=0 and float(r['requirement_ns'])>0 for r in bundles)
    skew_report=(audit/'reports/bus_skew.rpt').read_text('utf-8')
    # Vivado 2018.3 summary rows carry requirement, actual and slack; per-
    # constraint detail rows carry only actual and slack. Require the complete
    # 17-constraint inventory, including all seven new acknowledged mailboxes.
    skew_rows=[tuple(map(float,row)) for row in re.findall(r'^\s+(?:Slow|Fast)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*$',skew_report,re.M)]
    skew_ok=len(skew_rows)==17 and all(requirement>0 and actual>=0 and slack>=0 for requirement,actual,slack in skew_rows) and 'VIOLATED' not in skew_report
    internal_coverage=unconstrained is not None and int(unconstrained[1])==0 and no_clock is not None and int(no_clock[1])==0 and loops is not None and int(loops[1])==0
    okay=float(gate['wns_ns'])>=0 and float(gate['whs_ns'])>=0 and bram<=108 and gate['blackboxes']=='0' and gate['unexpected_new_mailbox_endpoints']=='0' and gate['blocking_DRC']=='0' and errors is not None and int(errors[1])==0 and internal_coverage and bundles_ok and skew_ok
    result=dict(schema='guangjian-0109-route-verification-v1',resource_and_internal_timing_gate_passed=okay,
        checkpoint_sha256=digest,source_manifest_sha256=sha(build/'INPUTS.json'),audit_input_sha256=sha(audit/'INPUTS.json'),
        wns_ns=float(gate['wns_ns']),whs_ns=float(gate['whs_ns']),BRAM36_equivalent=bram,blackboxes=int(gate['blackboxes']),
        unexpected_new_mailbox_endpoints=int(gate['unexpected_new_mailbox_endpoints']),blocking_DRC=int(gate['blocking_DRC']),route_errors=None if errors is None else int(errors[1]),
        unconstrained_internal_endpoints=None if unconstrained is None else int(unconstrained[1]),missing_register_clocks=None if no_clock is None else int(no_clock[1]),combinational_loops=None if loops is None else int(loops[1]),all_twelve_data_bundle_paths_meet_bounds=bundles_ok,
        bus_skew_constraints=len(skew_rows),all_bus_skew_constraints_pass=skew_ok,minimum_bus_skew_slack_ns=min((row[2] for row in skew_rows),default=None),
        full_external_IO_qualification=False,hardware_tested=False,release_ready=False,
        qualification_scope='Engineering same-input acceptance only; original IO/clock/BRAM reset warnings retained in expanded audit',
        reports_sha256={p.relative_to(audit).as_posix():sha(p) for p in (audit/'reports').iterdir() if p.is_file()})
    return cp,result
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    verify_kernels();cp,route=verify_route(a.build.resolve(),a.audit.resolve())
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);dump(out/'ROUTE_VERIFICATION.json',route)
    if not route['resource_and_internal_timing_gate_passed']:raise ValueError('Actual routed gate failed; no bit emitted')
    if a.verify_only:print('ENGINEERING_ROUTE_GATE_PASS_NO_BIT',flush=True);return
    subprocess.run([sys.executable,'-B',str(HERE/'verify_bundle.py'),'--git-head'],cwd=REPO,check=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    source=pinned('YMW/work/gray_transport_0105_20261025/emit_experimental_bitstream.tcl').replace(b'bx72_0106_gray_',b'bx72_0109_fusion_')
    script=out/'emit.tcl';script.write_bytes(source)
    cmd=['F:/Xilinx/Vivado/2018.3/bin/vivado.bat','-mode','batch','-source',str(script),'-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',str(cp),str(out/'bit')]
    start=time.monotonic();print('EMIT0109_ENGINEERING_BIT_STARTED',flush=True)
    with (out/'console.txt').open('w') as log:r=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    if r.returncode or sha(cp)!=route['checkpoint_sha256']:raise ValueError('Bit emission failed or checkpoint changed; logs retained')
    bit=out/'bit/bx72_0109_fusion_EXPERIMENTAL_NOT_RELEASED.bit'
    if not bit.is_file() or 'EXPERIMENTAL_BIT_COMPLETE' not in (out/'console.txt').read_text('utf-8',errors='replace'):raise ValueError('No successful bit artifact')
    # Parse actual .bit part header using the existing checked project helper.
    sys.path.insert(0,str(HERE.parent/'gray_transport_0105_20261025'));from emit_experimental_bitstream import bit_header
    header=bit_header(bit)
    if header['part']!='7a100tfgg484':raise ValueError('Unexpected part in emitted bit')
    receipt=dict(schema='guangjian-bit-from-qualified-checkpoint-v1',source_commit=commit,input_checkpoint_sha256=route['checkpoint_sha256'],
        write_bitstream_succeeded=True,bit_sha256=sha(bit),bit_bytes=bit.stat().st_size,header=header,tool_returncode=r.returncode,wall_seconds=time.monotonic()-start,
        emission_script_sha256=sha(script),route_verification_sha256=sha(out/'ROUTE_VERIFICATION.json'),hardware_programmed=False,release_ready=False)
    dump(out/'BIT_BUILD_RECEIPT.json',receipt)
    qualification=dict(schema='guangjian-0109-engineering-candidate-v1',engineering_capture_ready=True,release_ready=False,candidate_source_commit=commit,
        bundle_sha256=sha(HERE/'SOURCE_BINDING.json'),checkpoint_sha256=route['checkpoint_sha256'],
        bit_path=str(bit),bit_sha256=sha(bit),bit_build_receipt_path=str(out/'BIT_BUILD_RECEIPT.json'),bit_build_receipt_sha256=sha(out/'BIT_BUILD_RECEIPT.json'),
        route_verification_path=str(out/'ROUTE_VERIFICATION.json'),route_verification_sha256=sha(out/'ROUTE_VERIFICATION.json'),
        downloaded_bit_sha_readback_verified=False,physical_hardware_tested=False)
    dump(out/'QUALIFICATION.json',qualification);print('ENGINEERING_CANDIDATE_READY',str(out/'QUALIFICATION.json'),flush=True)
if __name__=='__main__':main()
