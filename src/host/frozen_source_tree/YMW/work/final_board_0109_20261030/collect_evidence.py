"""Publish bounded receipts and native reports, preserving all full E-drive runs."""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=Path('E:/GuangjianData/final_board_0109_20261030')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text('utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=HERE/'verification');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    copied={};rows=[]
    def copy(source,name):
        target=out/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        copied[name]=dict(source=str(source),sha256=sha(source),bytes=source.stat().st_size)
    cases=(('net_02',22),('board_gray_02',24),('board_dual_02',24),('sdk_02',9),('runtime_03',25),('reset_04',17),('profile_archive_01',9))
    for folder,count in cases:
        source=BASE/folder/'VERIFICATION.json';r=read(source)
        if r['status']!='PASS':raise ValueError('No successful verification '+folder)
        if r.get('physical_hardware') is True:raise ValueError('Do not relabel these tests as physical')
        copy(source,folder+'/VERIFICATION.json');rows.append(dict(run=folder,checks=count,physical_hardware=False,status='PASS'))
        extra=['PACKET_AUDIT.json','COMPILED_INPUTS.json'] if folder.startswith('board_') else []
        if folder.startswith('board_'):
            audit_record=read(BASE/folder/'PACKET_AUDIT.json')
            if audit_record['status']!='PASS' or audit_record['native_capture_frames']!=17 or audit_record['eight_frame_new_offload']!=8:raise ValueError('Incomplete board packet audit')
            for name,digest in audit_record['inputs_sha256'].items():
                if sha(BASE/folder/name)!=digest:raise ValueError('Audited packet input changed '+folder+'/'+name)
        if folder=='runtime_03':extra+=['sessions/VERIFICATION.json','ui/VERIFICATION.json','test_session_batch.py.log','test_continuous_app.py.log']
        if folder=='reset_04':extra+=['tests.log']
        for name in extra:copy(BASE/folder/name,folder+'/'+name)
    source=BASE/'worker_03';result=read(source/'RESULT.json')
    if result['physical_hardware'] is not False or result['parameter_freeze_id']!='f09eb5885e1d' or result['low_lines']!=300 or result['high_lines']!=700:raise ValueError('Worker provenance/freeze/actual exposure')
    for name,digest in read(source/'OUTPUT_MANIFEST.json')['files_sha256'].items():
        if sha(source/name)!=digest:raise ValueError('Worker output changed '+name)
    for name in ('RESULT.json','PERFORMANCE.json','DEVICE_SERVICE.json','DEVICE_SERVICE.html','OUTPUT_MANIFEST.json'):copy(source/name,'worker/'+name)
    copy(BASE/'implementation_01/SUPERSEDED.json','superseded_implementation_01.json')
    copy(BASE/'implementation_01/build/reports/utilization_synth.rpt','cache_inference_before.rpt')
    copy(BASE/'implementation_02/build/reports/utilization_synth.rpt','cache_inference_after.rpt')
    comparison=read(BASE/'phase_comparison_02/SAME_INPUT_PHASES.json')
    if comparison['physical_hardware'] is not False or any(r['R32_word_differences'] for r in comparison['PC_samples']) or any(v is not None for v in comparison['phase_scope_ratios'].values()):raise ValueError('Software comparison relabelled or unequal')
    copy(BASE/'phase_comparison_02/SAME_INPUT_PHASES.json','software_phase_comparison.json')
    copy(BASE/'implementation_02/INPUTS.json','implementation/INPUTS.json')
    tool=BASE/'implementation_02/TOOL_RUN.json'
    if tool.is_file():copy(tool,'implementation/TOOL_RUN.json')
    audit=BASE/'route_audit_01'
    if not (audit/'TOOL_RUN.json').is_file():raise ValueError('Route audit must complete before source sealing')
    for name in ('INPUTS.json','TOOL_RUN.json'):copy(audit/name,'route_audit/'+name)
    for path in (audit/'reports').iterdir():
        if path.is_file():copy(path,'route_audit/reports/'+path.name)
    route=BASE/'route_gate_01/ROUTE_VERIFICATION.json'
    if read(route)['resource_and_internal_timing_gate_passed'] is not True:raise ValueError('Route qualification failed')
    copy(route,'ROUTE_VERIFICATION.json')
    summary=dict(status='OFFLINE_SIMULATION_AND_ROUTED_ENGINEERING_GATES_PASSED',checks=sum(r['checks'] for r in rows),suites=rows,
        frozen_algorithm='f09eb5885e1d',physical_hardware=False,board_programmed=False,bit_emitted_by_this_collector=False,
        same_input_fusion_difference=0,mathematical_kernels_changed=False,full_external_IO_qualified=False,
        pending=['0109 actual device confirmation, manual exposure readback and 24 profiles','same-pose warm reuse on0109 actual board','0109 KEY2 window','fair PC-only and accelerated end-to-end acquisition comparison'],
        failures_retained=['implementation_01 cache inference; superseded before route/bit','reset_01 generator argument, reset_02/03 test fixture adaptation; successful reset_04','runtime_02 inherited environment variable destination; successful runtime_03','First route receipt check shadowed checkpoint digest with source digest; fixed local variable, identical checkpoint and actual audit passed without rerouting or relaxed constraints'])
    write(out/'VERIFICATION.json',summary)
    write(out/'EVIDENCE_INDEX.json',dict(files=copied,full_outputs=str(BASE),scope='Published receipts only; full source snapshots, packet captures, Vivado logs and checkpoints retained outside Git'))
    print('COLLECTED0109_EVIDENCE',len(copied),summary['checks'],flush=True)
if __name__=='__main__':main()
