// Asynchronous assertion, three local-clock edges for deassertion. Only the
// synchronizer's asynchronous controls are excluded from recovery/removal;
// local stage-to-stage D paths and downstream reset paths remain timed.
module reset_release_sync(input wire clk,async_reset,output wire reset);
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] pipe;
    always @(posedge clk or posedge async_reset)
        if(async_reset)pipe<=3'b111;else pipe<={pipe[1:0],1'b0};
    assign reset=pipe[2];
endmodule
