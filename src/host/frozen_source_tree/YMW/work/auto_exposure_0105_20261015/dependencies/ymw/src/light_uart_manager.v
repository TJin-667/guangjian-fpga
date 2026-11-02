`timescale 1ns/1ps
// Apply a complete four-channel mask. UDP ACK is delayed until the controller
// has returned '$' for all four serial commands. '&'/timeout aborts the apply.
module light_uart_manager #(
    parameter integer CLKS_PER_BIT=13021,
    parameter integer ACK_TIMEOUT_CYCLES=62500000,
    parameter integer CMD_GAP_CYCLES=1250000
)(
    input wire clk,reset,start,
    input wire [3:0] mask,
    input wire [7:0] brightness,
    input wire uart_rx,
    output wire uart_tx,
    output reg busy,done,error
);
    localparam IDLE=0,PREPARE=1,SEND=2,WAIT_BUSY=3,WAIT_TX=4,WAIT_ACK=5,GAP=6;
    reg [2:0] state;
    reg [3:0] held_mask;
    reg [7:0] held_brightness;
    reg [1:0] channel;
    reg [2:0] byte_index;
    reg [31:0] timer;
    reg [7:0] tx_data;
    reg tx_start,ack_seen,reject_seen;
    wire tx_busy,tx_done,rx_valid;
    wire [7:0] rx_data;
    reg [63:0] frame;
    function [7:0] hexchar;
        input [3:0] n;
        begin hexchar=n<10?8'h30+n:8'h41+(n-10);end
    endfunction
    wire [7:0] c1=held_mask[channel]?8'h33:8'h32;
    wire [7:0] c2=8'h31+channel;
    wire [7:0] c4=held_mask[channel]?hexchar(held_brightness[7:4]):8'h36;
    wire [7:0] c5=held_mask[channel]?hexchar(held_brightness[3:0]):8'h34;
    wire [7:0] checksum=8'h24^c1^c2^8'h30^c4^c5;
    uart_tx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx(
        .clk(clk),.reset_n(!reset),.start(tx_start),.data(tx_data),
        .tx(uart_tx),.busy(tx_busy),.done(tx_done));
    uart_rx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx(
        .clk(clk),.reset_n(!reset),.rx(uart_rx),.data(rx_data),.valid(rx_valid));
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;held_mask<=0;held_brightness<=0;channel<=0;
            byte_index<=0;timer<=0;tx_data<=0;tx_start<=0;
            frame<=0;busy<=0;done<=0;error<=0;ack_seen<=0;reject_seen<=0;
        end else begin
            tx_start<=0;done<=0;
            if(rx_valid && state!=IDLE && state!=GAP && state!=PREPARE)begin
                if(rx_data==8'h24)ack_seen<=1;
                if(rx_data==8'h26)reject_seen<=1;
            end
            case(state)
                IDLE:if(start)begin
                    held_mask<=mask;held_brightness<=brightness;channel<=0;
                    error<=0;busy<=1;state<=PREPARE;
                end
                PREPARE:begin
                    frame<={8'h24,c1,c2,8'h30,c4,c5,
                            hexchar(checksum[7:4]),hexchar(checksum[3:0])};
                    byte_index<=0;ack_seen<=0;reject_seen<=0;timer<=0;state<=SEND;
                end
                SEND:begin
                    tx_data<=frame[63-byte_index*8-:8];tx_start<=1;state<=WAIT_BUSY;
                end
                WAIT_BUSY:if(tx_busy)state<=WAIT_TX;
                WAIT_TX:if(tx_done)begin
                    if(byte_index==7)begin timer<=0;state<=WAIT_ACK;end
                    else begin byte_index<=byte_index+1'b1;state<=SEND;end
                end
                WAIT_ACK:begin
                    timer<=timer+1'b1;
                    if(reject_seen || timer==ACK_TIMEOUT_CYCLES-1)begin
                        error<=1;busy<=0;done<=1;state<=IDLE;
                    end else if(ack_seen)begin
                        if(channel==3)begin busy<=0;done<=1;state<=IDLE;end
                        else begin channel<=channel+1'b1;timer<=0;state<=GAP;end
                    end
                end
                GAP:if(timer==CMD_GAP_CYCLES-1)begin timer<=0;state<=PREPARE;end
                    else timer<=timer+1'b1;
                default:begin busy<=0;done<=1;error<=1;state<=IDLE;end
            endcase
        end
    end
endmodule
