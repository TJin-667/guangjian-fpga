"""Reuse immutable native evidence only after a full audit or strict live SDK.

This is a local integrity cache, not a signature or a replacement for first-time
CRC/metadata/H1/H2 verification. Any changed file invalidates reuse and is refused.
"""
from export_paths import legacy_location, data_path, lab_root, network
import hashlib,json,os,re,shutil,sys,uuid
from pathlib import Path
import numpy as np
import archive0109 as archive

DEFAULT_CACHE=legacy_location('E:/GuangjianData/VerifiedNative0109')
SCHEMA='guangjian-verified-native0109-v2'

def binding():
    return {str(Path(__file__).resolve()):archive.sha(__file__),str(Path(archive.__file__).resolve()):archive.sha(archive.__file__)}
def normalized(root):
    root=Path(root).resolve()
    return root/'fusion' if not (root/'fpga_result.r32').is_file() and (root/'fusion/fpga_result.r32').is_file() else root
def cache_path(root,base=DEFAULT_CACHE):
    root=normalized(root);key=hashlib.sha256((str(root)+'\0'+archive.sha(root/'RESULT.json')+'\0'+json.dumps(binding(),sort_keys=True)).encode()).hexdigest()
    return Path(base)/key
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
def require_shapes(x):
    h,w=x['roi'][3],x['roi'][2]
    archive.need(x['gray'].dtype==np.uint8 and x['gray'].shape==(8,h,w),'Invalid cached gray')
    archive.need(x['sat1'].dtype==bool and x['sat1'].shape==(8,h,w),'Invalid cached SAT')
    archive.need(x['board'].dtype==bool and x['board'].shape==(h,w) and x['board'].any(),'Invalid cached board')
    archive.need(x['words'].dtype==np.dtype('uint32') and x['words'].shape==(h,w),'Invalid cached R32')

def seal(x,base=DEFAULT_CACHE,*,origin):
    require_shapes(x);target=cache_path(x['root'],base)
    archive.need(not target.resolve().is_relative_to(x['root'].resolve()) and not x['root'].resolve().is_relative_to(target.resolve()),'Evidence cache overlaps source')
    if target.exists():
        # Never overwrite an invalid receipt or an artifact that another run owns.
        restore(x['root'],base,allow_fixture=not x['physical_hardware']);return target
    hashes=dict(x['source_hashes'])
    if x['physical_hardware']:hashes[str(x['root'].parent/'SUMMARY.json')]=archive.sha(x['root'].parent/'SUMMARY.json')
    if x.get('qualification'):
        hashes[str(Path(x['qualification']).resolve())]=archive.sha(x['qualification'])
    # Pin executable SDK sources already recorded by the strict capture.
    for record in x['records']:
        for key in ('SDK_executable_source_sha256','loaded_protocol_source_sha256'):
            for name,digest in record.get(key,{}).items():
                archive.need(name not in hashes or hashes[name]==digest,'Conflicting SDK source');hashes[name]=digest
    archive.need(all(archive.sha(p)==v for p,v in hashes.items()),'Verified source changed before cache seal')
    temp=target.with_name(target.name+'.pending_'+uuid.uuid4().hex[:8]);temp.mkdir(parents=True,exist_ok=False)
    try:
        np.savez_compressed(temp/'native.npz',gray=x['gray'],sat1=x['sat1'],board=x['board'],words=x['words'])
        receipt=dict(schema=SCHEMA,status='SEALED',origin=origin,root=str(x['root']),group_id=x['group_id'],sample=x['sample'],low=x['low'],high=x['high'],roi=x['roi'],
                     physical_hardware=x['physical_hardware'],qualification=x.get('qualification'),records=x['records'],files_sha256=hashes,
                     native_sha256=archive.sha(temp/'native.npz'),loader_binding=binding(),first_audit_complete=True,
                     security_scope='local_integrity_receipt_not_cryptographic_attestation')
        write(temp/'CACHE.json',receipt);os.replace(temp,target)
    except BaseException:
        # Keep incomplete diagnostics. An incomplete directory is never a cache hit.
        raise
    return target

