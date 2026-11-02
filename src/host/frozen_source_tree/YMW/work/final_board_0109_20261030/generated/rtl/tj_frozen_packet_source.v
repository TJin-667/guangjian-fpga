// Integrates the sole bank owner, actual FIFO reader/cache/H1/H2 and wire-v1
// packet window. All consumers share one FIFO pass; no reset/reread shortcut.
module tj_frozen_packet_source #(
    parameter integer WIDTH=1920,HEIGHT=1080,TIMEOUT_CYCLES=500000000
)(
    input wire clk,reset,capture,release_frame,cancel,invalidate_metadata,
    input wire [7:0] pixel_format,input wire [31:0] capture_pixel_count,
    input wire [255:0] capture_identity,input wire [63:0] capture_parameters,capture_geometry,
    input wire pub_valid,output wire pub_ready,input wire [415:0] pub_data,
    output wire reader_ctrl_toggle,reader_ctrl_enable,reader_ctrl_bank,input wire reader_ack_toggle,reader_seen_toggle,
    output wire rdfifo_clr,rdfifo_rden,input wire rdfifo_empty,input wire [15:0] rdfifo_dout,
    output wire mask_read,output wire [21:0] mask_address,input wire mask_data,
    input wire [15:0] requested_packet_id,read_addr,input wire read_en,output wire [15:0] read_data,
    output wire busy,ready,failed,output wire [2:0] fail_code,
    output wire cancel_request,output wire [255:0] cancel_identity,
    output reg last_valid,output reg [255:0] last_identity,
    output reg [7:0] last_format,output reg [31:0] last_payload_bytes,output reg [63:0] last_payload_crc64,
    output reg [63:0] last_parameters,last_geometry,
    output reg [319:0] last_statistics,output reg [191:0] last_features,output reg [63:0] last_rgb_crc64,output reg last_bank,output reg [1:0] last_flags,
    output reg [15:0] last_wait_counts,output reg [31:0] last_fifo_reads,
    output wire [31:0] stale_drops,output wire stats_commit,release_pulse,
    output wire [3:0] owner_state,analysis_error_out,
    output wire h2_valid,input wire h2_ready,output wire [7:0] h2_gray,
    output wire [14:0] h2_sum,output wire signed [15:0] h2_residual,
    output wire [15:0] h2_x,h2_y,output wire h2_sof,h2_eol,h2_eof,output wire [31:0] h2_request,
    output wire h2_begin,
    output wire h2_finish,output wire [3:0] h2_finish_error
);
    wire analysis_start,analysis_cancel,analysis_done,analysis_cfg_ready;
    assign h2_begin=analysis_start&&analysis_cfg_ready;
    reg [7:0] capture_format;
    wire [63:0] payload_crc64;wire [31:0] payload_bytes;wire encoding_complete;
    wire [3:0] analysis_error,packet_error,owner_error;
    assign h2_finish=analysis_done;assign h2_finish_error=analysis_error;
    wire [255:0] active_identity;
    wire active_bank;
    wire [31:0] issued_reads,returned_reads;
    reg [63:0] geometry;
    wire owner_analysis_done=analysis_done && (analysis_error!=0 || encoding_complete);
    reg [21:0] total_saved_pixels;
    reg [63:0] expected_parameters;
    reg [255:0] wanted;
    reg image_done;
    wire saved_valid,saved_ready;wire [15:0] saved_pixel,saved_x,saved_y;
    wire last_saved=saved_x==geometry[31:16]-1 && saved_y==geometry[15:0]-1;
    wire [31:0] pixel_count,gray_sum,near_black,near_white,rgb_any_max;
    wire [31:0] board_count,board_gray_sum,board_dark,board_white,board_rgb_any_max;
    wire h2_strong,h2_weak;
    reg [31:0] strong_count,weak_count;
    reg [63:0] sum9_total;
    reg signed [63:0] residual_total;
    reg [63:0] rgb_crc64;
    // CRC-64/ECMA polynomial, init=0, no reflection/xorout; RGB565 big endian.
    // Diagnostic content binding only, not physical freshness evidence.
    function [63:0] crc_pixel;
        input [63:0] crc;input [15:0] pixel;
        reg [63:0] c;integer bit_index;
        begin
            c=crc^{pixel,48'd0};
            for(bit_index=0;bit_index<16;bit_index=bit_index+1)c=c[63] ? (c<<1)^64'h42f0e1eba9ea3693 : c<<1;
            crc_pixel=c;
        end
    endfunction
    wire [3:0] checked_pub_error=pub_data[30:27]>=4 ? pub_data[30:27] :
        (pub_data[159:96]!=expected_parameters || pub_data[95:32]!=geometry || !pub_data[26] ? 4'd2 : pub_data[30:27]);
    assign fail_code=owner_error>7 ? 7 : owner_error[2:0];
    assign cancel_request=cancel || analysis_cancel || (busy && release_frame && (!owner_analysis_done || analysis_error!=0));
    assign cancel_identity=wanted;
    assign analysis_error_out=analysis_error;
    frozen_frame_owner #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) owner(
        .clk(clk),.reset(reset),.capture(capture),.cancel(cancel || packet_error!=0 || (release_frame && !owner_analysis_done)),.capture_identity(capture_identity),
        .pub_valid(pub_valid),.pub_ready(pub_ready),.pub_identity(pub_data[415:160]),.pub_bank(pub_data[31]),.pub_error(checked_pub_error),
        .active_identity(active_identity),.active_bank(active_bank),
        .reader_ctrl_toggle(reader_ctrl_toggle),.reader_ctrl_enable(reader_ctrl_enable),.reader_ctrl_bank(reader_ctrl_bank),.reader_ack_toggle(reader_ack_toggle),.reader_seen_toggle(reader_seen_toggle),
        .rdfifo_clr(rdfifo_clr),.analysis_start(analysis_start),.analysis_cancel(analysis_cancel),.analysis_done(owner_analysis_done),.analysis_error(analysis_error),
        .image_complete(image_done),.busy(busy),.failed(failed),.fail_code(owner_error),.stats_commit(stats_commit),.release_pulse(release_pulse),.stale_drops(stale_drops),.debug_state(owner_state));
    transport_packet_store packets(
        // A released packet window must not inspect the next request's reset
        // packet ID while that request is still waiting for publication.
        .clk(clk),.reset(reset),.cancel(analysis_cancel || release_pulse || (capture && !busy)),.start(analysis_start),
         .pixel_format(capture_format),.total_pixels(total_saved_pixels[21:0]),
        .payload_crc64(payload_crc64),.payload_bytes(payload_bytes),.encoding_complete(encoding_complete),
        .in_valid(saved_valid),.in_ready(saved_ready),.in_pixel(saved_pixel),.in_eof(last_saved),
        .analysis_complete(analysis_done && analysis_error==0),.requested_packet_id(requested_packet_id),
        .ready(ready),.error(packet_error),.read_en(read_en),.read_addr(read_addr),.read_data(read_data));
    tj_ddr_analysis_source #(.MAX_WIDTH(WIDTH),.MAX_HEIGHT(HEIGHT),.STALL_LIMIT(TIMEOUT_CYCLES)) analysis(
        .clk(clk),.reset(reset),.cancel(analysis_cancel || packet_error!=0),.cfg_valid(analysis_start),.cfg_ready(analysis_cfg_ready),.cfg_source_complete(1'b1),
        .cfg_full_width(WIDTH),.cfg_full_height(HEIGHT),.cfg_x(geometry[63:48]),.cfg_y(geometry[47:32]),.cfg_width(geometry[31:16]),.cfg_height(geometry[15:0]),
        .cfg_request_id(active_identity[191:160]),.rdfifo_rden(rdfifo_rden),.rdfifo_empty(rdfifo_empty),.rdfifo_dout(rdfifo_dout),
        .mask_read(mask_read),.mask_address(mask_address),.mask_data(mask_data),
        .out_valid(h2_valid),.out_ready(h2_ready),.out_x(h2_x),.out_y(h2_y),.out_gray(h2_gray),.out_background_sum(h2_sum),.out_residual_n(h2_residual),
        .out_candidate(h2_strong),.out_weak(h2_weak),.out_sof(h2_sof),.out_eol(h2_eol),.out_eof(h2_eof),.out_request_id(h2_request),
        .result_valid(analysis_done),.result_ready(release_pulse),.result_error(analysis_error),.issued_reads(issued_reads),.returned_reads(returned_reads),
        .pixel_count(pixel_count),.gray_sum(gray_sum),.near_black(near_black),.near_white(near_white),.rgb_any_max(rgb_any_max),
        .board_count(board_count),.board_gray_sum(board_gray_sum),.board_dark(board_dark),.board_white(board_white),.board_rgb_any_max(board_rgb_any_max),
        .saved_valid(saved_valid),.saved_ready(saved_ready),.saved_pixel(saved_pixel),.saved_x(saved_x),.saved_y(saved_y));
    always @(posedge clk)begin
        if(reset)begin total_saved_pixels<=0;capture_format<=1;last_format<=1;last_payload_bytes<=0;last_payload_crc64<=0;geometry<=0;expected_parameters<=0;wanted<=0;image_done<=0;last_valid<=0;last_identity<=0;last_parameters<=0;last_geometry<=0;last_statistics<=0;last_features<=0;last_rgb_crc64<=0;last_bank<=0;last_flags<=0;last_wait_counts<=0;last_fifo_reads<=0;strong_count<=0;weak_count<=0;sum9_total<=0;residual_total<=0;rgb_crc64<=0;end
        else begin
            if(analysis_start)begin strong_count<=0;weak_count<=0;sum9_total<=0;residual_total<=0;rgb_crc64<=0;end
            else if(h2_valid && h2_ready)begin
                if(h2_strong)strong_count<=strong_count+1;
                if(h2_weak)weak_count<=weak_count+1;
                sum9_total<=sum9_total+h2_sum;
                residual_total<=residual_total+$signed({{48{h2_residual[15]}},h2_residual});
            end
            if(saved_valid && saved_ready)rgb_crc64<=crc_pixel(rgb_crc64,saved_pixel);
            if(capture && !busy)begin
                total_saved_pixels<=capture_pixel_count[21:0];capture_format<=pixel_format;last_format<=pixel_format;last_payload_bytes<=0;last_payload_crc64<=0;geometry<=capture_geometry;expected_parameters<=capture_parameters;wanted<=capture_identity;image_done<=0;last_valid<=0;
                last_identity<=capture_identity;last_parameters<=capture_parameters;last_geometry<=capture_geometry;
                last_statistics<=0;last_features<=0;last_rgb_crc64<=0;last_bank<=0;last_flags<=0;last_wait_counts<=0;last_fifo_reads<=0;
            end
            if(pub_valid && owner_state==1 && pub_data[415:288]==wanted[255:128] && pub_data[223:160]==wanted[63:0])begin
                last_identity<=pub_data[415:160];last_bank<=pub_data[31];last_flags<=pub_data[26:25];
                last_wait_counts<={pub_data[24:17],pub_data[16:9]};
            end
            if(release_frame)image_done<=1;
            if(stats_commit)begin
                last_format<=capture_format;last_payload_bytes<=payload_bytes;last_payload_crc64<=payload_crc64;
                last_identity<=active_identity;last_bank<=active_bank;last_parameters<=pub_data[159:96];last_geometry<=geometry;
                last_flags<=pub_data[26:25];last_wait_counts<={pub_data[24:17],pub_data[16:9]};last_fifo_reads<=returned_reads;
                last_statistics<={pixel_count,gray_sum,near_black,near_white,rgb_any_max,board_count,board_gray_sum,board_dark,board_white,board_rgb_any_max};
                last_features<={strong_count,weak_count,sum9_total,residual_total};
                last_rgb_crc64<=rgb_crc64;
            end
            if(release_pulse && !(capture && !busy))last_valid<=!failed && owner_error==0 && owner_analysis_done && analysis_error==0 && packet_error==0 && active_identity[255:192]!=0;
            if(invalidate_metadata)last_valid<=0;
        end
    end
endmodule
