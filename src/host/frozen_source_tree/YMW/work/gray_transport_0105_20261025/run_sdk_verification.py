"""Run isolated software SDK checks into new evidence; never physical UDP."""
import argparse,hashlib,json,os,unittest
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    here=Path(__file__).resolve().parent
    sources=['sdk_transport.py','test_sdk_transport.py','software_transport_peer.py','generate_sdk_base.py','run_sdk_verification.py',
             'host_transport.py','fixed_eight.py','derived_sdk/acquisition_executor_0106_base.py']
    hashes={name:hashlib.sha256((here/name).read_bytes()).hexdigest() for name in sources}
    previous=os.environ.get('GRAY_SDK_TEST_OUTPUT');os.environ['GRAY_SDK_TEST_OUTPUT']=str(out/'cases')
    try:
        suite=unittest.defaultTestLoader.loadTestsFromName('test_sdk_transport')
        with (out/'unittest.txt').open('w',encoding='utf-8') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    finally:
        if previous is None:os.environ.pop('GRAY_SDK_TEST_OUTPUT',None)
        else:os.environ['GRAY_SDK_TEST_OUTPUT']=previous
    for name,digest in hashes.items():
        if hashlib.sha256((here/name).read_bytes()).hexdigest()!=digest:raise ValueError('source changed during verification')
    record=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        hardware_tested=False,new_physical_captures=0,network_scope='Offline and guarded 127.0.0.1 only',source_sha256=hashes)
    (out/'verification.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');print(json.dumps(record,indent=2))
    if not result.wasSuccessful():
        print((out/'unittest.txt').read_text(encoding='utf-8')[-14000:]);raise SystemExit(1)

if __name__=='__main__':main()
