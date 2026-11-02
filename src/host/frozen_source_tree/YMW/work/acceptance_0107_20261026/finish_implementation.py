"""Audit and emit from a timing-passing 0107 checkpoint. Never programs hardware."""
import argparse,csv,hashlib,json,re,subprocess,sys,time
from pathlib import Path
from generate_acceptance import HERE,BASE,REPO
sys.path.append(str(BASE))
from emit_experimental_bitstream import bit_header
from report_implementation import resources

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    build=a.build.resolve();gate=json.loads((build/'build_verification.json').read_bytes())
    if not gate['resource_and_timing_gate_passed']:raise ValueError('Actual implementation gate failed')
    cp=build/'build/routed.dcp';before=sha(cp);manifest=json.loads((build/'input_manifest.json').read_bytes())
    for name,digest in manifest['source_sha256'].items():
        if sha(build/'source'/name)!=digest:raise ValueError('Build snapshot changed: '+name)
    source_pin=json.loads((HERE/'SOURCE_PIN.json').read_bytes())['candidate_source_commit']
    source_names=['dual_view_encoder.v','transport_packet_store.v','transport_layout.v']+[f'derived/{p.name}' for p in sorted((HERE/'derived').glob('*.v'))]
    source_sha={}
    for name in source_names:
        target=HERE/name;relative=target.relative_to(REPO).as_posix()
        data=subprocess.check_output(['git','show',source_pin+':'+relative],cwd=REPO)
        if data!=target.read_bytes():raise ValueError('Candidate source differs from committed pin')
        source_sha[relative]=sha(target)
        built=build/'source'/('integration' if target.name in ('lght_core_camera_identity.v','bx72_ddr_identity_top.v') else 'rtl')/target.name
        if sha(built)!=sha(target):raise ValueError('Build did not use committed source: '+name)
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();vivado='F:/Xilinx/Vivado/2018.3/bin/vivado.bat'
    scripts={'audit':(BASE/'audit_io_cdc.tcl').read_bytes(),'emit':(BASE/'emit_experimental_bitstream.tcl').read_bytes().replace(b'bx72_0106_gray_',b'bx72_0107_acceptance_')}
    record=dict(candidate_source_commit=source_pin,checkpoint_sha256=before,build_manifest_sha256=sha(build/'input_manifest.json'),
        source_sha256=source_sha,hardware_contacted=False,release_ready=False,external_IO_qualified=False,bit_generated=False)
    dump(out/'input_manifest.json',record)
    for name,data in scripts.items():
        script=out/(name+'.tcl');script.write_bytes(data)
        command=[vivado,'-mode','batch','-source',str(script),'-log',str(out/(name+'.log')),'-journal',str(out/(name+'.jou')),
            '-tclargs',str(cp),str(out/(name+'_reports'))]
        print('READONLY_CHECKPOINT',name,flush=True)
        with (out/(name+'_console.txt')).open('w') as log:r=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:raise ValueError(name+' failed; original logs preserved')
        if sha(cp)!=before:raise ValueError('Checkpoint changed')
    artifact=out/'emit_reports/bx72_0107_acceptance_EXPERIMENTAL_NOT_RELEASED.bit'
    header=bit_header(artifact);rows=list(csv.DictReader((out/'emit_reports/gate.csv').open()))
    route=(out/'emit_reports/route_status.rpt').read_text();errors=re.search(r'# of nets with routing errors[.\s]*:\s*(\d+)',route)
    usage=resources(out/'emit_reports/utilization.rpt')
    if len(rows)!=1 or float(rows[0]['wns_ns'])<0 or float(rows[0]['whs_ns'])<0 or rows[0]['blocking_drc']!='0' or not errors or int(errors[1]) or usage['BRAM_36K_equivalent']>108:
        raise ValueError('Emission gates not met')
    if header['part']!='7a100tfgg484':raise ValueError('Wrong FPGA part')
    record.update(status='PASS',bit_generated=True,bit_file=artifact.name,bit_sha256=sha(artifact),bit_bytes=artifact.stat().st_size,
        header=header,resources=usage,wns_ns=float(rows[0]['wns_ns']),whs_ns=float(rows[0]['whs_ns']),
        checkpoint_unchanged=True,wall_seconds=time.monotonic()-start,
        reports_sha256={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.suffix not in ('.bit','.jou')})
    dump(out/'verification.json',record);print(json.dumps(record,indent=2),flush=True)

if __name__=='__main__':main()
