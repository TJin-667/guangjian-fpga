// One-entry bundled-data mailbox. Both domains require coherent reset.
// Source payload remains immutable until the destination consumes it.
module cdc_snapshot_mailbox #(parameter integer WIDTH=256)(
    input wire src_clk,src_reset,src_valid,output wire src_ready,input wire [WIDTH-1:0] src_data,
    input wire dst_clk,dst_reset,output wire dst_valid,input wire dst_ready,output reg [WIDTH-1:0] dst_data
);
    reg request_toggle,ack_toggle,seen;
    reg [WIDTH-1:0] held_data;
    (* ASYNC_REG="TRUE" *) reg [2:0] ack_sync,request_sync;
    reg pending;
    assign src_ready=request_toggle==ack_sync[2] && !src_reset;
    assign dst_valid=pending && !dst_reset;
    always @(posedge src_clk)begin
        if(src_reset)begin request_toggle<=0;held_data<=0;ack_sync<=0;end
        else begin
            ack_sync<={ack_sync[1:0],ack_toggle};
            if(src_valid && src_ready)begin held_data<=src_data;request_toggle<=~request_toggle;end
        end
    end
    always @(posedge dst_clk)begin
        if(dst_reset)begin request_sync<=0;seen<=0;ack_toggle<=0;pending<=0;dst_data<=0;end
        else begin
            request_sync<={request_sync[1:0],request_toggle};
            if(!pending && request_sync[2]!=seen)begin dst_data<=held_data;seen<=request_sync[2];pending<=1;end
            if(dst_valid && dst_ready)begin pending<=0;ack_toggle<=seen;end
        end
    end
endmodule
