"""Offline SDK -> portable gray/SAT input bridge. No capture or release override."""
import argparse,contextlib,hashlib,io,json,math,os,tempfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath

import cv2
import numpy as np
import fixed_eight
import host_transport as wire
import review_engineering_capture as audit
import xdl_reference

def require(ok,message):
    if not ok:raise ValueError(message)
def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def encoded(obj):return (json.dumps(obj,indent=2,allow_nan=False)+'\n').encode()
def inside(root,name):
    require(isinstance(name,str) and '\\' not in name and ':' not in name,'Nonportable artifact path')
    parts=PurePosixPath(name)
    require(not parts.is_absolute() and '..' not in parts.parts and parts.parts,'Unsafe artifact path')
    root=Path(root).resolve();p=(root/str(parts)).resolve()
    require(p.is_relative_to(root),'Artifact escapes root');return p
def npy_bytes(array):
    stream=io.BytesIO();np.save(stream,array,allow_pickle=False);return stream.getvalue()

@dataclass
class Frame:
    record:dict
    metadata:dict
    payload:bytes
    gray:np.ndarray
    sat:np.ndarray
    mask:np.ndarray
    files:dict
    sensor_size:tuple

    def validated(self):
        return dict(metadata=self.metadata,metadata_packet=self.files['metadata_packet.bin'],payload=self.payload,
            payload_sha256=digest(self.payload),gray=self.gray,sat=self.sat,
            board_mask_sha256=digest(self.mask.astype(np.uint8).tobytes()))

def load_commit(record_path,*,sensor_size=(1920,1080)):
    record_path=Path(record_path).resolve();folder=record_path.parent
    record_bytes=record_path.read_bytes();r=json.loads(record_bytes)
    require(r['status']=='COMMITTED' and r['strict_verified'] is True and r['mode']=='strict','Not a strict committed SDK frame')
    require(r['firmware']==262 and r['evidence_source'] in ('real_board','software_udp_peer'),'Unsupported firmware/evidence')
    sensor_size=tuple(sensor_size)
    require(len(sensor_size)==2 and all(type(v) is int and v>0 for v in sensor_size),'Sensor dimensions')
    if r['evidence_source']=='real_board':require(sensor_size==(1920,1080),'Real board sensor dimensions changed')
    files={}
    for name,sha in r['archived_file_sha256'].items():
        require(Path(name).name==name and '/' not in name and '\\' not in name,'Unsafe SDK artifact name')
        data=inside(folder,name).read_bytes();require(digest(data)==sha,'SDK artifact SHA mismatch: '+name);files[name]=data
    m=wire.decode_metadata(files['metadata_packet.bin'],r['metadata_query_seq'])
    require(m==r['diagnostic'] and m['identity']==r['identity'] and m['bank']==r['bank'],'Metadata object/identity differs')
    require(m['valid'] and m['mask_valid'] and m['parameters_valid'] and m['logical_association_available'] and not m['error'],'Invalid final metadata')
    require(r['session']==m['identity']['session'] and r['expected_request_id']==m['identity']['request_id'] and
        r['wire_frame_id']==m['identity']['frame_id'],'SDK request identity differs')
    require(m['parameters']==r['actual_parameters'] and all(r['requested'][k]==v for k,v in m['parameters'].items()) and
        m['roi']==r['requested']['roi'],'Requested parameters/ROI differ')
    require(m['fifo_reads']==math.prod(sensor_size),'Incomplete full-frame DDR drain')
    require(m['wait_complete_frames']>=m['parameters']['settle_frames'] and
        m['discard_complete_frames']>=m['parameters']['discard_frames'],'Incomplete wait/discard policy')
    fmt=m['pixel_format'];name='image.rgb565' if fmt==1 else 'image.gray_sat'
    require(r['pixel_format']==fmt and r['raw_payload_file']==name,'Raw format/name differs')
    payload=files[name];x,y,w,h=m['roi']
    require(min(w,h)>=9 and x>=0 and y>=0 and x+w<=sensor_size[0] and y+h<=sensor_size[1],'ROI exceeds saved domain')
    require(len(payload)==m['payload_bytes']==wire.payload_size(w,h,fmt) and
        digest(payload)==r['raw_payload_sha256'] and audit.crc64(payload)==m['payload_crc64'],'Raw CRC/size/SHA differs')
    gray,sat=audit.planes(payload,w,h,fmt)
    maskraw=files['board_mask.bin']
    require(len(maskraw)==w*h and set(maskraw)<={0,1} and any(maskraw),'Nonbinary/empty mask')
    mask=np.frombuffer(maskraw,np.uint8).reshape(h,w).astype(bool)
    require(digest(maskraw)==r['mask_sha256'],'Mask source differs')
    require(audit.h1_h2(gray,sat,mask)==(m['statistics'],m['features']),'H1/H2 differs from raw planes')
    require(files['image.gray8']==gray.tobytes() and files['image.sat1']==np.packbits(sat.reshape(-1),bitorder='big').tobytes(),'Saved gray/SAT differs from wire')
    png=files['image.gray.png']
    require(png[:8]==b'\x89PNG\r\n\x1a\n' and int.from_bytes(png[16:20],'big')==w and int.from_bytes(png[20:24],'big')==h,'Gray PNG dimensions differ')
    image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_UNCHANGED)
    require(image is not None and image.dtype==np.uint8 and np.array_equal(image,gray),'Gray PNG differs from wire')
    require(r['complete_packets']==r['expected_packets']==math.ceil(len(payload)/1380),'Incomplete packet count')
    require(r['cost']['capture_requests']==1 and r['cost']['saved_images']==1 and r['cost']['missing_image_packets']==0,'Incomplete capture cost/result')
    require(record_path.read_bytes()==record_bytes,'SDK record changed during read')
    files['result.json']=record_bytes
    return Frame(r,m,payload,gray,sat,mask,files,sensor_size)

