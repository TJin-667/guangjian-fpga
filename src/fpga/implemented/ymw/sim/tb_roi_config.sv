`timescale 1ns/1ps
module tb_roi_config;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,start=0;
    reg [15:0] rx=0,ry=0,rw=0,rh=0;
    wire busy,done,error,valid;
    wire [15:0] x,y,w,h,packets,generation;
    wire [31:0] pixels;wire [10:0] last_pixels;
    integer cases=0;
    roi_config_ctrl dut(.clk(clk),.reset(reset),.start(start),.request_x(rx),.request_y(ry),
        .request_width(rw),.request_height(rh),.busy(busy),.done(done),.error(error),.valid(valid),
        .x(x),.y(y),.width(w),.height(h),.packets(packets),.generation(generation),.pixels(pixels),.last_pixels(last_pixels));
    task tick;begin @(posedge clk);#1;end endtask
    task check(input integer a,b,c,d,good);
        integer old_generation,old_x,watch;
        begin
            old_generation=generation;old_x=x;
            @(negedge clk);rx=a;ry=b;rw=c;rh=d;start=1;tick();@(negedge clk);start=0;
            watch=0;while(!done && watch<4000)begin tick();watch=watch+1;end
            if(!done || error==good)$fatal(1,"ROI validity error");
            if(good)begin
                if(x!=a || y!=b || w!=c || h!=d || pixels!=c*d || packets!=(c*d+689)/690 ||
                    last_pixels!=c*d-((c*d+689)/690-1)*690 || generation!=old_generation+1 || !valid)$fatal(1,"ROI computation mismatch");
            end else if(generation!=old_generation || x!=old_x)$fatal(1,"failed config changed state");
            cases=cases+1;tick();
        end
    endtask
    initial begin
        repeat(5)tick();reset=0;tick();
        check(0,0,1920,1080,1);check(605,162,831,832,1);check(1919,1079,1,1,1);
        check(100,100,23,30,1);check(0,0,690,1,1);check(0,0,691,1,1);
        check(0,0,0,100,0);check(1919,0,2,1,0);check(65535,0,2,1,0);check(0,1079,1,2,0);
        check(605,163,831,833,1);
        $display("ROI_CONFIG_PASS %0d",cases);$finish;
    end
    initial begin #500000;$fatal(1,"test deadline");end
endmodule
