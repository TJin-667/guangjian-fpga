// 9x9 REFLECT_101 on a committed, contiguous RGB565 source domain.
// For XDL revision-2, width/height are the SAVED native image, with output ROI
// (0,0,width,height). A full-sensor DDR bank needs a separate address adapter;
// cfg_x/cfg_y only select outputs and do NOT change the reflection domain.
// Eight gray line banks, a 9-column sum window, and a delayed center pixel.
// Exact background/residual units are /81. No rounding before thresholding.
module h2_background9 #(
    parameter integer MAX_WIDTH=1920, MAX_HEIGHT=1080
)(
    input wire clk, reset, abort_frame,
    input wire cfg_valid, output wire cfg_ready,
    input wire cfg_source_complete,
    input wire [15:0] cfg_width, cfg_height, cfg_x, cfg_y, cfg_roi_width, cfg_roi_height,
    input wire [7:0] cfg_threshold,
    input wire [31:0] cfg_request_id,
    output wire read_valid, input wire read_ready,
    output wire [31:0] read_request_id,
    output wire [21:0] read_address,
    input wire response_valid, output wire response_ready,
    input wire [31:0] response_request_id,
    input wire [21:0] response_address,
    input wire [15:0] response_rgb565,
    output wire out_valid, input wire out_ready,
    output reg [31:0] out_request_id,
    output reg [15:0] out_x, out_y,
    output reg [7:0] out_gray,
    output reg [14:0] out_background_sum,
    output reg signed [15:0] out_residual_n,
    output wire [14:0] out_bright_n, out_dark_n,
    output wire out_candidate,
    output reg out_sof, out_eol, out_eof,
    output wire result_valid, input wire result_ready,
    output reg [2:0] result_error,
    output reg [31:0] output_count
);
    localparam IDLE=0, ISSUE=1, WAIT_RESPONSE=2, COMPUTE=3, EMIT=4, RESULT=5, FILTER=6, RESIDUAL=7, COLUMN_SUM=8;
    reg [3:0] state;
    reg [15:0] width,height,x0,y0,x1,y1,px,py;
    reg [14:0] threshold_n;
    reg [21:0] outstanding_address;
    reg [21:0] row_base;
    reg [7:0] gray_latched;
    reg [11:0] column_latched;
    reg [8:0] row_pairs [0:3];
    reg [7:0] center_latched;
    reg last_padded;
    reg [11:0] columns [0:7];
    reg [7:0] centers [0:3];
    wire [63:0] row_taps;
    wire [7:0] response_gray;
    rgb565_gray convert(.pixel(response_rgb565),.gray(response_gray));
    wire [16:0] cfg_right={1'b0,cfg_x}+{1'b0,cfg_roi_width};
    wire [16:0] cfg_bottom={1'b0,cfg_y}+{1'b0,cfg_roi_height};
    wire config_ok=cfg_source_complete && cfg_width>=9 && cfg_height>=9 &&
        cfg_width<=MAX_WIDTH && cfg_height<=MAX_HEIGHT && cfg_roi_width>0 && cfg_roi_height>0 &&
        cfg_right<={1'b0,cfg_width} && cfg_bottom<={1'b0,cfg_height};
    wire [15:0] source_x=px<4 ? 16'd4-px : (px<width+4 ? px-16'd4 : width*2+16'd2-px);
    // Maintain the reflected row base incrementally; no per-pixel multiplier.
    assign read_address=row_base+source_x;
    assign read_request_id=out_request_id;
    assign cfg_ready=state==IDLE && !reset;
    assign read_valid=state==ISSUE && !abort_frame && !reset;
    assign response_ready=state==WAIT_RESPONSE && !abort_frame && !reset;
    wire response_ok=response_address==outstanding_address && response_request_id==out_request_id;
    wire accept=response_valid && response_ready && response_ok;
    wire write_lines=state==COMPUTE && !abort_frame && !reset;
    assign out_valid=state==EMIT && !abort_frame && !reset;
    assign result_valid=state==RESULT && !reset;
    wire [15:0] abs_n=out_residual_n[15] ? -out_residual_n : out_residual_n;
    assign out_bright_n=out_residual_n[15] ? 15'd0 : out_residual_n[14:0];
    assign out_dark_n=out_residual_n[15] ? abs_n[14:0] : 15'd0;
    assign out_candidate=abs_n>{1'b0,threshold_n};

    genvar bank;
    generate for (bank=0;bank<8;bank=bank+1) begin: line_banks
        (* ram_style="block" *) reg [7:0] memory [0:MAX_WIDTH+7];
        reg [7:0] tap;
        assign row_taps[bank*8+:8]=tap;
        // RAM is not reset. Eight complete new padded rows precede any valid output.
        always @(posedge clk) if (accept) tap<=memory[px];
        if (bank==0) begin: first
            always @(posedge clk) if (write_lines) memory[px]<=gray_latched;
        end else begin: later
            always @(posedge clk) if (write_lines) memory[px]<=row_taps[(bank-1)*8+:8];
        end
    end endgenerate

    // Register the first adder level after synchronous BRAM read. The previous
    // flat nine-way expression failed the actual 125 MHz board setup check in
    // Vivado 2018.3. All sums remain exact; one extra cycle per padded pixel.
    wire [9:0] row_half0={1'b0,row_pairs[0]}+{1'b0,row_pairs[1]};
    wire [9:0] row_half1={1'b0,row_pairs[2]}+{1'b0,row_pairs[3]};
    wire [10:0] row_total={1'b0,row_half0}+{1'b0,row_half1};
    wire [11:0] column_sum={1'b0,row_total}+{4'd0,gray_latched};
    wire [12:0] window_pair0={1'b0,columns[0]}+{1'b0,columns[1]};
    wire [12:0] window_pair1={1'b0,columns[2]}+{1'b0,columns[3]};
    wire [12:0] window_pair2={1'b0,columns[4]}+{1'b0,columns[5]};
    wire [12:0] window_pair3={1'b0,columns[6]}+{1'b0,columns[7]};
    wire [13:0] window_half0={1'b0,window_pair0}+{1'b0,window_pair1};
    wire [13:0] window_half1={1'b0,window_pair2}+{1'b0,window_pair3};
    wire [14:0] window_total={1'b0,window_half0}+{1'b0,window_half1};
    wire [14:0] window_sum=window_total+{3'd0,column_latched};
    wire [15:0] center_scaled={8'd0,out_gray}*16'd81;
    wire signed [15:0] residual=$signed(center_scaled)-$signed({1'b0,out_background_sum});
    wire selected=px>=8 && py>=8 && px-8>=x0 && px-8<x1 && py-8>=y0 && py-8<y1;
    wire last_pixel=px==width+7 && py==height+7;
    integer i;
    always @(posedge clk) begin
        if (reset) begin
            state<=IDLE;result_error<=0;output_count<=0;
            width<=0;height<=0;x0<=0;y0<=0;x1<=0;y1<=0;px<=0;py<=0;
            threshold_n<=0;outstanding_address<=0;gray_latched<=0;last_padded<=0;
            row_base<=0;column_latched<=0;center_latched<=0;
            out_request_id<=0;out_x<=0;out_y<=0;out_gray<=0;out_background_sum<=0;out_residual_n<=0;
            out_sof<=0;out_eol<=0;out_eof<=0;
            for(i=0;i<8;i=i+1)columns[i]<=0;
            for(i=0;i<4;i=i+1)centers[i]<=0;
            for(i=0;i<4;i=i+1)row_pairs[i]<=0;
        end else if(abort_frame && state!=IDLE && state!=RESULT) begin
            result_error<=3;state<=RESULT;
        end else case(state)
            IDLE: if(cfg_valid) begin
                width<=cfg_width;height<=cfg_height;x0<=cfg_x;y0<=cfg_y;
                x1<=cfg_right[15:0];y1<=cfg_bottom[15:0];px<=0;py<=0;
                row_base<={4'd0,cfg_width,2'd0};
                out_request_id<=cfg_request_id;threshold_n<=cfg_threshold*15'd81;
                result_error<=0;output_count<=0;last_padded<=0;
                for(i=0;i<8;i=i+1)columns[i]<=0;
                for(i=0;i<4;i=i+1)centers[i]<=0;
                if(config_ok)state<=ISSUE;
                else begin result_error<=1;state<=RESULT;end
            end
            ISSUE: if(read_ready) begin outstanding_address<=read_address;state<=WAIT_RESPONSE;end
            WAIT_RESPONSE: if(response_valid) begin
                if(!response_ok) begin result_error<=2;state<=RESULT;end
                else begin gray_latched<=response_gray;state<=COMPUTE;end
            end
            COMPUTE: begin
                for(i=0;i<4;i=i+1)
                    row_pairs[i]<={1'b0,row_taps[i*16+:8]}+{1'b0,row_taps[i*16+8+:8]};
                center_latched<=row_taps[31:24];state<=COLUMN_SUM;
            end
            COLUMN_SUM: begin
                column_latched<=column_sum;state<=FILTER;
            end
            FILTER: begin
                columns[0]<=column_latched;
                for(i=1;i<8;i=i+1)columns[i]<=columns[i-1];
                centers[0]<=center_latched;
                for(i=1;i<4;i=i+1)centers[i]<=centers[i-1];
                if(selected) begin
                    out_x<=px-8;out_y<=py-8;out_gray<=centers[3];
                    out_background_sum<=window_sum;
                    out_sof<=px-8==x0 && py-8==y0;
                    out_eol<=px-8==x1-1;out_eof<=px-8==x1-1 && py-8==y1-1;
                    last_padded<=last_pixel;state<=RESIDUAL;
                end else state<=last_pixel ? RESULT : ISSUE;
                if(px==width+7) begin
                    px<=0;py<=py+1;
                    if(py<4 || py>=height+3)row_base<=row_base-width;
                    else row_base<=row_base+width;
                    for(i=0;i<8;i=i+1)columns[i]<=0;
                    for(i=0;i<4;i=i+1)centers[i]<=0;
                end else px<=px+1;
            end
            RESIDUAL: begin out_residual_n<=residual;state<=EMIT;end
            EMIT: if(out_ready) begin output_count<=output_count+1;state<=last_padded ? RESULT : ISSUE;end
            RESULT: if(result_ready) state<=IDLE;
            default:state<=IDLE;
        endcase
    end
endmodule
