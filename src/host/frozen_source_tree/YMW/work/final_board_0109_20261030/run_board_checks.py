"""0109 actual application/CDC/H2/DDR-fusion RTL, explicit physical boundary model."""
import argparse,importlib.util,json,sys
from pathlib import Path
from derive_candidate import HERE,REPO,replace,main as derive
PARENT=HERE.parent/'fusion_board_0108_20261028'
sys.path.insert(0,str(PARENT))
spec=importlib.util.spec_from_file_location('_pinned0108_board_models',PARENT/'run_board_protocol_checks.py')
parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--format',type=int,choices=(49,50),default=49)
    p.add_argument('--low',type=int,default=300);p.add_argument('--high',type=int,default=700);p.add_argument('--reset-mid-group',action='store_true');a=p.parse_args()
    if not 1<=a.low<a.high<=1116:raise ValueError('Legal ordered exposure pair required')
    derive();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);model=parent.boundary(out);tb=parent.testbench(out,a.format,a.reset_mid_group)
    text=tb.read_text(encoding='utf-8-sig').replace("16'h0108","16'h0109")
    text=replace(text,'        off_command(17,0,0);send_command(6,',f'        off_command(16,{{32\'d6,32\'d{a.low}}},0);off_command(16,{{32\'d7,32\'d{a.high}}},0);\n        off_command(17,0,0);send_command(6,')
    text=replace(text,"16'(slot%2 ? 400 : 800)",f"16'(slot%2 ? {a.low} : {a.high})")
    anchor='            if(slot<8&&last_off[13][1])$fatal(1,"published before eight frames");'
    metrics='''            off_command(26,{32'd0,32'(slot)},0);
            if({last_off[74],last_off[75],last_off[76],last_off[77]}!=32'h474a5039||
               {last_off[90],last_off[91],last_off[92],last_off[93]}!=1024)$fatal(1,"real H2 profile pixel count");
            off_command(26,{32'd1,32'(slot)},0);
            if({last_off[90],last_off[91],last_off[92],last_off[93]}!=256||
               {last_off[94],last_off[95],last_off[96],last_off[97]}!=16)$fatal(1,"real scratch profile handshakes");
            off_command(26,{32'd2,32'(slot)},0);
            if({last_off[90],last_off[91],last_off[92],last_off[93]}!=(slot==1 ? 256 : 512)||
               {last_off[94],last_off[95],last_off[96],last_off[97]}!=256)$fatal(1,"real fusion profile handshakes");
'''
    text=replace(text,anchor,metrics+anchor)
    text=replace(text,'        passed("0108_eight_actual_sensor_H2_DDR_table_and_fusion");','        passed("0109_all_eight_bound_NET_scratch_fusion_counters");\n        passed("0108_eight_actual_sensor_H2_DDR_table_and_fusion");')
    tb.write_text(text,encoding='utf-8')
    for f in (PARENT/'derived').glob('*.vh'):(out/f.name).write_bytes(f.read_bytes())
    names=('rgb565_gray.v','roi_h1_stream.v','h2_background9.v','ddr_saved_fifo_reader.v','h2_saved_line_cache.v','tj_ddr_analysis_source.v','axi4_to_fifo_epoch.v','cdc_snapshot_mailbox.v','frame_identity_tracker.v','capture_identity_bridge.v','frozen_frame_owner.v','executed_configuration.v','board_mask_store.v','reset_release_sync.v','ov5640_manual_bridge_identity.v')
    sources=[parent.TJ/'rtl'/n for n in names];ymw=REPO/'YMW/work/auto_exposure_0105_20261015/dependencies/ymw'
    sources += [p for p in sorted((ymw/'src').glob('*.v')) if p.name not in ('bx72_1080p_udp_top.v','lght_core_camera.v','ov5640_manual_bridge.v')]
    sources += [REPO/'YMW/work/gray_sat_0105_20261025/gray_sat_encoder.v']+[parent.ACCEPT/n for n in ('dual_view_encoder.v','transport_packet_store.v','transport_layout.v')]
    sources += [parent.KERNEL/'rtl'/n for n in ('maxabs8_pixel.v','fusion_group_guard.v','h2_scratch_writer.v')]
    inherited=sorted((PARENT/'rtl').glob('*.v'))+[p for p in sorted((PARENT/'derived').glob('*.v')) if p.name!='ddr3_ctrl_offload.v']
    overrides={p.name:p for p in (HERE/'generated').rglob('*.v')}
    sources += [overrides.get(p.name,p) for p in inherited]+[HERE/'rtl/stage_cycle_meter.v',model,tb]
    count=24 if a.reset_mid_group else 22
    hashes=parent.simulate(out,'tb_transport_board',sources,'OFFLOAD_BOARD_ALL_PASS '+str(count))
    (out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',cases=count,format=a.format,low=a.low,high=a.high,
        reset_mid_AXI=a.reset_mid_group,profiles='All8 slots; actual NET/H2, scratch W/B and fusion R/W counts checked',source_sha256=hashes,
        physical_hardware=False,boundary='Physical sensor/network/FIFO/MIG are models; actual application, H2, CDC, AXI, fusion and serialization RTL'),indent=2)+'\n',encoding='utf-8')
    print('0109_BOARD_RTL_PASS',count,flush=True)
if __name__=='__main__':main()