def frame_manifest(frame,files):
    m=frame.metadata;tag=m['identity'];prov=xdl_reference.load('provenance')
    fields=dict(session_id=str(tag['session']),frame_id=tag['frame_id'],
        hardware_identity={**{k:tag[k] for k in prov.HARDWARE_ID_FIELDS if k!='bank'},'bank':m['bank']},
        roi_xywh=list(m['roi']),source_path='capture/image.gray.png',source_sha256=digest(files['capture/image.gray.png']),
        gray8_path='planes/gray8.npy',gray8_sha256=digest(files['planes/gray8.npy']),
        sat1_path='planes/sat1.npy',sat1_sha256=digest(files['planes/sat1.npy']),
        valid_mask_path='planes/valid_mask.npy',valid_mask_sha256=digest(files['planes/valid_mask.npy']))
    fields['frame_payload_sha256']=prov.gray_sat_payload_sha256(fields['session_id'],fields['frame_id'],
        fields['hardware_identity'],fields['source_sha256'],fields['roi_xywh'],frame.gray,frame.sat)
    return dict(schema='guangjian-0106-portable-frame-v1',source_evidence=frame.record['evidence_source'],
        capture_record='capture/result.json',sensor_size=list(frame.sensor_size),roi_xywh=list(m['roi']),
        saved_origin_xy=m['roi'][:2],source_coordinate_space='saved_roi',pixel_format=m['pixel_format'],
        identity=tag,parameters=m['parameters'],xdl_fields=fields,
        binding_computed_at='offline_verified_export; same-frame raw payload CRC and metadata retained',
        artifacts={name:digest(data) for name,data in sorted(files.items())},
        training_data=False,labels='UNLABELED',quality_evaluated=False,release_ready=False)

@contextlib.contextmanager
def new_directory(out):
    out=Path(out).resolve();require(not out.exists(),'Output must be a new directory')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+out.name+'.stage-',dir=out.parent) as temporary:
        stage=Path(temporary).resolve();require(stage.parent==out.parent,'Unexpected stage directory')
        yield stage
        require(not out.exists(),'Output appeared during export')
        os.rename(stage,out)

