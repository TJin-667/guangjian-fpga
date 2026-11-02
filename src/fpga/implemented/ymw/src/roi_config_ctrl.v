`timescale 1ns/1ps
// Atomic ROI configuration with bounded packet-count subtraction.
module roi_config_ctrl #(
    parameter integer WIDTH=1920,HEIGHT=1080,PIXELS_PER_PACKET=690
)(
    input wire clk,reset,start,
    input wire [15:0] request_x,request_y,request_width,request_height,
    output wire busy,
    output reg done,error,valid,
    output reg [15:0] x,y,width,height,packets,generation,
    output reg [31:0] pixels,
    output reg [10:0] last_pixels
);
    localparam IDLE=0,PRODUCT=1,DIVIDE=2;
    reg [1:0] state;
    reg [15:0] pending_x,pending_y,pending_width,pending_height,count;
    reg [31:0] remaining,product;
    assign busy=state!=IDLE;
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;done<=0;error<=0;valid<=0;
            x<=0;y<=0;width<=WIDTH;height<=HEIGHT;
            pixels<=WIDTH*HEIGHT;packets<=(WIDTH*HEIGHT+PIXELS_PER_PACKET-1)/PIXELS_PER_PACKET;
            last_pixels<=WIDTH*HEIGHT-((WIDTH*HEIGHT+PIXELS_PER_PACKET-1)/PIXELS_PER_PACKET-1)*PIXELS_PER_PACKET;
            generation<=0;pending_x<=0;pending_y<=0;pending_width<=0;pending_height<=0;
            count<=0;remaining<=0;product<=0;
        end else begin
            done<=0;
            case(state)
                IDLE:if(start)begin
                    error<=0;
                    if(request_width==0 || request_height==0 ||
                       {1'b0,request_x}+{1'b0,request_width}>WIDTH ||
                       {1'b0,request_y}+{1'b0,request_height}>HEIGHT)begin error<=1;done<=1;end
                    else begin
                        pending_x<=request_x;pending_y<=request_y;
                        pending_width<=request_width;pending_height<=request_height;
                        product<=request_width*request_height;count<=0;state<=PRODUCT;
                    end
                end
                PRODUCT:begin remaining<=product;state<=DIVIDE;end
                DIVIDE:if(remaining>PIXELS_PER_PACKET)begin
                    remaining<=remaining-PIXELS_PER_PACKET;count<=count+1'b1;
                end else begin
                    x<=pending_x;y<=pending_y;width<=pending_width;height<=pending_height;
                    pixels<=product;packets<=count+1'b1;last_pixels<=remaining[10:0];
                    generation<=generation==16'hffff ? 16'd1 : generation+1'b1;
                    valid<=1;done<=1;state<=IDLE;
                end
                default:begin error<=1;done<=1;state<=IDLE;end
            endcase
        end
    end
endmodule
