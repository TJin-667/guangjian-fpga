`timescale 1ns/1ps
module tb_ddr_roi_source;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,capture=0,release_frame=0,crop_enable=0,published_toggle=0,published_bank=0;
    reg [15:0] cx=0,cy=0,cw=64,ch=48,cp=5,pid=0,read_addr=0;
    reg [10:0] last_pixels=312;
    wire ack,bank,clr,rden,busy,ready,failed;
    wire [2:0] fail_code;
    reg empty=0,read_en=0;
    reg [15:0] dout=0;
    wire [15:0] read_data;
    integer index=0,cycle=0,reads=0,cases=0;
    ddr_roi_packet_source #(.WIDTH(64),.HEIGHT(48),.WAIT_TIMEOUT(200),.FILL_TIMEOUT(20000)) dut(
        .clk(clk),.reset(reset),.capture(capture),.release_frame(release_frame),.crop_enable(crop_enable),
        .crop_x(cx),.crop_y(cy),.crop_width(cw),.crop_height(ch),.crop_packets(cp),.crop_last_pixels(last_pixels),
        .requested_packet_id(pid),.published_toggle(published_toggle),.published_bank(published_bank),
        .display_ack_toggle(ack),.rd_frame_bank(bank),.rdfifo_clr(clr),.rdfifo_rden(rden),
        .rdfifo_empty(empty),.rdfifo_dout(dout),.busy(busy),.ready(ready),.failed(failed),.fail_code(fail_code),
        .read_en(read_en),.read_addr(read_addr),.read_data(read_data));
    always @(posedge clk)begin
        cycle<=cycle+1;empty<=cycle%11==0;
        if(reset || clr)begin index<=0;reads<=0;dout<=0;end
        else if(rden)begin dout<=index^16'h5aa5;index<=index+1;reads<=reads+1;end
    end
    task tick;begin @(posedge clk);#1;end endtask
    task finish;begin
        @(negedge clk);release_frame=1;tick();@(negedge clk);release_frame=0;tick();
        if(busy)$fatal(1,"not released");
    end endtask
    task good_case(input integer x,y,w,h,input integer enabled);
        integer p,n,offset,k,expected,watch;
        begin
            @(negedge clk);cx=x;cy=y;cw=w;ch=h;crop_enable=enabled;
            cp=(w*h+689)/690;last_pixels=w*h-(cp-1)*690;pid=0;
            published_toggle=~published_toggle;published_bank=~published_bank;capture=1;
            tick();@(negedge clk);capture=0;offset=0;
            for(p=0;p<cp;p=p+1)begin
                watch=0;
                while(!ready && !failed && watch<10000)begin tick();watch=watch+1;end
                if(failed || !ready)$fatal(1,"ROI fill failed: code %d",fail_code);
                if(ack==published_toggle)$fatal(1,"bank released before consumer release");
                if(p==cp-1 && reads!=64*48)$fatal(1,"tail not drained before final ready");
                n=(p==cp-1)?last_pixels:690;
                for(k=0;k<n;k=k+1)begin
                    @(negedge clk);read_en=1;read_addr=k;tick();
                    expected=(((y+(offset+k)/w)*64+x+(offset+k)%w)^16'h5aa5)&65535;
                    if(read_data!==expected[15:0])$fatal(1,"pixel mismatch p=%d k=%d got=%h expected=%h",p,k,read_data,expected);
                end
                @(negedge clk);read_en=0;offset=offset+n;
                if(p<cp-1)begin pid=p+1;tick();if(ready)$fatal(1,"old packet ready after new ID");end
            end
            if(offset!=w*h)$fatal(1,"wrong crop size");finish();
            if(ack!=published_toggle)$fatal(1,"wrong bank acknowledgement");cases=cases+1;
        end
    endtask
    initial begin
        repeat(5)tick();reset=0;repeat(4)tick();
        good_case(0,0,64,48,0);
        good_case(11,13,23,17,1);
        good_case(8,5,41,35,1);
        good_case(63,47,1,1,1);
        good_case(0,0,1,1,1);
        good_case(0,10,23,30,1);
        // Invalid geometry, no publish timeout, illegal packet advance, then recovery.
        @(negedge clk);crop_enable=1;cx=63;cw=2;ch=1;cp=1;last_pixels=2;capture=1;tick();
        @(negedge clk);capture=0;tick();if(!failed || fail_code!=4)$fatal(1,"bad ROI accepted");finish();cases=cases+1;
        @(negedge clk);crop_enable=0;capture=1;tick();@(negedge clk);capture=0;
        repeat(220)tick();if(!failed || fail_code!=1)$fatal(1,"missing publish did not timeout");finish();cases=cases+1;
        @(negedge clk);published_toggle=~published_toggle;pid=0;capture=1;tick();@(negedge clk);capture=0;
        while(!ready && !failed)tick();@(negedge clk);pid=2;repeat(3)tick();
        if(!failed || fail_code!=3)$fatal(1,"packet jump accepted");finish();cases=cases+1;
        good_case(7,8,53,37,1);
        $display("DDR_ROI_SOURCE_PASS %0d",cases);$finish;
    end
    initial begin #5000000;$fatal(1,"test deadline");end
endmodule
