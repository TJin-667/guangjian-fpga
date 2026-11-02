`timescale 1ns/1ps
module tb_h2_scratch;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,cfg_valid=0;reg [15:0] width=9,height=9;reg [31:0] request=1;integer mode=0;
    wire read_valid,read_ready,response_ready;
    wire [31:0] read_request;wire [21:0] read_address;
    reg response_valid=0;reg [31:0] response_request=0;reg [21:0] response_address=0;reg [15:0] response_pixel=0;
    wire h2_valid,h2_ready;wire [31:0] h2_request;wire [15:0] h2_x,h2_y;
    wire [7:0] h2_gray;wire signed [15:0] h2_r;wire h2_sof,h2_eol,h2_eof,h2_finish,h2_finish_ready;wire [2:0] h2_error;
    wire writer_valid;reg result_ready=0;wire [3:0] writer_error;wire [31:0] writer_request,written;wire fence;
    wire abort_h2=writer_valid&&writer_error!=0;
    h2_background9 h2(.clk(clk),.reset(reset),.abort_frame(abort_h2),.cfg_valid(cfg_valid),.cfg_ready(),.cfg_source_complete(1'b1),
        .cfg_width(width),.cfg_height(height),.cfg_x(16'd0),.cfg_y(16'd0),.cfg_roi_width(width),.cfg_roi_height(height),.cfg_threshold(8'd20),.cfg_request_id(request),
        .read_valid(read_valid),.read_ready(read_ready),.read_request_id(read_request),.read_address(read_address),
        .response_valid(response_valid),.response_ready(response_ready),.response_request_id(response_request),.response_address(response_address),.response_rgb565(response_pixel),
        .out_valid(h2_valid),.out_ready(h2_ready),.out_request_id(h2_request),.out_x(h2_x),.out_y(h2_y),.out_gray(h2_gray),
        .out_background_sum(),.out_residual_n(h2_r),.out_bright_n(),.out_dark_n(),.out_candidate(),.out_sof(h2_sof),.out_eol(h2_eol),.out_eof(h2_eof),
        .result_valid(h2_finish),.result_ready(h2_finish_ready),.result_error(h2_error),.output_count());
    wire [3:0] awid;wire [29:0] awaddr;wire [7:0] awlen;wire [2:0] awsize;wire [1:0] awburst;wire awvalid,awready;
    wire [127:0] wdata;wire [15:0] wstrb;wire wvalid,wready,wlast,bready;
    reg [1:0] bresp=0;reg bvalid=0;wire cfg_ready;
    reg valid_map[0:746495];
    wire [31:0] h2_index={16'd0,h2_y}*{16'd0,width}+{16'd0,h2_x};
    h2_scratch_writer writer(.clk(clk),.reset(reset),.abort_frame(1'b0),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
        .cfg_width(width),.cfg_height(height),.cfg_request(request),.cfg_base(30'h01800000),
        .in_valid(h2_valid),.in_ready(h2_ready),.in_request(h2_request+(mode==2)),.in_x(h2_x),.in_y(h2_y),.in_residual_n(h2_r),.in_gray(h2_gray),
        .in_observation_valid(valid_map[h2_index]),.in_sof(h2_sof^(mode==3)),.in_eol(h2_eol),.in_eof(h2_eof),
        .finish_valid(h2_finish),.finish_ready(h2_finish_ready),.finish_request(h2_request+(mode==4)),.finish_error(mode==5 ? 3'd2 : h2_error),
        .result_valid(writer_valid),.result_ready(result_ready),.result_error(writer_error),.result_request(writer_request),.written_pixels(written),.fence_required(fence),
        .m_axi_awid(awid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
        .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
        .m_axi_bid(4'h9),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready));
    reg [15:0] image[0:746495];reg [31:0] expected[0:746495];
    integer cycle=0;reg pending=0;integer response_delay=0;reg [21:0] pending_address;reg [31:0] pending_request;
    assign read_ready=!pending && cycle%11!=0;
    reg write_active=0;integer block_start=0,write_index=0,write_beats=0,bdelay=0;
    integer bytes_written=0,pixels_written=0,h2_outputs=0;
    assign awready=!write_active && !bvalid && bdelay==0 && cycle%13!=0;
    assign wready=write_active && cycle%5!=0;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(reset)begin pending<=0;response_valid<=0;write_active<=0;bvalid<=0;bdelay<=0;bytes_written<=0;pixels_written<=0;h2_outputs<=0;end
        else begin
            if(response_valid&&response_ready)begin response_valid<=0;pending<=0;end
            if(read_valid&&read_ready)begin
                if(read_address>=width*height || read_request!=request)$fatal(1,"H2 source address/tag");
                pending<=1;pending_address<=read_address;pending_request<=read_request;response_delay<=cycle%3+1;
            end
            if(pending&&!response_valid)begin
                if(response_delay>0)response_delay<=response_delay-1;
                else begin response_valid<=1;response_address<=pending_address;response_request<=pending_request;response_pixel<=image[pending_address];end
            end
            if(h2_valid&&h2_ready)h2_outputs<=h2_outputs+1;
            if(awvalid&&awready)begin
                if(awid!=9 || awsize!=4 || awburst!=1 || awaddr[3:0]!=0 || awlen>15 || awaddr[11:0]+(awlen+1)*16>4096)$fatal(1,"scratch AR format");
                if(awaddr!=30'h01800000+pixels_written*4)$fatal(1,"scratch address not sequential");
                write_active<=1;block_start<=(awaddr-30'h01800000)/4;write_beats<=awlen+1;write_index<=0;
            end
            if(wvalid&&wready)begin: check_beat
                integer word_index,lane,add_bytes,add_pixels;
                add_bytes=0;add_pixels=0;
                if(wlast!=(write_index==write_beats-1))$fatal(1,"scratch WLAST");
                for(lane=0;lane<4;lane=lane+1)begin
                    word_index=block_start+write_index*4+lane;
                    if(word_index<width*height)begin
                        if(wstrb[lane*4+:4]!=4'hf || wdata[lane*32+:32]!==expected[word_index])
                            $fatal(1,"H2 scratch word differs pixel%0d actual%h expected%h",word_index,wdata[lane*32+:32],expected[word_index]);
                        add_bytes=add_bytes+4;add_pixels=add_pixels+1;
                    end else if(wstrb[lane*4+:4]!=0)$fatal(1,"scratch padding written");
                end
                bytes_written<=bytes_written+add_bytes;pixels_written<=pixels_written+add_pixels;
                if(wlast)begin write_active<=0;bdelay<=31;end else write_index<=write_index+1;
            end
            if(bdelay>0)begin bdelay<=bdelay-1;if(bdelay==1)bvalid<=1;end
            if(bvalid&&bready)bvalid<=0;
            if(writer_valid&&writer_error==0 && (pixels_written!=width*height || h2_outputs!=width*height || bdelay!=0 || bvalid || written!=width*height))
                $fatal(1,"scratch committed before full H2 and durable B");
        end
    end
    reg hold_aw=0,hold_w=0;reg [37:0] last_aw;reg [144:0] last_w;
    always @(posedge clk)begin
        if(!reset)begin
            if(hold_aw&&(!awvalid||{awaddr,awlen}!==last_aw))$fatal(1,"scratch AW instability");
            if(hold_w&&(!wvalid||{wdata,wstrb,wlast}!==last_w))$fatal(1,"scratch W instability");
            hold_aw<=awvalid&&!awready;last_aw<={awaddr,awlen};hold_w<=wvalid&&!wready;last_w<={wdata,wstrb,wlast};
        end else begin hold_aw<=0;hold_w<=0;end
    end
    task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
    integer receipt,passed=0;
    task run_case(input integer ci,input integer w,input integer h,input integer want_error);
        begin
            reset=1;repeat(4)tick();reset=0;tick();width=w;height=h;request=ci+1;bresp=want_error==5 ? 2 : 0;
            $readmemh($sformatf("h%0d_rgb565.hex",ci),image,0,w*h-1);
            $readmemh($sformatf("h%0d_expected.hex",ci),expected,0,w*h-1);
            $readmemh($sformatf("h%0d_valid.hex",ci),valid_map,0,w*h-1);
            cfg_valid=1;tick();cfg_valid=0;wait(writer_valid);@(negedge clk);
            if(writer_error!=want_error || writer_request!=ci+1 || fence)$fatal(1,"scratch result err%0d want%0d",writer_error,want_error);
            if(want_error==0&&bytes_written!=w*h*4)$fatal(1,"scratch byte count");
            repeat(3)tick();if(!writer_valid)$fatal(1,"scratch result hold");
            result_ready=1;tick();result_ready=0;passed=passed+1;
            $fwrite(receipt,"%0d,%0d,%0d,%0d,PASS\n",ci,w,h,want_error);$display("H2_SCRATCH_PASS %0d pixels%0d error%0d",ci,w*h,want_error);
        end
    endtask
    initial begin
        receipt=$fopen("h2_scratch_receipt.csv","w");$fwrite(receipt,"case,width,height,error,status\n");
        `include "h2_cases.svh"
        $fclose(receipt);$display("H2_SCRATCH_ALL_PASS %0d",passed);$finish;
    end
    initial begin #10000000000;$fatal(1,"H2 scratch TB watchdog");end
endmodule
