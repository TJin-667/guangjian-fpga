// Single-clock, backpressure-capable DDR-reader interface; NOT a direct DVP sink.
// Every cropped pixel is provisional until result_valid && result_error == 0.
module roi_h1_stream #(
    parameter integer MAX_WIDTH=1920, MAX_HEIGHT=1080,
    parameter integer ENABLE_BOARD_MASK=0,
    parameter [7:0] BOARD_BLACK=8'd10
)(
    input wire clk, reset, abort_frame,
    input wire cfg_valid, output wire cfg_ready,
    input wire [15:0] cfg_width, cfg_height, cfg_x, cfg_y, cfg_roi_width, cfg_roi_height,
    input wire [7:0] cfg_black, cfg_white, cfg_brightness,
    input wire [31:0] cfg_request_id,
    input wire [15:0] cfg_frame_id,
    input wire [1:0] cfg_channel,
    input wire in_valid, output wire in_ready,
    input wire [15:0] in_pixel,
    // Synchronous with in_pixel/in_valid; ignored by legacy instantiations.
    input wire in_board_mask,
    input wire in_sof, in_eol, in_eof,
    output wire out_valid, input wire out_ready,
    output reg [15:0] out_pixel,
    output reg [7:0] out_gray,
    output reg out_sof, out_eol, out_eof,
    output reg [31:0] request_id,
    output reg [15:0] frame_id, roi_width, roi_height,
    output reg [1:0] channel,
    output reg [7:0] brightness,
    output wire result_valid, input wire result_ready,
    output reg [2:0] result_error,
    output reg [31:0] pixel_count, gray_sum, near_black, near_white,
    output reg [31:0] rgb_any_max,
    output reg [31:0] board_count, board_gray_sum, board_dark, board_white, board_rgb_any_max,
    output reg [7:0] gray_min, gray_max,
    output wire [7:0] dynamic_range
);
    localparam IDLE=0, RECEIVE=1, DRAIN=2, RESULT=3;
    reg [1:0] state;
    reg pending;
    reg pending_board;
    reg [15:0] width, height, x0, y0, x1, y1, x, y;
    reg [7:0] black_level, white_level;
    wire [7:0] gray;
    wire output_rgb_max = (&out_pixel[15:11]) || (&out_pixel[10:5]) || (&out_pixel[4:0]);
    rgb565_gray gray_calc(.pixel(in_pixel), .gray(gray));
    wire selected = x>=x0 && x<x1 && y>=y0 && y<y1;
    wire first_input = x==0 && y==0;
    wire last_column = x==width-1;
    wire last_input = last_column && y==height-1;
    wire markers_ok = (in_sof==first_input) && (in_eol==last_column) && (in_eof==last_input);
    wire [16:0] cfg_right = {1'b0,cfg_x}+{1'b0,cfg_roi_width};
    wire [16:0] cfg_bottom = {1'b0,cfg_y}+{1'b0,cfg_roi_height};
    wire config_ok = cfg_width>0 && cfg_height>0 && cfg_width<=MAX_WIDTH && cfg_height<=MAX_HEIGHT &&
        cfg_roi_width>0 && cfg_roi_height>0 && cfg_right<={1'b0,cfg_width} &&
        cfg_bottom<={1'b0,cfg_height} && cfg_black<cfg_white;
    assign cfg_ready = state==IDLE && !reset;
    assign in_ready = state==RECEIVE && !abort_frame && !reset && (!pending || out_ready);
    assign out_valid = pending && !abort_frame && !reset;
    assign result_valid = state==RESULT && !reset;
    assign dynamic_range = pixel_count==0 ? 8'd0 : gray_max-gray_min;

    always @(posedge clk) begin
        if (reset) begin
            state<=IDLE; pending<=0; pending_board<=0; result_error<=0;
            width<=0; height<=0; x0<=0; y0<=0; x1<=0; y1<=0; x<=0; y<=0;
            black_level<=0; white_level<=0; request_id<=0; frame_id<=0;
            roi_width<=0; roi_height<=0; channel<=0; brightness<=0;
            pixel_count<=0; gray_sum<=0; near_black<=0; near_white<=0;
            rgb_any_max<=0; board_count<=0; board_gray_sum<=0;
            board_dark<=0; board_white<=0; board_rgb_any_max<=0;
            gray_min<=255; gray_max<=0; out_pixel<=0; out_gray<=0;
            out_sof<=0; out_eol<=0; out_eof<=0;
        end else begin
            // Accumulate the registered gray, not the combinational RGB path.
            // This elastic boundary also keeps statistics paired with crop handshakes.
            if (pending && out_ready && !abort_frame) begin
                pending<=0;
                pixel_count<=pixel_count+1;
                gray_sum<=gray_sum+out_gray;
                if (out_gray<=black_level) near_black<=near_black+1;
                if (out_gray>=white_level) near_white<=near_white+1;
                if (output_rgb_max) rgb_any_max<=rgb_any_max+1;
                if (pending_board) begin
                    board_count<=board_count+1;
                    board_gray_sum<=board_gray_sum+out_gray;
                    if (out_gray<=BOARD_BLACK) board_dark<=board_dark+1;
                    if (out_gray>=white_level) board_white<=board_white+1;
                    if (output_rgb_max) board_rgb_any_max<=board_rgb_any_max+1;
                end
                if (out_gray<gray_min) gray_min<=out_gray;
                if (out_gray>gray_max) gray_max<=out_gray;
            end
            if (abort_frame && (state==RECEIVE || state==DRAIN)) begin
                pending<=0; result_error<=3'd3; state<=RESULT;
            end else case (state)
                IDLE: if (cfg_valid) begin
                    request_id<=cfg_request_id; frame_id<=cfg_frame_id;
                    channel<=cfg_channel; brightness<=cfg_brightness;
                    width<=cfg_width; height<=cfg_height;
                    x0<=cfg_x; y0<=cfg_y; x1<=cfg_right[15:0]; y1<=cfg_bottom[15:0];
                    roi_width<=cfg_roi_width; roi_height<=cfg_roi_height;
                    black_level<=cfg_black; white_level<=cfg_white;
                    x<=0; y<=0; pending<=0; pending_board<=0;
                    pixel_count<=0; gray_sum<=0; near_black<=0; near_white<=0;
                    rgb_any_max<=0; board_count<=0; board_gray_sum<=0;
                    board_dark<=0; board_white<=0; board_rgb_any_max<=0;
                    gray_min<=255; gray_max<=0; result_error<=0;
                    if (config_ok) state<=RECEIVE;
                    else begin result_error<=3'd1; state<=RESULT; end
                end
                RECEIVE: if (in_valid && in_ready) begin
                    if (!markers_ok) begin
                        pending<=0; result_error<=3'd2; state<=RESULT;
                    end else begin
                        if (selected) begin
                            out_pixel<=in_pixel; out_gray<=gray; pending<=1;
                            pending_board<=ENABLE_BOARD_MASK ? in_board_mask : 1'b0;
                            out_sof<=x==x0 && y==y0;
                            out_eol<=x==x1-1;
                            out_eof<=x==x1-1 && y==y1-1;
                        end
                        if (last_column) begin x<=0; y<=y+1; end else x<=x+1;
                        if (last_input) state<=DRAIN;
                    end
                end
                DRAIN: if (!pending || out_ready) state<=RESULT;
                RESULT: if (result_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
