`timescale 1ns/1ps
module tb_stage_cycle_meter;
    reg clk=0;always #4 clk=~clk;
    reg reset=1,clear=0,start=0,finish=0,success=1,event0=0,event1=0,blocked=0;
    wire busy,valid,overflow;wire [3:0] cycles,count0,count1,blocked_cycles;
    stage_cycle_meter #(.BITS(4)) dut(.*);
    task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
    task fresh;begin clear=1;tick();clear=0;start=0;finish=0;event0=0;event1=0;blocked=0;end endtask
    initial begin
        repeat(3)tick();reset=0;tick();
        start=1;event0=1;tick();start=0;event0=0;event1=1;blocked=1;tick();event1=0;blocked=0;finish=1;tick();finish=0;
        if(!valid||busy||overflow||cycles!=3||count0!=1||count1!=1||blocked_cycles!=1)$fatal(1,"inclusive cycles/event counts");
        repeat(4)tick();if(cycles!=3||!valid)$fatal(1,"snapshot not held");
        fresh();start=1;finish=1;tick();start=0;finish=0;if(!valid||busy||cycles!=1)$fatal(1,"one cycle operation");
        fresh();success=0;start=1;tick();start=0;finish=1;tick();finish=0;if(valid||busy)$fatal(1,"failed op marked valid");success=1;
        fresh();start=1;tick();start=0;repeat(16)tick();finish=1;tick();finish=0;if(valid||!overflow||cycles!=15)$fatal(1,"overflow wrapped or valid");
        fresh();start=1;tick();start=0;tick();start=1;tick();start=0;finish=1;tick();finish=0;if(valid||!overflow)$fatal(1,"double start accepted");
        fresh();if(valid||overflow||busy||cycles!=0)$fatal(1,"clear leaked stale stats");
        start=1;tick();start=0;reset=1;tick();reset=0;tick();if(valid||busy||count0!=0)$fatal(1,"reset leaked stats");
        $display("STAGE_METER_ALL_PASS 7");$finish;
    end
    initial begin #100000;$fatal(1,"meter watchdog");end
endmodule
