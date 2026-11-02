"""Actual XSim of new counters and original adversarial NET contract plus0109."""
import argparse,json,sys
from pathlib import Path
from derive_candidate import HERE,REPO,original,replace,main as derive
sys.path.insert(0,str(HERE.parent/'fusion_offload_0108_20261028'))
from run_real_rtl import simulate

def testbench():
    tb=original('sim/tb_net_service.sv')
    tb=replace(tb,'    fusion_net_service #(','''    reg perf_h2_start=0,perf_h2_valid=0,perf_h2_ready=1,perf_h2_finish=0,perf_h2_success=1;
    reg profile_wrong_kind=0;
    fusion_net_service #(''')
    tb=replace(tb,'.clk(clk),.reset(reset),.session_changed(session_changed),','.clk(clk),.reset(reset),.session_changed(session_changed),\n        .perf_h2_start(perf_h2_start),.perf_h2_valid(perf_h2_valid),.perf_h2_ready(perf_h2_ready),.perf_h2_finish(perf_h2_finish),.perf_h2_success(perf_h2_success),')
    tb=tb.replace('header[63]!=8','header[63]!=9')
    tb=replace(tb,"pending_reply<=ui_response(0,ui_cmd_data[503:472],ui_cmd_data[471:440],bridge_request,0);pending_ui<=7;",'''pending_reply<=ui_response(0,ui_cmd_data[503:472],ui_cmd_data[471:440],bridge_request,0);pending_ui<=7;
                    if(ui_cmd_data[511:504]==9&&!profile_wrong_kind)begin
                        pending_reply<=ui_response(3,ui_cmd_data[503:472],ui_cmd_data[471:440],bridge_request,0);
                        pending_reply[129:128]<=2'b01;
                        pending_reply[127:0]<=ui_cmd_data[439:408]==1 ? {32'd500,32'd62,32'd4,32'd6} : {32'd601,32'd125,32'd62,32'd3};
                    end''')
    tb=replace(tb,'    task capture_frame(','''    task payload_rpc(input [7:0] op,input [63:0] args,input integer amount);
        reg [31:0] c;
        begin
            sequence_number=sequence_number+1;start_rpc(op,args,sequence_number);receive(0,amount);c=32'hffffffff;
            for(integer i=0;i<amount;i=i+1)c=dut.crc_byte(c,header[64+i]);
            if({header[52],header[53],header[54],header[55]}!==~c)$fatal(1,"0109 profile/config CRC");
        end
    endtask
    task capture_frame(''')
    tb=replace(tb,'        mask_matches=0;call_rpc(17,0,3);', '''        call_rpc(16,{32'd6,32'd0},2);call_rpc(16,{32'd7,32'd1117},2);
        if(dut.configuration_words[6]!=400||dut.configuration_words[7]!=800)$fatal(1,"invalid exposure mutated config");
        call_rpc(16,{32'd6,32'd900},0);call_rpc(17,0,2);call_rpc(16,{32'd6,32'd400},0);
        payload_rpc(27,0,16);
        if({header[64],header[65],header[66],header[67]}!=32'h474a4339||{header[68],header[69]}!=400||{header[70],header[71]}!=800)$fatal(1,"config echo");
        pass("0109_exposure_range_order_echo");
        mask_matches=0;call_rpc(17,0,3);''')
    tb=replace(tb,'        auto_reply=0;call_rpc(17,0,6);', '''        model_group=model_group+1;model_slots=0;model_published=0;
        call_rpc(16,{32'd0,model_group[63:32]},0);call_rpc(16,{32'd1,model_group[31:0]},0);
        call_rpc(16,{32'd6,32'd300},0);call_rpc(16,{32'd7,32'd700},0);call_rpc(17,0,0);
        call_rpc(16,{32'd6,32'd400},3);if(dut.group_low!=300||dut.group_high!=700)$fatal(1,"group exposure not frozen");
        parameters={16'd400,16'd16,4'd0,4'd1,8'd128,8'd1,8'd3};call_rpc(18,{32'd1001,32'd1},2);
        parameters[63:48]=300;call_rpc(18,{32'd1001,32'd1},0);capture_frame(0);call_rpc(26,{32'd0,32'd1001},3);
        perf_h2_start=1;tick();perf_h2_start=0;perf_h2_valid=1;repeat(247)tick();
        perf_h2_ready=0;repeat(3)tick();perf_h2_ready=1;perf_h2_valid=0;perf_h2_finish=1;tick();perf_h2_finish=0;
        bridge_done(0,0);call_rpc(20,{32'd0,32'h12345678},0);call_rpc(21,{32'd1,32'hbeef1234},0);
        call_rpc(22,{32'd1001,32'd1},0);complete_fuse();call_rpc(19,0,0);
        payload_rpc(26,{32'd0,32'd1001},28);
        if({header[64],header[65],header[66],header[67]}!=32'h474a5039||{header[72],header[73],header[74],header[75]}!=125000000||
            {header[76],header[77],header[78],header[79]}!=252||{header[80],header[81],header[82],header[83]}!=247||{header[84],header[85],header[86],header[87]}!=3)$fatal(1,"H2 service meter values");
        pass("0109_manual_pair_actual_ARM_and_NET_counter");
        payload_rpc(26,{32'd1,32'd1001},28);if({header[76],header[77],header[78],header[79]}!=500)$fatal(1,"UI scratch stats");
        payload_rpc(26,{32'd2,32'd1001},28);if({header[76],header[77],header[78],header[79]}!=601)$fatal(1,"UI merge stats");
        call_rpc(26,{32'd3,32'd1001},2);call_rpc(26,{32'd0,32'd1000},2);
        profile_wrong_kind=1;call_rpc(26,{32'd1,32'd1001},7);profile_wrong_kind=0;
        pass("0109_UI_counter_pages_identity_crc_and_wrong_kind");
        call_rpc(25,model_group,0);call_rpc(26,{32'd0,32'd1001},3);
        session_changed=1;tick();session_changed=0;tick();if(dut.configuration_words[6]!=400||dut.configuration_words[7]!=800||dut.h2_valid)$fatal(1,"new session stale config/profile");
        pass("0109_new_session_clears_profile_and_exposure_defaults");
        auto_reply=0;call_rpc(17,0,6);''')
    tb=tb.replace('NET_SERVICE_ALL_PASS','NET_SERVICE_0109_ALL_PASS')
    return tb

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();derive();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    meter=out/'meter';meter.mkdir();simulate(meter,'tb_stage_cycle_meter',[HERE/'rtl/stage_cycle_meter.v',HERE/'sim/tb_stage_cycle_meter.sv'],'STAGE_METER_ALL_PASS 7')
    net=out/'net';net.mkdir();tb=net/'tb_net_service.sv';tb.write_text(testbench(),encoding='utf-8')
    simulate(net,'tb_net_service',[HERE/'rtl/stage_cycle_meter.v',HERE/'generated/rtl/fusion_net_service.v',tb],'NET_SERVICE_0109_ALL_PASS 15')
    (out/'VERIFICATION.json').write_text(json.dumps(dict(status='PASS',meter_cases=7,net_cases=15,physical_hardware=False,bit_generated=False),indent=2)+'\n',encoding='utf-8');print('0109_NET_AND_METERS_PASS',flush=True)
if __name__=='__main__':main()
