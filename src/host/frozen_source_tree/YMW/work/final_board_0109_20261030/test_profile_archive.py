"""Reject misleading archived counters, identity, revision and CRC."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(HERE/'host'))
    from device_profiles import validate
    from offload_wire import ProtocolError
    source=json.loads(a.source.read_text('utf-8'));assert len(validate(source))==24
    cases=[dict(name='complete_24_pages',status='PASS')]
    def failure(name,change):
        x=copy.deepcopy(source);change(x)
        try:validate(x)
        except (ValueError,KeyError,IndexError):pass
        else:raise AssertionError('Accepted corrupt profile: '+name)
        cases.append(dict(name=name,status='PASS'))
    failure('wrong_summary_units',lambda x:x['device_profiles'][0][0].update(clock_hz=100000000))
    failure('wrong_summary_duration',lambda x:x['device_profiles'][0][0].update(service_seconds=0))
    failure('wrong_group',lambda x:x.update(group=x['group']+1))
    failure('wrong_request',lambda x:x['frames'][0]['identity'].update(request_id=999))
    failure('missing_stage',lambda x:x['device_profiles'][0].pop())
    failure('missing_frame',lambda x:x['device_profiles'].pop())
    def corrupt(x,offset):
        row=x['device_profiles'][0][0];raw=bytearray.fromhex(row['raw_response_hex']);raw[offset]^=1;row['raw_response_hex']=raw.hex()
    failure('wrong_revision',lambda x:corrupt(x,73))
    failure('bad_payload_CRC',lambda x:corrupt(x,-1))
    (a.out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',cases=cases,physical_hardware=False,input_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')
    print('PROFILE_ARCHIVE_PASS',len(cases),flush=True)
if __name__=='__main__':main()
