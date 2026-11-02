`timescale 1ns/1ps
// Bounded open-drain register transfer. Reads end with a master NACK.
module ov5640_sccb_master #(
    parameter integer TICK_CYCLES=125,
    parameter integer TIMEOUT_CYCLES=200000
)(
    input wire clk, reset_n, start, read,
    input wire [15:0] address,
    input wire [7:0] write_data,
    input wire sda, scl,
    output reg sda_low, scl_low,
    output wire busy,
    output reg done,
    output reg [2:0] error,
    output reg [7:0] read_data
);
    localparam IDLE=0, START_IDLE=1, START_SDA=2, START_LOW=3,
        SEND_SET=4, SEND_HIGH=5, SEND_SAMPLE=6, SEND_LOW=7,
        ACK_REL=8, ACK_HIGH=9, ACK_SAMPLE=10, ACK_LOW=11,
        REP_REL=12, REP_HIGH=13, REP_SDA=14, REP_LOW=15,
        READ_REL=16, READ_HIGH=17, READ_SAMPLE=18, READ_LOW=19,
        NACK_REL=20, NACK_HIGH=21, NACK_HOLD=22, NACK_LOW=23,
        STOP_SET=24, STOP_HIGH=25, STOP_HOLD=26, STOP_REL=27, BUS_END=28;
    reg [4:0] state;
    reg is_read;
    reg [15:0] saved_address;
    reg [7:0] saved_data, tx_byte;
    reg [2:0] bit_index;
    reg [1:0] phase;
    integer divider, watchdog;
    assign busy=state!=IDLE;
    always @(posedge clk or negedge reset_n) begin
        if(!reset_n)begin
            state<=IDLE;divider<=0;watchdog<=0;scl_low<=0;sda_low<=0;
            done<=0;error<=0;read_data<=0;is_read<=0;saved_address<=0;
            saved_data<=0;tx_byte<=0;bit_index<=7;phase<=0;
        end else begin
            done<=0;
            if(state==IDLE)begin
                divider<=0;watchdog<=0;scl_low<=0;sda_low<=0;
                if(start)begin
                    saved_address<=address;saved_data<=write_data;is_read<=read;
                    error<=0;read_data<=0;phase<=0;tx_byte<=8'h78;bit_index<=7;
                    state<=START_IDLE;
                end
            end else if(watchdog>=TIMEOUT_CYCLES-1)begin
                state<=IDLE;scl_low<=0;sda_low<=0;error<=2;done<=1;
            end else begin
                watchdog<=watchdog+1;
                if(divider<TICK_CYCLES-1)divider<=divider+1;
                else begin
                    divider<=0;
                    case(state)
                        START_IDLE:if(scl===1'b1 && sda===1'b1)state<=START_SDA;
                        START_SDA:begin sda_low<=1;state<=START_LOW;end
                        START_LOW:begin scl_low<=1;state<=SEND_SET;end
                        SEND_SET:begin sda_low<=~tx_byte[bit_index];state<=SEND_HIGH;end
                        SEND_HIGH:begin scl_low<=0;state<=SEND_SAMPLE;end
                        SEND_SAMPLE:if(scl===1'b1)state<=SEND_LOW;
                        SEND_LOW:begin
                            scl_low<=1;
                            if(bit_index==0)state<=ACK_REL;
                            else begin bit_index<=bit_index-1'b1;state<=SEND_SET;end
                        end
                        ACK_REL:begin sda_low<=0;state<=ACK_HIGH;end
                        ACK_HIGH:begin scl_low<=0;state<=ACK_SAMPLE;end
                        ACK_SAMPLE:if(scl===1'b1)begin
                            if(sda!==1'b0)error<=1;
                            state<=ACK_LOW;
                        end
                        ACK_LOW:begin
                            scl_low<=1;bit_index<=7;
                            if(error!=0)state<=STOP_SET;
                            else case(phase)
                                0:begin phase<=1;tx_byte<=saved_address[15:8];state<=SEND_SET;end
                                1:begin phase<=2;tx_byte<=saved_address[7:0];state<=SEND_SET;end
                                2:if(is_read)state<=REP_REL;
                                  else begin phase<=3;tx_byte<=saved_data;state<=SEND_SET;end
                                3:state<=is_read?READ_REL:STOP_SET;
                            endcase
                        end
                        REP_REL:begin sda_low<=0;state<=REP_HIGH;end
                        REP_HIGH:begin scl_low<=0;state<=REP_SDA;end
                        REP_SDA:if(scl===1'b1)begin sda_low<=1;state<=REP_LOW;end
                        REP_LOW:begin scl_low<=1;phase<=3;tx_byte<=8'h79;state<=SEND_SET;end
                        READ_REL:begin sda_low<=0;state<=READ_HIGH;end
                        READ_HIGH:begin scl_low<=0;state<=READ_SAMPLE;end
                        READ_SAMPLE:if(scl===1'b1)begin
                            read_data[bit_index]<=sda;state<=READ_LOW;
                        end
                        READ_LOW:begin
                            scl_low<=1;
                            if(bit_index==0)state<=NACK_REL;
                            else begin bit_index<=bit_index-1'b1;state<=READ_REL;end
                        end
                        NACK_REL:begin sda_low<=0;state<=NACK_HIGH;end
                        NACK_HIGH:begin scl_low<=0;state<=NACK_HOLD;end
                        NACK_HOLD:if(scl===1'b1)state<=NACK_LOW;
                        NACK_LOW:begin scl_low<=1;state<=STOP_SET;end
                        STOP_SET:begin sda_low<=1;state<=STOP_HIGH;end
                        STOP_HIGH:begin scl_low<=0;state<=STOP_HOLD;end
                        STOP_HOLD:if(scl===1'b1)state<=STOP_REL;
                        STOP_REL:begin sda_low<=0;state<=BUS_END;end
                        BUS_END:begin
                            if(scl!==1'b1 || sda!==1'b1)error<=3;
                            done<=1;state<=IDLE;
                        end
                        default:begin state<=IDLE;error<=3;done<=1;scl_low<=0;sda_low<=0;end
                    endcase
                end
            end
        end
    end
endmodule
