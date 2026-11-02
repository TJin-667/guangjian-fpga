"""Real localhost UDP and strict0109 SDK. Software timing values are models."""
import argparse,json,sys,socket
from pathlib import Path
from unittest.mock import patch
from derive_candidate import HERE
from derive_host import main as derive
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();derive();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(HERE/'host'))
    from engineering_executor import EngineeringExecutor,sdk
    from software_offload_peer import make_peer
    import numpy as np
    Peer,engine=make_peer();rows=[];roi=(3,5,19,13);board=(np.arange(247).reshape(13,19)%5<3)
    cases=[('', '',True,49,300,700),('', 'lose_first_arm_ack',True,49,350,900),('', 'wrong_stream_crc',False,49,400,800),
        ('wrong_H2','',False,49,400,800),('','',True,50,400,800),('','wrong_profile_crc',False,49,400,800),
        ('','wrong_profile_clock',False,49,400,800),('','wrong_config_echo',False,49,300,700)]
    for index,(fault,extension_fault,expected,fmt,low,high) in enumerate(cases,1):
        target=out/('case'+str(index));target.mkdir()
        with Peer(engine.root/'ymw',fault=fault,extension_fault=extension_fault,sensor_size=(96,32)) as peer:
            executor=EngineeringExecutor(group_id=index,group_digest=bytes([index])*16,group_roi=roi,group_board=board,group_low=low,group_high=high,
                result_directory=target/'fusion',board=peer.endpoint[0],port=peer.endpoint[1],bind='127.0.0.1',ymw_root=engine.root/'ymw',output_root=target/'captures',
                pixel_format=fmt,mode='strict',evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.3,retries=3,initial_seq=65520)
            failure=None;frames=0
            try:
                for slot in range(1,9):
                    executor.acquire(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=low if slot%2 else high,gain16=16,
                        roi=roi,board_mask=board.astype(np.uint8).tobytes(),settle_frames=1,discard_frames=3,timeout_s=12,sample_id='SOFTWARE109_NOT_TRAINING',round_id='r1');frames+=1
            except Exception as exc:failure=dict(type=type(exc).__name__,message=str(exc),code=getattr(exc,'code',None))
            finally:executor.close()
            success=(target/'fusion/RESULT.json').exists()
            if success!=expected:raise AssertionError(dict(case=index,frames=frames,failure=failure))
            if expected:
                result=json.loads((target/'fusion/RESULT.json').read_text(encoding='utf-8-sig'))
                if frames!=8 or any(result['differences'].values()) or len(result['device_profiles'])!=8 or any(len(r)!=3 for r in result['device_profiles']) or peer.off_live:raise AssertionError('Incomplete group/profile/math')
                if peer.off_execution.get(18)!=8 or peer.off_execution.get(22)!=8 or peer.off_execution.get(26)!=24:raise AssertionError('Repeated mutations or missing profile pages')
                if not (target/'fusion/index.html').is_file():raise AssertionError('Missing eight-original gallery')
            elif extension_fault=='wrong_stream_crc':
                if frames!=7 or not peer.off_published or (target/'fusion').exists():raise AssertionError('Corrupt result incorrectly released')
            elif frames!=0:raise AssertionError('Invalid first frame/config/profile was accepted')
            rows.append(dict(case=index,status='PASS',fault=fault,extension_fault=extension_fault,format=fmt,low=low,high=high,frames=frames,capture_requests=len(peer.captured),success=success,failure=failure))
            print('SDK109_LOOPBACK_PASS',index,frames,flush=True)
    with patch.object(socket,'socket',side_effect=AssertionError('Unexpected hardware socket')):
        try:sdk.TransportExecutor(evidence_source='real_board')
        except ValueError:pass
        else:raise AssertionError('Unqualified real0109 accepted')
        try:EngineeringExecutor(group_id=1,group_digest=b'a'*16,group_roi=roi,group_board=board,group_low=0,group_high=800,result_directory=out/'invalid')
        except ValueError:pass
        else:raise AssertionError('Illegal exposure accepted')
    rows.append(dict(case=9,status='PASS',check='No qualification or illegal exposure refuses before socket'))
    (out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',cases=rows,physical_hardware=False,timing_values_are_software_model=True,new_bit_generated=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('SDK109_LOOPBACK_ALL_PASS',len(rows),flush=True)
if __name__=='__main__':main()