def export_frame(record_path,out,*,sensor_size=(1920,1080)):
    frame=load_commit(record_path,sensor_size=sensor_size)
    files={'capture/'+k:v for k,v in frame.files.items()}
    files.update({'planes/gray8.npy':npy_bytes(frame.gray),'planes/sat1.npy':npy_bytes(frame.sat.astype(np.uint8)),
        'planes/valid_mask.npy':npy_bytes(frame.mask.astype(np.uint8))})
    manifest=frame_manifest(frame,files)
    with new_directory(out) as stage:
        for name,data in files.items():
            p=inside(stage,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        (stage/'frame.json').write_bytes(encoded(manifest));load_frame(stage)
    return manifest

def load_frame(root):
    root=Path(root).resolve();manifest=read(root/'frame.json')
    require(manifest['schema']=='guangjian-0106-portable-frame-v1','Unsupported frame schema')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(actual==set(manifest['artifacts'])|{'frame.json'},'Portable directory inventory differs')
    files={name:inside(root,name).read_bytes() for name in manifest['artifacts']}
    require(all(digest(data)==manifest['artifacts'][name] for name,data in files.items()),'Portable artifact SHA mismatch')
    require(manifest['capture_record']=='capture/result.json','Capture record path changed')
    frame=load_commit(root/'capture/result.json',sensor_size=manifest['sensor_size'])
    expected_names={'capture/'+k for k in frame.files}|{'planes/gray8.npy','planes/sat1.npy','planes/valid_mask.npy'}
    require(set(files)==expected_names,'Portable inventory differs')
    for name,expected in [('gray8',frame.gray),('sat1',frame.sat.astype(np.uint8)),('valid_mask',frame.mask.astype(np.uint8))]:
        array=np.load(io.BytesIO(files['planes/'+name+'.npy']),allow_pickle=False)
        require(array.dtype==np.uint8 and np.array_equal(array,expected),'Portable '+name+' differs from raw')
    require(manifest==frame_manifest(frame,files),'Portable metadata/binding differs from raw frame')
    return frame,manifest

def export_batch(batch,out,*,sensor_size=(1920,1080)):
    batch=Path(batch).resolve();summary=read(batch/'operator_summary.json');plan=read(batch/'approved_plan.json')
    require(summary['schema']=='fixed-pair-operator-0106-v1' and summary['status']=='ACQUIRED_EIGHT_REVIEW_REQUIRED' and
        summary['saved_observations']==8 and summary['lights_off']['acknowledged'] and
        not summary['changed_source_or_build_files'],'Not a complete cleaned-up fixed-eight batch')
    inventory=read(batch/'output_manifest.json')['files']
    require(all(digest(inside(batch,k).read_bytes())==v for k,v in inventory.items()),'Batch inventory differs')
    entries=read(batch/'observations.json');require(len(entries)==8,'Eight source observations required')
    records=[];manifest_entries=[];identities=set()
    with new_directory(out) as stage:
        for entry in entries:
            slot=entry['observation_id'];require(slot in {f'CH{c}_{r}' for c in range(1,5) for r in ('low','high')},'Invalid slot')
            require(slot not in {e['slot'] for e in manifest_entries},'Duplicate slot')
            path=inside(batch,entry['record']);frame=load_commit(path,sensor_size=sensor_size)
            require(frame.record['sample_id']==summary['sample_id'] and frame.record['round_id']==summary['pose_id'],'Specimen/pose context differs')
            require(entry['identity']==frame.metadata['identity'] and entry['payload_sha256']==digest(frame.payload),'Observation provenance differs')
            key=(frame.metadata['identity']['session'],frame.metadata['identity']['request_id'])
            require(key not in identities,'Duplicate frame identity');identities.add(key)
            relative='frames/'+slot;export_frame(path,stage/relative,sensor_size=sensor_size)
            records.append(dict(channel=entry['channel'],role=entry['role'],sample_id=summary['sample_id'],
                pose_id=summary['pose_id'],validated=frame.validated()))
            manifest_entries.append(dict(slot=slot,channel=entry['channel'],role=entry['role'],frame_root=relative))
        fixed_eight.validate_eight(records,sample_id=summary['sample_id'],pose_id=summary['pose_id'],low=summary['low'],
            high=summary['high'],roi=records[0]['validated']['metadata']['roi'],board=frame.mask)
        require(plan['physical_specimen_id']==summary['physical_specimen_id'] and plan['pose_id']==summary['pose_id'] and
            plan['low']==summary['low'] and plan['high']==summary['high'],'Approved plan differs')
        (stage/'source_operator_summary.json').write_bytes((batch/'operator_summary.json').read_bytes())
        (stage/'source_approved_plan.json').write_bytes((batch/'approved_plan.json').read_bytes())
        group=dict(schema='guangjian-0106-portable-eight-v1',specimen_id=summary['physical_specimen_id'],
            sample_id=summary['sample_id'],pose_id=summary['pose_id'],low=summary['low'],high=summary['high'],
            entries=manifest_entries,source_evidence=summary['evidence_source'],source_summary_sha256=digest((batch/'operator_summary.json').read_bytes()),
            source_plan_sha256=digest((batch/'approved_plan.json').read_bytes()),
            training_data=False,label_status='UNLABELED',quality_evaluated=False,release_ready=False)
        (stage/'group.json').write_bytes(encoded(group));load_group(stage,purpose='interface_test')
    return group

def load_group(root,*,purpose):
    require(purpose=='interface_test','Unreviewed bridge exports are for interface_test only')
    root=Path(root).resolve();g=read(root/'group.json')
    require(g['schema']=='guangjian-0106-portable-eight-v1' and len(g['entries'])==8,'Complete eight-frame group required')
    summary=read(root/'source_operator_summary.json');plan=read(root/'source_approved_plan.json')
    require(digest((root/'source_operator_summary.json').read_bytes())==g['source_summary_sha256'] and
        digest((root/'source_approved_plan.json').read_bytes())==g['source_plan_sha256'],'Source plan/summary SHA differs')
    require(summary['status']=='ACQUIRED_EIGHT_REVIEW_REQUIRED' and summary['saved_observations']==8 and
        summary['lights_off']['acknowledged'] and not summary['changed_source_or_build_files'],'Source batch incomplete')
    require(plan['physical_specimen_id']==g['specimen_id']==summary['physical_specimen_id'] and
        plan['pose_id']==g['pose_id']==summary['pose_id'] and g['sample_id']==summary['sample_id'] and
        plan['low']==g['low']==summary['low'] and plan['high']==g['high']==summary['high'],'Group specimen/pose/exposure differs from source')
    require(g['training_data'] is False and g['release_ready'] is False and g['quality_evaluated'] is False,'Unreviewed scope changed')
    records=[];observations=[];mask=None
    models=xdl_reference.load('models')
    for entry in g['entries']:
        frame,m=load_frame(inside(root,entry['frame_root']));fields=m['xdl_fields'];p=frame.metadata['parameters']
        require(entry['slot']==f"CH{entry['channel']}_{entry['role']}",'Slot label differs')
        require(frame.record['sample_id']==g['sample_id'] and frame.record['round_id']==g['pose_id'] and
            frame.record['evidence_source']==g['source_evidence']==summary['evidence_source'],'Frame specimen/pose/evidence differs')
        fields={**fields,'observation_id':entry['slot'],'specimen_id':g['specimen_id'],'pose_id':g['pose_id'],
            'direction':f"CH{entry['channel']}",'exposure_role':entry['role'],'exposure_lines':p['exposure_lines'],
            'gain16':p['gain16'],'led':p['brightness'],'valid_mask_id':frame.record['mask_sha256'],
            'gray8':frame.gray,'sat1':frame.sat.astype(np.uint8),'valid_mask':frame.mask.astype(np.uint8)}
        observations.append(models.Observation.from_mapping(fields));mask=frame.mask
        records.append(dict(channel=entry['channel'],role=entry['role'],sample_id=g['sample_id'],pose_id=g['pose_id'],validated=frame.validated()))
    fixed_eight.validate_eight(records,sample_id=g['sample_id'],pose_id=g['pose_id'],low=g['low'],high=g['high'],
        roi=frame.metadata['roi'],board=mask)
    group=models.ObservationGroup(g['specimen_id'],g['pose_id'],tuple(observations));models.validate_group(group)
    return group

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('frame');a.add_argument('--record',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('batch');a.add_argument('--batch',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('verify');a.add_argument('--frame',type=Path,required=True)
    a=p.parse_args()
    if a.action=='frame':result=export_frame(a.record,a.out)
    elif a.action=='batch':result=export_batch(a.batch,a.out)
    else:_,result=load_frame(a.frame)
    print(json.dumps(dict(status='OFFLINE_GRAY_INPUT_VERIFIED',schema=result['schema'],training_data=False,hardware_contacted=False),indent=2))
