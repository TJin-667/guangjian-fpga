"""Self-contained engineering qualification for the explicit public export.

Preserves the original commit/source/bit/route checks using package hashes and
Git Merkle proofs; no private Git database or machine installation is required.
"""
import hashlib,json,re
from pathlib import Path
from export_paths import SOURCE_ROOT,artifact
from export_guard import verify,manifest,upstream_blob_id,git_hash,need,matches_origin,inside
ROOT=Path(__file__).resolve().parents[1]
REPO=SOURCE_ROOT
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
require=need
def validate(path):
    m=verify();path=Path(path).resolve();record=json.loads(path.read_text(encoding='utf-8-sig'))
    require(record.get('schema')=='guangjian-0109-engineering-candidate-v1' and record.get('engineering_capture_ready') is True,'0109 engineering qualification missing')
    commit=record.get('candidate_source_commit','')
    require(commit=='0711fa1793845c225c8968300864c777d7e1659f','Unexpected original candidate commit')
    binding=ROOT/'SOURCE_BINDING.json'
    require(sha(binding)==record.get('bundle_sha256'),'Original candidate bundle changed')
    require(git_hash('blob',binding.read_bytes())==upstream_blob_id(commit,'YMW/work/final_board_0109_20261030/SOURCE_BINDING.json'),'Original bundle not in pinned source commit')
    members=json.loads(binding.read_bytes())['files_sha256']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p!=binding and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.jou','.dcp','.bit')}
    require(actual==set(members),'Unbound or missing qualified source members')
    files={}
    for name,digest in members.items():
        p=ROOT/name
        require(matches_origin(p,digest),'Qualified export source differs: '+name)
        relative=p.resolve().relative_to(inside('src/host/frozen_source_tree')).as_posix()
        original=m['files'][p.resolve().relative_to(inside('.')).as_posix()]
        oid=original.get('upstream_git_blob')
        require(oid==upstream_blob_id(commit,relative),'Qualified source not in original commit: '+name)
        files[str(p)]=sha(p)
    parent='ef02414acc1d5f55561de2ce1af1bd5e61ffc53f'
    kernel=ROOT.parent/'fusion_offload_0108_20261028';kb=kernel/'SOURCE_BINDING.json'
    require(git_hash('blob',kb.read_bytes())==upstream_blob_id(parent,'YMW/work/fusion_offload_0108_20261028/SOURCE_BINDING.json'),'Phase1 binding changed')
    for name,digest in json.loads(kb.read_bytes())['files_sha256'].items():
        p=kernel/name;require(matches_origin(p,digest),'Phase1 source changed: '+name);files[str(p)]=sha(p)
    app=ROOT.parent/'b1_detection_console_20261027'
    for name in ('common.py','VENDOR_BINDING.json'):
        p=app/name;row=m['files'][p.resolve().relative_to(inside('.')).as_posix()]
        require(row['upstream_git_blob']==upstream_blob_id(parent,'YMW/work/b1_detection_console_20261027/'+name),'Original algorithm binding changed')
        files[str(p)]=sha(p)
    from export_paths import vendor_root
    vendor=json.loads((app/'VENDOR_BINDING.json').read_bytes())
    for name,digest in vendor['files_sha256'].items():
        p=vendor_root()/name;require(sha(p)==digest,'Frozen vendor source changed: '+name);files[str(p)]=digest
    record=dict(record)
    for key in ('bit','bit_build_receipt','route_verification'):
        p=artifact(key);require(p.is_file() and sha(p)==record.get(key+'_sha256'),key+' missing/changed')
        record[key+'_path']=str(p.resolve());files[str(p)]=sha(p)
    receipt=json.loads(artifact('bit_build_receipt').read_bytes());route=json.loads(artifact('route_verification').read_bytes())
    require(receipt.get('schema')=='guangjian-bit-from-qualified-checkpoint-v1' and receipt.get('source_commit')==commit and receipt.get('write_bitstream_succeeded') is True and receipt.get('bit_sha256')==record['bit_sha256'],'Bit provenance is not qualified')
    require(route.get('schema')=='guangjian-0109-route-verification-v1' and route.get('resource_and_internal_timing_gate_passed') is True,'Actual route qualification missing')
    require(route.get('wns_ns',-1)>=0 and route.get('whs_ns',-1)>=0 and route.get('BRAM36_equivalent',999)<=108 and route.get('blackboxes',1)==0 and route.get('route_errors',1)==0 and route.get('unexpected_new_mailbox_endpoints',1)==0 and route.get('blocking_DRC',1)==0,'Route/CDC/resource gate failed')
    require(route.get('unconstrained_internal_endpoints',1)==0 and route.get('missing_register_clocks',1)==0 and route.get('combinational_loops',1)==0 and route.get('all_twelve_data_bundle_paths_meet_bounds') is True,'Internal coverage/data bounds failed')
    require(route.get('bus_skew_constraints')==17 and route.get('all_bus_skew_constraints_pass') is True and route.get('minimum_bus_skew_slack_ns',-1)>=0,'Bus-skew qualification failed')
    require(receipt.get('input_checkpoint_sha256')==route.get('checkpoint_sha256')==record.get('checkpoint_sha256'),'Bit/checkpoint provenance differs')
    require(record.get('release_ready') is False,'Engineering status must not become a production claim')
    files[str(path)]=sha(path);files[str(binding)]=sha(binding)
    record['submission_export']='v1.0.0-rc.1; portability-only source derivatives explicitly identified'
    return record,files
