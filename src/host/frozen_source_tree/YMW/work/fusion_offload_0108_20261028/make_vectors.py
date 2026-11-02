"""Frozen real development inputs + directed arithmetic/tail vectors, on E only."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n','utf-8')
def hex128(path,words):
    flat=np.asarray(words,dtype='<u4').ravel();pad=np.zeros((len(flat)+3)//4*4,dtype='<u4');pad[:len(flat)]=flat
    lines=[''.join(f'{int(x):08x}' for x in row[::-1])+'\n' for row in pad.reshape(-1,4)]
    path.write_text(''.join(lines),'ascii')

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(REPO/'YMW/work/b1_detection_console_20261027'))
    from common import verify_vendor
    vendor,_=verify_vendor();sys.path.insert(0,str(vendor))
    from dual_exposure_b1.fusion import maxabs_connect
    import cv2;cv2.setNumThreads(1)
    cases=[];protected={}
    rng=np.random.default_rng(10820261028)
    for h,w in [(9,9),(13,19),(65,65)]:
        r=rng.integers(-20655,20656,(8,h,w),dtype=np.int16)
        v=rng.random(r.shape)>.25;g=rng.integers(0,256,r.shape,dtype=np.uint8)
        boundary=np.array([0,648,-648,649,-649,1620,-1620,1621,-1621,20655,-20655],np.int16)
        r[:,:,0]=boundary[np.arange(8*h).reshape(8,h)%len(boundary)]
        r[:,:,1]=649;v[:,:,1]=True # earliest-slot ties
        r[:,:,2]=0;v[:,:,2]=True # valid zero has a nonzero source
        v[:,:,3]=False # all unknown
        r[0,:,4]=1621;r[1,:,4]=-1621;v[:2,:,4]=True
        board=rng.random((h,w))>.2
        cases.append(dict(name=f'directed_{w}x{h}',gray=g,residual=r,valid=v,board=board,real=False))
    evidence=json.loads((REPO/'YMW/handoffs/fusion_final_400_800_20261028/EXISTING_EVIDENCE.json').read_text('utf-8'))
    for item in evidence['groups']:
        root=Path(item['result']);path=root/'arrays/original_eight_frames.npz';protected[str(path)]=sha(path)
        with np.load(path,allow_pickle=False) as z:case=dict(gray=z['gray'],residual=z['residual_n'],valid=z['valid'],board=z['board'])
        case.update(name=item['specimen'],real=True,group_id=item['group_id'],frozen_result=str(root));cases.append(case)
    index=[];calls=[]
    for ci,case in enumerate(cases):
        g,r,v,b=case['gray'],case['residual'],case['valid'],case['board'];h,w=b.shape
        words=np.zeros((h,w),np.uint32);chosen=np.zeros((h,w),np.uint8)
        np.savez_compressed(out/f'c{ci}_reference.npz',gray=g,residual_n=r,valid=v,board=b)
        for frame in range(8):
            record=r[frame].astype('<i2').view('<u2').astype('<u4')|(g[frame].astype('<u4')<<16)|(v[frame].astype('<u4')<<24)
            hex128(out/f'c{ci}_s{frame+1}_input.hex',record)
            golden=maxabs_connect(r[:frame+1],v[:frame+1],board=b)
            source=golden['source_frame'];yy,xx=np.indices(b.shape)
            chosen=np.where(source>0,g[np.maximum(source.astype(int)-1,0),yy,xx],0).astype(np.uint8)
            words=golden['residual_n'].view('<u2').astype('<u4')|(source.astype('<u4')<<16)|\
                (golden['weak'].astype('<u4')<<20)|(golden['strong'].astype('<u4')<<21)|(chosen.astype('<u4')<<22)
            hex128(out/f'c{ci}_s{frame+1}_expected.hex',words)
        np.savez_compressed(out/f'c{ci}_golden.npz',**golden,selected_gray=chosen,words=words)
        index.append({k:val for k,val in case.items() if k not in ('gray','residual','valid','board')}|dict(case=ci,width=w,height=h,pixels=w*h))
        calls.append(f'run_group({ci},{w},{h});\n')
        print('VECTORS_READY',ci,case['name'],w,h,flush=True)
    assert all(sha(Path(p))==d for p,d in protected.items())
    (out/'groups.svh').write_text(''.join(calls),'ascii')
    dump(out/'VECTOR_INDEX.json',dict(cases=index,protected_source_sha256=protected,
        validity='Frozen PC tile-valid arrays; hardware tile quality is not claimed by this milestone',
        hashes_unchanged=True,hardware_commands=0))

if __name__=='__main__':main()