def restore(root,base=DEFAULT_CACHE,*,allow_fixture=False):
    root=normalized(root);target=cache_path(root,base);r=archive.read(target/'CACHE.json')
    archive.need(r['schema']==SCHEMA and r['status']=='SEALED' and r['first_audit_complete'] is True,'Unsealed evidence cache')
    archive.need(r['root']==str(root) and r['loader_binding']==binding(),'Evidence cache source/binding changed')
    source=archive.read(root/'RESULT.json');archive.verify_profiles(source)
    physical=source.get('physical_hardware') is True and source.get('evidence_source')=='real_board'
    archive.need(r['physical_hardware']==physical,'Cached evidence provenance differs from original result')
    archive.need(physical or allow_fixture,'SOFTWARE_FIXTURE_NOT_BOARD: cached fixture')
    archive.need(source['status']=='SAME_INPUT_EQUAL' and not any(source['differences'].values()) and len(source['frames'])==8 and r['roi']==source['roi'],'Cached group differs from original result')
    mandatory={str(root/'RESULT.json'):archive.sha(root/'RESULT.json'),str(root/'fpga_result.r32'):source['result_sha256']};records=[]
    if physical:mandatory[str(root.parent/'SUMMARY.json')]=archive.sha(root.parent/'SUMMARY.json')
    for slot,item in enumerate(source['frames'],1):
        p=Path(item['record']).resolve();record=archive.read(p)
        archive.need(item['slot']==slot and record['status']=='COMMITTED' and record['strict_verified'] is True and record['firmware']==265,'Cached frame contract differs')
        archive.need(record['evidence_source']==source['evidence_source'] and record['identity']==item['identity'],'Cached frame provenance differs')
        mandatory[str(p)]=item['record_sha256'];records.append(record)
        for name,digest in record['archived_file_sha256'].items():
            archive.need(Path(name).name==name and '/' not in name and '\\' not in name,'Unsafe cached source member')
            mandatory[str(p.parent/name)]=digest
        for key in ('SDK_executable_source_sha256','loaded_protocol_source_sha256'):
            mandatory.update(record.get(key,{}))
    archive.need(all(r['files_sha256'].get(p)==v for p,v in mandatory.items()),'Cache omitted or changed a mandatory verified source')
    archive.need(all(archive.sha(p)==v for p,v in r['files_sha256'].items()),'Verified evidence source changed; do not reuse')
    archive.need(archive.sha(target/'native.npz')==r['native_sha256'],'Verified native cache changed')
    if r['physical_hardware']:
        summary=archive.read(root.parent/'SUMMARY.json')
        archive.need(summary['status']=='ENGINEERING_SAME_INPUT_PASSED' and summary.get('cleanup',{}).get('acknowledged') is True,'Incomplete cached OFF lifecycle')
    with np.load(target/'native.npz',allow_pickle=False) as z:arrays={k:z[k].copy() for k in ('gray','sat1','board','words')}
    x=dict(root=root,group_id=r['group_id'],sample=r['sample'],low=source['low_lines'],high=source['high_lines'],roi=r['roi'],physical_hardware=r['physical_hardware'],qualification=r['qualification'],
           source_hashes={**r['files_sha256'],str(target/'CACHE.json'):archive.sha(target/'CACHE.json'),str(target/'native.npz'):r['native_sha256']},records=records,cache_receipt=str(target/'CACHE.json'),cache_receipt_sha256=archive.sha(target/'CACHE.json'),**arrays)
    require_shapes(x)
    # Bind the cached planes to the original archived planes too, even if a user
    # accidentally replaces both native.npz and its receipt digest together.
    archive.need(x['words'].tobytes()==(root/'fpga_result.r32').read_bytes(),'Cached R32 is not the original evidence')
    for i,item in enumerate(source['frames']):
        p=Path(item['record']).parent
        archive.need(x['gray'][i].tobytes()==(p/'image.gray8').read_bytes() and np.packbits(x['sat1'][i].reshape(-1),bitorder='big').tobytes()==(p/'image.sat1').read_bytes(),'Cached planes are not the original evidence')
        archive.need(x['board'].astype(np.uint8).tobytes()==(p/'board_mask.bin').read_bytes(),'Cached board is not the original evidence')
    expected_sample=re.sub('[^A-Za-z0-9_-]','_',str(records[0].get('sample_id','sample')))[:64] or 'sample'
    archive.need(x['sample']==expected_sample and x['group_id']==f'{expected_sample}_g{source["group"]}','Cached sample/group identity differs')
    return x

