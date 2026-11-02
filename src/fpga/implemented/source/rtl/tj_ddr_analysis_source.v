// H1/H2 integration behind the actual one-clock-latency sequential DDR FIFO.
// This module does not own a bank; frozen_frame_owner must STOP/ACK before release.
module tj_ddr_analysis_source #(
    parameter integer MAX_WIDTH=1920,MAX_HEIGHT=1080,STALL_LIMIT=125000000
)(
    input wire clk,reset,cancel,cfg_valid,output wire cfg_ready,input wire cfg_source_complete,
    input wire [15:0] cfg_full_width,cfg_full_height,cfg_x,cfg_y,cfg_width,cfg_height,
    input wire [31:0] cfg_request_id,
    output wire rdfifo_rden,input wire rdfifo_empty,input wire [15:0] rdfifo_dout,
    output wire mask_read,output wire [21:0] mask_address,input wire mask_data,
    output wire out_valid,input wire out_ready,output wire [15:0] out_x,out_y,
    output wire [7:0] out_gray,output wire [14:0] out_background_sum,
    output wire signed [15:0] out_residual_n,output wire out_candidate,out_weak,out_sof,out_eol,out_eof,
    output wire [31:0] out_request_id,
    output wire result_valid,input wire result_ready,output reg [3:0] result_error,
    output wire [31:0] issued_reads,returned_reads,
    output wire [31:0] pixel_count,gray_sum,near_black,near_white,rgb_any_max,
    output wire [31:0] board_count,board_gray_sum,board_dark,board_white,board_rgb_any_max,
    output wire saved_valid,input wire saved_ready,output wire [15:0] saved_pixel,
    output wire [15:0] saved_x,saved_y
);
    localparam IDLE=0,CONFIG=1,RUN=2,RESULT=3;
    reg [1:0] state;
    reg [15:0] fw,fh,x,y,w,h;reg [31:0] request_id;reg complete_source;
    wire core_reset=reset || state==IDLE;
    wire core_cfg=state==CONFIG;
    wire cancelling=cancel || result_error!=0;
    wire stream_valid,stream_ready,stream_mask,stream_sof,stream_eol,stream_eof;
    wire [15:0] stream_pixel,stream_x,stream_y;
    wire reader_result,h1_result,h2_result;
    wire [3:0] reader_error,cache_error;wire [2:0] h1_error,h2_error;
    wire cache_ready,h1_ready,h1_out_valid;
    wire [31:0] unused_count,stored;
    wire read_valid,read_ready,response_valid,response_ready;
    wire [31:0] read_request_id,response_request_id;
    wire [21:0] read_address,response_address;
    wire [15:0] response_rgb565;
    assign cfg_ready=state==IDLE && !reset;
    assign result_valid=state==RESULT && !reset;
    assign stream_ready=cache_ready && h1_ready && saved_ready;
    assign saved_valid=stream_valid && cache_ready && h1_ready && !cancelling;
    assign saved_pixel=stream_pixel;assign saved_x=stream_x;assign saved_y=stream_y;
    wire [15:0] abs_residual=out_residual_n[15] ? -out_residual_n : out_residual_n;
    assign out_weak=abs_residual>16'd648;
    ddr_saved_fifo_reader #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),.STALL_LIMIT(STALL_LIMIT)) reader(
        .clk(clk),.reset(core_reset),.cancel(cancelling),.cfg_valid(core_cfg),.cfg_ready(),
        .cfg_source_complete(complete_source),.cfg_full_width(fw),.cfg_full_height(fh),
        .cfg_x(x),.cfg_y(y),.cfg_width(w),.cfg_height(h),.cfg_request_id(request_id),
        .rdfifo_rden(rdfifo_rden),.rdfifo_empty(rdfifo_empty),.rdfifo_dout(rdfifo_dout),
        .mask_read(mask_read),.mask_address(mask_address),.mask_data(mask_data),
        .out_valid(stream_valid),.out_ready(stream_ready),.out_pixel(stream_pixel),.out_x(stream_x),.out_y(stream_y),
        .out_mask(stream_mask),.out_sof(stream_sof),.out_eol(stream_eol),.out_eof(stream_eof),.out_request_id(),
        .result_valid(reader_result),.result_ready(1'b0),.result_error(reader_error),
        .issued_reads(issued_reads),.returned_reads(returned_reads),.saved_pixels(unused_count));
    roi_h1_stream #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),.ENABLE_BOARD_MASK(1)) h1(
        .clk(clk),.reset(core_reset),.abort_frame(cancelling),.cfg_valid(core_cfg),.cfg_ready(),
        .cfg_width(w),.cfg_height(h),.cfg_x(16'd0),.cfg_y(16'd0),.cfg_roi_width(w),.cfg_roi_height(h),
        .cfg_black(8'd5),.cfg_white(8'd250),.cfg_brightness(8'd128),.cfg_request_id(request_id),.cfg_frame_id(16'd0),.cfg_channel(2'd0),
        .in_valid(stream_valid && cache_ready && saved_ready),.in_ready(h1_ready),.in_pixel(stream_pixel),.in_board_mask(stream_mask),
        .in_sof(stream_sof),.in_eol(stream_eol),.in_eof(stream_eof),.out_valid(h1_out_valid),.out_ready(1'b1),
        .out_pixel(),.out_gray(),.out_sof(),.out_eol(),.out_eof(),.request_id(),.frame_id(),.roi_width(),.roi_height(),.channel(),.brightness(),
        .result_valid(h1_result),.result_ready(1'b0),.result_error(h1_error),
        .pixel_count(pixel_count),.gray_sum(gray_sum),.near_black(near_black),.near_white(near_white),.rgb_any_max(rgb_any_max),
        .board_count(board_count),.board_gray_sum(board_gray_sum),.board_dark(board_dark),.board_white(board_white),.board_rgb_any_max(board_rgb_any_max),
        .gray_min(),.gray_max(),.dynamic_range());
    h2_saved_line_cache #(.MAX_WIDTH(MAX_WIDTH)) cache(
        .clk(clk),.reset(core_reset),.cancel(cancelling),.cfg_valid(core_cfg),.cfg_width(w),.cfg_height(h),.cfg_request_id(request_id),
        .in_valid(stream_valid && h1_ready && saved_ready),.in_ready(cache_ready),.in_pixel(stream_pixel),.in_x(stream_x),.in_y(stream_y),
        .read_valid(read_valid),.read_ready(read_ready),.read_address(read_address),.read_request_id(read_request_id),
        .response_valid(response_valid),.response_ready(response_ready),.response_address(response_address),.response_request_id(response_request_id),
        .response_rgb565(response_rgb565),.error(cache_error),.stored_pixels(stored));
    h2_background9 #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT)) h2(
        .clk(clk),.reset(core_reset),.abort_frame(cancelling),.cfg_valid(core_cfg),.cfg_ready(),.cfg_source_complete(complete_source),
        .cfg_width(w),.cfg_height(h),.cfg_x(16'd0),.cfg_y(16'd0),.cfg_roi_width(w),.cfg_roi_height(h),.cfg_threshold(8'd20),.cfg_request_id(request_id),
        .read_valid(read_valid),.read_ready(read_ready),.read_request_id(read_request_id),.read_address(read_address),
        .response_valid(response_valid),.response_ready(response_ready),.response_request_id(response_request_id),.response_address(response_address),.response_rgb565(response_rgb565),
        .out_valid(out_valid),.out_ready(out_ready),.out_request_id(out_request_id),.out_x(out_x),.out_y(out_y),.out_gray(out_gray),
        .out_background_sum(out_background_sum),.out_residual_n(out_residual_n),.out_bright_n(),.out_dark_n(),.out_candidate(out_candidate),
        .out_sof(out_sof),.out_eol(out_eol),.out_eof(out_eof),.result_valid(h2_result),.result_ready(1'b0),.result_error(h2_error),.output_count());
    always @(posedge clk)begin
        if(reset)begin state<=IDLE;result_error<=0;fw<=0;fh<=0;x<=0;y<=0;w<=0;h<=0;request_id<=0;complete_source<=0;end
        else case(state)
            IDLE:if(cfg_valid)begin
                fw<=cfg_full_width;fh<=cfg_full_height;x<=cfg_x;y<=cfg_y;w<=cfg_width;h<=cfg_height;
                request_id<=cfg_request_id;complete_source<=cfg_source_complete;result_error<=0;state<=CONFIG;
            end
            CONFIG:state<=RUN;
            RUN:begin
                if(cancel)result_error<=3;
                else if(result_error==0)begin
                    if(reader_error!=0)result_error<=reader_error;
                    else if(cache_error!=0)result_error<=cache_error;
                    else if(h1_result && h1_error!=0)result_error<={1'b0,h1_error};
                    else if(h2_result && h2_error!=0)result_error<={1'b0,h2_error};
                end
                if(reader_result && ((h1_result && h2_result) || reader_error!=0 || result_error!=0))state<=RESULT;
            end
            RESULT:if(result_ready)state<=IDLE;
        endcase
    end
endmodule
