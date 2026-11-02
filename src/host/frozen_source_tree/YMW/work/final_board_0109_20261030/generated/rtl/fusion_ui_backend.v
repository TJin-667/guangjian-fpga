// UI-domain control, exact uploaded tile map, transactional merge and result DMA.
// cmd[511:504]=op, [503:472]=ticket, [471:440]=scratch cookie,
// [439:376]=args, [375:312]=group, [311:184]=digest, [183:168]=W, [167:152]=H.
// op:1 begin,2 quality word,3 seal,4 fuse,5 release,6 fetch,7 status.
module fusion_ui_backend(
    input wire clk,reset,
    input wire cmd_valid,output wire cmd_ready,input wire [511:0] cmd_data,
    output reg reply_valid,input wire reply_ready,output reg [255:0] reply_data,
    input wire scratch_valid,input wire [31:0] scratch_cookie,scratch_request,
    input wire [15:0] scratch_width,scratch_height,
    input wire perf_writer_start,perf_writer_finish,perf_writer_success,perf_writer_write,perf_writer_response,perf_writer_blocked,
    input wire [31:0] perf_writer_cookie,
    output wire stream_valid,input wire stream_ready,input wire stream_idle,
    output wire [127:0] stream_data,output wire [4:0] stream_bytes,
    output wire [6:0] stream_index,output wire stream_last,output wire [31:0] stream_ticket,
    `include "backend_axi_ports.vh"
    output wire fault,output wire published,output wire [3:0] completed_slots
);
    localparam IDLE=0,EXEC=1,BEGIN_SEND=2,BEGIN_WAIT=3,Q_CRC=4,FUSE_SEND=5,FETCH_SEND=6,FETCH_WAIT=7;
    reg [3:0] state;
    reg [7:0] op;reg [31:0] ticket,cookie;reg [63:0] args,requested_group;
    reg [127:0] requested_digest;reg [15:0] requested_width,requested_height;
    reg [63:0] group_id;reg [127:0] group_digest;reg [15:0] width,height;
    reg [31:0] fuse_ticket,fuse_cookie,fuse_request;reg [3:0] fuse_slot;
    reg dma_busy;
    reg [31:0] quality_words[0:63];
    reg [6:0] quality_next;
    reg [31:0] quality_crc,quality_shift,quality_cookie,last_quality_word;
    reg [5:0] quality_bit;
    reg quality_valid;
    wire [31:0] tile_columns=(width+31)>>5,tile_rows=(height+31)>>5;
    wire [31:0] tile_count=tile_columns*tile_rows,expected_quality_words=(tile_count+31)>>5;
    wire unused_quality_zero=tile_count[4:0]==0 || (last_quality_word>>tile_count[4:0])==0;
    wire [43:0] quality_addresses;wire [3:0] quality_bits;
    genvar qp;
    generate for(qp=0;qp<4;qp=qp+1)begin:quality_lookup
        assign quality_bits[qp]=quality_words[quality_addresses[qp*11+5+:6]][quality_addresses[qp*11+:5]];
    end endgenerate
    wire guard_begin_ready,guard_frame_ready,guard_active,guard_fault;
    wire worker_cfg_valid,worker_cfg_ready,worker_first,worker_abort;
    wire [3:0] worker_slot;wire [31:0] worker_pixels,worker_tag;
    wire [29:0] worker_scratch,worker_previous,worker_target;
    wire worker_result_valid,worker_result_ready,worker_fence;
    wire [3:0] worker_error;wire [31:0] worker_result_tag,worker_written;
    wire guard_receipt_valid;wire [3:0] guard_receipt_error;wire [31:0] guard_receipt_request;
    wire [63:0] published_group;wire [127:0] published_digest;wire [15:0] published_width,published_height;
    wire [29:0] published_base;
    wire [31:0] pixels=width*height;
    wire reader_cfg_ready,reader_result_valid,reader_fence;
    wire [3:0] reader_error;wire [31:0] reader_result_ticket;
    reg [31:0] fetch_ticket,fetch_bytes;reg [29:0] fetch_address;
    assign fault=guard_fault||worker_fence||reader_fence;
    assign cmd_ready=state==IDLE&&!reply_valid&&!guard_receipt_valid&&!reset;
    assign stream_ticket=fetch_ticket;
    function [255:0] response;
        input [7:0] kind,status;input [31:0] response_ticket,response_cookie,response_request;
        begin response={kind,response_ticket,response_cookie,response_request,status,completed_slots,published,fault,
            quality_valid,quality_next,dma_busy,(state==FETCH_WAIT),group_id,published_base,pixels,2'd0};end
    endfunction
    wire guard_receipt_ready=(state==BEGIN_WAIT)||(state==IDLE&&!reply_valid&&dma_busy);
    fusion_group_guard guard(.clk(clk),.reset(reset),
        .begin_valid(state==BEGIN_SEND),.begin_ready(guard_begin_ready),.begin_group(requested_group),.begin_digest(requested_digest),
        .begin_width(requested_width),.begin_height(requested_height),.release_valid(state==EXEC&&op==5&&published&&args==published_group),.release_group(args),
        .abort_group(state==EXEC&&op==8&&!dma_busy&&!published&&guard_active&&args==group_id),
        .frame_valid(state==FUSE_SEND),.frame_ready(guard_frame_ready),.frame_group(group_id),.frame_digest(group_digest),
        .frame_slot(fuse_slot),.frame_request(fuse_request),.frame_source_complete(scratch_valid&&scratch_cookie==fuse_cookie&&scratch_request==fuse_request&&scratch_width==width&&scratch_height==height),
        .worker_cfg_valid(worker_cfg_valid),.worker_cfg_ready(worker_cfg_ready),.worker_first(worker_first),.worker_slot(worker_slot),
        .worker_pixels(worker_pixels),.worker_tag(worker_tag),.worker_scratch_base(worker_scratch),.worker_previous_base(worker_previous),.worker_target_base(worker_target),
        .worker_abort(worker_abort),.worker_result_valid(worker_result_valid),.worker_result_ready(worker_result_ready),.worker_result_error(worker_error),
        .worker_result_tag(worker_result_tag),.worker_written_pixels(worker_written),.worker_fence_required(worker_fence),
        .receipt_valid(guard_receipt_valid),.receipt_ready(guard_receipt_ready),.receipt_error(guard_receipt_error),.receipt_request(guard_receipt_request),
        .active(guard_active),.completed_slots(completed_slots),.published(published),.published_group(published_group),.published_digest(published_digest),
        .published_width(published_width),.published_height(published_height),.published_base(published_base),.fault(guard_fault));
    fusion_axi_frame_qualified merger(.clk(clk),.reset(reset),.abort_frame(worker_abort),
        .cfg_width(width),.quality_addresses(quality_addresses),.quality_bits(quality_bits),
        .cfg_valid(worker_cfg_valid),.cfg_ready(worker_cfg_ready),.cfg_first(worker_first),.cfg_slot(worker_slot),.cfg_pixels(worker_pixels),.cfg_tag(worker_tag),
        .cfg_scratch_base(worker_scratch),.cfg_previous_base(worker_previous),.cfg_target_base(worker_target),
        .result_valid(worker_result_valid),.result_ready(worker_result_ready),.result_error(worker_error),.result_tag(worker_result_tag),.written_pixels(worker_written),.fence_required(worker_fence),
        `include "backend_fusion_connect.vh"
    );
    axi_result_reader reader(.clk(clk),.reset(reset),.cfg_valid(state==FETCH_SEND),.cfg_ready(reader_cfg_ready),
        .cfg_address(fetch_address),.cfg_bytes(fetch_bytes),.cfg_ticket(fetch_ticket),
        .out_valid(stream_valid),.out_ready(stream_ready),.out_data(stream_data),.out_bytes(stream_bytes),.out_index(stream_index),.out_last(stream_last),
        .result_valid(reader_result_valid),.result_ready(state==FETCH_WAIT&&stream_idle&&!reply_valid),
        .result_error(reader_error),.result_ticket(reader_result_ticket),.fence_required(reader_fence),
        `include "backend_reader_connect.vh"
    );
    `include "backend_axi_ties.vh"
    wire perf_clear=(state==BEGIN_WAIT&&guard_active)||
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
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;op<=0;ticket<=0;cookie<=0;args<=0;requested_group<=0;requested_digest<=0;requested_width<=0;requested_height<=0;
            group_id<=0;group_digest<=0;width<=0;height<=0;fuse_ticket<=0;fuse_cookie<=0;fuse_request<=0;fuse_slot<=0;dma_busy<=0;
            quality_next<=0;quality_crc<=32'hffffffff;quality_shift<=0;quality_cookie<=0;last_quality_word<=0;quality_bit<=0;quality_valid<=0;
            reply_valid<=0;reply_data<=0;fetch_ticket<=0;fetch_bytes<=0;fetch_address<=0;
        end else begin
            if(reply_valid&&reply_ready)reply_valid<=0;
            if(state==IDLE&&!reply_valid&&dma_busy&&guard_receipt_valid)begin
                reply_valid<=1;reply_data<=response(1,{4'd0,guard_receipt_error},fuse_ticket,fuse_cookie,guard_receipt_request);dma_busy<=0;
                if(guard_receipt_error==0)quality_valid<=0;
            end else case(state)
                IDLE:if(cmd_valid&&cmd_ready)begin
                    op<=cmd_data[511:504];ticket<=cmd_data[503:472];cookie<=cmd_data[471:440];args<=cmd_data[439:376];
                    requested_group<=cmd_data[375:312];requested_digest<=cmd_data[311:184];requested_width<=cmd_data[183:168];requested_height<=cmd_data[167:152];
                    state<=EXEC;
                end
                EXEC:begin
                    if(fault && op!=7)begin reply_valid<=1;reply_data<=response(0,6,ticket,cookie,0);state<=IDLE;end
                    else case(op)
                        1:if(dma_busy||!guard_begin_ready)begin reply_valid<=1;reply_data<=response(0,3,ticket,cookie,0);state<=IDLE;end
                          else state<=BEGIN_SEND;
                        2:begin
                            if(dma_busy||published||!guard_active)begin reply_valid<=1;reply_data<=response(0,3,ticket,cookie,0);state<=IDLE;end
                            else if(!scratch_valid||cookie!=scratch_cookie||scratch_width!=width||scratch_height!=height||args[63:32]>=64||
                                (args[63:32]!=0&&(args[63:32]!=quality_next||quality_cookie!=cookie)))begin reply_valid<=1;reply_data<=response(0,2,ticket,cookie,scratch_request);state<=IDLE;end
                            else begin
                                quality_words[args[37:32]]<=args[31:0];last_quality_word<=args[31:0];quality_shift<=args[31:0];quality_bit<=0;
                                quality_crc<=args[63:32]==0 ? 32'hffffffff : quality_crc;quality_next<=args[38:32]+1;quality_cookie<=cookie;quality_valid<=0;state<=Q_CRC;
                            end
                        end
                        3:begin
                            reply_valid<=1;state<=IDLE;
                            if(dma_busy||!guard_active||!scratch_valid||cookie!=scratch_cookie||cookie!=quality_cookie||args[63:32]!=tile_count||quality_next!=expected_quality_words||
                                (~quality_crc)!=args[31:0]||!unused_quality_zero)begin reply_data<=response(0,2,ticket,cookie,scratch_request);quality_valid<=0;end
                            else begin quality_valid<=1;reply_data<=response(0,0,ticket,cookie,scratch_request);reply_data[137]<=1;end
                        end
                        4:begin
                            if(dma_busy||!guard_frame_ready)begin reply_valid<=1;reply_data<=response(0,3,ticket,cookie,0);state<=IDLE;end
                            else if(!scratch_valid||!quality_valid||quality_cookie!=cookie||scratch_cookie!=cookie||args[31:0]!=scratch_request||
                                args[63:32]!=completed_slots+1||args[63:32]<1||args[63:32]>8)begin reply_valid<=1;reply_data<=response(0,2,ticket,cookie,scratch_request);state<=IDLE;end
                            else begin fuse_slot<=args[35:32];fuse_request<=args[31:0];fuse_cookie<=cookie;fuse_ticket<=ticket;state<=FUSE_SEND;end
                        end
                        5:begin reply_valid<=1;reply_data<=response(0,(published&&args==published_group) ? 0 : 2,ticket,cookie,0);if(published&&args==published_group)reply_data[139]<=0;state<=IDLE;end
                        6:begin
                            if(dma_busy||!published||!reader_cfg_ready)begin reply_valid<=1;reply_data<=response(0,3,ticket,cookie,0);state<=IDLE;end
                            else if(args[41:32]!=0 || args[31:0]==0||args[31:0]>1024||args[1:0]!=0||({1'b0,args[63:32]}+args[31:0])>({1'b0,pixels}<<2))begin
                                reply_valid<=1;reply_data<=response(0,2,ticket,cookie,0);state<=IDLE;
                            end else begin fetch_ticket<=ticket;fetch_address<=published_base+args[63:32];fetch_bytes<=args[31:0];state<=FETCH_SEND;end
                        end
                        7:begin reply_valid<=1;reply_data<=response(0,0,ticket,cookie,scratch_request);state<=IDLE;end
                        8:begin
                            reply_valid<=1;state<=IDLE;
                            if(dma_busy||published||!guard_active||args!=group_id)reply_data<=response(0,3,ticket,cookie,0);
                            else begin quality_valid<=0;quality_next<=0;reply_data<=response(0,0,ticket,cookie,0);reply_data[143:139]<=0;reply_data[137:130]<=0;end
                        end
                        9:begin
                            reply_valid<=1;state<=IDLE;reply_data<=response(3,0,ticket,cookie,fuse_request);
                            reply_data[129:128]<=2'b00;reply_data[127:0]<=0;
                            if(dma_busy||cookie!=fuse_cookie||args[31:0]!=cookie||args[63:32]<1||args[63:32]>2)reply_data[151:144]<=2;
                            else if(args[63:32]==1&&scratch_meter_valid&&!scratch_meter_overflow&&perf_scratch_cookie==cookie)begin
                                reply_data[129:128]<=2'b01;reply_data[127:0]<={scratch_cycles,scratch_writes,scratch_responses,scratch_blocked};
                            end else if(args[63:32]==2&&fuse_meter_valid&&!fuse_meter_overflow&&perf_fuse_cookie==cookie)begin
                                reply_data[129:128]<=2'b01;reply_data[127:0]<={fuse_cycles,fuse_reads,fuse_writes,fuse_blocked};
                            end else reply_data[151:144]<=2;
                        end
                        default:begin reply_valid<=1;reply_data<=response(0,2,ticket,cookie,0);state<=IDLE;end
                    endcase
                end
                BEGIN_SEND:if(guard_begin_ready)state<=BEGIN_WAIT;
                BEGIN_WAIT:begin
                    if(guard_receipt_valid)begin reply_valid<=1;reply_data<=response(0,{4'd0,guard_receipt_error},ticket,cookie,0);state<=IDLE;end
                    else if(guard_active)begin
                        group_id<=requested_group;group_digest<=requested_digest;width<=requested_width;height<=requested_height;
                        quality_valid<=0;quality_next<=0;reply_valid<=1;reply_data<=response(0,0,ticket,cookie,0);state<=IDLE;
                        reply_data[127:64]<=requested_group;reply_data[33:2]<=requested_width*requested_height;reply_data[137:130]<=0;
                    end
                end
                Q_CRC:begin
                    quality_crc<=(quality_crc[0]^quality_shift[0]) ? (quality_crc>>1)^32'hedb88320 : quality_crc>>1;
                    quality_shift<=quality_shift>>1;
                    if(quality_bit==31)begin reply_valid<=1;reply_data<=response(0,0,ticket,cookie,scratch_request);state<=IDLE;end
                    else quality_bit<=quality_bit+1;
                end
                FUSE_SEND:if(guard_frame_ready)begin dma_busy<=1;reply_valid<=1;reply_data<=response(0,0,ticket,cookie,fuse_request);reply_data[129]<=1;state<=IDLE;end
                FETCH_SEND:if(reader_cfg_ready)state<=FETCH_WAIT;
                FETCH_WAIT:if(reader_result_valid&&stream_idle&&!reply_valid)begin
                    reply_valid<=1;reply_data<=response(2,reader_fence ? 8'd6 : {4'd0,reader_error},fetch_ticket,cookie,scratch_request);state<=IDLE;
                end
            endcase
        end
    end
endmodule