def load(root,*,mode='reuse',base=DEFAULT_CACHE,allow_fixture=False,qualification=archive.QUALIFICATION):
    archive.need(mode in ('audit','reuse'),'Unknown evidence validation mode')
    if mode=='reuse' and cache_path(root,base).exists():return restore(root,base,allow_fixture=allow_fixture),'VERIFIED_HASH_REUSE'
    x=archive.load(root,allow_fixture=allow_fixture,qualification=qualification)
    if mode=='reuse':
        try:seal(x,base,origin='full_archive_CRC_metadata_H1_H2_audit')
        except OSError as exc:
            # Optional cache storage failure must not break a completed full audit.
            # Existing malformed/tampered receipts still fail in restore above.
            x['cache_unavailable_reason']=str(exc);return x,'FULL_STRICT_AUDIT_CACHE_UNAVAILABLE'
    return x,'FULL_STRICT_AUDIT'

def seal_live(executor,qualification=archive.QUALIFICATION,base=DEFAULT_CACHE):
    """Use already-verified SDK return objects; no duplicate CRC/H2 computation."""
    root=normalized(executor._off_output);result=archive.read(root/'RESULT.json');rows=executor._off_rows
    archive.need(result['status']=='SAME_INPUT_EQUAL' and not any(result['differences'].values()) and len(rows)==8,'No complete same-input live audit')
    archive.verify_profiles(result)
    gray=[];sat=[];records=[];hashes={str(root/'RESULT.json'):archive.sha(root/'RESULT.json'),str(root/'fpga_result.r32'):archive.sha(root/'fpga_result.r32')}
    archive.need(hashes[str(root/'fpga_result.r32')]==result['result_sha256'],'Live R32 changed')
    for slot,(row,item) in enumerate(zip(rows,result['frames']),1):
        cap=row['capture'];p=Path(cap.record_path).resolve();r=archive.read(p);v=cap.validated
        archive.need(item['slot']==slot and item['record']==str(p) and archive.sha(p)==item['record_sha256'],'Live record identity changed')
        archive.need(r['strict_verified'] is True and r['status']=='COMMITTED' and r['firmware']==265,'Live SDK frame not strict0109')
        archive.need(v['metadata']==r['diagnostic'] and v['metadata']['identity']==item['identity'],'SDK validated metadata differs')
        archive.need(r['actual_parameters']['exposure_lines']==(result['low_lines'] if slot%2 else result['high_lines']) and r['actual_parameters']['gain16']==16 and r['actual_parameters']['brightness']==128 and r['actual_parameters']['light_mask']==1<<((slot-1)//2),'Live parameters changed')
        archive.need(r['evidence_source']==result['evidence_source'] and r['roi']==result['roi'],'Live source/ROI changed')
        for name,digest in r['archived_file_sha256'].items():
            archive.need(Path(name).name==name and '/' not in name and '\\' not in name,'Unsafe live archive member')
            path=p.parent/name;archive.need(archive.sha(path)==digest,'Live source bytes changed');hashes[str(path)]=digest
        archive.need(archive.sha(p.parent/r['raw_payload_file'])==r['raw_payload_sha256']==hashlib.sha256(v['payload']).hexdigest(),'Live payload differs from strict SDK')
        archive.need((p.parent/'image.gray8').read_bytes()==v['gray'].tobytes() and (p.parent/'image.sat1').read_bytes()==np.packbits(v['sat'].reshape(-1),bitorder='big').tobytes(),'Live native planes differ')
        archive.need((p.parent/'board_mask.bin').read_bytes()==executor._off_board.astype(np.uint8).tobytes(),'Live native board differs')
        archive.need(r['complete_packets']==r['expected_packets'] and r['cost']['missing_image_packets']==0,'Incomplete live frame')
        hashes[str(p)]=item['record_sha256'];gray.append(v['gray']);sat.append(v['sat'].astype(bool));records.append(r)
    identities=[r['identity'] for r in records]
    archive.need(len({i['session'] for i in identities})==1 and len({(i['session'],i['request_id'],i['frame_id']) for i in identities})==8,'Repeated live identity')
    sample=re.sub('[^A-Za-z0-9_-]','_',str(records[0].get('sample_id','sample')))[:64] or 'sample';roi=result['roi']
    x=dict(root=root,group_id=f'{sample}_g{result["group"]}',sample=sample,low=result['low_lines'],high=result['high_lines'],roi=roi,gray=np.stack(gray),sat1=np.stack(sat),board=executor._off_board.copy(),
           words=np.frombuffer((root/'fpga_result.r32').read_bytes(),dtype='<u4').reshape(roi[3],roi[2]),physical_hardware=result['physical_hardware'],
           qualification=str(qualification) if result['physical_hardware'] else None,records=records,source_hashes=hashes)
    return seal(x,base,origin='strict_live_SDK_CRC_metadata_H1_H2_and_engineering_same_input_audit')
