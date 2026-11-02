`timescale 1ns/1ps
// 23 restoring-division steps; no combinational /1380 on a TX header path.
module transport_layout(
    input wire clk,reset,cancel,start,input wire [7:0] pixel_format,
    input wire [21:0] total_pixels,
    output reg ready,output reg error,output reg [31:0] total_bytes,
    output reg [15:0] packet_count,last_bytes
);
    reg busy;reg [4:0] step;
    reg [22:0] dividend,quotient;reg [10:0] remainder;
    wire [31:0] size=pixel_format==8'h32 ? ({10'd0,total_pixels}*3)+(({10'd0,total_pixels}+7)>>3) : pixel_format==8'h31 ? {10'd0,total_pixels}+(({10'd0,total_pixels}+7)>>3) : {9'd0,total_pixels,1'b0};
    wire [11:0] trial={remainder,dividend[22]};
    wire subtract=trial>=12'd1380;
    wire [11:0] next_remainder=subtract ? trial-12'd1380 : trial;
    wire [22:0] next_quotient={quotient[21:0],subtract};
    always @(posedge clk)begin
        if(reset || cancel)begin
            busy<=0;ready<=0;error<=0;step<=0;dividend<=0;quotient<=0;remainder<=0;total_bytes<=0;packet_count<=0;last_bytes<=0;
        end else if(start)begin
            ready<=0;error<=0;step<=0;quotient<=0;remainder<=0;dividend<=size[22:0];total_bytes<=size;packet_count<=0;last_bytes<=0;
            if(busy || total_pixels==0 || total_pixels>22'd2073600 || (pixel_format!=1 && pixel_format!=8'h31 && pixel_format!=8'h32))begin error<=1;busy<=0;end
            else busy<=1;
        end else if(busy)begin
            dividend<={dividend[21:0],1'b0};quotient<=next_quotient;remainder<=next_remainder[10:0];step<=step+1;
            if(step==22)begin
                packet_count<=next_quotient[15:0]+(next_remainder!=0);
                last_bytes<=next_remainder==0 ? 16'd1380 : {4'd0,next_remainder};
                ready<=1;busy<=0;
            end
        end
    end
endmodule
