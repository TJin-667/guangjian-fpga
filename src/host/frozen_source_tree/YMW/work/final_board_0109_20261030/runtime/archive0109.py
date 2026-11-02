"""Strict read-only import of existing0109 engineering archives, never hardware IO."""
from export_paths import legacy_location, data_path, lab_root, network
import hashlib,importlib.util,json,re,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
HOST=HERE.parent/'host'
QUALIFICATION=legacy_location('E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json')

def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise ValueError(message)

def load(root,*,allow_fixture=False,qualification=QUALIFICATION):
    root=Path(root).resolve()
    if not (root/'fpga_result.r32').is_file() and (root/'fusion/fpga_result.r32').is_file():root=root/'fusion'
    result=read(root/'RESULT.json');need(result['schema']=='0109-engineering-same-input-result-v1' and result['status']=='SAME_INPUT_EQUAL','Incomplete0109 result')
    physical=result.get('physical_hardware') is True and result.get('evidence_source')=='real_board'
    need(physical or allow_fixture,'SOFTWARE_FIXTURE_NOT_BOARD: no physical0109 evidence')
    sys.path.insert(0,str(HOST));from sdk_loader import load_sdk
    sdk=load_sdk(qualification=qualification if physical else None);wire=sdk.wire
    if physical:
        summary=read(root.parent/'SUMMARY.json');need(summary['status']=='ENGINEERING_SAME_INPUT_PASSED' and summary.get('cleanup',{}).get('acknowledged') is True,'Incomplete0109/OFF lifecycle')
    verify_profiles(result)
    need(len(result['frames'])==8 and not any(result['differences'].values()),'Eight matching engineering frames required')
    low,high=result['low_lines'],result['high_lines'];need(type(low) is int and type(high) is int and 1<=low<high<=1116,'Invalid frozen pair')
    roi=result['roi'];raw=(root/'fpga_result.r32').read_bytes();need(sha(root/'fpga_result.r32')==result['result_sha256'] and len(raw)==4*roi[2]*roi[3],'R32 content changed')
    gray=[];sat=[];board=None;records=[];identities=[];source_hashes={str(root/'fpga_result.r32'):sha(root/'fpga_result.r32'),str(root/'RESULT.json'):sha(root/'RESULT.json')}
    for slot,item in enumerate(result['frames'],1):
        record_path=Path(item['record']).resolve();need(item['slot']==slot and sha(record_path)==item['record_sha256'],'Frame record/slot changed');r=read(record_path)
        need(r['status']=='COMMITTED' and r['strict_verified'] is True and r['mode']=='strict' and r['firmware']==265,'Not a strict0109 frame')
        need(r['evidence_source']==result['evidence_source'],'Mixed physical/software evidence')
        files={}
        for name,digest in r['archived_file_sha256'].items():
            need(Path(name).name==name and '/' not in name and '\\' not in name,'Unsafe archive member')
            path=record_path.parent/name;need(sha(path)==digest,'Archived frame content changed');files[name]=path.read_bytes();source_hashes[str(path)]=digest
        meta=wire.decode_metadata(files['metadata_packet.bin'],r['metadata_query_seq']);params=meta['parameters']
        need(meta==r['diagnostic'] and meta['identity']==item['identity']==r['identity'] and meta['roi']==roi,'Frame metadata/ROI/identity changed')
        need(meta['valid'] and meta['mask_valid'] and meta['parameters_valid'] and not meta['error'],'Invalid committed metadata')
        need(params==r['actual_parameters'] and params['exposure_lines']==(low if slot%2 else high) and params['gain16']==16 and params['brightness']==128 and params['light_mask']==1<<((slot-1)//2),'Unexpected actual exposure/light')
        payload=files[r['raw_payload_file']];need(hashlib.sha256(payload).hexdigest()==r['raw_payload_sha256'] and len(payload)==meta['payload_bytes'] and wire.legacy.crc64_ecma(payload)==meta['payload_crc64'],'Frame payload CRC/length mismatch')
        g,s=wire.planes_from_payload(payload,roi[2],roi[3],meta['pixel_format'])
        mask=np.frombuffer(files['board_mask.bin'],np.uint8).reshape(roi[3],roi[2]);need(np.all(mask<=1) and mask.any(),'Invalid native mask');mask=mask.astype(bool)
        if board is None:board=mask
        need(np.array_equal(mask,board) and wire.recompute(g,s,board)==(meta['statistics'],meta['features']),'Per-frame native planes/H1/H2 differ')
        need(files['image.gray8']==g.tobytes() and files['image.sat1']==np.packbits(s.reshape(-1),bitorder='big').tobytes(),'Saved evidence differs')
        need(r['complete_packets']==r['expected_packets'] and r['cost']['missing_image_packets']==0,'Incomplete original capture')
        source_hashes[str(record_path)]=item['record_sha256'];gray.append(g);sat.append(s);records.append(r);identities.append(meta['identity'])
    need(len({i['session'] for i in identities})==1 and len({(i['session'],i['request_id'],i['frame_id']) for i in identities})==8,'Mixed session or repeated frame identity')
    sample=str(records[0].get('sample_id','sample'));sample=re.sub('[^A-Za-z0-9_-]','_',sample)[:64] or 'sample'
    return dict(root=root,group_id=f'{sample}_g{result["group"]}',sample=sample,roi=roi,
                gray=np.stack(gray),sat1=np.stack(sat),board=board,words=np.frombuffer(raw,dtype='<u4').reshape(roi[3],roi[2]),
                low=low,high=high,physical_hardware=physical,source_hashes=source_hashes,qualification=str(qualification) if physical else None,records=records)

def verify_profiles(result):
    sys.path.insert(0,str(HOST))
    from device_profiles import validate
    return validate(result)
