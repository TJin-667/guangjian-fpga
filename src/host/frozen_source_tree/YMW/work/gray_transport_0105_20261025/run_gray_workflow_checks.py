import argparse,hashlib,json,os,time,unittest
from pathlib import Path
import gray_acquisition_workflow as workflow

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    os.environ['GRAY_WORKFLOW_TEST_OUTPUT']=str(out)
    suite=unittest.defaultTestLoader.loadTestsFromName('test_gray_acquisition_workflow')
    with (out/'unittest.txt').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    reports=[json.loads(p.read_bytes()) for p in out.glob('*/workflow/workflow.json')]
    captures=sum(r['acquisition_result']['summary']['recorded_network_cost_totals']['capture_requests']
        for r in reports if r['acquisition_result'])
    record=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),software_capture_requests=captures,
        statuses=[r['status'] for r in reports],physical_captures=0,production_gate_modified=False,
        source_sha256={str(HERE/name):sha(HERE/name) for name in ['gray_acquisition_workflow.py',
            'test_gray_acquisition_workflow.py','run_gray_workflow_checks.py','gray_capture_bridge.py','operator_host.py']},
        release_ready=False,wall_seconds=round(time.monotonic()-start,3))
    (out/'verification.json').write_bytes((json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({k:record[k] for k in ['status','tests','failures','errors','software_capture_requests','wall_seconds']},indent=2))
    if not result.wasSuccessful():raise SystemExit(2)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
