"""Run real RTL integration with explicit pin/DDR/SCCB/transport models."""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from generate_candidate import generate,replace,HERE,REPO,PIN,TJ
import host_transport as host

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def simulate(out,top,sources,bin_path,marker):
    before={str(p):sha(p) for p in sources}
    commands=[['xvlog.bat','-sv',*map(str,sources)],['xelab.bat','--timescale','1ns/1ps','--mt','2',top,'-s','transport_sim'],['xsim.bat','transport_sim','-runall']]
    for i,command in enumerate(commands):
        command[0]=str(bin_path/command[0]);print('RTL',top,Path(command[0]).name,flush=True)
        with (out/f'{i}_tool.txt').open('w',encoding='utf-8') as log:
            result=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        text=(out/f'{i}_tool.txt').read_text(encoding='utf-8',errors='replace')
        if result.returncode or 'ERROR:' in text or 'Fatal:' in text:raise RuntimeError(text[-5000:])
    if marker not in text:raise ValueError('missing simulation completion marker')
    for p in sources:
        if sha(p)!=before[str(p)]:raise ValueError('source changed during simulation')
    return before

def unit(out,bin_path):
    out.mkdir()
    cases=[];lines=[]
    for fmt,ns in [(1,[1,689,690,691,65536]),(49,[1,7,8,9,1223,1224,1225,1226,1227,2453,65536])]:
        for n in ns:
            i=len(cases);words=(np.arange(n,dtype=np.uint32)*7919+i*17)&65535
            raw=words.astype('>u2').tobytes()
            w=next(v for v in range(min(n,1920),0,-1) if n%v==0 and n//v<=1080)
            h=n//w
            gray,sat=host.planes_from_payload(raw,w,h,1)
            payload=raw if fmt==1 else host.codec.encode(gray,sat)
            (out/f'pixels_{i}.hex').write_text(''.join(f'{v:04x}\n' for v in words),encoding='ascii')
            (out/f'payload_{i}.hex').write_text(''.join(f'{v:02x}\n' for v in payload),encoding='ascii')
            crc=host.legacy.crc64_ecma(payload)
            cases.append(dict(index=i,pixels=n,format=fmt,bytes=len(payload),crc64=f'{crc:016x}',sha256=hashlib.sha256(payload).hexdigest()))
            lines.append(f"run_case({i},{n},{fmt},{len(payload)},64'h{crc:016x});\n")
    (out/'unit_cases.svh').write_text(''.join(lines),encoding='ascii');dump(out/'vectors.json',cases)
    sources=[HERE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v',HERE/'transport_packet_store.v',HERE/'tb_packet_store.sv']
    receipt=simulate(out,'tb_packet_store',sources,bin_path,'TRANSPORT_PACKET_STORE_ALL_PASS 28')
    rows=list(csv.DictReader((out/'packet_store_receipt.csv').open()))
    if len(rows)!=28 or any(r['status']!='PASS' for r in rows):raise ValueError('unit case receipt')
    return {'cases':len(rows),'golden_payloads':len(cases),'source_sha256':receipt}

def board_tb(out):
    p=REPO/(TJ+'sim/tb_identity_board.sv')
    s=subprocess.check_output(['git','show',PIN+':'+p.relative_to(REPO).as_posix()],cwd=REPO).decode('utf-8').replace('\r\n','\n')
    if p.read_bytes()!=subprocess.check_output(['git','show',PIN+':'+p.relative_to(REPO).as_posix()],cwd=REPO):raise ValueError('board TB changed')
    s=replace(s,'module tb_identity_board;', 'module tb_transport_board;')
    s=replace(s,'integer ack_count=0,meta_count=0,', 'integer commands_file;\n    integer ack_count=0,meta_count=0,')
    s=replace(s,'integer ack_count=0,meta_count=0,', 'integer cap_count=0;\n    reg [7:0] last_cap[0:31];\n    integer ack_count=0,meta_count=0,')
    s=replace(s,'seq=seq+1;expected_ack_seq=seq;', 'seq=seq+1;$fwrite(commands_file,"%0d,%0d,%016h,%0d\\n",seq,kind,arguments,expected_result);expected_ack_seq=seq;')
    s=replace(s,'if(kind!=9)begin','if(kind!=9 && kind!=14)begin')
    s=replace(s,'last_metadata[10]!=1', 'last_metadata[10]!=2')
    s=replace(s,"if(packet[5]==8'h90)frame_packets=frame_packets+1;", """if(packet[5]==8'h86)begin
                    if(tx_size!=32)$fatal(1,"capability length");
                    if({packet[6],packet[7]}!=expected_ack_seq || expected_ack_kind!=14)$fatal(1,"capability request sequence");
                    for(integer p=0;p<32;p++)last_cap[p]=packet[p];
                    cap_count++;
                end
                if(packet[5]==8'h90)frame_packets=frame_packets+1;""")
    s=replace(s,"if(packet[5]==8'h85)begin", "if(packet[5]==8'h85)begin\n                    if({packet[6],packet[7]}!=expected_ack_seq || expected_ack_kind!=9)$fatal(1,\"metadata request sequence\");")
    s=replace(s,'receipt=$fopen("board_receipt.csv","w");', 'commands_file=$fopen("commands.csv","w");$fwrite(commands_file,"sequence,kind,args_hex,expected_result\\n");\n        receipt=$fopen("board_receipt.csv","w");')
    s=replace(s,'$fclose(trace);$fclose(binary);', '$fclose(commands_file);$fclose(trace);$fclose(binary);')
    s=replace(s,'    task load_mask(','''    task capabilities(input integer fmt);
        integer target;
        begin
            target=cap_count+1;send_command(14,0,0);
            waits=0;while(cap_count<target && waits<200000)begin @(negedge rgmii_rx_clk_i);#1;waits++;end
            if(cap_count!=target || last_cap[10]!=1 || {last_cap[11],last_cap[12]}!=16'h0106 || last_cap[13]!=fmt || last_cap[14]!=3)$fatal(1,"capabilities mismatch");
        end
    endtask
    task load_mask(''')
    s=replace(s,'query(0,-1,0);send_command(3,0,0);', 'query(0,-1,0);capabilities(1);send_command(15,49,2);send_command(3,0,0);')
    s=replace(s,'        // Real AXI read faults are sticky until common reset.', '''        capabilities(1);send_command(15,2,2);send_command(15,49,0);capabilities(49);
        query(0,-1,0);passed("format_capability_selection_invalidates_old_metadata");
        send_command(2,{16'd3,16'd0,16'd0,16'd1},0);
        send_command(15,1,3);await_capture();query(1,1,0);
        if(last_metadata[154]!=49 || {last_metadata[158],last_metadata[159],last_metadata[160],last_metadata[161]}!=364)$fatal(1,"gray ROI metadata");
        passed("gray_odd_roi_with_busy_format_change_rejected");
        send_command(2,{16'd3,16'd0,16'd0,16'd1},0);
        wait(dut.u_source.owner_state==4 && dut.u_source.packets.pixels>=9);
        send_command(13,{dut.request_counter,32'd0},0);
        waits=0;while(dut.owner_busy && waits<300000)begin @(negedge rgmii_rx_clk_i);#1;waits++;end
        if(dut.owner_busy || dut.last_valid)$fatal(1,"gray cancel did not retire");query(0,2,3);
        passed("gray_cancel_during_analysis_does_not_commit");
        send_command(6,{16'd0,16'd0,16'd32,16'd32},0);load_mask(32,32,2);
        send_command(2,{16'd3,16'd0,16'd0,16'd2},0);await_capture();query(1,3,0);passed("gray_full_saved_domain_h1_h2_and_drain");
        send_command(15,1,0);capabilities(1);query(0,-1,0);
        send_command(2,{16'd3,16'd0,16'd0,16'd2},0);await_capture();query(1,4,0);passed("rgb_recovery_after_gray_selection");
        send_command(15,49,0);send_command(8,64'h1234567812345678,0);capabilities(1);query(0,-1,0);
        if(dut.request_counter!=0)$fatal(1,"session did not reset request context");passed("fresh_session_restores_rgb_and_invalidates_metadata");
        // Real AXI read faults are sticky until common reset.''')
    s=replace(s,"send_command(2,{16'd3,16'd0,16'd0,16'd1},1);\n        if(dut.owner_busy || !dut.source_busy", "send_command(2,{16'd3,16'd0,16'd0,16'd2},1);\n        if(dut.owner_busy || !dut.source_busy")
    s=replace(s,'IDENTITY_BOARD_ALL_PASS', 'TRANSPORT_BOARD_ALL_PASS')
    target=out/'tb_transport_board.sv';target.write_text(s,encoding='utf-8');return target

def audit_board(out):
    raw=(out/'packets.bin').read_bytes();rows=list(csv.DictReader((out/'packets_index.csv').open()))
    commands=list(csv.DictReader((out/'commands.csv').open()))
    expected_metadata=[int(r['sequence']) for r in commands if int(r['kind'])==9]
    expected_caps=[int(r['sequence']) for r in commands if int(r['kind'])==14]
    images={};offset=0;decoded=[];caps=0;negative=0
    for row in rows:
        n=int(row['length']);packet=raw[offset:offset+n];offset+=n;kind=int(row['kind'])
        if len(packet)!=n:raise ValueError('truncated packet capture')
        if kind==0x90:
            fields=host.codec.HEADER.unpack(packet[:20]);fid,pid,count=fields[3:6]
            if fid not in images:images[fid]={}
            if pid in images[fid]:raise ValueError('duplicate simulated packet')
            images[fid][pid]=packet
        elif kind==0x86:
            host.decode_capabilities(packet,expected_caps.pop(0));caps+=1
        elif kind==0x85:
            seq=expected_metadata.pop(0);m=host.decode_metadata(packet,seq)
            if not m['valid']:continue
            tag=m['identity'];fid=tag['frame_id'];x,y,w,h=m['roi']
            source=((np.arange(1024,dtype=np.uint32)*13)^(tag['dvp_sequence']*271)).astype(np.uint16).reshape(32,32)
            rgb=source[y:y+h,x:x+w].astype('>u2').tobytes()
            gray,sat=host.planes_from_payload(rgb,w,h,1)
            expected=rgb if m['pixel_format']==1 else host.codec.encode(gray,sat)
            payload=b''.join(images[fid][k][20:] for k in range(len(images[fid])))
            if payload!=expected:raise ValueError('DVP -> FIFO -> encoded network bytes mismatch')
            board=(np.arange(w*h).reshape(h,w)%5<2)
            def receiver():return host.StrictReceiver(identity={k:tag[k] for k in host.REQUEST_KEYS},parameters=m['parameters'],roi=m['roi'],board=board,pixel_format=m['pixel_format'],started=0,full_frame_pixels=1024)
            r=receiver()
            # The strict adapter also handles network reordering and identical
            # duplicates; it never publishes a plane from add_packet.
            order=list(reversed(sorted(images[fid])))
            for pid in order:
                if r.add_packet(images[fid][pid],now=0) is not None:raise ValueError('premature host publication')
            r.add_packet(images[fid][order[0]],now=0)
            result=r.finalize(packet,expected_query_seq=seq,now=0)
            if not np.array_equal(result['gray'],gray) or not np.array_equal(result['sat'],sat):raise ValueError('host planes differ')
            decoded.append({'identity':tag,'roi':m['roi'],'format':m['pixel_format'],'bytes':len(payload),'payload_sha256':hashlib.sha256(payload).hexdigest(),'payload_crc64':f"{m['payload_crc64']:016x}",'exact_source_bytes_and_H1_H2':True})
            images.pop(fid)
    if offset!=len(raw) or len(decoded)!=7 or expected_metadata or expected_caps or {m['format'] for m in decoded}!={1,49}:raise ValueError('missing committed format/query cases')
    dump(out/'packet_audit.json',{'status':'PASS','packets':len(rows),'capabilities':caps,'committed_images':decoded,'hardware_tested':False,'physical_freshness_verified':False})
    return decoded

def board(out,bin_path):
    out.mkdir();tb=board_tb(out);root=REPO/TJ;ymw=REPO/'YMW/work/auto_exposure_0105_20261015/dependencies/ymw'
    names=('rgb565_gray.v','roi_h1_stream.v','h2_background9.v','ddr_saved_fifo_reader.v','h2_saved_line_cache.v','tj_ddr_analysis_source.v','axi4_to_fifo_epoch.v','cdc_snapshot_mailbox.v','frame_identity_tracker.v','capture_identity_bridge.v','frozen_frame_owner.v','executed_configuration.v','board_mask_store.v','reset_release_sync.v','ov5640_manual_bridge_identity.v')
    sources=[root/'rtl'/n for n in names]
    sources += [p for p in sorted((ymw/'src').glob('*.v')) if p.name not in ('bx72_1080p_udp_top.v','lght_core_camera.v','ov5640_manual_bridge.v')]
    sources += [HERE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v',HERE/'transport_packet_store.v',HERE/'transport_layout.v']
    sources += sorted((HERE/'derived').glob('*.v'))+[root/'sim/board_boundary_models.sv',tb]
    receipt=simulate(out,'tb_transport_board',sources,bin_path,'TRANSPORT_BOARD_ALL_PASS 15')
    decoded=audit_board(out)
    return {'cases':15,'committed_images':len(decoded),'source_sha256':receipt,'limits':'Physical clocks, MIG/DDR/FIFO and pin/network/SCCB-register boundaries are models; app/router/encoding/ownership/H1/H2 are RTL.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--vivado-bin',type=Path,default=Path('F:/Xilinx/Vivado/2018.3/bin'));parser.add_argument('--only',choices=['unit','board','all'],default='all');a=parser.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();generate()
    report={'hardware_tested':False,'bit_generated':False,'base_commit':PIN,'reports':{}}
    if a.only in ('unit','all'):report['reports']['unit']=unit(out/'unit',a.vivado_bin)
    if a.only in ('board','all'):report['reports']['board']=board(out/'board',a.vivado_bin)
    report.update(status='PASS',wall_seconds=round(time.monotonic()-start,3))
    dump(out/'verification.json',report);print(json.dumps({k:v for k,v in report.items() if k!='reports'},indent=2),flush=True)

if __name__=='__main__':main()
