// Read <=1024 result bytes, bursting 16 aligned 128-bit beats at a time.
// Output is elastic. Caller waits for the final output CDC ACK before replying.
module axi_result_reader #(
    parameter [3:0] AXI_ID=4'ha,
    parameter integer WATCHDOG_CYCLES=125000000
)(
    input wire clk,reset,cfg_valid,output wire cfg_ready,
    input wire [29:0] cfg_address,input wire [31:0] cfg_bytes,cfg_ticket,
    output reg out_valid,input wire out_ready,output reg [127:0] out_data,
    output reg [4:0] out_bytes,output reg [6:0] out_index,output reg out_last,
    output wire result_valid,input wire result_ready,output reg [3:0] result_error,
    output reg [31:0] result_ticket,output reg fence_required,
    output wire [3:0] m_axi_arid,output wire [29:0] m_axi_araddr,output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,output wire [1:0] m_axi_arburst,output wire m_axi_arvalid,input wire m_axi_arready,
    input wire [3:0] m_axi_rid,input wire [127:0] m_axi_rdata,input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,m_axi_rvalid,output wire m_axi_rready
);
    localparam IDLE=0,PREP=1,AR=2,R=3,DRAIN=4,RESULT=5,FENCE=6;
    reg [2:0] state;reg [29:0] address;reg [10:0] remaining_bytes;
    reg [6:0] index;reg [4:0] beats;reg [3:0] beat;reg [31:0] watchdog;
    wire [7:0] remaining_beats=({1'b0,remaining_bytes}+15)>>4;
    wire cfg_ok=cfg_bytes>0&&cfg_bytes<=1024&&cfg_bytes[1:0]==0&&cfg_address[7:0]==0&&
        ({1'b0,cfg_address}+cfg_bytes)<=31'h02000000;
    assign cfg_ready=state==IDLE&&!reset&&!fence_required;
    assign m_axi_arid=AXI_ID;assign m_axi_araddr=address;assign m_axi_arlen=beats-1;
    assign m_axi_arsize=4;assign m_axi_arburst=1;assign m_axi_arvalid=state==AR&&!reset;
    assign m_axi_rready=state==R&&(!out_valid||out_ready)&&!reset;
    assign result_valid=state==RESULT&&!reset;
    wire progress=state==PREP||(m_axi_arvalid&&m_axi_arready)||(m_axi_rvalid&&m_axi_rready)||(out_valid&&out_ready);
    always @(posedge clk)begin
        if(reset)begin state<=IDLE;address<=0;remaining_bytes<=0;index<=0;beats<=0;beat<=0;watchdog<=0;
            out_valid<=0;out_data<=0;out_bytes<=0;out_index<=0;out_last<=0;result_error<=0;result_ticket<=0;fence_required<=0;end
        else begin
            if(state==IDLE||state==RESULT||progress)watchdog<=0;else watchdog<=watchdog+1;
            if(state!=IDLE&&state!=RESULT&&WATCHDOG_CYCLES>0&&watchdog>=WATCHDOG_CYCLES-1&&!progress)begin fence_required<=1;result_error<=6;end
            if(out_valid&&out_ready)out_valid<=0;
            case(state)
                IDLE:if(cfg_valid&&cfg_ready)begin
                    address<=cfg_address;remaining_bytes<=cfg_bytes[10:0];result_ticket<=cfg_ticket;
                    result_error<=0;index<=0;out_valid<=0;
                    if(cfg_ok)state<=PREP;else begin result_error<=1;state<=RESULT;end
                end
                PREP:begin beats<=remaining_beats>=16 ? 16 : remaining_beats[4:0];beat<=0;state<=fence_required ? FENCE : AR;end
                AR:if(m_axi_arready)state<=R;
                R:if(m_axi_rvalid&&m_axi_rready)begin
                    if(m_axi_rid!=AXI_ID || m_axi_rlast!=(beat==beats-1))begin result_error<=7;fence_required<=1;state<=FENCE;end
                    else begin
                        if(m_axi_rresp!=0)result_error<=4;
                        out_valid<=1;out_data<=m_axi_rdata;out_bytes<=remaining_bytes>=16 ? 16 : remaining_bytes[4:0];
                        out_index<=index;out_last<=remaining_bytes<=16;
                        index<=index+1;remaining_bytes<=remaining_bytes>=16 ? remaining_bytes-16 : 0;
                        if(remaining_bytes<=16)state<=DRAIN;
                        else if(beat==beats-1)begin address<=address+({25'd0,beats}<<4);state<=PREP;end
                        else beat<=beat+1;
                    end
                end
                DRAIN:if(!out_valid||out_ready)state<=RESULT;
                RESULT:if(result_ready)state<=IDLE;
                FENCE:state<=FENCE;
            endcase
        end
    end
endmodule
