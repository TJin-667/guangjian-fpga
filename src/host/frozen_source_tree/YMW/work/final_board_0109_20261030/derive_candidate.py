"""Derive0109 from pinned0108 bytes, without writing any parent directory."""
import hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
BASE='8771bdf8dafdbeb3799a5526d17e92ae93b74226'
PARENT='YMW/work/fusion_board_0108_20261028/'

def sha(b):return hashlib.sha256(b).hexdigest()
def replace(s,old,new,n=1):
    if s.count(old)!=n:raise ValueError('Changed0108 anchor '+old[:100])
    return s.replace(old,new)
def original(name):
    path=PARENT+name;b=subprocess.check_output(['git','show',BASE+':'+path],cwd=REPO)
    if (REPO/path).read_bytes()!=b:raise ValueError('Immutable0108 source changed '+path)
    return b.decode('utf-8').replace('\r\n','\n')
def save(name,s):
    p=HERE/'generated'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(s.encode('utf-8'))

def main():
    net=original('rtl/fusion_net_service.v')
    net=replace(net,'    input wire ui_fault','    input wire perf_h2_start,perf_h2_valid,perf_h2_ready,perf_h2_finish,perf_h2_success,\n    input wire ui_fault')
    net=replace(net,'UI_WAIT=3,BUILD=4;','UI_WAIT=3,BUILD=4,PROFILE_COPY=5;')
    net=replace(net,'configuration_words[0:5]','configuration_words[0:7]')
    net=replace(net,'reg [63:0] group_id,group_geometry;', 'reg [15:0] group_low,group_high;\n    reg [63:0] group_id,group_geometry;')
    net=replace(net,"(rpc_args[0] ? 16'd400 : 16'd800)",'(rpc_args[0] ? group_low : group_high)')
    net=replace(net,'association_error,3\'d0,scratch_error,8\'d8',"association_error,3'd0,scratch_error,8'd9")
    marker='    integer n;'
    block='''    // PROFILE pages reuse the immutable response buffer and existing reply CDC.
    reg [223:0] profile_data;reg [5:0] profile_index,profile_length;
    wire [7:0] profile_byte=profile_data[223-profile_index*8-:8];
    wire [31:0] profile_next_crc=crc_byte(payload_crc,profile_byte);
    // Exactly one synchronous write port preserves distributed RAM inference.
    wire reply_write=(copy_busy&&copy_allowed)||(state==PROFILE_COPY);
    wire [9:0] reply_write_address=(state==PROFILE_COPY) ? profile_index : copy_base+copy_byte;
    wire [7:0] reply_write_byte=(state==PROFILE_COPY) ? profile_byte : copy_value;
    always @(posedge clk)if(!reset&&reply_write)response_payload[reply_write_address]<=reply_write_byte;
    wire h2_clear=(state==IDLE&&rpc_valid&&rpc_ready&&sequence_forward&&rpc_op==18&&!group_lock)||
        (state==IDLE&&rpc_valid&&rpc_ready&&sequence_forward&&rpc_op==17&&!group_lock)||
        (state==ARM_SEND&&bridge_cfg_valid&&bridge_cfg_ready)||
        (session_changed&&!group_lock);
    wire h2_busy,h2_valid,h2_overflow;wire [31:0] h2_cycles,h2_pixels,h2_stalls,h2_blocked;
    stage_cycle_meter h2_meter(.clk(clk),.reset(reset),.clear(h2_clear),
        .start(perf_h2_start&&capture_seen),.finish(perf_h2_finish),.success(perf_h2_success&&!association_error),
        .event0(perf_h2_valid&&perf_h2_ready),.event1(perf_h2_valid&&!perf_h2_ready),.blocked(perf_h2_valid&&!perf_h2_ready),
        .busy(h2_busy),.valid(h2_valid),.overflow(h2_overflow),.cycles(h2_cycles),.count0(h2_pixels),.count1(h2_stalls),.blocked_cycles(h2_blocked));
    task start_profile(input [223:0] data,input [5:0] length);
        begin profile_data<=data;profile_index<=0;profile_length<=length;payload_crc<=32'hffffffff;state<=PROFILE_COPY;end
    endtask
'''
    net=replace(net,marker,block+marker)
    net=replace(net,'response_payload[copy_base+copy_byte]<=copy_value;','')
    net=replace(net,'state<=IDLE;group_lock<=0;group_id<=0;', 'state<=IDLE;group_lock<=0;group_low<=400;group_high<=800;profile_data<=0;profile_index<=0;profile_length<=0;group_id<=0;')
    net=replace(net,'for(n=0;n<6;n=n+1)configuration_words[n]<=0;','for(n=0;n<6;n=n+1)configuration_words[n]<=0;configuration_words[6]<=400;configuration_words[7]<=800;')
    net=replace(net,'begin last_reply_valid<=0;sequence_valid<=0;scratch_ready<=0;armed<=0;end','begin last_reply_valid<=0;sequence_valid<=0;scratch_ready<=0;armed<=0;configuration_words[6]<=400;configuration_words[7]<=800;end')
    net=replace(net,'ui_snapshot<=ui_reply_data;','if(ui_kind!=3)ui_snapshot<=ui_reply_data;')
    net=replace(net,'if(state==UI_WAIT&&ui_ticket==waiting_ticket&&(ui_kind==0||ui_kind==2))begin','''if(state==UI_WAIT&&ui_ticket==waiting_ticket&&ui_kind==3&&held_op==26)begin
                    if(ui_status!=0||ui_cookie!=arm_cookie||ui_request!=arm_request||!ui_reply_data[128]||ui_reply_data[129])begin reply_status<=2;state<=BUILD;end
                    else start_profile({32'h474a5039,held_args[63:32],32'd100000000,ui_reply_data[127:0]},28);
                end
                if(state==UI_WAIT&&ui_ticket==waiting_ticket&&(ui_kind==0||ui_kind==2))begin''')
    net=replace(net,'reply_status<=ui_status;state<=BUILD;', 'reply_status<=(held_op==26&&ui_status==0) ? 8\'d7 : ui_status;state<=BUILD;')
    net=replace(net,'if(group_lock||bridge_active||job_busy||rpc_args[63:32]>=6)reply_status<=3;\n                            else configuration_words[rpc_args[34:32]]<=rpc_args[31:0];state<=BUILD;', '''if(group_lock||bridge_active||job_busy)reply_status<=3;
                            else if(rpc_args[63:32]>=8||(rpc_args[63:32]>=6&&(rpc_args[31:0]<1||rpc_args[31:0]>1116)))reply_status<=2;
                            else configuration_words[rpc_args[34:32]]<=rpc_args[31:0];state<=BUILD;''')
    net=replace(net,'else begin\n                                group_id<={configuration_words[0],configuration_words[1]};', '''else if(configuration_words[6]<1||configuration_words[7]>1116||configuration_words[6]>=configuration_words[7])begin reply_status<=2;state<=BUILD;end
                            else begin
                                group_low<=configuration_words[6][15:0];group_high<=configuration_words[7][15:0];
                                group_id<={configuration_words[0],configuration_words[1]};''')
    net=replace(net,'                        19,31:state<=BUILD;', '''                        19,31:state<=BUILD;
                        26:begin
                            if(!group_lock||legacy_busy||bridge_active||job_busy||done_slots==0||done_slots!=arm_slot)begin reply_status<=3;state<=BUILD;end
                            else if(rpc_args[63:32]>2||rpc_args[31:0]!=arm_cookie||!h2_valid||h2_overflow||h2_pixels!=frame_pixels)begin reply_status<=2;state<=BUILD;end
                            else if(rpc_args[63:32]==0)start_profile({32'h474a5039,32'd0,32'd125000000,h2_cycles,h2_pixels,h2_stalls,h2_blocked},28);
                            else state<=BUILD;
                        end
                        27:begin
                            if(rpc_args!=0)begin reply_status<=2;state<=BUILD;end
                            else start_profile({32'h474a4339,(group_lock ? group_low : configuration_words[6][15:0]),(group_lock ? group_high : configuration_words[7][15:0]),16'd16,8'd128,8'd3,16'd1116,8'd1,8'd9,96'd0},16);
                        end''')
    net=replace(net,'                BUILD:begin','''                PROFILE_COPY:begin
                    payload_crc<=profile_next_crc;
                    if(profile_index==profile_length-1)respond(0,{26'd0,profile_length},~profile_next_crc);
                    else profile_index<=profile_index+1;
                end
                BUILD:begin''')
    net=replace(net,'else if(!ui_dispatched&&held_op==25)send_ui(8,held_args,0);','else if(!ui_dispatched&&held_op==25)send_ui(8,held_args,0);\n                    else if(!ui_dispatched&&held_op==26)send_ui(9,held_args,arm_cookie);')
    save('rtl/fusion_net_service.v',net)

    bridge=original('rtl/h2_offload_cdc_bridge.v')
    bridge=replace(bridge,'    output wire [3:0] m_axi_awid,', '''    output wire perf_writer_start,perf_writer_finish,perf_writer_success,perf_writer_write,perf_writer_response,perf_writer_blocked,
    output wire [31:0] perf_writer_cookie,
    output wire [3:0] m_axi_awid,''')
    bridge=replace(bridge,'    wire [3:0] upstream_error=', '''    assign perf_writer_start=cfg_dst_valid&&cfg_dst_ready;
    assign perf_writer_finish=writer_result_valid;
    assign perf_writer_success=writer_error==0&&!writer_fence;
    assign perf_writer_write=m_axi_wvalid&&m_axi_wready;
    assign perf_writer_response=m_axi_bvalid&&m_axi_bready;
    assign perf_writer_blocked=(m_axi_awvalid&&!m_axi_awready)||(m_axi_wvalid&&!m_axi_wready);
    assign perf_writer_cookie=cfg_dst_data[95:64];
    wire [3:0] upstream_error=''')
    save('rtl/h2_offload_cdc_bridge.v',bridge)

    ui=original('rtl/fusion_ui_backend.v')
    ui=replace(ui,'    input wire [15:0] scratch_width,scratch_height,','''    input wire [15:0] scratch_width,scratch_height,
    input wire perf_writer_start,perf_writer_finish,perf_writer_success,perf_writer_write,perf_writer_response,perf_writer_blocked,
    input wire [31:0] perf_writer_cookie,''')
    marker='    always @(posedge clk)begin'
    block='''    wire perf_clear=(state==BEGIN_WAIT&&guard_active)||
        (state==EXEC&&op==5&&published&&args==published_group)||
        (state==EXEC&&op==8&&!dma_busy&&!published&&guard_active&&args==group_id);
    reg [31:0] perf_scratch_cookie,perf_fuse_cookie;
    wire scratch_meter_busy,scratch_meter_valid,scratch_meter_overflow;
    wire [31:0] scratch_cycles,scratch_writes,scratch_responses,scratch_blocked;
    wire fuse_meter_busy,fuse_meter_valid,fuse_meter_overflow;
    wire [31:0] fuse_cycles,fuse_reads,fuse_writes,fuse_blocked;
    stage_cycle_meter scratch_meter(.clk(clk),.reset(reset),.clear(perf_clear),.start(perf_writer_start),.finish(perf_writer_finish),.success(perf_writer_success),
        .event0(perf_writer_write),.event1(perf_writer_response),.blocked(perf_writer_blocked),.busy(scratch_meter_busy),.valid(scratch_meter_valid),.overflow(scratch_meter_overflow),
        .cycles(scratch_cycles),.count0(scratch_writes),.count1(scratch_responses),.blocked_cycles(scratch_blocked));
    stage_cycle_meter fuse_meter(.clk(clk),.reset(reset),.clear(perf_clear),.start(worker_cfg_valid&&worker_cfg_ready),
        .finish(worker_result_valid&&worker_result_ready),.success(worker_error==0&&!worker_fence),
        .event0(m_rvalid[0]&&m_rready[0]),.event1(m_wvalid[0]&&m_wready[0]),
        .blocked((m_rvalid[0]&&!m_rready[0])||(m_wvalid[0]&&!m_wready[0])||(m_arvalid[0]&&!m_arready[0])||(m_awvalid[0]&&!m_awready[0])),
        .busy(fuse_meter_busy),.valid(fuse_meter_valid),.overflow(fuse_meter_overflow),
        .cycles(fuse_cycles),.count0(fuse_reads),.count1(fuse_writes),.blocked_cycles(fuse_blocked));
    always @(posedge clk)begin
        if(reset||perf_clear)begin perf_scratch_cookie<=0;perf_fuse_cookie<=0;end
        else begin
            if(perf_writer_start)perf_scratch_cookie<=perf_writer_cookie;
            if(worker_cfg_valid&&worker_cfg_ready)perf_fuse_cookie<=fuse_cookie;
        end
    end
'''
    ui=replace(ui,marker,block+marker)
    ui=replace(ui,'                        default:begin reply_valid<=1;', '''                        9:begin
                            reply_valid<=1;state<=IDLE;reply_data<=response(3,0,ticket,cookie,fuse_request);
                            reply_data[129:128]<=2'b00;reply_data[127:0]<=0;
                            if(dma_busy||cookie!=fuse_cookie||args[31:0]!=cookie||args[63:32]<1||args[63:32]>2)reply_data[151:144]<=2;
                            else if(args[63:32]==1&&scratch_meter_valid&&!scratch_meter_overflow&&perf_scratch_cookie==cookie)begin
                                reply_data[129:128]<=2'b01;reply_data[127:0]<={scratch_cycles,scratch_writes,scratch_responses,scratch_blocked};
                            end else if(args[63:32]==2&&fuse_meter_valid&&!fuse_meter_overflow&&perf_fuse_cookie==cookie)begin
                                reply_data[129:128]<=2'b01;reply_data[127:0]<={fuse_cycles,fuse_reads,fuse_writes,fuse_blocked};
                            end else reply_data[151:144]<=2;
                        end
                        default:begin reply_valid<=1;''')
    save('rtl/fusion_ui_backend.v',ui)

    tap=original('derived/tj_frozen_packet_source.v')
    tap=replace(tap,'    output wire h2_finish,','    output wire h2_begin,\n    output wire h2_finish,')
    tap=replace(tap,'    wire analysis_start,analysis_cancel,analysis_done;','    wire analysis_start,analysis_cancel,analysis_done,analysis_cfg_ready;\n    assign h2_begin=analysis_start&&analysis_cfg_ready;')
    tap=replace(tap,'.cfg_valid(analysis_start),.cfg_ready(),','.cfg_valid(analysis_start),.cfg_ready(analysis_cfg_ready),')
    save('rtl/tj_frozen_packet_source.v',tap)
    router=original('derived/lght_identity_router.v').replace("16'h0108","16'h0109")
    save('rtl/lght_identity_router.v',router)
    core=original('derived/lght_core_camera_identity.v')
    core=replace(core,'12:tx_data=1;13:tx_data=8;','12:tx_data=1;13:tx_data=9;')
    save('integration/lght_core_camera_identity.v',core)
    top=original('derived/bx72_ddr_identity_top.v')
    top=replace(top,'    wire off_h2_valid,','    wire off_h2_begin;\n    wire off_perf_start,off_perf_finish,off_perf_success,off_perf_write,off_perf_response,off_perf_blocked;wire [31:0] off_perf_cookie;\n    wire off_h2_valid,')
    perf='''.perf_writer_start(off_perf_start),.perf_writer_finish(off_perf_finish),.perf_writer_success(off_perf_success),.perf_writer_write(off_perf_write),.perf_writer_response(off_perf_response),.perf_writer_blocked(off_perf_blocked),.perf_writer_cookie(off_perf_cookie),'''
    top=replace(top,'h2_offload_cdc_bridge u_off_h2_bridge(\n','h2_offload_cdc_bridge u_off_h2_bridge(\n        '+perf+'\n')
    top=replace(top,'fusion_ui_backend u_off_backend(.clk(off_ui_clk),.reset(off_backend_reset),','fusion_ui_backend u_off_backend(.clk(off_ui_clk),.reset(off_backend_reset),\n        '+perf)
    top=replace(top,'fusion_net_service u_off_service(.clk(net_clk),.reset(off_net_reset),','fusion_net_service u_off_service(.clk(net_clk),.reset(off_net_reset),\n        .perf_h2_start(off_h2_begin),.perf_h2_valid(off_h2_valid),.perf_h2_ready(off_h2_ready),.perf_h2_finish(off_h2_finish),.perf_h2_success(off_h2_finish_error==0),')
    top=replace(top,'.h2_finish(off_h2_finish),','.h2_begin(off_h2_begin),.h2_finish(off_h2_finish),')
    save('integration/bx72_ddr_identity_top.v',top)
    files={p.relative_to(HERE).as_posix():sha(p.read_bytes()) for p in sorted((HERE/'generated').rglob('*')) if p.is_file()}
    (HERE/'DERIVATION.json').write_text(json.dumps(dict(parent_commit=BASE,parent_path=PARENT,generated_sha256=files,numerical_kernels_changed=False,CDC_widths_changed=False,board_commands=0),indent=2)+'\n',encoding='utf-8')
    print('DERIVED0109',len(files),flush=True)

if __name__=='__main__':main()
