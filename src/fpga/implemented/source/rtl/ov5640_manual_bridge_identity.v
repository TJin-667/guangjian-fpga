`timescale 1ns/1ps
// Candidate replacement for the pinned bridge. Payload is captured by a
// destination register before the manual controller evaluates range checks.
// A single request remains outstanding until its complete response is consumed.
module ov5640_manual_bridge_identity(
    input wire net_clk,camera_clk,reset_n,start,set_values,
    input wire [15:0] exposure_lines,input wire [9:0] gain16,
    output reg busy,done,locked,output reg [2:0] error,
    output reg [15:0] generation,output reg [111:0] raw,
    input wire config_ok,output wire bus_start,bus_read,
    output wire [15:0] bus_address,output wire [7:0] bus_data,
    input wire bus_done,input wire [2:0] bus_error,input wire [7:0] bus_read_data
);
    wire net_reset,camera_reset;
    reset_release_sync nr(.clk(net_clk),.async_reset(!reset_n),.reset(net_reset));
    reset_release_sync cr(.clk(camera_clk),.async_reset(!reset_n),.reset(camera_reset));
    wire request_ready,request_valid,response_ready,response_valid;
    wire [26:0] request_data;
    wire [131:0] response_data;
    wire camera_busy,camera_done,camera_locked;
    wire [2:0] camera_error;wire [15:0] camera_generation;wire [111:0] camera_raw;
    reg camera_start;reg [26:0] local_request;
    cdc_snapshot_mailbox #(.WIDTH(27)) requests(
        .src_clk(net_clk),.src_reset(net_reset),.src_valid(start && !busy),.src_ready(request_ready),
        .src_data({set_values,exposure_lines,gain16}),.dst_clk(camera_clk),.dst_reset(camera_reset),
        .dst_valid(request_valid),.dst_ready(!camera_busy && !camera_start),.dst_data(request_data));
    cdc_snapshot_mailbox #(.WIDTH(132)) responses(
        .src_clk(camera_clk),.src_reset(camera_reset),.src_valid(camera_done),.src_ready(response_ready),
        .src_data({camera_locked,camera_error,camera_generation,camera_raw}),
        .dst_clk(net_clk),.dst_reset(net_reset),.dst_valid(response_valid),.dst_ready(1'b1),.dst_data(response_data));
    ov5640_manual_control u_control(
        .clk(camera_clk),.reset_n(!camera_reset),.config_ok(config_ok),.start(camera_start),
        .set_values(local_request[26]),.exposure_lines(local_request[25:10]),.gain16(local_request[9:0]),
        .busy(camera_busy),.done(camera_done),.locked(camera_locked),.error(camera_error),
        .generation(camera_generation),.raw(camera_raw),.bus_start(bus_start),.bus_read(bus_read),
        .bus_address(bus_address),.bus_data(bus_data),.bus_done(bus_done),.bus_error(bus_error),.bus_read_data(bus_read_data));
    always @(posedge camera_clk)begin
        if(camera_reset)begin camera_start<=0;local_request<=0;end
        else begin
            camera_start<=request_valid && !camera_busy && !camera_start;
            if(request_valid && !camera_busy && !camera_start)local_request<=request_data;
        end
    end
    always @(posedge net_clk)begin
        if(net_reset)begin busy<=0;done<=0;locked<=0;error<=0;generation<=0;raw<=0;end
        else begin
            done<=0;
            if(start && !busy && request_ready)begin busy<=1;locked<=0;end
            if(response_valid && busy)begin
                {locked,error,generation,raw}<=response_data;busy<=0;done<=1;
            end
        end
    end
endmodule
