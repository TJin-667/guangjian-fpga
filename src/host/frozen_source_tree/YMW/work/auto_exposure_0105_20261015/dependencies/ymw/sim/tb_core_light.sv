`timescale 1ns/1ps
module tb_core_light;
    reg clk=0,reset=1,rx_start=0,rx_valid=0,rx_done=0;
    reg [7:0] rx_data=0;
    reg light_busy=0,light_done=0,light_error=0;
    wire light_start;
    wire [3:0] light_mask;
    wire [7:0] light_brightness;
    wire tx_start;
    reg tx_ready=1,tx_req=0,tx_done=0;
    wire [15:0] tx_length;
    wire [7:0] tx_data;
    reg [7:0] packet[0:31];
    reg [7:0] req[0:19];
    integer packets=0;
    integer expected_result=0;
    always #4 clk=~clk;
    lght_core_camera dut(.clk(clk),.reset(reset),
        .light_busy(light_busy),.light_done(light_done),.light_error(light_error),
        .light_start(light_start),.light_mask(light_mask),.light_brightness(light_brightness),
        .rx_start(rx_start),.rx_valid(rx_valid),.rx_done(rx_done),.rx_error(1'b0),
        .rx_data(rx_data),.rx_mac(48'h020000000003),.rx_ip(32'hc0a80003),.rx_port(16'd6000),
        .tx_ready(tx_ready),.tx_req(tx_req),.tx_done(tx_done),.tx_start(tx_start),
        .tx_length(tx_length),.tx_data(tx_data),
        .manual_busy(1'b0),.manual_done(1'b0),.manual_locked(1'b1),.manual_error(3'b0),
        .manual_raw(112'b0),.manual_generation(16'b0),
        .camera_config_ok(1'b1),.camera_busy(1'b0),.camera_ready(1'b0),
        .camera_failed(1'b0),.camera_fail_code(3'b0),.camera_pixel(16'b0));
    task send_command;
        begin
            @(negedge clk);rx_start=1;
            @(negedge clk);rx_start=0;
            for(integer k=0;k<20;k=k+1)begin
                rx_valid=1;rx_data=req[k];@(negedge clk);
            end
            rx_valid=0;rx_done=1;
            @(negedge clk);rx_done=0;
        end
    endtask
    initial forever begin
        @(posedge tx_start);
        @(negedge clk);tx_ready=0;
        repeat(3)@(negedge clk);
        for(integer i=0;i<tx_length;i=i+1)begin
            tx_req=1;@(posedge clk);packet[i]=tx_data;@(negedge clk);
        end
        tx_req=0;
        if(tx_length!=20 || packet[5]!=8'h81 || packet[10]!=1 ||
           packet[11]!=expected_result || packet[17]!=127)$fatal(1,"light ACK incorrect");
        packets=packets+1;tx_done=1;
        @(negedge clk);tx_done=0;
        repeat(3)@(negedge clk);tx_ready=1;
    end
    initial begin
        req[0]="L";req[1]="G";req[2]="H";req[3]="T";
        req[4]=1;req[5]=1;req[6]=0;req[7]=1;
        req[8]=0;req[9]=10;req[10]=0;req[11]=0;
        req[12]=0;req[13]=8;req[14]=0;req[15]=128;
        req[16]=0;req[17]=0;req[18]=0;req[19]=0;
        repeat(5)@(negedge clk);reset=0;
        send_command();
        if(!light_start || light_mask!=8 || light_brightness!=128)$fatal(1,"missing launch");
        light_busy=1;
        repeat(50)begin @(negedge clk);if(tx_start || packets!=0)$fatal(1,"ACK before controller completed");end
        light_busy=0;light_done=1;
        @(negedge clk);light_done=0;
        wait(packets==1);repeat(10)@(negedge clk);
        expected_result=4;req[7]=2;send_command();
        if(!light_start)$fatal(1,"second launch missing");
        light_busy=1;repeat(10)@(negedge clk);
        light_busy=0;light_error=1;light_done=1;
        @(negedge clk);light_done=0;
        wait(packets==2);repeat(10)@(negedge clk);
        expected_result=2;req[7]=3;req[13]=16;send_command();
        if(light_start)$fatal(1,"invalid mask launched");
        wait(packets==3);repeat(10)@(negedge clk);
        $display("PASS: light ACK deferred, controller failure propagated, invalid mask rejected");$finish;
    end
    initial begin #100000;$fatal(1,"watchdog");end
endmodule
