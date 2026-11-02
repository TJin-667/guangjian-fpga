"""Acceptance RTL: all three formats, packet boundaries and common reset phases."""
import argparse,csv,hashlib,importlib.util,json,sys,time
from pathlib import Path
import numpy as np
import generate_acceptance as gen
import dual_view

BASE=gen.BASE
sys.path.append(str(BASE))
import host_transport as wire
import run_verification as old

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);gen.generate();start=time.monotonic()
    unit=out/'unit';unit.mkdir();cases=[];lines=[]
    for fmt in (1,49,50):
        for n in (1,7,8,9,440,441,442,689,690,691,1223,1224,1225,65536):
            words=((np.arange(n,dtype=np.uint32)*7919+len(cases)*17)&65535).astype(np.uint16)
            w=next(v for v in range(min(n,1920),0,-1) if n%v==0 and n//v<=1080)
            rgb=words.astype('>u2').tobytes();g,s=wire.planes_from_payload(rgb,w,n//w,1)
            raw=rgb if fmt==1 else wire.codec.encode(g,s) if fmt==49 else dual_view.encode(rgb,g,s)
            i=len(cases)
            (unit/f'pixels_{i}.hex').write_text(''.join(f'{v:04x}\n' for v in words),encoding='ascii')
            (unit/f'payload_{i}.hex').write_text(''.join(f'{v:02x}\n' for v in raw),encoding='ascii')
            crc=wire.legacy.crc64_ecma(raw)
            cases.append(dict(index=i,pixels=n,format=fmt,bytes=len(raw),crc64=f'{crc:016x}',payload_sha256=hashlib.sha256(raw).hexdigest()))
            lines.append(f"run_case({i},{n},{fmt},{len(raw)},64'h{crc:016x});\n")
    (unit/'unit_cases.svh').write_text(''.join(lines),encoding='ascii');gen_manifest=gen.generate()
    tb=(BASE/'tb_packet_store.sv').read_text().replace('[0:147455]','[0:204799]').replace('#30000000','#100000000')
    tb=tb.replace('malformed_eof(49,0);','malformed_eof(49,0);malformed_eof(50,1);malformed_eof(50,0);')
    extra='''
        // Reset during conversion, RGB emission, full window and final commit wait.
        for(integer phase=0;phase<4;phase++)begin
            clear();pixel_format=50;total_pixels=(phase==0)?16:(phase==1)?8:(phase==2)?1000:1;
            start=1;tick();start=0;
            if(phase==0)push(16'hffff,0);
            if(phase==1)begin for(integer q=0;q<8;q++)push(q,q==7);wait(dut.encoder.codec_valid);tick();end
            if(phase==2)begin for(integer q=0;q<448;q++)push(q,0);wait(dut.full);end
            if(phase==3)begin push(16'hffff,1);wait(dut.encoding_complete);end
            reset=1;tick();reset=0;tick();
            if(ready || in_ready || error || encoding_complete || payload_bytes || payload_crc64)$fatal(1,"common reset leaked frame");
            passed($sformatf("common_reset_phase_%0d_clears_provisional_frame",phase));
        end
        run_case(28,1,50,4,64'h0000000000000000); // replaced with generated CRC below
'''
    first50=cases[28];extra=extra.replace("64'h0000000000000000", "64'h"+first50['crc64'])
    tb=tb.replace('        $fclose(receipt);',extra+'        $fclose(receipt);')
    (unit/'tb_packet_store.sv').write_text(tb,encoding='utf-8',newline='\n')
    sources=[BASE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v',gen.HERE/'dual_view_encoder.v',gen.HERE/'transport_packet_store.v',unit/'tb_packet_store.sv']
    hashes=old.simulate(unit,'tb_packet_store',sources,Path('F:/Xilinx/Vivado/2018.3/bin'),'TRANSPORT_PACKET_STORE_ALL_PASS 61')
    rows=list(csv.DictReader((unit/'packet_store_receipt.csv').open()))
    if len(rows)!=61 or any(r['status']!='PASS' for r in rows):raise ValueError('RTL receipt')
    (out/'verification.json').write_text(json.dumps(dict(status='PASS',cases=len(rows),source_sha256=hashes,
        derived_manifest=gen_manifest,vectors=cases,wall_seconds=time.monotonic()-start,hardware_contacted=False),indent=2)+'\n')
    print('ACCEPTANCE_RTL_PASS',len(rows),flush=True)

if __name__=='__main__':main()
