// Same-domain service cycles and observed handshakes. No timing crosses domains.
// start edge is cycle1; finish edge is included. Saturation invalidates results.
module stage_cycle_meter #(parameter integer BITS=32)(
    input wire clk,reset,clear,start,finish,success,event0,event1,blocked,
    output reg busy,valid,overflow,
    output reg [BITS-1:0] cycles,count0,count1,blocked_cycles
);
    localparam [BITS-1:0] MAXIMUM={BITS{1'b1}};
    wire would_overflow=(cycles==MAXIMUM)||(event0&&count0==MAXIMUM)||
        (event1&&count1==MAXIMUM)||(blocked&&blocked_cycles==MAXIMUM);
    always @(posedge clk)begin
        if(reset||clear)begin
            busy<=0;valid<=0;overflow<=0;cycles<=0;count0<=0;count1<=0;blocked_cycles<=0;
        end else if(start)begin
            // A second start during service is a protocol error, never a new sample.
            if(busy)begin valid<=0;overflow<=1;end
            else begin
                busy<=!finish;valid<=finish&&success;overflow<=0;cycles<=1;
                count0<=event0 ? 1 : 0;count1<=event1 ? 1 : 0;blocked_cycles<=blocked ? 1 : 0;
            end
        end else if(busy)begin
            if(cycles!=MAXIMUM)cycles<=cycles+1;
            if(event0&&count0!=MAXIMUM)count0<=count0+1;
            if(event1&&count1!=MAXIMUM)count1<=count1+1;
            if(blocked&&blocked_cycles!=MAXIMUM)blocked_cycles<=blocked_cycles+1;
            if(would_overflow)overflow<=1;
            if(finish)begin busy<=0;valid<=success&&!overflow&&!would_overflow;end
        end
    end
endmodule
