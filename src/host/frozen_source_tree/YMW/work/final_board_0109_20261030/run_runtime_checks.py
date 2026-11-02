"""Re-run inherited ownership/UI checks using strict109; add exposure changes."""
import argparse,ast,hashlib,json,os,subprocess,sys
from pathlib import Path
from derive_runtime import original,HERE,REPO

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    runtime=HERE/'runtime'
    test=original('performance_followup_0108_20261030/test_session_batch.py').replace('0108','0109').replace('BATCH108_TEST_OUT','BATCH109_TEST_OUT')
    test=test.replace("WORK=Path(__file__).resolve().parent.parent",'WORK=Path('+repr(str(HERE.parent))+')')
    test=test.replace("HOST=WORK/'fusion_board_0109_20261028/host'",'HOST=Path('+repr(str(HERE/'host'))+')')
    test=test.replace("sys.path.insert(0,str(WORK/'final_system_20261029'))",'sys.path.insert(0,'+repr(str(runtime))+')')
    test=test.replace("with self.assertRaisesRegex(ValueError,'requires400/800'):self.session.capture(plan(low_lines=300))","with self.assertRaisesRegex(ValueError,'Legal ordered'):self.session.capture(plan(low_lines=900))")
    test=test.replace("        sys.path.insert(0,str(WORK/'performance_closure_20261030'))\n        import run_offline",'        import pc_comparison as run_offline')
    insertion='''
def test_manual_pair_changes_preserve_session_and_freeze_each_group(self):
    first,a=self.session.capture(plan(low_lines=300,high_lines=700))
    second,b=self.session.capture(plan(1002,low_lines=400,high_lines=900))
    self.assertEqual(a['session'],b['session']);self.assertEqual(b['mask_commands'],0)
    self.assertTrue(b['reuse'])
    for path,pair in ((first,(300,700)),(second,(400,900))):
        result=read(path/'fusion/RESULT.json')
        self.assertEqual((result['low_lines'],result['high_lines']),pair)
        self.assertEqual(len(result['device_profiles']),8)
        for slot,item in enumerate(result['frames'],1):
            record=read(item['record'])
            self.assertEqual(record['actual_parameters']['exposure_lines'],pair[(slot-1)%2])
            self.assertEqual([x['stage'] for x in result['device_profiles'][slot-1]],[0,1,2])
    ROWS.append(dict(case='manual_pair_between_warm_groups',first_pair=[300,700],second_pair=[400,900],mask_commands_second=0,physical=False))
BatchTests.test_manual_pair_changes_preserve_session_and_freeze_each_group=test_manual_pair_changes_preserve_session_and_freeze_each_group
'''
    test=test.replace("if __name__=='__main__':",insertion+"\nif __name__=='__main__':")
    (out/'test_session_batch.py').write_text(test,encoding='utf-8')
    raw=original('performance_closure_20261030/run_offline.py');node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='pc_reference')
    function=ast.get_source_segment(raw,node).replace('archive0108','archive0109')
    imports='''import json,sys,time,statistics
from pathlib import Path
import numpy as np
import archive0109,frozen_algorithm
from hybrid import build_context
from performance import Ledger
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def need(ok,message):
    if not ok:raise ValueError(message)
'''
    (out/'pc_comparison.py').write_text(imports+function+'\n',encoding='utf-8')
    ui=original('performance_followup_0108_20261030/test_continuous_app.py').replace('0108','0109')
    ui=ui.replace("self.ui.low_lines.set('300')","self.ui.low_lines.set('0')").replace("self.ui.continuous_low.get(),'300'","self.ui.continuous_low.get(),'0'")
    ui=ui.replace("self.assertIn('没有发出CAP',self.ui.status.get())","self.assertIn('尚未采集',self.ui.status.get())")
    ui=ui.replace("self.assertRaisesRegex(ValueError,'没有发出CAP')","self.assertRaisesRegex(ValueError,'曝光')").replace('low=300,high=800','low=900,high=800')
    # Exercise a changed manual pair through the actual controller/cache path too.
    ui=ui.replace('low_lines=400,high_lines=800', 'low_lines=300 if number==1 else 400,high_lines=700 if number==1 else 900')
    (out/'test_continuous_app.py').write_text(ui,encoding='utf-8')
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(runtime)+os.pathsep+str(HERE/'host')+os.pathsep+str(out),'BATCH109_TEST_OUT':str(out/'sessions'),'CONTINUOUS_UI_TEST_OUT':str(out/'ui')}
    rows=[]
    for name in ('test_session_batch.py','test_continuous_app.py'):
        cmd=[sys.executable,'-B',str(out/name)]
        with (out/(name+'.log')).open('w',encoding='utf-8') as log:r=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(test=name,returncode=r.returncode));print('RUNTIME109_TEST',name,r.returncode,flush=True)
        if r.returncode:raise RuntimeError('Runtime test failed; see '+str(out/(name+'.log')))
    proofs=[json.loads((out/n/'VERIFICATION.json').read_text('utf-8')) for n in ('sessions','ui')]
    (out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',tests=sum(r['tests'] for r in proofs),suites=rows,physical_hardware=False,scope='Strict109 localhost UDP, inherited ownership/errors, changed exposure within retained session, dense frozen f09 equality and real hidden Tk'),indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
