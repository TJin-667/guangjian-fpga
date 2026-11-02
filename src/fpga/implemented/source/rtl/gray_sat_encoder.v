`timescale 1ns/1ps
// Isolated candidate primitive, not connected to or enabled in a board bit.
// 8 gray bytes then one SAT byte (bit7 = first pixel). Tail: k gray + SAT.
module gray_sat_encoder(
    input wire clk,reset,cancel,start,input wire [21:0] total_pixels,
    input wire in_valid,output wire in_ready,input wire [15:0] in_pixel,input wire in_eof,
    output wire out_valid,input wire out_ready,output wire [7:0] out_byte,
    output wire out_sof,out_eof,output reg done,output reg [1:0] error
);
    reg active,emitting,final_group,first_group;
    reg [21:0] total,accepted;
    reg [3:0] filled,emit_index,emit_count;
    reg [7:0] gray_bytes[0:7];reg [7:0] sat_bits;
    reg [1:0] convert_state;
    reg [7:0] red,green,blue;
    (* use_dsp="no" *) reg [23:0] red_product,green_product,blue_product;
    reg pixel_sat,pixel_final;
    wire [23:0] weighted=red_product+green_product+blue_product+24'd16384;
    wire [7:0] gray=weighted[22:15];
    wire sat=(in_pixel[15:11]==5'd31)||(in_pixel[10:5]==6'd63)||(in_pixel[4:0]==5'd31);
    assign in_ready=active && !emitting && convert_state==0 && !reset && !cancel && !start;
    assign out_valid=active && emitting && !reset && !cancel && !start;
    assign out_byte=emit_index<emit_count ? gray_bytes[emit_index[2:0]] : sat_bits;
    assign out_sof=out_valid && first_group && emit_index==0;
    assign out_eof=out_valid && final_group && emit_index==emit_count;
    integer i;
    always @(posedge clk)begin
        if(reset || cancel)begin
            active<=0;emitting<=0;final_group<=0;first_group<=1;total<=0;accepted<=0;
            filled<=0;emit_index<=0;emit_count<=0;sat_bits<=0;done<=0;error<=0;
            convert_state<=0;red<=0;green<=0;blue<=0;red_product<=0;green_product<=0;blue_product<=0;pixel_sat<=0;pixel_final<=0;
            for(i=0;i<8;i=i+1)gray_bytes[i]<=0;
        end else if(start)begin
            if(active)begin active<=0;emitting<=0;error<=2;done<=0;end
            else begin
                active<=total_pixels>0 && total_pixels<=22'd2073600;
                error<=(total_pixels==0 || total_pixels>22'd2073600)?1:0;
                total<=total_pixels;accepted<=0;filled<=0;emit_index<=0;emit_count<=0;
                sat_bits<=0;emitting<=0;final_group<=0;first_group<=1;done<=0;
                convert_state<=0;
            end
        end else begin
            if(in_valid && in_ready)begin
                if(in_eof!=(accepted==total-1))begin active<=0;emitting<=0;error<=1;end
                else begin
                    red<={in_pixel[15:11],in_pixel[15:13]};green<={in_pixel[10:5],in_pixel[10:9]};blue<={in_pixel[4:0],in_pixel[4:2]};
                    pixel_sat<=sat;pixel_final<=in_eof;accepted<=accepted+1;convert_state<=1;
                end
            end
            if(active && convert_state==1)begin
                red_product<=red*24'd9798;green_product<=green*24'd19235;blue_product<=blue*24'd3735;convert_state<=2;
            end
            if(active && convert_state==2)begin
                gray_bytes[filled[2:0]]<=gray;sat_bits[7-filled[2:0]]<=pixel_sat;
                filled<=filled+1;convert_state<=0;
                if(filled==7 || pixel_final)begin
                    emitting<=1;emit_index<=0;emit_count<=filled+1;final_group<=pixel_final;
                end
            end
            if(out_valid && out_ready)begin
                if(emit_index==emit_count)begin
                    if(final_group)begin active<=0;done<=1;end
                    emitting<=0;filled<=0;sat_bits<=0;first_group<=0;
                end else emit_index<=emit_index+1;
            end
        end
    end
endmodule
