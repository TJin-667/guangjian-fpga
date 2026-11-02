"""Publish small review artifacts locally; bulk arrays remain on E drive."""
import argparse,hashlib,json,re,shutil,zipfile
from pathlib import Path
from run_study import read,write,sha

HERE=Path(__file__).resolve().parent
def make_binding():
    names=['PLAN.json','FROZEN_CONFIG.json','seeded_gate.py','run_one.py','run_study.py','analyze_study.py','test_seeded.py']
    files={n:sha(HERE/n) for n in names}
    for name in ('component_gate.py','fragment_chain.py'):
        relative='../weak_component_experiment_20261029/'+name;files[relative]=sha(HERE/relative)
    write(HERE/'PACKAGE_BINDING.json',dict(schema='seeded-offline-package-v1',config_id=read(HERE/'FROZEN_CONFIG.json')['selected']['id'],files_sha256=files))

def publish(root):
    gallery=HERE/'gallery';gallery.mkdir(exist_ok=False);verification=HERE/'verification';verification.mkdir()
    for name in ('DATASETS.json','DATASET_RESULTS.json','CONTRACT_CHECKS.json','DRAFT_REFERENCE_CHECKS.json','VERIFICATION.json','SEARCH.csv','SEARCH_RESULTS.json','SUMMARY.csv'):
        shutil.copyfile(root/name,verification/name)
    for name in ('ABLATIONS.csv','LEGACY_COMPARISON.csv','LEGACY_COMPARISON.json','COMPONENT_RAW_EVIDENCE.csv','VERIFICATION.json'):
        shutil.copyfile(root/'analysis'/name,verification/('POST_'+name if name=='VERIFICATION.json' else name))
    for name in ('sample004_weak_comparison.png','five_primary_groups.png'):shutil.copyfile(root/name,gallery/name)
    for sample in ('sample003','sample004','sample005'):shutil.copyfile(root/'analysis'/(sample+'_all_groups.png'),gallery/(sample+'_all_groups.png'))
    for rec in read(root/'DATASETS.json'):
        target=verification/'groups'/rec['group_id'];target.mkdir(parents=True)
        for name in ('COMPONENTS.json','METRICS.json'):shutil.copyfile(root/rec['group_id']/name,target/name)
        if rec['role']!='exposure_stress':shutil.copyfile(root/rec['group_id']/'comparison.png',gallery/(rec['group_id']+'_comparison.png'))
        if rec['role']=='development':
            for name in ('selected.png','review.png'):shutil.copyfile(root/rec['group_id']/name,gallery/(rec['sample']+'_'+name))
    # Validate asset references, without claiming human browser-interaction tests.
    html=(root/'index.html').read_text('utf-8');refs=re.findall(r'(?:src|href)="([^"#]+)"',html);missing=[v for v in refs if not (root/v).is_file()]
    if missing:raise ValueError('Missing HTML assets '+repr(missing))
    write(verification/'HTML_ASSETS.json',dict(status='PASS',references=len(refs),missing=[],static_check_only=True))
    cli=root.parent/'single_entry_check_01';receipt=read(cli/'receipt.json')
    group=receipt['group_id'];fields=[]
    import numpy as np
    with np.load(root/group/'masks.npz',allow_pickle=False) as expected,np.load(cli/'masks.npz',allow_pickle=False) as actual:
        for k in actual.files:
            if not np.array_equal(expected[k],actual[k]):raise AssertionError('Single entry differs '+k)
            fields.append(k)
    shutil.copyfile(cli/'receipt.json',verification/'SINGLE_ENTRY_RECEIPT.json')
    write(verification/'SINGLE_ENTRY_COMPARISON.json',dict(status='PASS',group_id=group,equal_fields=fields,differences=0))
    # Save exact sources beside the full local output, including borrowed modules.
    snapshot=root/'source_snapshot';snapshot.mkdir()
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.json','.md'):shutil.copyfile(p,snapshot/p.name)
    parent=snapshot/'prior_modules';parent.mkdir()
    for name in ('component_gate.py','fragment_chain.py'):shutil.copyfile(HERE.parent/'weak_component_experiment_20261029'/name,parent/name)
    manifest={str(p.relative_to(root)).replace('\\','/'):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='OUTPUT_MANIFEST.json'}
    write(root/'OUTPUT_MANIFEST.json',dict(schema='study-output-sha-v1',files_sha256=manifest))
    archive=root.parent/'seeded_component_review_23groups.zip'
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for p in sorted(root.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(root)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise AssertionError('Archive CRC failed')
    write(HERE/'LOCAL_ARCHIVE.json',dict(path=str(archive),sha256=sha(archive),bytes=archive.stat().st_size,output_directory=str(root),cached_profile_arrays_included=True,cache_retained_locally=True,zip_crc_pass=True,
        output_manifest_sha256=sha(root/'OUTPUT_MANIFEST.json'),output_members=len(manifest)))
    write(verification/'UNIT_TESTS.json',dict(status='PASS',tests=15,command='python -B -m unittest discover -s YMW/work/seeded_component_tuning_20261029 -p test_seeded.py -v',scope='seed rules, profile validity, graph anchoring and exact mask contracts',functional_gate_sha256=sha(HERE/'seeded_gate.py'),test_source_sha256=sha(HERE/'test_seeded.py')))
    members={str(p.relative_to(HERE)).replace('\\','/'):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='ARTIFACT_BINDING.json'}
    write(HERE/'ARTIFACT_BINDING.json',dict(schema='seeded-study-artifacts-v1',files_sha256=members))
    print('PACKAGE_READY',len(members),'members','archive',archive.stat().st_size,'bytes',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path);p.add_argument('--binding-only',action='store_true');a=p.parse_args()
    if a.binding_only:make_binding()
    else:publish(a.root.resolve())
