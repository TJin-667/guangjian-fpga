"""Persist software operator-host results; physical sockets forbidden by tests."""
import argparse,hashlib,json,unittest
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);here=Path(__file__).resolve().parent
    names=['operator_host.py','board_probe.py','frozen_diagnostic.py','test_operator_host.py','run_operator_verification.py',
        'sdk_transport.py','fixed_eight.py','software_transport_peer.py','test_sdk_transport.py']
    hashes={name:hashlib.sha256((here/name).read_bytes()).hexdigest() for name in names}
    suite=unittest.defaultTestLoader.loadTestsFromName('test_operator_host')
    with (out/'unittest.txt').open('w',encoding='utf-8') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    for name,digest in hashes.items():
        if hashlib.sha256((here/name).read_bytes()).hexdigest()!=digest:raise ValueError('Source changed during checks')
    receipt=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,errors=len(result.errors),failures=len(result.failures),
        network_scope='Offline and guarded 127.0.0.1 only',hardware_0106_tested=False,new_physical_captures=0,source_sha256=hashes)
    (out/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8');print(json.dumps(receipt,indent=2))
    if not result.wasSuccessful():print((out/'unittest.txt').read_text(encoding='utf-8')[-18000:]);raise SystemExit(1)

if __name__=='__main__':main()
