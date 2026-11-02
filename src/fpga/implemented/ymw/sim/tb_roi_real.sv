`timescale 1ns/1ps
// Replay original OV5640 bytes through a sequential DDR FIFO model with gaps.
module tb_roi_real;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,capture=0,release_frame=0,published_toggle=0,published_bank=0;
    reg [15:0] cx=0,cy=0,cw=1920,ch=1080,cp=3006,pid=0,read_addr=0;
    reg [10:0] last_pixels=150;
    wire ack,bank,clr,rden,busy,ready,failed;
    wire [2:0] fail_code;
    reg empty=0,read_en=0;reg [15:0] dout=0;wire [15:0] read_data;
    reg [15:0] original[0:2073599];reg [15:0] expected[0:2073599];
    integer index=0,cycle=0,reads=0,cases=0,total_compared=0;
    integer file_handle,status,x,y,w,h,p,n,offset,k,watch;
    reg [1023:0] input_file,golden_file;
    ddr_roi_packet_source #(.WIDTH(1920),.HEIGHT(1080),.FILL_TIMEOUT(10000000)) dut(
        .clk(clk),.reset(reset),.capture(capture),.release_frame(release_frame),.crop_enable(1'b1),
        .crop_x(cx),.crop_y(cy),.crop_width(cw),.crop_height(ch),.crop_packets(cp),.crop_last_pixels(last_pixels),
        .requested_packet_id(pid),.published_toggle(published_toggle),.published_bank(published_bank),
        .display_ack_toggle(ack),.rd_frame_bank(bank),.rdfifo_clr(clr),.rdfifo_rden(rden),
        .rdfifo_empty(empty),.rdfifo_dout(dout),.busy(busy),.ready(ready),.failed(failed),.fail_code(fail_code),
        .read_en(read_en),.read_addr(read_addr),.read_data(read_data));
    always @(posedge clk)begin
        cycle<=cycle+1;empty<=cycle%29==0;
        if(reset || clr)begin index<=0;reads<=0;dout<=0;end
        else if(rden)begin dout<=original[index];index<=index+1;reads<=reads+1;end
    end
    task tick;begin @(posedge clk);#1;end endtask
    initial begin
        repeat(5)tick();reset=0;repeat(4)tick();
        file_handle=$fopen("real_cases.txt","r");if(!file_handle)$fatal(1,"missing fixture case file");
        while(!$feof(file_handle))begin
            status=$fscanf(file_handle,"%s %s %d %d %d %d\n",input_file,golden_file,x,y,w,h);
            if(status==6)begin
                $readmemh(input_file,original,0,2073599);$readmemh(golden_file,expected,0,w*h-1);
                @(negedge clk);cx=x;cy=y;cw=w;ch=h;cp=(w*h+689)/690;last_pixels=w*h-(cp-1)*690;pid=0;
                published_toggle=~published_toggle;published_bank=~published_bank;capture=1;
                tick();@(negedge clk);capture=0;offset=0;
                for(p=0;p<cp;p=p+1)begin
                    watch=0;
                    while(!ready && !failed && watch<3000000)begin tick();watch=watch+1;end
                    if(failed || !ready)$fatal(1,"real ROI fill failed %d",fail_code);
                    if(ack==published_toggle)$fatal(1,"bank released early");
                    if(p==cp-1 && reads!=2073600)$fatal(1,"unconsumed full-frame tail");
                    n=(p==cp-1)?last_pixels:690;
                    for(k=0;k<n;k=k+1)begin
                        @(negedge clk);read_en=1;read_addr=k;tick();
                        if(read_data!==expected[offset+k])$fatal(1,"real pixel mismatch case=%d pixel=%d got=%h expected=%h",cases,offset+k,read_data,expected[offset+k]);
                    end
                    @(negedge clk);read_en=0;offset=offset+n;
                    if(p<cp-1)begin pid=p+1;tick();if(ready)$fatal(1,"old ready flag");end
                end
                if(offset!=w*h)$fatal(1,"real ROI pixel count");
                @(negedge clk);release_frame=1;tick();@(negedge clk);release_frame=0;tick();
                if(busy || ack!=published_toggle)$fatal(1,"release failed");
                cases=cases+1;total_compared=total_compared+offset;
                $display("REAL_FRAME_PASS %0d pixels=%0d",cases,offset);
            end else if(status!=-1)$fatal(1,"bad fixture case row");
        end
        $fclose(file_handle);if(cases!=4)$fatal(1,"fixture count");
        $display("ROI_REAL_PIXELS_PASS %0d frames %0d pixels",cases,total_compared);$finish;
    end
    initial begin #500000000;$fatal(1,"test deadline");end
endmodule
