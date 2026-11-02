`timescale 1ns/1ps
module tb_core_roi;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,rx_start=0,rx_valid=0,rx_done=0,rx_error=0;
    reg [7:0] rx_data=0;
    reg tx_ready=1,tx_req=0,tx_done=0,manual_locked=1;
    wire tx_start;wire [15:0] tx_length;wire [7:0] tx_data;
    wire camera_capture,camera_release,read_en,crop_enable,busy,ready,failed,frame_busy,clr,rden,ack;
    wire [2:0] fail_code;
    wire [15:0] pid,read_addr,pixel,cx,cy,cw,ch,cp;
    wire [10:0] last_pixels;
    reg publish=0,pub_bank=0;
    reg [15:0] dout=0;
    integer input_index=0,packets=0,cases=0;
    reg [7:0] received[0:63][0:1400];integer lengths[0:63];
    lght_core_camera #(.WIDTH(8),.HEIGHT(8),.CAM_WIDTH(64),.CAM_HEIGHT(48),.PACKET_GAP_CYCLES(2)) core(
        .clk(clk),.reset(reset),.rx_start(rx_start),.rx_valid(rx_valid),.rx_done(rx_done),.rx_error(rx_error),
        .rx_data(rx_data),.rx_mac(48'h020000000003),.rx_ip(32'hc0a80003),.rx_port(16'd6000),
        .tx_ready(tx_ready),.tx_req(tx_req),.tx_done(tx_done),.tx_start(tx_start),.tx_length(tx_length),.tx_data(tx_data),
        .light_busy(1'b0),.light_done(1'b0),.light_error(1'b0),.camera_config_ok(1'b1),
        .camera_busy(busy),.camera_ready(ready),.camera_failed(failed),.camera_fail_code(fail_code),
        .camera_pixel(pixel),.camera_capture(camera_capture),.camera_release(camera_release),
        .camera_packet_id(pid),.camera_read_en(read_en),.camera_read_addr(read_addr),.frame_busy(frame_busy),
        .manual_busy(1'b0),.manual_done(1'b0),.manual_locked(manual_locked),.manual_error(3'b0),.manual_raw(112'b0),.manual_generation(16'b0),
        .camera_crop_enable(crop_enable),.camera_roi_x(cx),.camera_roi_y(cy),.camera_roi_width(cw),.camera_roi_height(ch),
        .camera_roi_packets(cp),.camera_roi_last_pixels(last_pixels));
    ddr_roi_packet_source #(.WIDTH(64),.HEIGHT(48),.FILL_TIMEOUT(20000)) source(
        .clk(clk),.reset(reset),.capture(camera_capture),.release_frame(camera_release),.crop_enable(crop_enable),
        .crop_x(cx),.crop_y(cy),.crop_width(cw),.crop_height(ch),.crop_packets(cp),.crop_last_pixels(last_pixels),
        .requested_packet_id(pid),.published_toggle(publish),.published_bank(pub_bank),.display_ack_toggle(ack),
        .rdfifo_clr(clr),.rdfifo_rden(rden),.rdfifo_empty(1'b0),.rdfifo_dout(dout),.busy(busy),.ready(ready),
        .failed(failed),.fail_code(fail_code),.read_en(read_en),.read_addr(read_addr),.read_data(pixel));
    always @(posedge clk)begin
        if(reset)begin publish<=0;pub_bank<=0;input_index<=0;dout<=0;end
        else begin
            if(camera_capture)begin publish<=~publish;pub_bank<=~pub_bank;end
            if(clr)input_index<=0;
            else if(rden)begin dout<=input_index^16'h35a7;input_index<=input_index+1;end
        end
    end
    initial forever begin
        @(posedge tx_start);@(negedge clk);tx_ready=0;repeat(3)@(negedge clk);lengths[packets]=tx_length;
        for(integer i=0;i<tx_length;i=i+1)begin tx_req=1;@(posedge clk);received[packets][i]=tx_data;@(negedge clk);end
        tx_req=0;packets=packets+1;tx_done=1;@(negedge clk);tx_done=0;repeat(2)@(negedge clk);tx_ready=1;
    end
    task send(input integer kind,seq,a0,a1,a2,a3);
        reg [159:0] bytes;
        begin
            bytes={32'h4c474854,8'd1,8'(kind),16'(seq),16'd10,16'd0,16'(a0),16'(a1),16'(a2),16'(a3)};
            @(negedge clk);rx_start=1;@(negedge clk);rx_start=0;
            for(integer i=0;i<20;i=i+1)begin rx_valid=1;rx_data=bytes[159-i*8 -: 8];@(negedge clk);end
            rx_valid=0;rx_done=1;@(negedge clk);rx_done=0;
        end
    endtask
    task check_ack(input integer begin_packet,kind,seq,result);
        integer p,found,watch;
        begin
            found=-1;watch=0;
            while(found<0 && watch<20000)begin
                for(p=begin_packet;p<packets;p=p+1)
                    if(received[p][5]==8'h81 && received[p][7]==seq && received[p][10]==kind)found=p;
                @(negedge clk);watch=watch+1;
            end
            if(found<0 || received[found][11]!=result || received[found][17]!=127)$fatal(1,"ACK mismatch kind %d seq %d result %d",kind,seq,result);
            cases=cases+1;
        end
    endtask
    task wait_idle;begin wait(!frame_busy && !core.pending && core.state==0);repeat(5)@(negedge clk);end endtask
    task check_frames(input integer begin_packet,x,y,w,h);
        integer p,k,seen,expected,offset,payload,count;
        begin
            wait_idle();seen=0;offset=0;count=(w*h+689)/690;
            for(p=begin_packet;p<packets;p=p+1)if(received[p][5]==8'h90)begin
                if({received[p][8],received[p][9]}!=seen || {received[p][10],received[p][11]}!=count ||
                   {received[p][14],received[p][15]}!=w || {received[p][16],received[p][17]}!=h)$fatal(1,"frame header incorrect");
                payload=(seen==count-1)?2*(w*h-(count-1)*690):1380;
                if(lengths[p]!=20+payload || {received[p][12],received[p][13]}!=payload)$fatal(1,"tail packet length incorrect");
                for(k=0;k<payload/2;k=k+1)begin
                    expected=(((y+(offset+k)/w)*64+x+(offset+k)%w)^16'h35a7)&65535;
                    if({received[p][20+2*k],received[p][21+2*k]}!==expected[15:0])$fatal(1,"UDP pixel mismatch offset=%d",offset+k);
                end
                offset=offset+payload/2;seen=seen+1;
            end
            if(seen!=count || offset!=w*h || input_index!=64*48)$fatal(1,"frame output/drain incomplete");
            cases=cases+1;
        end
    endtask
    integer mark;
    initial begin
        repeat(5)@(negedge clk);reset=0;
        send(2,1,3,0,0,0);check_ack(0,2,1,2);wait_idle();
        mark=packets;send(6,2,11,7,23,31);check_ack(mark,6,2,0);wait_idle();
        if(core.roi_generation!=1 || core.roi_pixels!=713 || core.roi_packets!=2 || core.roi_last_pixels!=23)$fatal(1,"ROI set calculation wrong");
        if(received[packets-1][5]!=8'h84 || received[packets-1][13]!=11 || received[packets-1][15]!=7 || received[packets-1][25]!=1)$fatal(1,"ROI snapshot incorrect");
        mark=packets;send(7,3,0,0,0,0);check_ack(mark,7,3,0);wait_idle();
        mark=packets;send(6,2,11,7,23,31);check_ack(mark,6,2,0);wait_idle();if(core.roi_generation!=1)$fatal(1,"ROI retry not idempotent");
        mark=packets;send(6,2,11,7,22,31);check_ack(mark,6,2,2);wait_idle();
        mark=packets;send(6,4,63,0,2,1);check_ack(mark,6,4,2);wait_idle();
        mark=packets;send(2,5,3,23,31,0);check_ack(mark,2,5,2);wait_idle();
        mark=packets;send(2,6,3,23,31,1);check_ack(mark,2,6,0);
        send(6,7,0,0,10,10);check_ack(mark,6,7,1);check_frames(mark,11,7,23,31);
        if(core.roi_generation!=1)$fatal(1,"busy SET changed ROI");
        mark=packets;send(2,8,2,64,48,0);check_ack(mark,2,8,0);check_frames(mark,0,0,64,48);
        mark=packets;send(6,9,63,47,1,1);check_ack(mark,6,9,0);wait_idle();
        mark=packets;send(2,10,3,1,1,2);check_ack(mark,2,10,0);check_frames(mark,63,47,1,1);
        manual_locked=0;mark=packets;send(2,11,3,1,1,2);check_ack(mark,2,11,4);wait_idle();
        $display("CORE_ROI_PASS %0d",cases);$finish;
    end
    initial begin #3000000;$fatal(1,"core ROI deadline");end
endmodule
