"""Freeze RGB565 bytes and verify dual-format returned bytes offline.

This does not freeze FPGA DDR, issue CAP, or establish hardware identities.
Two new camera exposures are not a valid substitute for one frozen input.
"""
import argparse,json
from pathlib import Path
import numpy as np
import host_transport as wire

def digest(data):return wire.hashlib.sha256(data).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sources():
    return {str(Path(p).resolve()):digest(Path(p).read_bytes()) for p in
        (__file__,wire.__file__,wire.codec.__file__,wire.reference.__file__)}

def freeze(rgb,*,width,height,out,mask=None):
    wire.codec.layout(width,height)
    if min(width,height)<9 or len(rgb)!=width*height*2:raise ValueError('RGB565 dimensions/bytes')
    mask=bytes([1])*(width*height) if mask is None else mask
    if len(mask)!=width*height or any(v not in (0,1) for v in mask) or not any(mask):raise ValueError('Nonempty binary saved-domain mask required')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    (out/'input.rgb565').write_bytes(rgb);(out/'board_mask.bin').write_bytes(mask)
    plan=dict(schema='offline-frozen-input-v1',width=width,height=height,source_kind='frozen_RGB565_file_bytes',
        rgb565_sha256=digest(rgb),rgb_crc64=wire.legacy.crc64_ecma(rgb),board_mask_sha256=digest(mask),
        executable_source_sha256=sources(),hardware_freeze_established=False,hardware_identity_verified=False)
    write(out/'input_binding.json',plan);return plan

def verify(frozen,*,rgb_payload,gray_payload):
    frozen=Path(frozen);plan=json.loads((frozen/'input_binding.json').read_bytes())
    if plan.get('schema')!='offline-frozen-input-v1' or plan['executable_source_sha256']!=sources():raise ValueError('Frozen input source/schema changed')
    expected=(frozen/'input.rgb565').read_bytes();mask=(frozen/'board_mask.bin').read_bytes()
    if digest(expected)!=plan['rgb565_sha256'] or digest(mask)!=plan['board_mask_sha256']:raise ValueError('Frozen input/mask changed')
    if rgb_payload!=expected or wire.legacy.crc64_ecma(rgb_payload)!=plan['rgb_crc64']:raise ValueError('RGB return is not the frozen input')
    width,height=plan['width'],plan['height']
    rg,rs=wire.planes_from_payload(rgb_payload,width,height,1);gg,gs=wire.planes_from_payload(gray_payload,width,height,49)
    if not np.array_equal(rg,gg):raise ValueError('GRAY pixels differ from frozen RGB reference')
    if not np.array_equal(rs,gs):raise ValueError('SAT1 flags differ from frozen RGB reference')
    board=np.frombuffer(mask,np.uint8).reshape(height,width).astype(bool)
    h1,h2=wire.recompute(rg,rs,board);g1,g2=wire.recompute(gg,gs,board)
    if (h1,h2)!=(g1,g2):raise ValueError('H1/H2 differ')
    return dict(schema='offline-frozen-dual-format-check-v1',status='OFFLINE_FROZEN_BYTES_EQUIVALENT',
        rgb565_sha256=digest(rgb_payload),gray_sat_sha256=digest(gray_payload),width=width,height=height,
        rgb_bytes=len(rgb_payload),gray_sat_bytes=len(gray_payload),H1=h1,H2=h2,
        full_gray_and_SAT_planes_equal=True,hardware_freeze_established=False,hardware_identity_verified=False,
        detector_or_fusion_quality_validated=False,scope='Offline byte/plane/statistic equivalence only')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--rgb565',type=Path,required=True);a.add_argument('--width',type=int,required=True);a.add_argument('--height',type=int,required=True);a.add_argument('--mask',type=Path);a.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('verify');a.add_argument('--frozen',type=Path,required=True);a.add_argument('--rgb-payload',type=Path,required=True);a.add_argument('--gray-payload',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.action=='prepare':result=freeze(args.rgb565.read_bytes(),width=args.width,height=args.height,out=args.out,mask=args.mask.read_bytes() if args.mask else None)
    else:
        if args.out.exists():raise ValueError('Use a new diagnostic result path')
        result=verify(args.frozen,rgb_payload=args.rgb_payload.read_bytes(),gray_payload=args.gray_payload.read_bytes());write(args.out,result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
