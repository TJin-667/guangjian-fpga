"""Board-top RTL integration and 23-bit transport-layout verification."""
import argparse,csv,hashlib,json,sys,time
from pathlib import Path
import numpy as np
import generate_acceptance as gen
import host_transport as wire
import dual_view
sys.path.append(str(gen.BASE))
import run_verification as old

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();binpath=Path('F:/Xilinx/Vivado/2018.3/bin')
    layout=out/'layout';layout.mkdir()
    s=(gen.BASE/'tb_transport_layout.sv').read_text().replace('fmt<2','fmt<3').replace('fmt==0?1:49','fmt==0?1:(fmt==1?49:50)')
    s=s.replace('cycles!=22','cycles!=23').replace('expected_size=format_value==49 ?',
        'expected_size=format_value==50 ? pixels*3+(pixels+7)/8 : format_value==49 ?')
    (layout/'tb_transport_layout.sv').write_text(s)
    lh=old.simulate(layout,'tb_transport_layout',[gen.HERE/'transport_layout.v',layout/'tb_transport_layout.sv'],binpath,'TRANSPORT_LAYOUT_ALL_PASS 868')
    board=out/'board';board.mkdir();tb=old.board_tb(board)
    s=tb.read_text().replace("16'h0106","16'h0107").replace('last_cap[14]!=3','last_cap[14]!=7')
    extra='''
        send_command(15,50,0);capabilities(50);
        send_command(2,{16'd3,16'd0,16'd0,16'd2},0);await_capture();query(1,1,0);
        if(last_metadata[154]!=50 || {last_metadata[158],last_metadata[159],last_metadata[160],last_metadata[161]}!=3200)$fatal(1,"dual native metadata");
        passed("same_frozen_RGB_gray_SAT_single_capture");
        // Reset a partly uploaded mask and reject an unbound CAP afterwards.
        send_command(10,64'd0,0);
        reset_n=0;uart_model_reset=1;repeat(20)@(negedge rgmii_rx_clk_i);
        reset_n=1;uart_model_reset=0;repeat(30)@(negedge rgmii_rx_clk_i);
        query(0,-1,0);capabilities(1);
        if(dut.session_id!=0 || dut.request_counter!=0 || dut.mask_valid || dut.last_valid)$fatal(1,"common reset context leak");
        send_command(2,{16'd2,48'd0},4);passed("common_reset_invalidates_session_mask_and_metadata");
        send_command(8,64'h9988776655443322,0);send_command(12,{16'd1,16'd2,32'd0},0);
        send_command(4,{16'd600,16'd16,32'd0},0);send_command(1,{16'd1,16'd128,32'd0},0);
        load_mask(32,32,0);send_command(15,49,0);
        send_command(2,{16'd2,48'd0},0);await_capture();query(1,1,0);
        if(meta_session!=64'h9988776655443322)$fatal(1,"post-reset stale session");
        passed("common_reset_fresh_session_reconfiguration_and_capture");
'''
    s=s.replace('        // Real AXI read faults are sticky until common reset.',extra+'        // Real AXI read faults are sticky until common reset.')
    s=s.replace('\\"time_ns\\":%0d,','\\"source_frame\\":%0d,\\"time_ns\\":%0d,').replace('name,domain,$time,tag,','name,domain,sensor_frame,$time,tag,')
    s=s.replace("send_command(2,{16'd3,16'd0,16'd0,16'd2},1);", "send_command(2,{16'd2,48'd0},1);")
    tb.write_text(s,encoding='utf-8',newline='\n')
    root=gen.REPO/gen.TJ;ymw=gen.REPO/'YMW/work/auto_exposure_0105_20261015/dependencies/ymw'
    names=('rgb565_gray.v','roi_h1_stream.v','h2_background9.v','ddr_saved_fifo_reader.v','h2_saved_line_cache.v','tj_ddr_analysis_source.v','axi4_to_fifo_epoch.v','cdc_snapshot_mailbox.v','frame_identity_tracker.v','capture_identity_bridge.v','frozen_frame_owner.v','executed_configuration.v','board_mask_store.v','reset_release_sync.v','ov5640_manual_bridge_identity.v')
    sources=[root/'rtl'/n for n in names]+[p for p in sorted((ymw/'src').glob('*.v')) if p.name not in ('bx72_1080p_udp_top.v','lght_core_camera.v','ov5640_manual_bridge.v')]
    sources += [gen.BASE.parent/'gray_sat_0105_20261025/gray_sat_encoder.v',gen.HERE/'dual_view_encoder.v',gen.HERE/'transport_packet_store.v',gen.HERE/'transport_layout.v']
    sources += sorted((gen.HERE/'derived').glob('*.v'))+[root/'sim/board_boundary_models.sv',tb]
    bh=old.simulate(board,'tb_transport_board',sources,binpath,'TRANSPORT_BOARD_ALL_PASS 18')
    raw=(board/'packets.bin').read_bytes();images={};at=0;verified=[];source_frames={}
    for line in (board/'board_trace.jsonl').read_text().splitlines():
        e=json.loads(line)
        if e['event']=='FRAME_START':
            tag=int(e['identity_hex'],16);source_frames[(tag>>192,(tag>>160)&0xffffffff)]=e['source_frame']
    for row in csv.DictReader((board/'packets_index.csv').open()):
        n=int(row['length']);packet=raw[at:at+n];at+=n;kind=packet[5]
        if kind==0x90:
            fields=wire.codec.HEADER.unpack(packet[:20]);fid,pid=fields[3:5]
            if fid not in images:images[fid]={}
            images[fid][pid]=packet
        elif kind==0x86:wire.decode_capabilities(packet,int.from_bytes(packet[6:8],'big'))
        elif kind==0x85:
            seq=int.from_bytes(packet[6:8],'big');m=wire.decode_metadata(packet,seq)
            if not m['valid']:continue
            t=m['identity'];fid=t['frame_id'];x,y,w,h=m['roi']
            source_frame=source_frames[(t['session'],t['request_id'])]
            source=((np.arange(1024,dtype=np.uint32)*13)^(source_frame*271)).astype(np.uint16).reshape(32,32)
            rgb=source[y:y+h,x:x+w].astype('>u2').tobytes();g,sat=wire.planes_from_payload(rgb,w,h,1)
            expected=rgb if m['pixel_format']==1 else wire.codec.encode(g,sat) if m['pixel_format']==49 else dual_view.encode(rgb,g,sat)
            payload=b''.join(images[fid][k][20:] for k in sorted(images[fid]))
            if expected!=payload:raise ValueError('Board network differs from exact DVP source')
            mask=(np.arange(w*h).reshape(h,w)%5<2)
            r=wire.StrictReceiver(identity={k:t[k] for k in wire.REQUEST_KEYS},parameters=m['parameters'],roi=m['roi'],
                board=mask,pixel_format=m['pixel_format'],started=0,full_frame_pixels=1024)
            for k in reversed(sorted(images[fid])):r.add_packet(images[fid][k],now=0)
            r.finalize(packet,expected_query_seq=seq,now=0);images.pop(fid)
            verified.append(dict(identity=t,format=m['pixel_format'],payload_bytes=len(payload),payload_sha256=hashlib.sha256(payload).hexdigest(),all_pixels_sat_crc_h1_h2_equal=True))
    if at!=len(raw) or len(verified)!=9 or {r['format'] for r in verified}!={1,49,50}:raise ValueError('Committed board coverage')
    result=dict(status='PASS',board_cases=18,layout_cases=868,committed_images=verified,layout_source_sha256=lh,board_source_sha256=bh,
        hardware_contacted=False,wall_seconds=time.monotonic()-start,
        limits='Real control/ownership/codec/H1/H2 RTL; physical clocks, PHY, DDR and SCCB boundaries are models.')
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print('BOARD_AND_LAYOUT_PASS',flush=True)

if __name__=='__main__':main()
