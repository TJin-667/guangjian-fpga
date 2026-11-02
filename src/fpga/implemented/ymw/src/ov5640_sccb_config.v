`timescale 1ns/1ps
// Initial table and runtime manual control share one SCCB master.
module ov5640_sccb_config #(
    parameter integer POWER_WAIT_CYCLES=5000000,
    parameter integer WRITE_GAP_CYCLES=500000,
    parameter integer TICK_CYCLES=125,
    parameter integer TIMEOUT_CYCLES=200000
)(
    input wire clk_50m, reset_n,
    input wire cam_sda_i, cam_scl_i,
    output wire cam_sda_low, cam_scl_low,
    output wire config_ok,
    output reg config_done, ack_error,
    input wire control_start, control_read,
    input wire [15:0] control_address,
    input wire [7:0] control_data,
    output wire control_done,
    output wire [2:0] control_error,
    output wire [7:0] control_read_data
);
    localparam POWER_WAIT=0, LOAD=1, WRITE=2, GAP=3, FINISHED=4;
    reg [2:0] state;
    integer delay_counter;
    reg [8:0] config_index;
    reg master_start;
    reg [15:0] master_address;
    reg [7:0] master_data;
    wire [23:0] rom_data;
    wire [8:0] rom_size;
    wire master_done, master_busy;
    wire [2:0] master_error;
    assign config_ok=config_done && !ack_error;
    assign control_done=state==FINISHED && master_done;
    assign control_error=master_error;
    I2C_OV5640_RGB565_Config config_rom(
        .LUT_INDEX(config_index+9'd2),.LUT_DATA(rom_data),.LUT_SIZE(rom_size));
    ov5640_sccb_master #(.TICK_CYCLES(TICK_CYCLES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) u_master(
        .clk(clk_50m),.reset_n(reset_n),
        .start(state==FINISHED?(control_start && config_ok):master_start),
        .read(state==FINISHED && control_read),
        .address(state==FINISHED?control_address:master_address),
        .write_data(state==FINISHED?control_data:master_data),
        .sda(cam_sda_i),.scl(cam_scl_i),.sda_low(cam_sda_low),.scl_low(cam_scl_low),
        .busy(master_busy),.done(master_done),
        .error(master_error),.read_data(control_read_data));
    always @(posedge clk_50m or negedge reset_n) begin
        if(!reset_n)begin
            state<=POWER_WAIT;delay_counter<=0;config_index<=0;
            master_start<=0;master_address<=0;master_data<=0;config_done<=0;ack_error<=0;
        end else begin
            master_start<=0;
            case(state)
                POWER_WAIT:if(delay_counter>=POWER_WAIT_CYCLES-1)begin delay_counter<=0;state<=LOAD;end
                           else delay_counter<=delay_counter+1;
                LOAD:begin master_address<=rom_data[23:8];master_data<=rom_data[7:0];master_start<=1;state<=WRITE;end
                WRITE:if(master_done)begin
                    if(master_error!=0)begin ack_error<=1;config_done<=1;state<=FINISHED;end
                    else begin delay_counter<=0;state<=GAP;end
                end
                GAP:if(delay_counter>=WRITE_GAP_CYCLES-1)begin
                    delay_counter<=0;
                    if(config_index==rom_size-3)begin config_done<=1;state<=FINISHED;end
                    else begin config_index<=config_index+1'b1;state<=LOAD;end
                end else delay_counter<=delay_counter+1;
                FINISHED:state<=FINISHED;
                default:begin ack_error<=1;config_done<=1;state<=FINISHED;end
            endcase
        end
    end
endmodule
