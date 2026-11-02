"""Exact offline tile-table preparation for the TRANSITIONAL offload mode.

No camera/network access and no new capture. This is a data contract, not a
claim that a tile-upload command already exists in the board protocol.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np

REPO=Path(__file__).resolve().parents[4]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')

def main():
    p=argparse.ArgumentParser();p.add_argument('--result',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    root=a.result.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(REPO/'YMW/work/b1_detection_console_20261027'))
    from common import verify_vendor
    vendor,_=verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import assess_quality
    audit_path=root/'input_audit.json';audit=json.loads(audit_path.read_text('utf-8'))
    if audit.get('status')!='STRICT_INPUT_VERIFIED' or (audit['low_lines'],audit['high_lines'])!=(400,800):
        raise ValueError('Require previously verified 400/800 input result')
    if len(audit['frames'])!=8 or any((f['gain16'],f['led'])!=(16,128) for f in audit['frames']):
        raise ValueError('Eight frames, 1x gain and LED128 required')
    array_path=root/'arrays/original_eight_frames.npz';original_hash=sha(array_path)
    with np.load(array_path,allow_pickle=False) as z:gray=z['gray'];valid=z['valid'];board=z['board']
    if gray.shape!=valid.shape or gray.shape[0]!=8:raise ValueError('Invalid input arrays')
    h,w=board.shape;rows=[]
    binding=dict(group_id=audit['group_id'],roi=audit['roi_xywh'],frame_order=audit['frame_order'],
        frames=audit['frames'],audit_sha256=sha(audit_path),arrays_sha256=original_hash,
        board_sha256=hashlib.sha256(board.astype(np.uint8).tobytes()).hexdigest())
    digest=hashlib.sha256(canonical(binding)).hexdigest()
    for i,frame in enumerate(audit['frames']):
        fresh=assess_quality(gray[i])['valid_mask']
        if not np.array_equal(fresh,valid[i]):raise ValueError('Saved valid map differs from frozen quality')
        tiles=[]
        for y in range(0,h,32):
            for x in range(0,w,32):
                tile=valid[i,y:y+32,x:x+32]
                if not np.all(tile==tile[0,0]):raise ValueError('Nonuniform valid tile')
                tiles.append(tile[0,0])
        data=np.packbits(np.asarray(tiles,np.uint8),bitorder='little').tobytes()
        name=f'slot{i+1}_{frame["slot"]}_valid.bin';(out/name).write_bytes(data)
        rows.append(dict(slot=i+1,source_identity=frame,group_digest128=digest[:32],file=name,
            bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),tile_count=len(tiles),
            valid_tiles=int(np.count_nonzero(tiles)),gray_sha256=hashlib.sha256(gray[i].tobytes()).hexdigest()))
    manifest=dict(schema='0108-transition-exact-tile-table-v1',mode='OFFLINE_PREPARATION_NO_HARDWARE_UPLOAD',
        group_id=audit['group_id'],group_digest128=digest[:32],full_binding_sha256=digest,binding=binding,
        width=w,height=h,tile_size=32,tile_columns=(w+31)//32,tile_rows=(h+31)//32,
        tile_bit_order='row-major, least-significant bit first; zero padding',
        quality_owner='Frozen PC assess_quality, no FPGA quality approximation',frames=rows,hardware_commands=0)
    (out/'QUALITY_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
    if sha(array_path)!=original_hash:raise ValueError('Input changed during preparation')
    print(json.dumps(dict(status='EXACT_TABLES_PREPARED_OFFLINE',group_id=audit['group_id'],bytes=sum(r['bytes'] for r in rows)),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
