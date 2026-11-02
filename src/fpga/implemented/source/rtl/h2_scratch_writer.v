// Durable, sequential H2 record writer. Burst buffer is 64 pixels (256 bytes).
// PC-supplied EXACT tile validity is an explicit transitional input; this module
// does not approximate quality or derive it from SAT1. The whole ROI is saved.
module h2_scratch_writer #(
    parameter integer MAX_PIXELS=2073600,
    parameter integer WATCHDOG_CYCLES=125000000,
    parameter [3:0] AXI_ID=4'h9
)(
    input wire clk,reset,abort_frame,
    input wire cfg_valid,output wire cfg_ready,
    input wire [15:0] cfg_width,cfg_height,input wire [31:0] cfg_request,
    input wire [29:0] cfg_base,
    input wire in_valid,output wire in_ready,
    input wire [31:0] in_request,input wire [15:0] in_x,in_y,
    input wire signed [15:0] in_residual_n,input wire [7:0] in_gray,
    input wire in_observation_valid,in_sof,in_eol,in_eof,
    input wire finish_valid,output wire finish_ready,input wire [31:0] finish_request,input wire [2:0] finish_error,
    output wire result_valid,input wire result_ready,
    output reg [3:0] result_error,output reg [31:0] result_request,written_pixels,
    output reg fence_required,
    output wire [3:0] m_axi_awid,output wire [29:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen,output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,output wire m_axi_awvalid,input wire m_axi_awready,
    output wire [127:0] m_axi_wdata,output wire [15:0] m_axi_wstrb,
    output wire m_axi_wlast,m_axi_wvalid,input wire m_axi_wready,
    input wire [3:0] m_axi_bid,input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,output wire m_axi_bready
);
    localparam IDLE=0,COLLECT=1,AW=2,W=3,B=4,FINISH=5,RESULT=6,FENCE=7,CONFIG=8;
    reg [3:0] state;
    reg [15:0] width,height,x,y;
    reg [31:0] pixels,received,block_start,watchdog;
    reg [29:0] base;
    reg [5:0] buffer_pixels;
    reg [4:0] beats;
    reg [3:0] beat_index;
    reg [127:0] assembling;
    reg [127:0] buffer [0:15];
    reg [15:0] buffer_strobes [0:15];
    reg finish_seen,aborting;
    wire [31:0] configured_pixels=cfg_width*cfg_height;
    wire [33:0] configured_end={4'd0,base}+({2'd0,pixels}<<2);
    wire cfg_ok=cfg_width>=9 && cfg_height>=9 && cfg_width<=1920 && cfg_height<=1080 &&
        cfg_base[11:0]==0;
    assign cfg_ready=state==IDLE && !reset && !fence_required;
    assign in_ready=state==COLLECT && !reset && !abort_frame && !aborting;
    wire accept=in_valid&&in_ready;
    wire last_pixel=received==pixels-1;
    wire input_ok=in_request==result_request && in_x==x && in_y==y && in_sof==(received==0) &&
        in_eol==(x==width-1) && in_eof==last_pixel && in_residual_n>=-20655 && in_residual_n<=20655;
    assign finish_ready=state!=IDLE && state!=CONFIG && state!=RESULT && state!=FENCE && !finish_seen && !reset && !abort_frame;
    wire finish_bad=finish_valid&&finish_ready && (finish_request!=result_request || finish_error!=0 ||
        !(received==pixels || (accept&&last_pixel)));
    reg [127:0] assembled;
    always @* begin
        assembled=assembling;
        assembled[buffer_pixels[1:0]*32+:32]={7'd0,in_observation_valid,in_gray,in_residual_n};
    end
    assign result_valid=state==RESULT && !reset;
    assign m_axi_awid=AXI_ID;assign m_axi_awaddr=base+(block_start<<2);
    assign m_axi_awlen={3'd0,beats}-1'b1;assign m_axi_awsize=3'd4;assign m_axi_awburst=2'b01;
    assign m_axi_awvalid=state==AW && !reset;
    assign m_axi_wdata=buffer[beat_index];
    assign m_axi_wstrb=buffer_strobes[beat_index];
    assign m_axi_wlast=beat_index==beats-1;assign m_axi_wvalid=state==W&&!reset;
    assign m_axi_bready=(state==B||state==FENCE)&&!reset;
    wire progress=state==CONFIG || accept || (finish_valid&&finish_ready) || (m_axi_awvalid&&m_axi_awready) ||
        (m_axi_wvalid&&m_axi_wready) || (m_axi_bvalid&&m_axi_bready);
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;width<=0;height<=0;x<=0;y<=0;pixels<=0;received<=0;block_start<=0;watchdog<=0;base<=0;
            buffer_pixels<=0;beats<=0;beat_index<=0;assembling<=0;finish_seen<=0;aborting<=0;
            result_error<=0;result_request<=0;written_pixels<=0;fence_required<=0;
        end else begin
            if(state==IDLE||state==RESULT||progress)watchdog<=0;else watchdog<=watchdog+1;
            if(abort_frame && state!=IDLE && state!=RESULT)begin aborting<=1;result_error<=3;end
            if(finish_valid&&finish_ready)begin
                finish_seen<=1;
                if(finish_bad)begin aborting<=1;result_error<=4;end
            end
            if(state!=IDLE&&state!=RESULT&&state!=FENCE&&WATCHDOG_CYCLES>0&&watchdog>=WATCHDOG_CYCLES-1&&!progress)begin
                fence_required<=1;aborting<=1;result_error<=6;
            end else case(state)
                IDLE:if(cfg_valid&&cfg_ready)begin
                    width<=cfg_width;height<=cfg_height;pixels<=configured_pixels;result_request<=cfg_request;base<=cfg_base;
                    received<=0;written_pixels<=0;block_start<=0;buffer_pixels<=0;assembling<=0;beat_index<=0;
                    x<=0;y<=0;finish_seen<=0;aborting<=0;result_error<=0;
                    if(cfg_ok)state<=CONFIG;else begin result_error<=1;state<=RESULT;end
                end
                CONFIG:begin
                    if(aborting||abort_frame)state<=RESULT;
                    else if(pixels==0 || pixels>MAX_PIXELS || configured_end>34'h40000000)begin result_error<=1;state<=RESULT;end
                    else state<=COLLECT;
                end
                COLLECT:begin
                    if(aborting||abort_frame||finish_bad)state<=RESULT;
                    else if(accept)begin
                        if(!input_ok)begin result_error<=2;state<=RESULT;end
                        else begin
                            received<=received+1;assembling<=assembled;
                            if(buffer_pixels[1:0]==3 || last_pixel)begin
                                buffer[buffer_pixels[5:2]]<=assembled;assembling<=0;
                                // Store tail byte enables when the beat is formed;
                                // do not put a 32-bit address compare on AXI WSTRB.
                                case(buffer_pixels[1:0])
                                    0:buffer_strobes[buffer_pixels[5:2]]<=16'h000f;
                                    1:buffer_strobes[buffer_pixels[5:2]]<=16'h00ff;
                                    2:buffer_strobes[buffer_pixels[5:2]]<=16'h0fff;
                                    3:buffer_strobes[buffer_pixels[5:2]]<=16'hffff;
                                endcase
                            end
                            if(buffer_pixels==63 || last_pixel)begin
                                beats<=({1'b0,buffer_pixels}+4)>>2;beat_index<=0;state<=AW;
                            end else buffer_pixels<=buffer_pixels+1;
                            if(x==width-1)begin x<=0;y<=y+1;end else x<=x+1;
                        end
                    end
                end
                AW:if(m_axi_awready)begin beat_index<=0;state<=W;end
                W:if(m_axi_wready)begin
                    if(beat_index==beats-1)begin beat_index<=0;state<=B;end else beat_index<=beat_index+1;
                end
                B:if(m_axi_bvalid)begin
                    if(m_axi_bid!=AXI_ID)begin fence_required<=1;result_error<=7;state<=FENCE;end
                    else if(m_axi_bresp!=0)begin result_error<=5;state<=RESULT;end
                    else if(aborting||abort_frame||finish_bad)state<=RESULT;
                    else begin
                        written_pixels<=received;block_start<=received;buffer_pixels<=0;assembling<=0;
                        state<=received==pixels ? FINISH : COLLECT;
                    end
                end
                FINISH:if(aborting||abort_frame||finish_bad||finish_seen||(finish_valid&&finish_ready))state<=RESULT;
                RESULT:if(result_ready)state<=IDLE;
                FENCE:state<=FENCE;
                default:begin fence_required<=1;result_error<=7;state<=FENCE;end
            endcase
        end
    end
endmodule
