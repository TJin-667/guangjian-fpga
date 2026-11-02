"""Bind actual receipts to final source and recheck every preserved baseline file."""
import argparse,csv,hashlib,json,re,shutil,subprocess,sys
from pathlib import Path
from run_real_rtl import HERE,REPO,sha,dump

def read(p):return json.loads(p.read_text('utf-8-sig'))
def resource(path,top):
    for line in path.read_text('utf-8').splitlines():
        cells=[s.strip() for s in line.split('|')[1:-1]]
        if len(cells)==10 and cells[0]==top:
            return dict(LUT=int(cells[2]),FF=int(cells[6]),BRAM36=int(cells[7])+int(cells[8])/2,DSP=int(cells[9]))
    raise ValueError('Missing utilization row '+top)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('E:/GuangjianData/fpga_0108_20261028'))
    p.add_argument('--fusion',default='rtl_real_05');p.add_argument('--faults',default='rtl_faults_05');p.add_argument('--h2',default='rtl_h2_05')
    p.add_argument('--dma-build',default='synthesis_08');p.add_argument('--guard-build',default='synthesis_09');p.add_argument('--writer-build',default='synthesis_06');a=p.parse_args()
    root=a.root.resolve();receipts={}
    for name,folder in [('fusion',a.fusion),('faults',a.faults),('h2',a.h2)]:
        path=root/folder/'VERIFICATION.json';r=read(path)
        if r['status']!='PASS':raise ValueError('Functional failure '+name)
        for source,digest in r['source_sha256'].items():
            if sha(Path(source))!=digest:raise ValueError('Tested source differs from final '+source)
        receipts[name]=dict(path=str(path),sha256=sha(path),report=r)
    assert len(receipts['faults']['report']['checks'])==15
    assert receipts['fusion']['report']['full_ROI_real_frames']==24
    assert all(not any(c['RTL_plus_PC_vs_frozen'].values()) for c in receipts['fusion']['report']['cases'])
    assert all(not any(c['vs_existing_saved_result'].values()) for c in receipts['fusion']['report']['cases'] if c['real'])
    checkpoint_audit_path=root/'checkpoint_audits_final_01/VERIFICATION.json'
    checkpoint_audits=read(checkpoint_audit_path)
    if checkpoint_audits['status']!='REOPEN_AUDIT_PASS_NOT_BOARD_QUALIFICATION':raise ValueError('Checkpoint audit not passed')
    for item in checkpoint_audits['modules']:
        if item['tool_returncode'] or item['timing']['blackboxes']!='0' or sha(Path(item['checkpoint']))!=item['checkpoint_sha256']:
            raise ValueError('Independent checkpoint audit failed or checkpoint changed')
    hostlog=subprocess.run([sys.executable,'-B',str(HERE/'host/test_result_codec.py')],cwd=REPO,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
    if hostlog.returncode or 'Ran 11 tests' not in hostlog.stdout or '\nOK' not in hostlog.stdout:raise RuntimeError(hostlog.stdout)
    modules=[]
    for top,build,deps in [('fusion_axi_frame',a.dma_build,['maxabs8_pixel.v','fusion_axi_frame.v']),
        ('h2_scratch_writer',a.writer_build,['h2_scratch_writer.v']),('fusion_group_guard',a.guard_build,['fusion_group_guard.v'])]:
        base=root/build;hashes={k.replace('\\','/'):v for k,v in read(base/'INPUTS.json').items()};report=base/'build'/top
        for dep in deps:
            if sha(HERE/'rtl'/dep)!=hashes['rtl/'+dep]:raise ValueError('Routed RTL differs '+dep)
        status=list(csv.DictReader((report/'status.csv').open()))[0]
        if 'internal_setup_ns' not in status:raise ValueError('Need internal timing report '+top)
        modules.append(dict(top=top,build=str(base),resources=resource(report/'utilization_routed.rpt',top),
            full_OOC_setup_ns=float(status['wns_ns']),full_OOC_hold_ns=float(status['whs_ns']),
            full_OOC_budget_met=status['timing_met']=='1',internal_setup_ns=float(status['internal_setup_ns']),
            internal_hold_ns=float(status['internal_hold_ns']),internal_timing_met=status['internal_timing_met']=='1',
            reports_sha256={f.name:sha(f) for f in report.glob('*.rpt')},standalone_only=True,board_timing_qualified=False))
    backup=Path('E:/GuangjianData/backups/before_0108_20261028');old=read(backup/'BACKUP_MANIFEST.json')
    if sha(Path(old['archive']))!=old['archive_sha256']:raise ValueError('Old-mode backup archive changed')
    changed=[name for name,item in old['files_sha256'].items() if sha(Path(name))!=item['sha256']]
    if changed:raise ValueError('Old mode changed: '+str(changed))
    preserve=dict(status='PASS',files_rechecked=len(old['files_sha256']),changed_files=changed,
        backup_archive=old['archive'],backup_sha256=old['archive_sha256'],baseline_commit=old['baseline_commit'],
        raw_data_not_duplicated=True,Python_environment_preserved_in_place=True,physical_commands=0)
    evidence=HERE/'evidence';evidence.mkdir(exist_ok=True)
    for name,item in receipts.items():shutil.copyfile(item['path'],evidence/(name.upper()+'_RTL.json'))
    shutil.copyfile(checkpoint_audit_path,evidence/'CHECKPOINT_AUDITS.json')
    dump(evidence/'MODULE_OOC.json',dict(modules=modules,clock_period_ns=8,
        full_board_timing_passed=False,interface_budgets_are_placeholder=True,
        representative_OOC_clock_source='BUFGCTRL_X0Y0, not an actual top-level placement claim'))
    dump(evidence/'BASELINE_PRESERVATION.json',preserve)
    (evidence/'HOST_TESTS.txt').write_text(hostlog.stdout,'utf-8')
    quality=[]
    for sample in ('sample003','sample004','sample005'):
        path=root/f'quality_table_{sample}_01/QUALITY_MANIFEST.json';q=read(path)
        quality.append(dict(specimen=sample,group_id=q['group_id'],group_digest128=q['group_digest128'],
            bytes=sum(f['bytes'] for f in q['frames']),manifest_sha256=sha(path),actual_hardware_upload=False))
    report=dict(status='KERNEL_FUNCTIONAL_PASS_BOARD_INTEGRATION_PENDING',date='2026-10-28',
        real_groups=[{k:c[k] for k in ('name','group_id','pixels','candidate_pixels','RTL_plus_PC_vs_frozen','vs_existing_saved_result')}
                     for c in receipts['fusion']['report']['cases'] if c['real']],
        RTL_real_frames=24,directed_synthetic_frames=24,fault_checks=15,H2_scratch_cases=9,host_tests=11,
        final_source_matches_functional_and_routed_receipts=True,baseline=preserve,modules=modules,
        all_module_internal_timing_met=all(m['internal_timing_met'] for m in modules),
        all_module_full_OOC_budget_met=all(m['full_OOC_budget_met'] for m in modules),
        quality_preparation=quality,independent_checkpoint_reopen_audits_passed=True,
        original_build_tool_exit=dict(fusion_axi_frame='NONZERO_AFTER_ROUTE_REPORTS',h2_scratch_writer='NONZERO_AFTER_ROUTE_REPORTS',fusion_group_guard=0),
        new_board_synthesis=False,new_bit_generated=False,hardware_commands=0,new_captures=0,
        current_mode_switched=False,TJ_confidence_modified=False,release_ready=False,
        open=['Real MIG arbitration/CDC and producer identity integration',
              'New tile-upload/result network protocol and saved_ready ownership path',
              'Exact quality still supplied by PC in this stage',
              'Whole-board resources/timing/qualification, frozen-input board replay and physical acceptance'])
    dump(HERE/'VERIFICATION.json',report)
    dump(HERE/'STATUS.json',{k:report[k] for k in ['status','date','RTL_real_frames','fault_checks','H2_scratch_cases','host_tests',
        'all_module_internal_timing_met','all_module_full_OOC_budget_met','new_board_synthesis','new_bit_generated',
        'hardware_commands','new_captures','current_mode_switched','TJ_confidence_modified','release_ready','open']})
    print(json.dumps(read(HERE/'STATUS.json'),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
