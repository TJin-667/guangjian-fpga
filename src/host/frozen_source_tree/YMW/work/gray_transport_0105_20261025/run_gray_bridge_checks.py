"""Run new guarded-loopback bridge checks and source-bound receipts."""
import argparse,hashlib,json,os,socket,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import gray_capture_bridge as bridge
import xdl_reference

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,o):p.write_bytes((json.dumps(o,indent=2)+'\n').encode())

def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    os.environ['GRAY_BRIDGE_TEST_OUTPUT']=str(out)
    suite=unittest.defaultTestLoader.loadTestsFromName('test_gray_capture_bridge')
    with (out/'unittest.txt').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    record=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),
        physical_captures=0,software_capture_requests=8,network_policy='Only127.0.0.1 permitted by LocalSocket',
        production_gate_modified=False,release_ready=False,source_sha256={str(HERE/name):sha(HERE/name) for name in
            ['gray_capture_bridge.py','xdl_reference.py','test_gray_capture_bridge.py','run_gray_bridge_checks.py']},
        XDL_snapshot=xdl_reference.verify(),wall_seconds=round(time.monotonic()-start,3))
    write(out/'verification.json',record);print(json.dumps({k:record[k] for k in ['status','tests','failures','errors','wall_seconds']},indent=2))
    if not result.wasSuccessful():raise SystemExit(2)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
