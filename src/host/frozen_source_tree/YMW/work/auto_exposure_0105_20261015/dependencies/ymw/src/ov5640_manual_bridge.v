`timescale 1ns/1ps
// One outstanding request, bundled data held across three-flop toggle
// synchronizers. The common reset cancels both sides together.
module ov5640_manual_bridge(
    input wire net_clk, camera_clk, reset_n,
    input wire start, set_values,
    input wire [15:0] exposure_lines,
    input wire [9:0] gain16,
    output reg busy, done, locked,
    output reg [2:0] error,
    output reg [15:0] generation,
    output reg [111:0] raw,
    input wire config_ok,
    output wire bus_start, bus_read,
    output wire [15:0] bus_address,
    output wire [7:0] bus_data,
    input wire bus_done,
    input wire [2:0] bus_error,
    input wire [7:0] bus_read_data
);
    reg request_toggle,response_toggle;
    reg saved_set;
    reg [15:0] saved_exposure;
    reg [9:0] saved_gain;
    (* ASYNC_REG="TRUE" *) reg [2:0] request_sync,response_sync;
    reg request_seen,response_seen,camera_start;
    wire camera_busy,camera_done,camera_locked;
    wire [2:0] camera_error;
    wire [15:0] camera_generation;
    wire [111:0] camera_raw;
    reg response_locked;
    reg [2:0] response_error;
    reg [15:0] response_generation;
    reg [111:0] response_raw;
    ov5640_manual_control u_control(
        .clk(camera_clk),.reset_n(reset_n),.config_ok(config_ok),
        .start(camera_start),.set_values(saved_set),.exposure_lines(saved_exposure),.gain16(saved_gain),
        .busy(camera_busy),.done(camera_done),.locked(camera_locked),.error(camera_error),
        .generation(camera_generation),.raw(camera_raw),.bus_start(bus_start),.bus_read(bus_read),
        .bus_address(bus_address),.bus_data(bus_data),.bus_done(bus_done),.bus_error(bus_error),.bus_read_data(bus_read_data));
    always @(posedge net_clk or negedge reset_n)begin
        if(!reset_n)begin
            request_toggle<=0;response_sync<=0;response_seen<=0;busy<=0;done<=0;
            locked<=0;error<=0;raw<=0;generation<=0;saved_set<=0;saved_exposure<=0;saved_gain<=0;
        end else begin
            response_sync<={response_sync[1:0],response_toggle};done<=0;
            if(start && !busy)begin
                saved_set<=set_values;saved_exposure<=exposure_lines;saved_gain<=gain16;
                request_toggle<=~request_toggle;busy<=1;locked<=0;
            end
            if(busy && response_sync[2]!=response_seen)begin
                response_seen<=response_sync[2];busy<=0;done<=1;
                locked<=response_locked;error<=response_error;generation<=response_generation;raw<=response_raw;
            end
        end
    end
    always @(posedge camera_clk or negedge reset_n)begin
        if(!reset_n)begin
            request_sync<=0;request_seen<=0;response_toggle<=0;camera_start<=0;
            response_locked<=0;response_error<=0;response_raw<=0;response_generation<=0;
        end else begin
            request_sync<={request_sync[1:0],request_toggle};camera_start<=0;
            if(!camera_busy && request_sync[2]!=request_seen)begin
                request_seen<=request_sync[2];camera_start<=1;
            end
            if(camera_done)begin
                response_locked<=camera_locked;response_error<=camera_error;
                response_raw<=camera_raw;response_generation<=camera_generation;
                response_toggle<=~response_toggle;
            end
        end
    end
endmodule
