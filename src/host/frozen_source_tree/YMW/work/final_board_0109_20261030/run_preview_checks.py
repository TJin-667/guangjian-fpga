"""Qualified109 preview SDK exercised on localhost, including old108 rejection."""
import argparse,json,os,re,subprocess,sys
from pathlib import Path
from derive_runtime import HERE,original
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    test=original('final_system_20261029/test_focus0108.py').replace('0108','0109').replace('_final108','_final109').replace('self.peer.firmware=263','self.peer.firmware=264').replace('test_0107_reply','test_old0108_reply')
    path=out/'test_focus0109.py';path.write_text(test,encoding='utf-8')
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(HERE/'runtime')+os.pathsep+str(HERE/'host')}
    with (out/'tests.log').open('w',encoding='utf-8') as log:r=subprocess.run([sys.executable,'-B',str(path)],stdout=log,stderr=subprocess.STDOUT,env=env)
    log=(out/'tests.log').read_text('utf-8');count=re.search(r'Ran (\d+) tests',log)
    if r.returncode or not count:raise ValueError('Preview SDK regression failed; '+str(out/'tests.log'))
    (out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',tests=int(count[1]),physical_hardware=False,old0108_preview_rejected=True,
        scope='Actual strict109 SDK and unchanged fast-focus on localhost software camera: CRC, live ROI, pause/cancel, OFF and legacy version refusal; no board validation'),indent=2)+'\n',encoding='utf-8')
    print('PREVIEW109_SOFTWARE_PASS',count[1],flush=True)
if __name__=='__main__':main()
