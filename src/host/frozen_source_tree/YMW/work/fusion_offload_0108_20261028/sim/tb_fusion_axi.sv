`timescale 1ns/1ps
module tb_fusion_axi;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,abort_group=0;
    reg begin_valid=0;wire begin_ready;reg [63:0] begin_group=0;
    reg [127:0] begin_digest=128'h10800000000000000000000000000408;
    reg [15:0] width=0,height=0;reg release_valid=0;reg [63:0] release_group=0;
    reg frame_valid=0;wire frame_ready;reg [63:0] frame_group=0;
    reg [127:0] frame_digest=0;reg [3:0] frame_slot=0;reg [31:0] frame_request=0;reg frame_complete=1;
    wire cfg_valid,cfg_ready,first;wire [3:0] slot;
    wire [31:0] pixels,tag;wire [29:0] src_base,old_base,dst_base;wire worker_abort;
    wire result_valid,result_ready;wire [3:0] error;wire [31:0] result_tag,written;wire fence;
    wire receipt_valid;reg receipt_ready=0;wire [3:0] receipt_error;wire [31:0] receipt_request;
    wire active;wire [3:0] completed;wire published;wire [63:0] published_group;
    wire [127:0] published_digest;wire [15:0] published_width,published_height;wire [29:0] published_base;wire fault;
    fusion_group_guard guard(.clk(clk),.reset(reset),.begin_valid(begin_valid),.begin_ready(begin_ready),
        .begin_group(begin_group),.begin_digest(begin_digest),.begin_width(width),.begin_height(height),
        .release_valid(release_valid),.release_group(release_group),.abort_group(abort_group),
        .frame_valid(frame_valid),.frame_ready(frame_ready),.frame_group(frame_group),.frame_digest(frame_digest),
        .frame_slot(frame_slot),.frame_request(frame_request),.frame_source_complete(frame_complete),
        .worker_cfg_valid(cfg_valid),.worker_cfg_ready(cfg_ready),.worker_first(first),.worker_slot(slot),
        .worker_pixels(pixels),.worker_tag(tag),.worker_scratch_base(src_base),.worker_previous_base(old_base),.worker_target_base(dst_base),
        .worker_abort(worker_abort),.worker_result_valid(result_valid),.worker_result_ready(result_ready),
        .worker_result_error(error),.worker_result_tag(result_tag),.worker_written_pixels(written),.worker_fence_required(fence),
        .receipt_valid(receipt_valid),.receipt_ready(receipt_ready),.receipt_error(receipt_error),.receipt_request(receipt_request),
        .active(active),.completed_slots(completed),.published(published),.published_group(published_group),
        .published_digest(published_digest),.published_width(published_width),.published_height(published_height),.published_base(published_base),.fault(fault));
    wire [3:0] arid,awid;wire [29:0] araddr,awaddr;wire [7:0] arlen,awlen;wire [2:0] arsize,awsize;wire [1:0] arburst,awburst;
    wire arvalid,arready,awvalid,awready,rready,wvalid,wready,wlast,bready;
    reg [3:0] rid=8,bid=8;reg [127:0] rdata=0;reg [1:0] rresp=0,bresp=0;reg rlast=0,rvalid=0,bvalid=0;
    wire [127:0] wdata;wire [15:0] wstrb;
    fusion_axi_frame #(.WATCHDOG_CYCLES(64)) dma(.clk(clk),.reset(reset),.abort_frame(worker_abort),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_first(first),.cfg_slot(slot),.cfg_pixels(pixels),.cfg_tag(tag),
        .cfg_scratch_base(src_base),.cfg_previous_base(old_base),.cfg_target_base(dst_base),
        .result_valid(result_valid),.result_ready(result_ready),.result_error(error),.result_tag(result_tag),.written_pixels(written),.fence_required(fence),
        .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
        .m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready),
        .m_axi_awid(awid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
        .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
        .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready));
    localparam DEPTH=186624;
    reg [127:0] scratch [0:DEPTH-1],state0 [0:DEPTH-1],state1 [0:DEPTH-1],expected [0:DEPTH-1];
    reg read_active=0,write_active=0;reg [29:0] read_base=0,write_base=0;
    integer read_index=0,write_index=0,read_beats=0,write_beats=0,bdelay=0,cycle=0,read_commands=0,write_commands=0;
    reg force_ar_hold=0,force_aw_hold=0,force_w_hold=0,force_b_hold=0;
    assign arready=!force_ar_hold && !read_active && !rvalid && cycle%7!=0;
    assign awready=!force_aw_hold && !write_active && !bvalid && bdelay==0 && cycle%11!=0;
    assign wready=!force_w_hold && write_active && cycle%5!=0;
    function [127:0] memory_read(input [29:0] address);
        integer ix;
        begin
            if(address>=30'h01800000)begin ix=(address-30'h01800000)>>4;memory_read=scratch[ix];end
            else if(address>=30'h01000000)begin ix=(address-30'h01000000)>>4;memory_read=state1[ix];end
            else begin ix=(address-30'h00800000)>>4;memory_read=state0[ix];end
            if(ix<0 || ix>=DEPTH)$fatal(1,"DDR model address outside allocation %h",address);
        end
    endfunction
    reg [127:0] old_word;integer ix,j;
    always @(posedge clk)begin
        cycle<=cycle+1;
        if(reset)begin
            read_active<=0;write_active<=0;rvalid<=0;bvalid<=0;bdelay<=0;read_index<=0;write_index<=0;
        end else begin
            if(arvalid&&arready)begin
                if(arid!=8 || arsize!=4 || arburst!=1 || araddr[3:0]!=0 || arlen>15 || araddr[11:0]+(arlen+1)*16>4096)$fatal(1,"bad AXI AR");
                read_active<=1;read_base<=araddr;read_beats<=arlen+1;read_index<=0;read_commands<=read_commands+1;
            end
            if(read_active && (!rvalid||rready))begin
                if(rvalid&&rready&&rlast)begin rvalid<=0;read_active<=0;end
                else if(cycle%3!=0)begin
                    rvalid<=1;rdata<=memory_read(read_base+read_index*16);rlast<=read_index==read_beats-1;read_index<=read_index+1;
                end else rvalid<=0;
            end
            if(awvalid&&awready)begin
                if(awid!=8 || awsize!=4 || awburst!=1 || awaddr[3:0]!=0 || awlen>15 || awaddr[11:0]+(awlen+1)*16>4096)$fatal(1,"bad AXI AW");
                if(awaddr<30'h00800000 || awaddr>=30'h01800000)$fatal(1,"write outside fusion banks");
                write_active<=1;write_base<=awaddr;write_beats<=awlen+1;write_index<=0;write_commands<=write_commands+1;
            end
            if(wvalid&&wready)begin
                if(wlast!=(write_index==write_beats-1))$fatal(1,"bad WLAST");
                ix=((write_base>=30'h01000000 ? write_base-30'h01000000 : write_base-30'h00800000)>>4)+write_index;
                old_word=write_base>=30'h01000000 ? state1[ix] : state0[ix];
                for(j=0;j<16;j=j+1)if(wstrb[j])old_word[j*8+:8]=wdata[j*8+:8];
                if(write_base>=30'h01000000)state1[ix]<=old_word;else state0[ix]<=old_word;
                if(wlast)begin write_active<=0;bdelay<=9;end else write_index<=write_index+1;
            end
            if(bdelay>0 && !force_b_hold)begin bdelay<=bdelay-1;if(bdelay==1)bvalid<=1;end
            if(bvalid&&bready)bvalid<=0;
            if(published && (read_active||write_active||bvalid||bdelay!=0))$fatal(1,"published before durable completion");
        end
    end
    // Check AXI payload stability while independently backpressured.
    reg hold_ar=0,hold_aw=0,hold_w=0;reg [37:0] last_ar,last_aw;reg [144:0] last_w;
    always @(posedge clk)begin
        if(!reset)begin
            if(hold_ar && (!arvalid || {araddr,arlen}!==last_ar))$fatal(1,"AR changed under backpressure");
            if(hold_aw && (!awvalid || {awaddr,awlen}!==last_aw))$fatal(1,"AW changed under backpressure");
            if(hold_w && (!wvalid || {wdata,wstrb,wlast}!==last_w))$fatal(1,"W changed under backpressure");
            hold_ar<=arvalid&&!arready;last_ar<={araddr,arlen};hold_aw<=awvalid&&!awready;last_aw<={awaddr,awlen};
            hold_w<=wvalid&&!wready;last_w<={wdata,wstrb,wlast};
        end else begin hold_ar<=0;hold_aw<=0;hold_w<=0;end
    end
    task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
    integer receipt,passed=0;
    task run_group(input integer ci,input integer w,input integer h);
        integer s,n,bi,lane,fd;reg [127:0] actual;
        begin
            wait(begin_ready);@(negedge clk);begin_group=ci+1;width=w;height=h;begin_valid=1;tick();begin_valid=0;
            wait(active||receipt_valid);@(negedge clk);if(!active)$fatal(1,"group not opened");n=w*h;
            for(s=1;s<=8;s=s+1)begin
                $readmemh($sformatf("c%0d_s%0d_input.hex",ci,s),scratch,0,(n+3)/4-1);
                $readmemh($sformatf("c%0d_s%0d_expected.hex",ci,s),expected,0,(n+3)/4-1);
                wait(frame_ready);@(negedge clk);frame_group=begin_group;frame_digest=begin_digest;frame_slot=s;frame_request=s;frame_valid=1;
                tick();frame_valid=0;wait(receipt_valid);@(negedge clk);
                if(receipt_error!=0 || receipt_request!=s || completed!=s || fault || fence || written!=n)$fatal(1,"frame commit mismatch case%0d slot%0d err%0d count%0d",ci,s,receipt_error,written);
                if(published!=(s==8))$fatal(1,"early/missing group publication");
                for(bi=0;bi<(n+3)/4;bi=bi+1)begin
                    actual=published_base==30'h01000000 ? state1[bi] : state0[bi];
                    for(lane=0;lane<4;lane=lane+1)if(bi*4+lane<n && actual[32*lane+:32]!==expected[bi][32*lane+:32])
                        $fatal(1,"word differs case%0d slot%0d pixel%0d actual%h expected%h",ci,s,bi*4+lane,actual[32*lane+:32],expected[bi][32*lane+:32]);
                end
                passed=passed+1;$fwrite(receipt,"%0d,%0d,%0d,PASS\n",ci,s,n);$display("FRAME_PASS case%0d slot%0d pixels%0d",ci,s,n);
                receipt_ready=1;tick();receipt_ready=0;
            end
            if(published_group!=begin_group || published_digest!=begin_digest || published_width!=w || published_height!=h)$fatal(1,"published identity mismatch");
            fd=$fopen($sformatf("c%0d_actual.hex",ci),"w");
            for(bi=0;bi<(n+3)/4;bi=bi+1)begin
                actual=published_base==30'h01000000 ? state1[bi] : state0[bi];
                for(lane=0;lane<4;lane=lane+1)if(bi*4+lane<n)$fwrite(fd,"%08h\n",actual[32*lane+:32]);
            end
            $fclose(fd);release_group=begin_group;release_valid=1;tick();release_valid=0;
        end
    endtask
    initial begin
        receipt=$fopen("rtl_real_receipt.csv","w");$fwrite(receipt,"case,slot,pixels,status\n");
        for(integer k=0;k<DEPTH;k=k+1)begin state0[k]=128'hdeadbeef0123456789abcdef98765432;state1[k]=~state0[k];end
        repeat(5)tick();reset=0;repeat(2)tick();
        `include "groups.svh"
        $fclose(receipt);$display("FUSION_AXI_ALL_PASS %0d",passed);$finish;
    end
    initial begin #10000000000;$fatal(1,"watchdog TB");end
endmodule
