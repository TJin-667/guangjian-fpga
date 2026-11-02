"""Offline evidence builder; never imports a live acquisition executor."""
import argparse,hashlib,io,json,os,socket,subprocess,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from codec import planes,encode,decode,tile_quality_gray

HERE=Path(__file__).resolve().parent
FROZEN=HERE.parent/'inspection_console_0105_20261022/vendor'
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=HERE/'verification/run_04')
OUT=ap.parse_args().out.resolve()

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    log=io.StringIO();suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_codec.py')
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (OUT/'python_tests.txt').write_text(log.getvalue(),encoding='utf-8')
    if not result.wasSuccessful():raise RuntimeError(log.getvalue())
    sys.path.insert(0,str(FROZEN));from fourlight_fusion.fusion import single_features,tile_quality
    repo=HERE.parents[2]
    raw=repo/'YMW/data/0105_preview_exposure_gain_20261023/sample004_A_v1_CH1_sweep01/raw'
    archives=sorted(raw.glob('*.zip'))+[
        Path('C:/BX72_0105_LAB/results/inspection_online_sample005_A_v0_20261024_165421_6dd55f.zip'),
        Path('C:/BX72_0105_LAB/results/inspection_online_sample005_A_v1_20261024_171608_33d8bd.zip')]
    if len(archives)!=10:raise ValueError('Expected 8 pinned preview ZIPs and 2 sample005 ZIPs')
    checks=[]
    for archive in archives:
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            names=[n for n in z.namelist() if n.endswith('.rgb565')]
            if not names:raise ValueError('No formal RGB frame: '+str(archive))
            for member in names:
                png=member[:-7]+'.png'
                if png not in z.namelist():raise ValueError('Missing paired PNG '+png)
                image=cv2.imdecode(np.frombuffer(z.read(png),np.uint8),cv2.IMREAD_COLOR)
                rawrgb=z.read(member)
                words=np.frombuffer(rawrgb,dtype='>u2').reshape(image.shape[:2]).astype(np.uint32)
                rr=(words>>11)&31;gg=(words>>5)&63;bb=words&31
                rebuilt=np.stack(((bb<<3)|(bb>>2),(gg<<2)|(gg>>4),(rr<<3)|(rr>>2)),axis=2).astype(np.uint8)
                if not np.array_equal(image,rebuilt):raise ValueError('PNG/RGB mismatch')
                g,s=planes(image);payload=encode(g,s);gd,sd=decode(payload,image.shape[1],image.shape[0])
                original=single_features(image);candidate=single_features(gd)
                for key in original:
                    if not np.array_equal(original[key],candidate[key]):raise ValueError('Feature changed: '+key)
                board=np.ones(g.shape,bool);board[:4]=False;board[-4:]=False;board[:,:4]=False;board[:,-4:]=False
                oldq=tile_quality(image,board);newq=tile_quality_gray(gd,sd,board)
                if oldq['tiles']!=newq['tiles'] or not np.array_equal(oldq['quality_q8'],newq['quality_q8']):
                    raise ValueError('Tile quality changed')
                checks.append(dict(archive=str(archive),archive_sha256=digest,member=member,
                    shape=list(g.shape),rgb_bytes=len(rawrgb),gray_sat_bytes=len(payload),
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    gray_H2_valid_weak_strong_mask_equal=True,tile_quality_equal=True))
        print('Image replay '+archive.name,flush=True)
    (OUT/'image_equivalence.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sim=OUT/'rtl';sim.mkdir()
    for k,n in enumerate((65536,1,7,8,9,1223,1224,1225)):
        words=np.arange(n,dtype=np.uint32) if k==0 else (np.arange(n,dtype=np.uint32)*7919+k*17)&65535
        rr=(words>>11)&31;gg=(words>>5)&63;bb=words&31
        image=np.stack(((bb<<3)|(bb>>2),(gg<<2)|(gg>>4),(rr<<3)|(rr>>2)),axis=1).astype(np.uint8).reshape(1,n,3)
        # The primitive supports arbitrary linear pixel count; gray codec shape
        # is bounded to a physical frame, so reshape the exhaustive case.
        if k==0:image=image.reshape(256,256,3)
        g,s=planes(image);packed=encode(g,s)
        (sim/f'pixels_{k}.hex').write_text(''.join(f'{w:04x}\n' for w in words),encoding='ascii')
        (sim/f'bytes_{k}.hex').write_text(''.join(f'{b:02x}\n' for b in packed),encoding='ascii')
    bin=Path('F:/Xilinx/Vivado/2018.3/bin')
    wrapper=sim/'gray_source.sv'
    wrapper.write_text('`timescale 1ns/1ps\n`include "C:/BX72_0105_LAB/runtime/rtl/rgb565_gray.v"\n',encoding='ascii')
    commands=[['xvlog.bat','-sv',str(wrapper),str(HERE/'gray_sat_encoder.v'),str(HERE/'tb_gray_sat.sv')],
              ['xelab.bat','tb_gray_sat','-s','gray_sat_sim'],['xsim.bat','gray_sat_sim','-runall']]
    for k,command in enumerate(commands):
        command[0]=str(bin/command[0]);logfile=OUT/f'rtl_tool_{k}.txt'
        print('RTL '+Path(command[0]).name,flush=True)
        with logfile.open('w',encoding='utf-8') as handle:
            r=subprocess.run(command,cwd=sim,stdout=handle,stderr=subprocess.STDOUT,timeout=180)
        text=logfile.read_text(encoding='utf-8',errors='replace')
        if r.returncode or 'ERROR:' in text or 'Fatal:' in text:raise RuntimeError(text[-5000:])
    if 'GRAY_SAT_RTL_ALL_PASS' not in text:raise RuntimeError('RTL completion marker missing')
    result=dict(status='PASS',scope='Isolated primitive, offline codec and historical image equivalence; not a new board bit',
        python_tests=7,exhaustive_RGB565_codes=65536,image_members=len(checks),
        unique_gray_sat_payloads=len({c['payload_sha256'] for c in checks}),images=checks,
        rtl_exhaustive_and_boundary_pause_cancel_restart_tests=True,
        board_integration=False,board_tested=False,new_resource_report=False,
        whole_new_fusion_quality_validated=False)
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='images'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('Offline verification forbids sockets')):main()
