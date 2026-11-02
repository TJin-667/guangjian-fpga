// AXI read -> FIFO, with an acknowledged START/STOP command mailbox.
// Unlike the old addr_clr heuristic, a command poisons an outstanding read even
// when ARVALID and RVALID are both low while waiting for the first response.
// ctrl_enable/ctrl_bank are held in the source domain until ctrl_ack_toggle.
module axi4_to_fifo_epoch #(
    parameter integer FRAME_BYTES=4147200,BANK1_BASE=4194304,
    parameter integer AXI_DATA_WIDTH=128,AXI_ADDR_WIDTH=30,AXI_ID_WIDTH=4,
    parameter [AXI_ID_WIDTH-1:0] AXI_ID=0,
    parameter integer AXI_BURST_LEN=31,FIFO_ADDR_WIDTH=6
)(
    input wire clk,reset,ctrl_toggle,ctrl_enable,ctrl_bank,
    output reg ctrl_ack_toggle,ctrl_seen_toggle,output reg active_enable,output reg [3:0] fault,output reg fault_active,
    output reg fifo_wrreq,output reg [AXI_DATA_WIDTH-1:0] fifo_wrdata,
    input wire fifo_alfull,fifo_rst_busy,input wire [FIFO_ADDR_WIDTH-1:0] fifo_wr_cnt,
    output wire [AXI_ID_WIDTH-1:0] m_axi_arid,output reg [AXI_ADDR_WIDTH-1:0] m_axi_araddr,
    output wire [7:0] m_axi_arlen,output wire [2:0] m_axi_arsize,output wire [1:0] m_axi_arburst,
    output wire [0:0] m_axi_arlock,output wire [3:0] m_axi_arcache,
    output wire [2:0] m_axi_arprot,output wire [3:0] m_axi_arqos,m_axi_arregion,
    output reg m_axi_arvalid,input wire m_axi_arready,
    input wire [AXI_ID_WIDTH-1:0] m_axi_rid,input wire [AXI_DATA_WIDTH-1:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,input wire m_axi_rlast,m_axi_rvalid,
    output wire m_axi_rready
);
    localparam IDLE=0,ADDRESS=1,RESPONSE=2;
    reg [1:0] state;reg active_bank,pending,held_enable,held_bank,held_toggle;
    reg command_arrived;
    (* ASYNC_REG="TRUE" *) reg [2:0] ctrl_sync;
    reg [8:0] beats;
    wire changing=pending || command_arrived || ctrl_sync[2]!=ctrl_ack_toggle;
    wire [AXI_ADDR_WIDTH-1:0] base=active_bank ? BANK1_BASE : 0;
    wire room=fifo_wr_cnt < (2**FIFO_ADDR_WIDTH)-(AXI_BURST_LEN+1)-2;
    assign m_axi_arid=AXI_ID;assign m_axi_arlen=AXI_BURST_LEN;
    assign m_axi_arsize=$clog2(AXI_DATA_WIDTH/8);assign m_axi_arburst=2'b01;
    assign m_axi_arlock=0;assign m_axi_arcache=0;assign m_axi_arprot=0;assign m_axi_arqos=0;assign m_axi_arregion=0;
    assign m_axi_rready=state==RESPONSE && (changing || !active_enable || fault!=0 || !fifo_alfull);
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;active_bank<=0;active_enable<=0;pending<=0;held_enable<=0;held_bank<=0;held_toggle<=0;command_arrived<=0;
            ctrl_sync<=0;ctrl_ack_toggle<=0;ctrl_seen_toggle<=0;fault<=0;fault_active<=0;fifo_wrreq<=0;fifo_wrdata<=0;
            m_axi_araddr<=0;m_axi_arvalid<=0;beats<=0;
        end else begin
            ctrl_sync<={ctrl_sync[1:0],ctrl_toggle};fifo_wrreq<=0;
            // Only the sticky one-bit alarm crosses into net_clk. Error-code
            // bits may change together and must not be independently decoded.
            if(fault!=0)fault_active<=1;
            command_arrived<=!pending && !command_arrived && ctrl_sync[2]!=ctrl_ack_toggle;
            // Capture the held two-bit command using a local registered CE.
            // START/STOP poisoning above is immediate, even before this latch.
            if(command_arrived)begin
                pending<=1;held_toggle<=ctrl_sync[2];held_enable<=ctrl_enable;held_bank<=ctrl_bank;
                ctrl_seen_toggle<=ctrl_sync[2];
            end
            case(state)
                IDLE:begin
                    if(pending && !fifo_rst_busy)begin
                        active_enable<=held_enable;active_bank<=held_bank;
                        m_axi_araddr<=held_bank ? BANK1_BASE : 0;
                        ctrl_ack_toggle<=held_toggle;pending<=0;
                        // Faults require common reset; a START cannot erase an AXI failure.
                    end else if(active_enable && !changing && room && !fifo_rst_busy && fault==0)begin
                        m_axi_arvalid<=1;state<=ADDRESS;
                    end
                end
                ADDRESS:if(m_axi_arvalid && m_axi_arready)begin
                    m_axi_arvalid<=0;beats<=0;state<=RESPONSE;
                end
                RESPONSE:if(m_axi_rvalid && m_axi_rready)begin
                    beats<=beats+1;
                    if(m_axi_rid!=AXI_ID || m_axi_rresp!=0)fault<=1;
                    if(m_axi_rlast!=(beats==AXI_BURST_LEN))fault<=2;
                    if(!changing && active_enable && fault==0 && m_axi_rid==AXI_ID && m_axi_rresp==0 &&
                        m_axi_rlast==(beats==AXI_BURST_LEN) && !fifo_rst_busy)begin fifo_wrreq<=1;fifo_wrdata<=m_axi_rdata;end
                    if(m_axi_rlast)begin
                        state<=IDLE;
                        if(m_axi_araddr+((AXI_BURST_LEN+1)*(AXI_DATA_WIDTH/8))>=base+FRAME_BYTES)m_axi_araddr<=base;
                        else m_axi_araddr<=m_axi_araddr+((AXI_BURST_LEN+1)*(AXI_DATA_WIDTH/8));
                    end
                end
            endcase
        end
    end
endmodule
