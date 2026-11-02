`timescale 1ns/1ps
module tb_core_camera;
    reg clk=0;
    always #4 clk=~clk;
    reg reset=1;
    reg rx_start=0,rx_valid=0,rx_done=0,rx_error=0;
    reg [7:0] rx_data=0;
    wire tx_start;
    reg tx_ready=1,tx_req=0,tx_done=0;
    wire [15:0] tx_length;
    wire [47:0] tx_mac;
    wire [31:0] tx_ip;
    wire [15:0] tx_port;
    wire [7:0] tx_data;
    wire frame_busy;
    wire [31:0] commands,frames_started,rx_dropped;
    reg camera_busy=0,camera_ready=0,camera_failed=0;
    reg [15:0] camera_pixel=0;
    wire camera_capture,camera_release,camera_read_en;
    wire [15:0] camera_packet_id;
    wire [15:0] camera_read_addr;
    integer countdown=0;
    integer packet_count=0;
    integer packet_index=0;
    reg [7:0] packet [0:1400];
    reg seen_capture=0,seen_release=0;

    lght_core_camera #(.WIDTH(8),.HEIGHT(4),.CAM_WIDTH(32),.CAM_HEIGHT(32),
                       .PACKET_GAP_CYCLES(12500)) dut(
        .clk(clk),.reset(reset),.light_busy(1'b0),.light_done(1'b0),.light_error(1'b0),.rx_start(rx_start),.rx_valid(rx_valid),
        .rx_done(rx_done),.rx_error(rx_error),.rx_data(rx_data),
        .rx_mac(48'h020000000003),.rx_ip(32'hc0a80003),.rx_port(16'd6000),
        .tx_ready(tx_ready),.tx_req(tx_req),.tx_done(tx_done),
        .tx_start(tx_start),.tx_length(tx_length),.tx_mac(tx_mac),
        .tx_ip(tx_ip),.tx_port(tx_port),.tx_data(tx_data),
        .frame_busy(frame_busy),.commands(commands),
        .frames_started(frames_started),.rx_dropped(rx_dropped),
        .camera_config_ok(1'b1),.camera_busy(camera_busy),
        .camera_ready(camera_ready),.camera_failed(camera_failed),
        .camera_fail_code(3'b000),
        .manual_busy(1'b0),.manual_done(1'b0),.manual_locked(1'b1),.manual_error(3'b0),
        .manual_raw(112'b0),.manual_generation(16'b0),
        .camera_pixel(camera_pixel),.camera_capture(camera_capture),
        .camera_release(camera_release),.camera_read_en(camera_read_en),
        .camera_read_addr(camera_read_addr),.camera_packet_id(camera_packet_id)
    );
    always @(posedge clk) begin
        if(reset) begin
            camera_busy<=0;camera_ready<=0;camera_pixel<=0;countdown<=0;
        end else begin
            if(camera_capture)begin
                camera_busy<=1;camera_ready<=0;countdown<=5;seen_capture<=1;
            end else if(countdown>0)begin
                countdown<=countdown-1;
                if(countdown==1)camera_ready<=1;
            end
            if(camera_read_en && camera_ready && camera_read_addr<690)
                camera_pixel<=16'h4000+camera_packet_id*690+camera_read_addr;
            if(camera_release)begin
                camera_busy<=0;camera_ready<=0;seen_release<=1;
            end
        end
    end

    // Byte-pull TX model. It captures exactly what the real UDP TX would
    // request, with a few header cycles before the payload starts.
    integer i;
    initial forever begin
        @(posedge tx_start);
        @(negedge clk);tx_ready=0;
        repeat(3)@(negedge clk);
        packet_index=0;
        for(i=0;i<tx_length;i=i+1)begin
            tx_req=1;
            @(posedge clk);
            packet[packet_index]=tx_data;
            packet_index=packet_index+1;
            @(negedge clk);
        end
        tx_req=0;
        if(packet_count==0 || packet_count==3)begin
            if(packet_index!=20 || packet[5]!=8'h81 || packet[11]!=0 ||
               packet[17]!=127 || packet[12]!=0 || packet[13]!=(packet_count==0?1:2))
                $fatal(1,"camera ACK mismatch");
        end else if(packet_count==1 || packet_count==2 || packet_count==4 || packet_count==5)begin
            if(packet_index!=(packet_count%3==1?1400:688) ||
               packet[5]!=8'h90 || packet[8]!=0 ||
               packet[9]!=packet_count%3-1 || packet[10]!=0 ||
               packet[11]!=2 || packet[12]!=(packet_count%3==1?5:2) ||
               packet[13]!=(packet_count%3==1?100:156) ||
               packet[14]!=0 || packet[15]!=32 || packet[16]!=0 ||
               packet[17]!=32 || packet[19]!=(packet_count%3==1?1:2) ||
               packet[7]!=(packet_count<3?1:2))
                $fatal(1,"camera frame header mismatch");
            for(integer k=0;k<(packet_index-20)/2;k=k+1)begin
                reg [15:0] expected;
                expected=16'h4000+(packet_count%3-1)*690+k;
                if(packet[20+2*k]!==expected[15:8] ||
                   packet[21+2*k]!==expected[7:0])
                    $fatal(1,"pixel byte mismatch at %0d: %h %h",k,
                           packet[20+2*k],packet[21+2*k]);
            end
        end else $fatal(1,"unexpected packet");
        packet_count=packet_count+1;
        tx_done=1;
        @(negedge clk);tx_done=0;
        repeat(2)@(negedge clk);
        tx_ready=1;
    end

    reg [7:0] request[0:19];
    initial begin
        request[0]="L";request[1]="G";request[2]="H";request[3]="T";
        request[4]=1;request[5]=2;request[6]=0;request[7]=1;
        request[8]=0;request[9]=10;request[10]=0;request[11]=0;
        request[12]=0;request[13]=2;request[14]=0;request[15]=32;
        request[16]=0;request[17]=32;request[18]=0;request[19]=0;
        repeat(5)@(negedge clk);reset=0;
        @(negedge clk);rx_start=1;
        @(negedge clk);rx_start=0;
        for(integer n=0;n<20;n=n+1)begin
            rx_valid=1;rx_data=request[n];@(negedge clk);
        end
        rx_valid=0;rx_done=1;
        @(negedge clk);rx_done=0;
        wait(packet_count==3 && seen_release);
        repeat(8)@(negedge clk);
        seen_release=0;
        request[7]=2;
        @(negedge clk);rx_start=1;
        @(negedge clk);rx_start=0;
        for(integer m=0;m<20;m=m+1)begin
            rx_valid=1;rx_data=request[m];@(negedge clk);
        end
        rx_valid=0;rx_done=1;
        @(negedge clk);rx_done=0;
        wait(packet_count==6 && seen_release);
        if(!seen_capture || commands!=2 || frames_started!=2)
            $fatal(1,"capture control not exercised");
        $display("CAMERA_UDP_PACED_CORE_PASS: two sequential captures, 100 us packet spacing");
        $finish;
    end
    initial begin #1000000;$fatal(1,"simulation watchdog");end
endmodule
