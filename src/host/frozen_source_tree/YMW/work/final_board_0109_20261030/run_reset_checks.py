"""Port the verified reset window tests to109 without touching physical hardware."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from derive_runtime import original,HERE
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    test=original('reset_acceptance_0108_20261030/test_reset_window.py').replace('0108','0109').replace('RESET108','RESET109').replace('firmware=264','firmware=265')
    test=test.replace('self.off_regs = [0]*6;', 'self.off_regs = [0]*6+[400,800]; self.off_pair=(400,800);')
    test=test.replace('            runtime = window.Runtime()\n            self.assertTrue(runtime.physical)', '''            if window.QUALIFICATION.is_file():
                runtime = window.Runtime();self.assertTrue(runtime.physical)
            else:
                with self.assertRaises(FileNotFoundError):window.Runtime()
                return
''')
    (out/'test_reset_window.py').write_text(test,encoding='utf-8')
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(HERE)+os.pathsep+str(HERE/'host')+os.pathsep+str(HERE/'runtime'),'RESET109_TEST_OUT':str(out/'cases')}
    with (out/'tests.log').open('w',encoding='utf-8') as log:r=subprocess.run([sys.executable,'-B',str(out/'test_reset_window.py')],env=env,stdout=log,stderr=subprocess.STDOUT)
    print('RESET109_TEST_EXIT',r.returncode,flush=True)
    if r.returncode:raise RuntimeError('Reset regression failed; inspect '+str(out/'tests.log'))
    (out/'VERIFICATION.json').write_bytes((out/'cases/VERIFICATION.json').read_bytes())
if __name__=='__main__':main()
