`timescale 1ns/1ps
module tb_roi_latch_repro;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,rx_start=0,rx_valid=0,rx_done=0;reg [7:0] rx_data=0;
    wire capture,crop;wire [15:0] x,y,w,h,generation;wire frame_busy;
    integer captures=0;
    always @(posedge clk)if(capture)captures<=captures+1;
    lght_core_camera_identity #(.WIDTH(16),.HEIGHT(16),.CAM_WIDTH(64),.CAM_HEIGHT(48),.PACKET_GAP_CYCLES(0)) dut(
        .clk(clk),.reset(reset),.session_changed(1'b0),.identity_configuration_valid(1'b1),.pixel_format(8'd1),
        .light_busy(1'b0),.light_done(1'b0),.light_error(1'b0),
        .rx_start(rx_start),.rx_valid(rx_valid),.rx_done(rx_done),.rx_error(1'b0),.rx_data(rx_data),
        .rx_mac(48'd1),.rx_ip(32'd1),.rx_port(16'd5000),.tx_ready(1'b1),.tx_req(1'b1),.tx_done(1'b1),
        .capture_inhibit(1'b0),.roi_lock(1'b0),.camera_config_ok(1'b1),.camera_busy(1'b0),.camera_ready(1'b0),.camera_failed(1'b0),.camera_fail_code(3'd0),
        .manual_busy(1'b0),.manual_done(1'b0),.manual_locked(1'b1),.manual_error(3'd0),.manual_raw(112'd0),.manual_generation(16'd1),.camera_pixel(16'd0),
        .camera_capture(capture),.camera_crop_enable(crop),.camera_roi_x(x),.camera_roi_y(y),.camera_roi_width(w),.camera_roi_height(h),.identity_roi_generation(generation),.frame_busy(frame_busy));
    task command(input [7:0] op,input [15:0] seq,input [63:0] args);
        reg [159:0] message;
        begin
            message={32'h4c474854,8'd1,op,seq,16'd10,16'd0,args};
            @(negedge clk);rx_start=1;@(negedge clk);rx_start=0;
            for(integer i=0;i<20;i=i+1)begin rx_valid=1;rx_data=message[159-i*8-:8];@(negedge clk);end
            rx_valid=0;rx_done=1;@(negedge clk);rx_done=0;
        end
    endtask
    initial begin
        repeat(5)@(negedge clk);reset=0;repeat(5)@(negedge clk);
        command(6,1,{16'd4,16'd4,16'd16,16'd16});repeat(100)@(negedge clk);
        if(!dut.roi_valid||dut.roi_generation!=1||dut.roi_width!=16||dut.roi_height!=16)$fatal(1,"ROI configuration did not commit");
        if(crop||w!=64||h!=48||generation!=0||captures!=0)$fatal(1,"Expected previous full-frame active geometry before CAP");
        // With a sealed16x16/generation1 mask, the exact top-level predicate is false.
        if(w==16&&h==16&&generation==1)$fatal(1,"Unexpected pre-CAP mask match");
        $display("CASE PASS: configured ROI differs from active geometry before BEGIN");
        command(2,2,{16'd3,16'd16,16'd16,16'd1});repeat(12)@(negedge clk);
        if(!crop||x!=4||y!=4||w!=16||h!=16||generation!=1||captures!=1)$fatal(1,"ROI preparation CAP did not align actual domain");
        $display("CASE PASS: one native ROI CAP aligns active geometry and mask generation");
        $display("ROI_LATCH_REPRO_PASS 2");$finish;
    end
    initial begin #100000;$fatal(1,"Timeout");end
endmodule
