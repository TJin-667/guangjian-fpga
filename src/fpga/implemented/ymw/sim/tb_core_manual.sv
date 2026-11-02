`timescale 1ns/1ps
module tb_core_manual;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,rx_start=0,rx_valid=0,rx_done=0,rx_error=0;
    reg [7:0] rx_data=0;
    reg tx_ready=1,tx_req=0,tx_done=0;
    wire tx_start;wire [15:0] tx_length;wire [7:0] tx_data;
    reg manual_busy=0,manual_done=0,manual_locked=0,light_busy=0;
    reg [2:0] manual_error=0;
    reg [111:0] manual_raw=0;
    reg [15:0] manual_generation=0;
    wire manual_start,manual_set,camera_capture;
    wire [15:0] manual_exposure;wire [9:0] manual_gain16;
    integer starts=0,captures=0,packets=0,cases=0;
    reg [7:0] received[0:31][0:1400];
    integer lengths[0:31];
    lght_core_camera #(.WIDTH(2),.HEIGHT(2),.CAM_WIDTH(2),.CAM_HEIGHT(2),
        .PACKET_GAP_CYCLES(0),.CONTROL_TIMEOUT_CYCLES(200)) dut(
        .clk(clk),.reset(reset),.rx_start(rx_start),.rx_valid(rx_valid),.rx_done(rx_done),
        .rx_error(rx_error),.rx_data(rx_data),.rx_mac(48'h020000000003),.rx_ip(32'hc0a80003),.rx_port(16'd6000),
        .tx_ready(tx_ready),.tx_req(tx_req),.tx_done(tx_done),.tx_start(tx_start),.tx_length(tx_length),.tx_data(tx_data),
        .light_busy(light_busy),.light_done(1'b0),.light_error(1'b0),
        .camera_config_ok(1'b1),.camera_busy(1'b0),.camera_ready(1'b0),.camera_failed(1'b0),
        .camera_fail_code(3'b0),.camera_pixel(16'b0),.camera_capture(camera_capture),
        .manual_busy(manual_busy),.manual_done(manual_done),.manual_locked(manual_locked),
        .manual_error(manual_error),.manual_raw(manual_raw),.manual_generation(manual_generation),
        .manual_start(manual_start),.manual_set(manual_set),.manual_exposure(manual_exposure),.manual_gain16(manual_gain16));
    always @(posedge clk)if(!reset)begin
        if(manual_start)starts=starts+1;
        if(camera_capture)captures=captures+1;
    end
    initial forever begin
        @(posedge tx_start);@(negedge clk);tx_ready=0;repeat(3)@(negedge clk);
        lengths[packets]=tx_length;
        for(integer i=0;i<tx_length;i=i+1)begin
            tx_req=1;@(posedge clk);received[packets][i]=tx_data;@(negedge clk);
        end
        tx_req=0;packets=packets+1;tx_done=1;@(negedge clk);tx_done=0;
        repeat(2)@(negedge clk);tx_ready=1;
    end
    task automatic send(input integer kind,input integer seq,input integer a0,input integer a1,input integer a2,input integer a3);
        reg [159:0] bytes;
        bytes={32'h4c474854,8'd1,8'(kind),16'(seq),16'd10,16'd0,16'(a0),16'(a1),16'(a2),16'(a3)};
        @(negedge clk);rx_start=1;@(negedge clk);rx_start=0;
        for(integer i=0;i<20;i=i+1)begin rx_valid=1;rx_data=bytes[159-i*8 -: 8];@(negedge clk);end
        rx_valid=0;rx_done=1;@(negedge clk);rx_done=0;
    endtask
    task automatic ack(input integer packet,input integer kind,input integer seq,input integer result);
        wait(packets>packet);repeat(4)@(negedge clk);
        if(lengths[packet]!=20 || received[packet][5]!=8'h81 || received[packet][7]!=seq ||
            received[packet][10]!=kind || received[packet][11]!=result || received[packet][17]!=127)
            $fatal(1,"ACK mismatch packet %0d",packet);
        cases=cases+1;
    endtask
    task automatic complete(input bit good,input integer detail,input integer gen);
        @(negedge clk);manual_busy=0;manual_done=1;manual_locked=good;
        manual_error=detail;manual_generation=gen;
        manual_raw=112'h030045c003ff09c4046000005640;
        @(negedge clk);manual_done=0;
        // Live adapter inputs change; the entire transmitted snapshot must stay frozen.
        manual_raw=0;manual_generation=99;manual_error=0;
    endtask
    initial begin
        repeat(5)@(negedge clk);reset=0;
        send(2,1,2,2,2,0);ack(0,2,1,4);if(captures!=0)$fatal(1,"Unlocked CAPTURE was issued");
        send(4,2,0,16,0,0);ack(1,4,2,2);if(starts!=0)$fatal(1,"Invalid SET was issued");
        send(4,3,1116,1023,0,0);repeat(8)@(negedge clk);
        if(packets!=2 || starts!=1 || manual_exposure!=1116 || manual_gain16!=1023 || !manual_set)
            $fatal(1,"SET ACK sent before sensor completion or wrong parameters");
        complete(1,0,7);ack(2,4,3,0);wait(packets==4);repeat(4)@(negedge clk);
        if(lengths[3]!=32 || received[3][5]!=8'h83 || received[3][10]!=1 || received[3][11]!=1 ||
            received[3][14]!=3 || received[3][16]!=8'h45 || received[3][17]!=8'hc0 ||
            received[3][18]!=3 || received[3][19]!=8'hff || received[3][29]!=7)
            $fatal(1,"CAMERA_STATUS raw readback/byte order/snapshot changed");
        send(4,3,1116,1023,0,0);ack(4,4,3,0);wait(packets==6);repeat(4)@(negedge clk);
        if(starts!=1 || received[5][29]!=7)$fatal(1,"Same-identity retry rewrote sensor");
        send(4,3,1115,1023,0,0);ack(6,4,3,2);if(starts!=1)$fatal(1,"Conflicting retry rewrote sensor");
        light_busy=1;send(5,4,0,0,0,0);ack(7,5,4,1);light_busy=0;
        send(5,5,0,0,0,0);repeat(5)@(negedge clk);complete(1,0,7);
        ack(8,5,5,0);wait(packets==10);repeat(4)@(negedge clk);
        send(4,6,1116,1023,0,0);repeat(5)@(negedge clk);complete(0,1,7);
        ack(10,4,6,5);wait(packets==12);repeat(4)@(negedge clk);
        if(received[11][11]!=0 || received[11][12]!=1)$fatal(1,"Sensor failure lost its detail or kept a lock");
        send(2,7,2,2,2,0);ack(12,2,7,4);
        send(5,8,0,0,0,0);manual_busy=1;ack(13,5,8,5);wait(packets==15);repeat(4)@(negedge clk);
        if(received[14][11]!=0 || received[14][12]!=4)$fatal(1,"Backend watchdog did not fail closed");
        send(4,9,128,16,0,0);ack(15,4,9,1);manual_busy=0;
        send(4,10,1116,1023,0,0);repeat(5)@(negedge clk);complete(1,0,8);
        ack(16,4,10,0);wait(packets==18);repeat(4)@(negedge clk);
        send(2,11,2,2,2,0);ack(18,2,11,0);if(captures!=1)$fatal(1,"Locked CAPTURE was not issued");
        send(4,12,128,16,0,0);ack(19,4,12,1);
        if(starts!=5)$fatal(1,"Unexpected backend writes/reads during busy frame or replay: %0d",starts);
        $display("CORE_MANUAL_ALL_PASS %0d",cases);$finish;
    end
    initial begin #1000000;$fatal(1,"core manual watchdog");end
endmodule
