// One frame update, four pixels/128-bit AXI beat, 16-beat bursts.
// All addresses are BYTE addresses, 4 KiB aligned. No subword DDR transaction.
// Scratch records: R_n[15:0], gray[23:16], valid[24], reserved[31:25]=0.
// Writes ONLY inactive state memory; success follows every required B response.
// cfg_first never reads uninitialized previous state. Last WSTRB masks padding.
// Abort drains issued AXI traffic. Timeout/protocol corruption latches fence_required:
// reset is safe only together with an external AXI/MIG fence/common reset.
module fusion_axi_frame #(
    parameter integer MAX_PIXELS=2073600,
    parameter integer WATCHDOG_CYCLES=125000000,
    parameter [3:0] AXI_ID=4'h8
)(
    input wire clk,reset,abort_frame,
    input wire cfg_valid,output wire cfg_ready,
    input wire cfg_first,input wire [3:0] cfg_slot,
    input wire [31:0] cfg_pixels,cfg_tag,
    input wire [29:0] cfg_scratch_base,cfg_previous_base,cfg_target_base,
    output wire result_valid,input wire result_ready,
    output reg [3:0] result_error,output reg [31:0] result_tag,written_pixels,
    output reg fence_required,
    output wire [3:0] m_axi_arid,output wire [29:0] m_axi_araddr,
    output wire [7:0] m_axi_arlen,output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,output wire m_axi_arvalid,input wire m_axi_arready,
    input wire [3:0] m_axi_rid,input wire [127:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,input wire m_axi_rlast,m_axi_rvalid,output wire m_axi_rready,
    output wire [3:0] m_axi_awid,output wire [29:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen,output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,output wire m_axi_awvalid,input wire m_axi_awready,
    output wire [127:0] m_axi_wdata,output wire [15:0] m_axi_wstrb,
    output wire m_axi_wlast,m_axi_wvalid,input wire m_axi_wready,
    input wire [3:0] m_axi_bid,input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,output wire m_axi_bready
);
    localparam IDLE=0,SRC_AR=1,SRC_R=2,OLD_AR=3,OLD_R=4,MERGE=5,AW=6,W=7,B=8,RESULT=9,FENCE=10,LOAD=11,PREPARE=12,CONFIG_END=13,CONFIG_CHECK=14,CHECK=15;
    reg [3:0] state;
    reg [29:0] src_base,old_base,dst_base;
    reg [20:0] pixels,offset,remaining_count;
    reg [31:0] watchdog;
    reg [6:0] block_count;
    reg [4:0] beats;
    reg [3:0] beat_index,slot;
    reg first,aborting;
    reg config_simple_ok;
    reg [33:0] src_end,old_end,dst_end;
    reg [127:0] scratch [0:15];
    reg [127:0] history [0:15];
    reg [127:0] updated [0:15];
    reg [15:0] updated_strobes [0:15];
    reg [127:0] scratch_beat,history_beat;
    reg [3:0] active_lanes;
    reg [127:0] merged_beat;
    reg [3:0] merged_error;
    wire [20:0] completed_offset=offset+block_count;
    wire cfg_ok=cfg_pixels>0 && cfg_pixels<=MAX_PIXELS && cfg_pixels<=2073600 && cfg_slot>=1 && cfg_slot<=8 &&
        cfg_first==(cfg_slot==1) && cfg_scratch_base[11:0]==0 && cfg_previous_base[11:0]==0 && cfg_target_base[11:0]==0;
    wire layout_ok=config_simple_ok &&
        src_end<=34'h40000000 && old_end<=34'h40000000 && dst_end<=34'h40000000 &&
        (src_end<={4'b0,dst_base} || dst_end<={4'b0,src_base}) &&
        (old_end<={4'b0,dst_base} || dst_end<={4'b0,old_base}) &&
        (src_end<={4'b0,old_base} || old_end<={4'b0,src_base});
    assign cfg_ready=state==IDLE && !reset && !fence_required;
    assign result_valid=state==RESULT && !reset;
    assign m_axi_arid=AXI_ID;
    assign m_axi_araddr=(state==OLD_AR ? old_base : src_base)+{7'd0,offset,2'd0};
    assign m_axi_arlen={3'd0,beats}-1'b1;
    assign m_axi_arsize=3'd4;assign m_axi_arburst=2'b01;
    // VALID is never withdrawn while READY is low, including after abort.
    assign m_axi_arvalid=(state==SRC_AR || state==OLD_AR) && !reset;
    assign m_axi_rready=(state==SRC_R || state==OLD_R || state==FENCE) && !reset;
    assign m_axi_awid=AXI_ID;assign m_axi_awaddr=dst_base+{7'd0,offset,2'd0};
    assign m_axi_awlen={3'd0,beats}-1'b1;assign m_axi_awsize=3'd4;assign m_axi_awburst=2'b01;
    assign m_axi_awvalid=state==AW && !reset;
    assign m_axi_wdata=updated[beat_index];
    assign m_axi_wstrb=updated_strobes[beat_index];
    assign m_axi_wlast=beat_index==beats-1;
    assign m_axi_wvalid=state==W && !reset;
    assign m_axi_bready=(state==B || state==FENCE) && !reset;
    wire progress=(m_axi_arvalid&&m_axi_arready)||(m_axi_rvalid&&m_axi_rready)||
        (m_axi_awvalid&&m_axi_awready)||(m_axi_wvalid&&m_axi_wready)||(m_axi_bvalid&&m_axi_bready)||state==MERGE||state==LOAD||state==PREPARE||state==CONFIG_END||state==CONFIG_CHECK||state==CHECK;
    wire [127:0] merged;
    wire [3:0] merge_error;
    genvar lane;
    generate for(lane=0;lane<4;lane=lane+1)begin: pixels4
        wire [31:0] record=scratch_beat[32*lane+:32];
        wire [31:0] prior=history_beat[32*lane+:32];
        wire pixel_error;
        maxabs8_pixel pixel(.previous(prior),.residual_n(record[15:0]),.gray(record[23:16]),
            .observation_valid(record[24]),.source(slot),.merged(merged[32*lane+:32]),.error(pixel_error));
        assign merge_error[lane]=active_lanes[lane] && (pixel_error || record[31:25]!=0);
    end endgenerate
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;src_base<=0;old_base<=0;dst_base<=0;pixels<=0;offset<=0;remaining_count<=0;block_count<=0;watchdog<=0;
            beats<=0;beat_index<=0;slot<=0;first<=0;aborting<=0;
            result_error<=0;result_tag<=0;written_pixels<=0;fence_required<=0;
            scratch_beat<=0;history_beat<=0;active_lanes<=0;
            config_simple_ok<=0;src_end<=0;old_end<=0;dst_end<=0;
            merged_beat<=0;merged_error<=0;
        end else begin
            if(state==IDLE || state==RESULT || progress)watchdog<=0;else watchdog<=watchdog+1;
            if(abort_frame && state!=IDLE && state!=RESULT)begin aborting<=1;if(result_error==0)result_error<=3;end
            if(state!=IDLE && state!=RESULT && state!=FENCE && WATCHDOG_CYCLES>0 && watchdog>=WATCHDOG_CYCLES-1 && !progress)begin
                // Never reuse memory after an unacknowledged outstanding command.
                // Keep any stalled VALID asserted. Drain if the bus resumes;
                // cfg_ready remains blocked until a common reset/fence.
                fence_required<=1;result_error<=6;aborting<=1;
            end else case(state)
                IDLE:if(cfg_valid && cfg_ready)begin
                    result_tag<=cfg_tag;result_error<=0;written_pixels<=0;aborting<=0;
                    src_base<=cfg_scratch_base;old_base<=cfg_previous_base;dst_base<=cfg_target_base;
                    pixels<=cfg_pixels[20:0];remaining_count<=cfg_pixels[20:0];offset<=0;slot<=cfg_slot;first<=cfg_first;beat_index<=0;
                    config_simple_ok<=cfg_ok;state<=CONFIG_END;
                end
                CONFIG_END:begin
                    src_end<={4'd0,src_base}+{11'd0,pixels,2'd0};
                    old_end<={4'd0,old_base}+{11'd0,pixels,2'd0};
                    dst_end<={4'd0,dst_base}+{11'd0,pixels,2'd0};
                    if(aborting||abort_frame)state<=RESULT;else state<=CONFIG_CHECK;
                end
                CONFIG_CHECK:begin
                    if(aborting||abort_frame)state<=RESULT;
                    else if(layout_ok)state<=PREPARE;
                    else begin result_error<=1;state<=RESULT;end
                end
                PREPARE:begin
                    // Bounded 21-bit count and a separate block-preparation cycle
                    // avoid cascaded 32-bit subtract/ceil/select in the B path.
                    block_count<=remaining_count>=64 ? 7'd64 : remaining_count[6:0];
                    beats<=remaining_count>=64 ? 5'd16 : ({1'b0,remaining_count[5:2]}+(|remaining_count[1:0]));
                    if(aborting||abort_frame)state<=RESULT;else state<=SRC_AR;
                end
                SRC_AR:if(m_axi_arready)begin beat_index<=0;state<=SRC_R;end
                OLD_AR:if(m_axi_arready)begin beat_index<=0;state<=OLD_R;end
                SRC_R,OLD_R:if(m_axi_rvalid)begin
                    if(m_axi_rid!=AXI_ID || m_axi_rlast!=(beat_index==beats-1))begin
                        fence_required<=1;result_error<=7;state<=FENCE;
                    end else begin
                        if(m_axi_rresp!=0)begin aborting<=1;result_error<=4;end
                        if(state==SRC_R)scratch[beat_index]<=m_axi_rdata;else history[beat_index]<=m_axi_rdata;
                        if(beat_index==beats-1)begin
                            beat_index<=0;
                            if(aborting || abort_frame || m_axi_rresp!=0)state<=RESULT;
                            else if(state==SRC_R && !first)state<=OLD_AR;
                            else state<=LOAD;
                        end else beat_index<=beat_index+1;
                    end
                end
                LOAD:begin
                    // Break LUT RAM selection -> signed magnitude -> error and
                    // data decision into separate cycles at the fixed 125 MHz target.
                    scratch_beat<=scratch[beat_index];history_beat<=first ? 128'd0 : history[beat_index];
                    active_lanes[0]<={1'b0,beat_index,2'd0}<block_count;
                    active_lanes[1]<={1'b0,beat_index,2'd0}+7'd1<block_count;
                    active_lanes[2]<={1'b0,beat_index,2'd0}+7'd2<block_count;
                    active_lanes[3]<={1'b0,beat_index,2'd0}+7'd3<block_count;
                    if(aborting||abort_frame)state<=RESULT;else state<=MERGE;
                end
                MERGE:begin
                    merged_beat<=merged;merged_error<=merge_error;
                    if(aborting||abort_frame)state<=RESULT;else state<=CHECK;
                end
                CHECK:begin
                    updated[beat_index]<=merged_beat;
                    updated_strobes[beat_index]<={{4{active_lanes[3]}},{4{active_lanes[2]}},{4{active_lanes[1]}},{4{active_lanes[0]}}};
                    if(aborting || abort_frame)state<=RESULT;
                    else if(|merged_error)begin result_error<=2;state<=RESULT;end
                    else if(beat_index==beats-1)begin beat_index<=0;state<=AW;end
                    else begin beat_index<=beat_index+1;state<=LOAD;end
                end
                AW:if(m_axi_awready)begin beat_index<=0;state<=W;end
                W:if(m_axi_wready)begin
                    if(beat_index==beats-1)begin beat_index<=0;state<=B;end else beat_index<=beat_index+1;
                end
                B:if(m_axi_bvalid)begin
                    if(m_axi_bid!=AXI_ID)begin fence_required<=1;result_error<=7;state<=FENCE;end
                    else if(m_axi_bresp!=0)begin result_error<=5;state<=RESULT;end
                    else if(aborting || abort_frame)state<=RESULT;
                    else begin
                        written_pixels<={11'd0,completed_offset};
                        if(remaining_count==block_count)state<=RESULT;
                        else begin
                            offset<=completed_offset;remaining_count<=remaining_count-block_count;
                            beat_index<=0;state<=PREPARE;
                        end
                    end
                end
                RESULT:if(result_ready)state<=IDLE;
                FENCE:state<=FENCE;
                default:begin fence_required<=1;result_error<=7;state<=FENCE;end
            endcase
        end
    end
endmodule
