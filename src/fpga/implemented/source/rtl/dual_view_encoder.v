`timescale 1ns/1ps
// Acceptance diagnostic only. Each group contains 2*k original RGB bytes,
// k bytes from the unchanged gray encoder, then its original SAT byte.
// No second camera capture, DDR replay, full-frame buffer or image algorithm.
module dual_view_encoder(
    input wire clk,reset,cancel,start,input wire dual_view,
    input wire [21:0] total_pixels,
    input wire in_valid,output wire in_ready,input wire [15:0] in_pixel,input wire in_eof,
    output wire out_valid,input wire out_ready,output wire [7:0] out_byte,
    output wire out_eof,output wire done,output wire [1:0] error
);
    reg [15:0] rgb[0:7];
    reg [3:0] filled,gray_index;
    reg [4:0] rgb_index;
    reg selected;
    wire codec_valid,codec_ready,codec_eof;
    wire [7:0] codec_byte;
    wire emit_rgb=selected && rgb_index < {filled,1'b0};
    wire codec_in_ready;
    assign in_ready=codec_in_ready;
    assign out_valid=codec_valid;
    assign out_byte=emit_rgb ? (rgb_index[0] ? rgb[rgb_index[3:1]][7:0] : rgb[rgb_index[3:1]][15:8]) : codec_byte;
    assign out_eof=codec_eof && !emit_rgb;
    assign codec_ready=out_ready && !emit_rgb;
    gray_sat_encoder encoder(
        .clk(clk),.reset(reset),.cancel(cancel),.start(start),.total_pixels(total_pixels),
        .in_valid(in_valid),.in_ready(codec_in_ready),.in_pixel(in_pixel),.in_eof(in_eof),
        .out_valid(codec_valid),.out_ready(codec_ready),.out_byte(codec_byte),
        .out_sof(),.out_eof(codec_eof),.done(done),.error(error));
    integer i;
    always @(posedge clk)begin
        if(reset || cancel || start)begin
            selected<=start && dual_view;filled<=0;gray_index<=0;rgb_index<=0;
            for(i=0;i<8;i=i+1)rgb[i]<=0;
        end else begin
            if(in_valid && in_ready)begin rgb[filled[2:0]]<=in_pixel;filled<=filled+1;end
            if(out_valid && out_ready)begin
                if(emit_rgb)rgb_index<=rgb_index+1;
                else if(gray_index==filled)begin filled<=0;rgb_index<=0;gray_index<=0;end
                else gray_index<=gray_index+1;
            end
        end
    end
endmodule
