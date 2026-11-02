"""Validate engineering bit/checkpoint/source binding before opening a socket."""
import hashlib,json,re,subprocess
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[2]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)
def validate(path):
    path=Path(path).resolve();record=json.loads(path.read_text('utf-8'))
    require(record.get('schema')=='guangjian-0109-engineering-candidate-v1' and record.get('engineering_capture_ready') is True,'0109 engineering qualification missing')
    commit=record.get('candidate_source_commit','');require(re.fullmatch('[0-9a-f]{40}',commit) is not None,'Actual candidate Git commit required')
    binding=ROOT/'SOURCE_BINDING.json';require(sha(binding)==record.get('bundle_sha256'),'Candidate source bundle changed')
    blob=subprocess.check_output(['git','show',commit+':'+binding.relative_to(REPO).as_posix()],cwd=REPO)
    require(blob==binding.read_bytes(),'Bundle is not from the pinned Git commit')
    members=json.loads(blob)['files_sha256']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p!=binding and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.jou','.dcp','.bit')}
    require(actual==set(members),'Unbound or missing candidate files')
    tree=subprocess.check_output(['git','ls-tree','-r','-z',commit,'--',ROOT.relative_to(REPO).as_posix()],cwd=REPO)
    git_blobs={}
    for entry in tree.split(b'\0'):
        if entry:
            metadata,name=entry.split(b'\t',1);git_blobs[name.decode('utf-8')]=metadata.split()[2].decode('ascii')
    for name,digest in members.items():
        relative=PurePosixPath(name);target=(ROOT/name).resolve()
        require(not relative.is_absolute() and '..' not in relative.parts and target.is_relative_to(ROOT),'Invalid bundle member')
        require(target.is_file() and sha(target)==digest,'Changed candidate member '+name)
        data=target.read_bytes();oid=hashlib.sha1(b'blob '+str(len(data)).encode('ascii')+b'\0'+data).hexdigest()
        require(git_blobs.get(target.relative_to(REPO).as_posix())==oid,'Candidate member was not committed '+name)
    files={}
    # Lock the immutable mathematical decoder and the exact PC quality/H2
    # reference too; those live outside this new independent candidate folder.
    parent='ef02414acc1d5f55561de2ce1af1bd5e61ffc53f';kernel=ROOT.parent/'fusion_offload_0108_20261028'
    kernel_binding=kernel/'SOURCE_BINDING.json'
    require(subprocess.check_output(['git','show',parent+':'+kernel_binding.relative_to(REPO).as_posix()],cwd=REPO)==kernel_binding.read_bytes(),'Phase1 source binding changed')
    for name,digest in json.loads(kernel_binding.read_text('utf-8'))['files_sha256'].items():
        member=kernel/name;require(sha(member)==digest,'Phase1 mathematical source changed '+name);files[str(member)]=digest
    app=ROOT.parent/'b1_detection_console_20261027'
    for name in ('common.py','VENDOR_BINDING.json'):
        member=app/name;require(subprocess.check_output(['git','show',parent+':'+member.relative_to(REPO).as_posix()],cwd=REPO)==member.read_bytes(),'Frozen algorithm binding changed '+name);files[str(member)]=sha(member)
    vendor=json.loads((app/'VENDOR_BINDING.json').read_text('utf-8'));vendor_root=Path(vendor['installed_path']).resolve()
    for name,digest in vendor['files_sha256'].items():
        member=vendor_root/name;require(sha(member)==digest,'Frozen algorithm changed '+name);files[str(member)]=digest
    for key in ('bit','bit_build_receipt','route_verification'):
        member=Path(record.get(key+'_path','')).resolve();require(member.is_file() and sha(member)==record.get(key+'_sha256'),key+' missing/changed')
        files[str(member)]=sha(member)
    receipt=json.loads(Path(record['bit_build_receipt_path']).read_text('utf-8'))
    require(receipt.get('schema')=='guangjian-bit-from-qualified-checkpoint-v1' and receipt.get('source_commit')==commit and receipt.get('write_bitstream_succeeded') is True and receipt.get('bit_sha256')==record['bit_sha256'],'Bit provenance is not qualified')
    route=json.loads(Path(record['route_verification_path']).read_text('utf-8'))
    require(route.get('schema')=='guangjian-0109-route-verification-v1' and route.get('resource_and_internal_timing_gate_passed') is True,'Actual routed qualification missing')
    require(route.get('wns_ns',-1)>=0 and route.get('whs_ns',-1)>=0 and route.get('BRAM36_equivalent',999)<=108 and route.get('blackboxes',1)==0 and route.get('route_errors',1)==0 and route.get('unexpected_new_mailbox_endpoints',1)==0 and route.get('blocking_DRC',1)==0,'Route/CDC/resource gate failed')
    require(route.get('unconstrained_internal_endpoints',1)==0 and route.get('missing_register_clocks',1)==0 and route.get('combinational_loops',1)==0 and route.get('all_twelve_data_bundle_paths_meet_bounds') is True,'Internal timing coverage or data-bundle bounds failed')
    require(route.get('bus_skew_constraints')==17 and route.get('all_bus_skew_constraints_pass') is True and route.get('minimum_bus_skew_slack_ns',-1)>=0,'Bus-skew qualification failed')
    require(receipt.get('input_checkpoint_sha256')==route.get('checkpoint_sha256')==record.get('checkpoint_sha256'),'Bit is not from the same reviewed routed checkpoint')
    require(record.get('release_ready') is False,'Engineering entry requires an explicit engineering status, not a production claim')
    files[str(path)]=sha(path);files[str(binding)]=sha(binding)
    return record,files
