"""Read-only validation of the 24 archived same-domain profile replies."""
import struct
from offload_wire import decode,require

def validate(result):
    require(len(result['frames'])==len(result['device_profiles'])==8,'Eight profile rows required')
    pixels=result['roi'][2]*result['roi'][3];beats=(pixels+3)//4;rows=[]
    for slot,(frame,stages) in enumerate(zip(result['frames'],result['device_profiles']),1):
        require(frame['slot']==slot and len(stages)==3,'Profile frame/stage count')
        cookie=None
        for stage,p in enumerate(stages):
            raw=bytes.fromhex(p['raw_response_hex']);reply=decode(raw,op=26,sequence=int.from_bytes(raw[6:8],'big'))
            require(reply.status==0 and not reply.fatal and not reply.association_error and not reply.job_busy,'Invalid profile state')
            require((reply.group,reply.digest,reply.roi,reply.slot,reply.completed_slots,reply.request)==(result['group'],bytes.fromhex(result['digest128']),tuple(result['roi']),slot,slot,frame['identity']['request_id']),'Profile archive identity mismatch')
            if cookie is None:cookie=reply.cookie
            require(reply.cookie==cookie and cookie>0,'Mixed profile frame cookie')
            magic,actual,hz,cycles,c0,c1,blocked=struct.unpack('>4s6I',reply.payload)
            require(magic==b'GJP9' and actual==stage and hz==(125000000 if stage==0 else 100000000),'Profile stage/clock mismatch')
            require(cycles>0 and max(c0,c1,blocked)<=cycles,'Profile counts out of range')
            expected=(pixels,None) if stage==0 else ((beats,(beats+15)//16) if stage==1 else (beats*(1 if slot==1 else 2),beats))
            require(c0==expected[0] and (expected[1] is None or c1==expected[1]),'Profile frame-size handshake mismatch')
            keys=dict(stage=stage,clock_hz=hz,service_cycles=cycles,count0=c0,count1=c1,blocked_cycles=blocked,group=reply.group,cookie=reply.cookie,request=reply.request,slot=slot)
            require(all(p[k]==v for k,v in keys.items()) and abs(p['service_seconds']-cycles/hz)<1e-15,'Profile summary differs from original wire reply')
            rows.append({**p,'physical_hardware':result.get('physical_hardware') is True,'software_model':result.get('evidence_source')!='real_board'})
    return rows
