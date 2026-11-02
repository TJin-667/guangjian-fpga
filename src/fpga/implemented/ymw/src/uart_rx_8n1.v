`timescale 1ns/1ps
module uart_rx_8n1 #(
    parameter integer CLKS_PER_BIT = 13021
)(
    input wire clk,reset_n,rx,
    output reg [7:0] data,
    output reg valid
);
    (* ASYNC_REG="TRUE" *) reg rx_meta,rx_sync;
    reg [1:0] state;
    reg [15:0] counter;
    reg [2:0] bit_index;
    reg [7:0] shift;
    always @(posedge clk) begin
        if(!reset_n)begin
            rx_meta<=1;rx_sync<=1;state<=0;counter<=0;
            bit_index<=0;shift<=0;data<=0;valid<=0;
        end else begin
            rx_meta<=rx;rx_sync<=rx_meta;valid<=0;
            case(state)
                0:if(!rx_sync)begin counter<=0;state<=1;end
                1:if(counter==(CLKS_PER_BIT/2)-1)begin
                    counter<=0;
                    if(!rx_sync)begin bit_index<=0;state<=2;end else state<=0;
                end else counter<=counter+1'b1;
                2:if(counter==CLKS_PER_BIT-1)begin
                    counter<=0;shift[bit_index]<=rx_sync;
                    if(bit_index==7)state<=3;else bit_index<=bit_index+1'b1;
                end else counter<=counter+1'b1;
                3:if(counter==CLKS_PER_BIT-1)begin
                    counter<=0;state<=0;
                    if(rx_sync)begin data<=shift;valid<=1;end
                end else counter<=counter+1'b1;
            endcase
        end
    end
endmodule
