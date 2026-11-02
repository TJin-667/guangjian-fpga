`timescale 1ns/1ps
module tb_manual_camera;
    reg net_clk=0,camera_clk=0,reset_n=0;
    always #4 net_clk=~net_clk;
    always #10 camera_clk=~camera_clk;
    tri1 sda,scl;
    wire sda_low,scl_low;
    assign sda=sda_low?1'b0:1'bz;
    assign scl=scl_low?1'b0:1'bz;
    reg start=0,set_values=0,nack_all=0,hold_clock=0,corrupt_gain=0;
    reg [15:0] exposure_lines=0;
    reg [9:0] gain16=0;
    wire busy,done,locked,config_ok,config_done,ack_error;
    wire [2:0] error,bus_error;
    wire [15:0] generation,bus_address;
    wire [111:0] raw;
    wire bus_start,bus_read,bus_done;
    wire [7:0] bus_data,bus_read_data;
    integer cases=0,start_writes,start_reads;
    ov5640_sensor_model sensor(.sda(sda),.scl(scl),.reset_n(reset_n),
        .nack_all(nack_all),.hold_clock(hold_clock),.corrupt_gain(corrupt_gain));
    ov5640_sccb_config #(.POWER_WAIT_CYCLES(4),.WRITE_GAP_CYCLES(4),
        .TICK_CYCLES(2),.TIMEOUT_CYCLES(2000)) config_dut(
        .clk_50m(camera_clk),.reset_n(reset_n),.cam_sda_i(sda),.cam_scl_i(scl),
        .cam_sda_low(sda_low),.cam_scl_low(scl_low),
        .config_ok(config_ok),.config_done(config_done),.ack_error(ack_error),
        .control_start(bus_start),.control_read(bus_read),.control_address(bus_address),
        .control_data(bus_data),.control_done(bus_done),.control_error(bus_error),.control_read_data(bus_read_data));
    ov5640_manual_bridge bridge(.net_clk(net_clk),.camera_clk(camera_clk),.reset_n(reset_n),
        .start(start),.set_values(set_values),.exposure_lines(exposure_lines),.gain16(gain16),
        .busy(busy),.done(done),.locked(locked),.error(error),.generation(generation),.raw(raw),
        .config_ok(config_ok),.bus_start(bus_start),.bus_read(bus_read),.bus_address(bus_address),
        .bus_data(bus_data),.bus_done(bus_done),.bus_error(bus_error),.bus_read_data(bus_read_data));
    task automatic request(input bit setting,input integer exposure,input integer gain);
        @(negedge net_clk);set_values=setting;exposure_lines=exposure;gain16=gain;start=1;
        @(negedge net_clk);start=0;exposure_lines=999;gain16=999;set_values=~setting;
        // Mutation immediately after acceptance tests the bundled-data CDC hold.
        wait(done);@(negedge net_clk);cases=cases+1;
    endtask
    task automatic expect_lock(input integer exposure,input integer gain,input integer gen);
        if(!locked || error!=0 || generation!=gen || raw[111:104]!=3 ||
           {raw[99:96],raw[95:88],raw[87:80]}!=(exposure<<4) ||
           {raw[73:72],raw[71:64]}!=gain || raw[63:48]!=2500 || raw[47:32]!=1120 || raw[15:0]!=16'h5640)
            $fatal(1,"manual lock / register byte order / CDC mismatch");
    endtask
    initial begin
        repeat(5)@(negedge net_clk);reset_n=1;
        wait(config_done);@(negedge net_clk);
        if(!config_ok || ack_error || sensor.registers[16'h3503]!=3 || sensor.writes!=257 || locked ||
           sensor.registers[16'h3501]!=6 || sensor.registers[16'h3502]!=8'h40 || sensor.registers[16'h350b]!=16)
            $fatal(1,"boot table failed, automatic mode retained, or boot incorrectly marked locked");
        cases=cases+1;
        request(0,0,0);if(locked || error!=0 || generation!=0)$fatal(1,"GET invented a user lock");
        request(1,17,16);expect_lock(17,16,1);
        start_writes=sensor.writes;start_reads=sensor.reads;
        request(0,0,0);expect_lock(17,16,1);
        if(sensor.writes!=start_writes || sensor.reads-start_reads!=14)$fatal(1,"GET must read all 14 registers and write none");
        request(1,1116,1023);expect_lock(1116,1023,2);
        request(1,1,16);expect_lock(1,16,3);
        start_writes=sensor.writes;
        request(1,0,16);if(locked || error!=3 || sensor.writes!=start_writes)$fatal(1,"Invalid exposure reached the sensor");
        request(1,1117,16);if(locked || error!=3 || sensor.writes!=start_writes)$fatal(1,"Exposure beyond VTS-4 accepted");
        request(1,1,15);if(locked || error!=3 || sensor.writes!=start_writes)$fatal(1,"Gain below unity accepted");
        request(1,256,32);expect_lock(256,32,4);
        sensor.registers[16'h3503]=0;
        request(0,0,0);if(locked || error!=2)$fatal(1,"AEC/AGC readback drift not detected");
        sensor.registers[16'h3503]=3;
        request(0,0,0);if(locked)$fatal(1,"Lost lock must require a new explicit SET");
        corrupt_gain=1;request(1,256,32);
        if(locked || error!=2)$fatal(1,"Write ACK incorrectly substituted for register readback");
        corrupt_gain=0;nack_all=1;request(1,512,48);
        if(locked || error!=1)$fatal(1,"SCCB NACK not propagated");
        nack_all=0;hold_clock=1;request(1,512,48);
        if(locked || error!=1)$fatal(1,"Stuck clock did not time out");
        hold_clock=0;request(1,512,48);expect_lock(512,48,5);
        @(negedge net_clk);start=1;set_values=1;exposure_lines=128;gain16=16;
        @(negedge net_clk);start=0;wait(bus_start);
        @(negedge net_clk);reset_n=0;repeat(5)@(negedge net_clk);reset_n=1;
        wait(config_done);repeat(8)@(negedge net_clk);
        if(locked || busy || done || generation!=0)$fatal(1,"Reset retained a lock or completed an old request");
        cases=cases+1;
        request(1,128,16);expect_lock(128,16,1);
        $display("MANUAL_CAMERA_ALL_PASS %0d",cases);$finish;
    end
    initial begin #100000000;$fatal(1,"manual camera simulation watchdog");end
endmodule
