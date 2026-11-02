// Isolated ROI + H1 + payload candidate. Commit only after the final byte drains.
module tj_roi_h1_top(
    input wire clk, reset, abort_frame,
    input wire cfg_valid, output wire cfg_ready,
    input wire [15:0] cfg_width, cfg_height, cfg_x, cfg_y, cfg_roi_width, cfg_roi_height,
    input wire [7:0] cfg_black, cfg_white, cfg_brightness,
    input wire [31:0] cfg_request_id,
    input wire [15:0] cfg_frame_id,
    input wire [1:0] cfg_channel,
    input wire in_valid, output wire in_ready,
    input wire [15:0] in_pixel,
    input wire in_sof, in_eol, in_eof,
    output wire out_valid, input wire out_ready,
    output wire [7:0] out_byte,
    output wire packet_first, packet_last, frame_first, frame_last,
    output wire [15:0] packet_id, byte_index,
    output wire [31:0] request_id,
    output wire [15:0] frame_id, roi_width, roi_height,
    output wire [1:0] channel,
    output wire [7:0] brightness,
    output wire result_valid, input wire result_ready,
    output wire [2:0] result_error,
    output wire [31:0] pixel_count, gray_sum, near_black, near_white,
    output wire [7:0] gray_min, gray_max, dynamic_range
);
    wire crop_valid, crop_ready, crop_sof, crop_eol, crop_eof;
    wire [15:0] crop_pixel;
    wire [7:0] crop_gray;
    wire stats_valid, stats_ready;
    wire cancel = abort_frame || (stats_valid && result_error!=0);
    assign result_valid = stats_valid && (result_error!=0 || crop_ready);
    assign stats_ready = result_ready && (result_error!=0 || crop_ready);
    roi_h1_stream core(
        .clk(clk),.reset(reset),.abort_frame(abort_frame),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_width(cfg_width),.cfg_height(cfg_height),
        .cfg_x(cfg_x),.cfg_y(cfg_y),.cfg_roi_width(cfg_roi_width),.cfg_roi_height(cfg_roi_height),
        .cfg_black(cfg_black),.cfg_white(cfg_white),.cfg_brightness(cfg_brightness),
        .cfg_request_id(cfg_request_id),.cfg_frame_id(cfg_frame_id),.cfg_channel(cfg_channel),
        .in_valid(in_valid),.in_ready(in_ready),.in_pixel(in_pixel),.in_board_mask(1'b0),
        .in_sof(in_sof),.in_eol(in_eol),.in_eof(in_eof),
        .out_valid(crop_valid),.out_ready(crop_ready),.out_pixel(crop_pixel),.out_gray(crop_gray),
        .out_sof(crop_sof),.out_eol(crop_eol),.out_eof(crop_eof),
        .request_id(request_id),.frame_id(frame_id),.roi_width(roi_width),.roi_height(roi_height),
        .channel(channel),.brightness(brightness),.result_valid(stats_valid),.result_ready(stats_ready),
        .result_error(result_error),.pixel_count(pixel_count),.gray_sum(gray_sum),
        .near_black(near_black),.near_white(near_white),.gray_min(gray_min),.gray_max(gray_max),
        .dynamic_range(dynamic_range));
    rgb565_payload payload(.clk(clk),.reset(reset),.cancel(cancel),
        .in_valid(crop_valid),.in_ready(crop_ready),.in_pixel(crop_pixel),.in_sof(crop_sof),.in_eof(crop_eof),
        .out_valid(out_valid),.out_ready(out_ready),.out_byte(out_byte),
        .packet_first(packet_first),.packet_last(packet_last),.frame_first(frame_first),.frame_last(frame_last),
        .packet_id(packet_id),.byte_index(byte_index));
endmodule
