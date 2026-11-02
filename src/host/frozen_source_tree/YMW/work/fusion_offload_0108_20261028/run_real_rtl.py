"""Run XSim against complete saved ROI arrays; decode actual RTL output on PC."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n','utf-8')
def simulate(out,top,sources,marker,timeout=1800):
    bin=Path('F:/Xilinx/Vivado/2018.3/bin');hashes={str(p):sha(p) for p in sources}
    snapshot=out/'compiled_sources';snapshot.mkdir()
    compiled=[]
    for p in sources:
        target=snapshot/p.name
        if target.exists():raise ValueError('Duplicate source basename')
        target.write_bytes(p.read_bytes());compiled.append(target)
    dump(out/'COMPILED_INPUTS.json',hashes)
    commands=[['xvlog.bat','-sv','-i',str(out),*map(str,compiled)],
        ['xelab.bat','--timescale','1ns/1ps','--mt','2',top,'-s','offload_sim'],
        ['xsim.bat','offload_sim','-runall']]
    for i,cmd in enumerate(commands):
        cmd[0]=str(bin/cmd[0]);print('RUN',top,Path(cmd[0]).name,flush=True)
        with (out/f'{i}_tool.txt').open('w',encoding='utf-8') as log:
            r=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        text=(out/f'{i}_tool.txt').read_text('utf-8',errors='replace')
        if r.returncode or 'ERROR:' in text or 'Fatal:' in text:raise RuntimeError(text[-6000:])
    if marker not in text:raise RuntimeError('Missing final marker: '+text[-2000:])
    assert all(sha(Path(p))==d for p,d in hashes.items())
    return hashes

def main():
    p=argparse.ArgumentParser();p.add_argument('--vectors',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    vectors=a.vectors.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    for path in vectors.glob('*.hex'):os.link(path,out/path.name)
    (out/'groups.svh').write_bytes((vectors/'groups.svh').read_bytes())
    sources=[HERE/'rtl'/n for n in ('maxabs8_pixel.v','fusion_axi_frame.v','fusion_group_guard.v')]+[HERE/'sim/tb_fusion_axi.sv']
    hashes=simulate(out,'tb_fusion_axi',sources,'FUSION_AXI_ALL_PASS 48')
    sys.path.insert(0,str(REPO/'YMW/work/b1_detection_console_20261027'))
    from common import verify_vendor
    vendor,_=verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    sys.path.insert(0,str(HERE/'host'));from result_codec import decode_words
    index=json.loads((vectors/'VECTOR_INDEX.json').read_text('utf-8'));cases=[]
    for case in index['cases']:
        ci=case['case'];shape=(case['height'],case['width'])
        word=np.fromiter((int(s,16) for s in (out/f'c{ci}_actual.hex').read_text('ascii').splitlines()),dtype='<u4').reshape(shape)
        with np.load(vectors/f'c{ci}_reference.npz',allow_pickle=False) as z:board=z['board']
        actual,selected=decode_words(word,board,hysteresis_connect)
        with np.load(vectors/f'c{ci}_golden.npz',allow_pickle=False) as z:
            diffs={k:int(np.count_nonzero(value!=z[k])) for k,value in actual.items()}
            diffs['selected_gray']=int(np.count_nonzero(selected!=z['selected_gray']))
            diffs['packed_words']=int(np.count_nonzero(word!=z['words']))
        assert not any(diffs.values()), (case,diffs)
        if case['real']:
            with np.load(Path(case['frozen_result'])/'arrays/all8_B1.npz',allow_pickle=False) as z:
                saved_diff={k:int(np.count_nonzero(value!=z[k])) for k,value in actual.items()}
            assert not any(saved_diff.values()),saved_diff
        else:saved_diff=None
        cases.append(case|dict(RTL_plus_PC_vs_frozen=diffs,vs_existing_saved_result=saved_diff,candidate_pixels=int(actual['mask'].sum())))
    assert all(sha(Path(path))==digest for path,digest in index['protected_source_sha256'].items())
    dump(out/'VERIFICATION.json',dict(status='PASS',milestone='DDR fusion RTL plus unchanged PC connection',cases=cases,
        full_ROI_real_frames=24,source_sha256=hashes,host_codec_sha256=sha(HERE/'host/result_codec.py'),
        vector_index_sha256=sha(vectors/'VECTOR_INDEX.json'),wall_seconds=time.monotonic()-started,
        PC_supplied_frozen_tile_validity=True,new_H2_integration_verified=False,physical_MIG=False,bit_generated=False,board_commands=0))
    print('REAL_RTL_AND_HOST_PASS',len(cases),flush=True)

if __name__=='__main__':main()
