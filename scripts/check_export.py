"""Verify a relocated release and reject changed inputs without board access."""
from pathlib import Path
import argparse,base64,datetime,hashlib,json,os,shutil,subprocess,sys,uuid
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path);a=parser.parse_args()
    out=(a.out or ROOT/'_work'/('export_check_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])).resolve()
    if out.exists():raise FileExistsError('Use a new verification directory')
    if ROOT.is_relative_to(out):raise ValueError('Output cannot contain the original release')
    out.mkdir(parents=True)
    moved=out/'relocated copy'
    shutil.copytree(ROOT,moved,ignore=shutil.ignore_patterns('.git','_work','__pycache__','.venv','runtime.local.json'))
    rows=[]
    def run(name,script,args,expect=None):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env.pop('PYTHONPATH',None)
        env.pop('GUANGJIAN_DATA_ROOT',None)
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(moved/'scripts'/script),*args],cwd=moved,
                         env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
        (out/(name+'.log')).write_text(p.stdout,encoding='utf8')
        passed=p.returncode==0 if expect is None else p.returncode!=0 and expect in p.stdout
        rows.append(dict(case=name,passed=passed,exit_code=p.returncode,expected_failure_text=expect))
        write(out/'PROGRESS.json',rows)
        if not passed:raise AssertionError(name+': see '+str(out/(name+'.log')))
    run('01_relocated_entry','launch_gui.py',['--check-only'])
    run('02_relocated_GUI_SDK_focus_engine','probe_host.py',['--gui'])
    run('03_relocated_full_host_algorithm','replay_host_example.py',['--out',str(moved/'_work/replay')])
    from_context='src/host/frozen_source_tree/YMW/work/'
    mutations=[('04_changed_bit','board/artifacts/bx72_0109_fusion_EXPERIMENTAL_NOT_RELEASED.bit'),
               ('05_changed_numerical_source',from_context+'weak_stability_tuning_20261030/seed_parameters.py')]
    for name,relative in mutations:
        target=moved/relative;original=target.read_bytes()
        try:
            target.write_bytes(original+b'\nCHANGED_TEST_BYTE')
            run(name,'launch_gui.py',['--check-only'],'Export file missing/changed: '+relative)
        finally:target.write_bytes(original)
    extra=moved/(from_context+'final_board_0109_20261030/runtime/unbound_test.py')
    try:
        extra.write_text('unbound=True\n',encoding='ascii')
        run('06_extra_unbound_member','launch_gui.py',['--check-only'],'Unbound or missing export members')
    finally:extra.unlink()
    manifest=moved/'provenance/export_manifest.json';seal=moved/'scripts/export_seal.py'
    original_manifest=manifest.read_bytes();original_seal=seal.read_bytes()
    def reseal(relatives):
        m=read(manifest)
        for relative in relatives:m['files'][relative]['sha256']=sha(moved/relative)
        write(manifest,m);seal.write_text('MANIFEST_SHA256='+repr(sha(manifest))+'\n',encoding='ascii')
    proof_rel='provenance/upstream_git_proofs.json';proof=moved/proof_rel;original_proof=proof.read_bytes()
    try:
        spec=read(proof);first=next(iter(spec['objects'].values()))
        first['base64']=base64.b64encode(base64.b64decode(first['base64'])+b'!').decode('ascii')
        write(proof,spec);reseal([proof_rel])
        run('07_changed_Merkle_object_with_fixture_reseal','launch_gui.py',['--check-only'],'Upstream proof object changed')
    finally:
        proof.write_bytes(original_proof);manifest.write_bytes(original_manifest);seal.write_bytes(original_seal)
    route_rel='board/artifacts/ROUTE_VERIFICATION.json';q_rel='board/artifacts/QUALIFICATION.json'
    route=moved/route_rel;q=moved/q_rel;route0=route.read_bytes();q0=q.read_bytes()
    try:
        r=read(route);r['wns_ns']=-1;write(route,r)
        v=read(q);v['route_verification_sha256']=sha(route);write(q,v)
        reseal([route_rel,q_rel])
        run('08_failed_timing_with_fixture_reseal','launch_gui.py',['--check-only'],'Route/CDC/resource gate failed')
    finally:
        route.write_bytes(route0);q.write_bytes(q0);manifest.write_bytes(original_manifest);seal.write_bytes(original_seal)
    run('09_restored_copy','build_fpga.py',['--check-only'])
    local=moved/'configs/runtime.local.json'
    try:
        write(local,dict(data_root='_work/alternate_data',network=dict(board='192.0.2.2',bind='192.0.2.3',port=5001)))
        run('10_local_endpoint_and_data_configuration','probe_host.py',[])
        write(local,dict(data_root='src'))
        run('11_output_cannot_target_source','launch_gui.py',['--check-only'],'Data outputs must not overwrite packaged inputs')
        write(local,dict(strong_threshold=8))
        run('12_local_config_cannot_change_algorithm','launch_gui.py',['--check-only'],'Unknown local runtime configuration fields')
    finally:local.unlink(missing_ok=True)
    report=dict(status='RELOCATED_EXPORT_CHECKS_PASSED',cases=rows,all_passed=all(r['passed'] for r in rows),
                private_Git_database_required=False,hardware_contacted=False,original_release_modified=False,
                relocated_directory=str(moved),test_fixture_resealing_used_only_for_negative_gate_tests=True)
    write(out/'EXPORT_VERIFICATION.json',report)
    print(json.dumps(dict(status=report['status'],cases=len(rows),report=str(out/'EXPORT_VERIFICATION.json'))),flush=True)
if __name__=='__main__':main()
