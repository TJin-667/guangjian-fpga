// Group transaction ownership, independent of transport. No eight-frame PUBLISH
// until slots 1..8 each complete and the DDR worker acknowledges durable writes.
// The camera/H2/scratch producer must present only COMMITTED scratch frames.
// The application must bind its complete parameter/ROI/mask identity to cfg_digest.
module fusion_group_guard #(
    parameter integer MAX_PIXELS=2073600,
    parameter [29:0] STATE0_BASE=30'h00800000,
    parameter [29:0] STATE1_BASE=30'h01000000,
    parameter [29:0] SCRATCH_BASE=30'h01800000
)(
    input wire clk,reset,
    input wire begin_valid,output wire begin_ready,
    input wire [63:0] begin_group,
    input wire [127:0] begin_digest,
    input wire [15:0] begin_width,begin_height,
    input wire release_valid,input wire [63:0] release_group,
    input wire abort_group,
    input wire frame_valid,output wire frame_ready,
    input wire [63:0] frame_group,input wire [127:0] frame_digest,
    input wire [3:0] frame_slot,input wire [31:0] frame_request,
    input wire frame_source_complete,
    output wire worker_cfg_valid,input wire worker_cfg_ready,
    output wire worker_first,output wire [3:0] worker_slot,
    output wire [31:0] worker_pixels,worker_tag,
    output wire [29:0] worker_scratch_base,worker_previous_base,worker_target_base,
    output wire worker_abort,
    input wire worker_result_valid,output wire worker_result_ready,
    input wire [3:0] worker_result_error,input wire [31:0] worker_result_tag,worker_written_pixels,
    input wire worker_fence_required,
    output reg receipt_valid,input wire receipt_ready,
    output reg [3:0] receipt_error,output reg [31:0] receipt_request,
    output reg active,output reg [3:0] completed_slots,
    output reg published,output reg [63:0] published_group,
    output reg [127:0] published_digest,
    output reg [15:0] published_width,published_height,
    output wire [29:0] published_base,
    output reg fault
);
    localparam WAIT=0,LAUNCH=1,RUN=2,OPEN=3;
    reg [1:0] state;
    reg bank,discard;
    reg [63:0] group_id,last_group;
    reg [127:0] digest;
    reg [15:0] width,height;
    reg [31:0] pixels,request_id,last_request;
    reg [3:0] slot;
    wire [31:0] begin_pixels=begin_width*begin_height;
    assign begin_ready=!active && !published && !receipt_valid && state==WAIT && !fault && !reset;
    assign frame_ready=active && !published && state==WAIT && !receipt_valid && !fault && !reset && !abort_group;
    assign worker_cfg_valid=state==LAUNCH && !reset && !discard && !abort_group && !fault;
    assign worker_first=slot==1;assign worker_slot=slot;
    assign worker_pixels=pixels;assign worker_tag=request_id;
    assign worker_scratch_base=SCRATCH_BASE;
    assign worker_previous_base=bank ? STATE1_BASE : STATE0_BASE;
    assign worker_target_base=bank ? STATE0_BASE : STATE1_BASE;
    assign published_base=bank ? STATE1_BASE : STATE0_BASE;
    assign worker_abort=abort_group || discard;
    assign worker_result_ready=state==RUN && !reset;
    always @(posedge clk)begin
        if(reset)begin
            state<=WAIT;bank<=0;discard<=0;group_id<=0;last_group<=0;digest<=0;width<=0;height<=0;
            pixels<=0;request_id<=0;last_request<=0;slot<=0;
            receipt_valid<=0;receipt_error<=0;receipt_request<=0;
            active<=0;completed_slots<=0;published<=0;published_group<=0;published_digest<=0;
            published_width<=0;published_height<=0;fault<=0;
        end else begin
            if(receipt_valid && receipt_ready)receipt_valid<=0;
            if(worker_fence_required)begin fault<=1;published<=0;end
            if(release_valid && published && release_group==published_group)published<=0;
            if(begin_valid && begin_ready)begin
                if(begin_group<=last_group || begin_width<9 || begin_height<9 || begin_width>1920 || begin_height>1080)begin
                    receipt_valid<=1;receipt_error<=1;receipt_request<=0;
                end else begin
                    group_id<=begin_group;digest<=begin_digest;width<=begin_width;height<=begin_height;
                    pixels<=begin_pixels;state<=OPEN;
                end
            end
            if(state==OPEN)begin
                state<=WAIT;
                if(abort_group)begin receipt_valid<=1;receipt_error<=3;receipt_request<=0;end
                else if(pixels>MAX_PIXELS)begin receipt_valid<=1;receipt_error<=1;receipt_request<=0;end
                else begin active<=1;completed_slots<=0;last_request<=0;discard<=0;last_group<=group_id;end
            end
            if(abort_group && active)begin
                discard<=1;published<=0;
                if(state==WAIT || state==LAUNCH)begin active<=0;completed_slots<=0;state<=WAIT;end
            end else if(state==WAIT && frame_valid && frame_ready)begin
                receipt_request<=frame_request;
                if(frame_group!=group_id || frame_digest!=digest || frame_slot!=completed_slots+1 ||
                    frame_request<=last_request || !frame_source_complete)begin receipt_valid<=1;receipt_error<=2;end
                else begin slot<=frame_slot;request_id<=frame_request;state<=LAUNCH;end
            end
            if(state==LAUNCH && worker_cfg_valid && worker_cfg_ready)state<=RUN;
            if(state==RUN && worker_result_valid)begin
                state<=WAIT;receipt_valid<=1;receipt_request<=request_id;
                if(discard || abort_group)begin receipt_error<=3;active<=0;completed_slots<=0;end
                else if(worker_result_tag!=request_id || worker_result_error!=0 || worker_written_pixels!=pixels || worker_fence_required)begin
                    receipt_error<=worker_result_error!=0 ? worker_result_error : 4'd4;
                end else begin
                    receipt_error<=0;bank<=!bank;completed_slots<=slot;last_request<=request_id;
                    if(slot==8)begin
                        published<=1;active<=0;published_group<=group_id;published_digest<=digest;
                        published_width<=width;published_height<=height;
                    end
                end
            end
        end
    end
endmodule
