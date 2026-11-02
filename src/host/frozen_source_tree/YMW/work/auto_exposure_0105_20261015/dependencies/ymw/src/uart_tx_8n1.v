`timescale 1ns/1ps
module uart_tx_8n1 #(
    parameter integer CLKS_PER_BIT = 5208
) (
    input  wire       clk,
    input  wire       reset_n,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output reg        busy,
    output reg        done
);
    localparam [1:0] IDLE = 2'd0, START = 2'd1, DATA = 2'd2, STOP = 2'd3;

    reg [1:0] state;
    reg [15:0] bit_clock;
    reg [2:0] bit_index;
    reg [7:0] held_data;

    initial begin
        state = IDLE;
        bit_clock = 0;
        bit_index = 0;
        held_data = 0;
        tx = 1'b1;
        busy = 1'b0;
        done = 1'b0;
    end

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= IDLE;
            bit_clock <= 0;
            bit_index <= 0;
            held_data <= 0;
            tx <= 1'b1;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                IDLE: begin
                    tx <= 1'b1;
                    busy <= 1'b0;
                    bit_clock <= 0;
                    if (start) begin
                        held_data <= data;
                        bit_index <= 0;
                        tx <= 1'b0;
                        busy <= 1'b1;
                        state <= START;
                    end
                end
                START: begin
                    if (bit_clock == CLKS_PER_BIT - 1) begin
                        bit_clock <= 0;
                        tx <= held_data[0];
                        state <= DATA;
                    end else bit_clock <= bit_clock + 1'b1;
                end
                DATA: begin
                    if (bit_clock == CLKS_PER_BIT - 1) begin
                        bit_clock <= 0;
                        if (bit_index == 3'd7) begin
                            tx <= 1'b1;
                            state <= STOP;
                        end else begin
                            bit_index <= bit_index + 1'b1;
                            tx <= held_data[bit_index + 1'b1];
                        end
                    end else bit_clock <= bit_clock + 1'b1;
                end
                STOP: begin
                    if (bit_clock == CLKS_PER_BIT - 1) begin
                        bit_clock <= 0;
                        tx <= 1'b1;
                        busy <= 1'b0;
                        done <= 1'b1;
                        state <= IDLE;
                    end else bit_clock <= bit_clock + 1'b1;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
