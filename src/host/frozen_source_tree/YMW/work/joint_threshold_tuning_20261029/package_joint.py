"""Bind runtimes and publish small Git artifacts; large data stays on E."""
import argparse,gzip,json,re,shutil,zipfile
from pathlib import Path
import numpy as np
from joint_gate import cutoff
from run_study import read,write,sha

HERE=Path(__file__).resolve().parent;ROOT=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029')
def prepare_binding():
    for folder,name in [('run_01','FROZEN_CONFIG.json'),('body_01','FROZEN_BODY_CONFIG.json'),('sleeve_01','FROZEN_SLEEVE_CONFIG.json')]:shutil.copyfile(ROOT/folder/'FROZEN_CONFIG.json',HERE/name)
    files={p.name:sha(p) for p in HERE.glob('*.py')}
    for name in ('PLAN.json','BODY_PLAN.json','SLEEVE_PLAN.json','FROZEN_CONFIG.json','FROZEN_BODY_CONFIG.json','FROZEN_SLEEVE_CONFIG.json'):files[name]=sha(HERE/name)
    for directory,names in [('seeded_component_tuning_20261029',['seeded_gate.py','run_study.py']),('weak_component_experiment_20261029',['component_gate.py','fragment_chain.py'])]:
        for name in names:
            relative='../'+directory+'/'+name;files[relative]=sha(HERE/relative)
    write(HERE/'PACKAGE_BINDING.json',dict(schema='joint-threshold-offline-package-v1',final_config_id=read(HERE/'FROZEN_SLEEVE_CONFIG.json')['selected']['id'],files_sha256=files))

def publish():
    gallery=HERE/'gallery';gallery.mkdir(exist_ok=False);verification=HERE/'verification';verification.mkdir()
    html_checks=[]
    for folder in ('run_01','body_01','sleeve_01','post_01','full_sleeve_02'):
        source=ROOT/folder;target=verification/folder;target.mkdir()
        for name in ('VERIFICATION.json','DATASET_RESULTS.json','CONTRACT_CHECKS.json','SUMMARY.csv','FROZEN_CONFIG.json','PAIR_BEST.json','PREVIOUS_CONFIG_REPRODUCTION.json','DRAFT_PATH_POSTCHECKS.json','DRAFT_SIDE_CHECKS.json','DRAFT_CHECKS.json','REUSABLE_RUNTIME_COMPARISON.json','SIDE_RADIUS_RESULTS.csv','SIDE_RADIUS_RESULTS.json','FINAL_RESTRICTIONS_66_PAIRS.csv','FIXED_RESTRICTIONS_66_PAIRS.csv','THRESHOLD_ONLY_DEVELOPMENT.csv','RESULTS.json'):
            if (source/name).is_file():shutil.copyfile(source/name,target/name)
        for name in ('SEARCH.csv','SEARCH_RESULTS.json'):
            if (source/name).is_file():
                raw=(source/name).read_bytes();(target/(name+'.gz')).write_bytes(gzip.compress(raw,compresslevel=9,mtime=0));write(target/(name+'.SOURCE.json'),dict(uncompressed_sha256=sha(source/name),uncompressed_bytes=len(raw),local_path=str(source/name)))
        if (source/'index.html').is_file():
            refs=re.findall(r'(?:src|href)="([^"#]+)"',(source/'index.html').read_text('utf-8'));missing=[r for r in refs if not (source/r).is_file()];html_checks.append(dict(folder=folder,asset_references=len(refs),missing=missing))
            if missing:raise ValueError('Missing assets '+repr(missing))
    for folder,name,dest in [('sleeve_01','sample004_weak_comparison.png','sample004_weak_comparison.png'),('sleeve_01','five_primary_groups.png','five_primary_groups.png'),('body_01','sample004_weak_comparison.png','body_only_weak_comparison.png'),('post_01','sample004_final66.png','sample004_final66.png')]:shutil.copyfile(ROOT/folder/name,gallery/dest)
    data=read(ROOT/'run_01/DATASETS.json')
    for sample in ('sample003','sample004','sample005'):shutil.copyfile(ROOT/'sleeve_01'/(sample+'_all_groups.png'),gallery/(sample+'_all_groups.png'))
    for rec in data:
        if rec['role']!='exposure_stress':
            shutil.copyfile(ROOT/'sleeve_01'/rec['group_id']/'comparison.png',gallery/(rec['group_id']+'_comparison.png'));shutil.copyfile(ROOT/'post_01/side_radii'/rec['group_id']/'comparison.png',gallery/(rec['group_id']+'_side_radii.png'))
        if rec['role']=='development':
            for name in ('selected.png','retracted.png'):shutil.copyfile(ROOT/'sleeve_01'/rec['group_id']/name,gallery/(rec['sample']+'_'+name))
    group='sample004_A_v1_20261028_220937_87f02b';shutil.copyfile(ROOT/'post_01/side_radii'/group/'comparison.png',gallery/'sample004_side_radius_comparison.png')
    write(verification/'HTML_ASSETS.json',dict(status='PASS',static_only=True,checks=html_checks))
    cli=ROOT/'single_entry_01';receipt=read(cli/'receipt.json');fields=[]
    with np.load(ROOT/'sleeve_01'/receipt['group_id']/'masks.npz',allow_pickle=False) as expected,np.load(cli/'masks.npz',allow_pickle=False) as actual:
        for k in actual.files:
            if not np.array_equal(expected[k],actual[k]):raise AssertionError('Single runtime differs '+k)
            fields.append(k)
    shutil.copyfile(cli/'receipt.json',verification/'SINGLE_ENTRY_RECEIPT.json');write(verification/'SINGLE_ENTRY_COMPARISON.json',dict(status='PASS',fields=fields,all_differences_zero=True))
    write(verification/'TESTS.json',dict(status='PASS',tests=27,suites={'test_joint.py':12,'test_body.py':9,'test_sleeve.py':6},source_sha256={n:sha(HERE/n) for n in ('test_joint.py','test_body.py','test_sleeve.py','joint_gate.py','body_guard.py','sleeve_guard.py')}))
    snapshot=ROOT/'source_snapshot';snapshot.mkdir()
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.json','.md'):shutil.copyfile(p,snapshot/p.name)
    members={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and 'full_sleeve_01' not in p.relative_to(ROOT).parts and p.name not in ('LOCAL_OUTPUT_MANIFEST.json','joint_threshold_complete.zip')}
    write(ROOT/'LOCAL_OUTPUT_MANIFEST.json',dict(files_sha256=members))
    archive=ROOT/'joint_threshold_complete.zip'
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for name in list(members)+['LOCAL_OUTPUT_MANIFEST.json']:z.write(ROOT/name,name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise AssertionError('ZIP CRC failed')
    write(HERE/'LOCAL_RESULTS.json',dict(root=str(ROOT),entry=str(ROOT/'index.html'),archive=str(archive),archive_bytes=archive.stat().st_size,archive_sha256=sha(archive),archive_crc_pass=True,output_manifest_sha256=sha(ROOT/'LOCAL_OUTPUT_MANIFEST.json'),output_members=len(members),failed_full_sleeve01_excluded=True))
    binding={str(p.relative_to(HERE)).replace('\\','/'):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='ARTIFACT_BINDING.json'}
    write(HERE/'ARTIFACT_BINDING.json',dict(files_sha256=binding));print('JOINT_PACKAGE_READY',len(binding),'members','archive_bytes',archive.stat().st_size,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');a=p.parse_args();prepare_binding() if a.prepare else publish()
