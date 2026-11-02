// Four clients, 128-bit AXI, one read burst and one write burst outstanding.
// Client0=old camera/FIFO, 1=scratch writer, 2=fusion, 3=controlled service.
// Round-robin at transaction completion; AR and AW/W/B arbitrate independently.
// Original IDs are restored. MIG IDs encode the client. No client interleaving
// within a burst. Reset MUST fence/reset the shared AXI/MIG epoch as well.
module axi4_burst_arbiter4 #(
    parameter integer WATCHDOG_CYCLES=125000000,
    parameter integer ENFORCE_RANGES=1
)(
    input wire clk,reset,output reg fence_required,
    input wire [15:0] s_awid,input wire [119:0] s_awaddr,input wire [31:0] s_awlen,
    input wire [11:0] s_awsize,input wire [7:0] s_awburst,input wire [3:0] s_awlock,
    input wire [15:0] s_awcache,input wire [11:0] s_awprot,input wire [15:0] s_awqos,
    input wire [3:0] s_awvalid,output wire [3:0] s_awready,
    input wire [511:0] s_wdata,input wire [63:0] s_wstrb,input wire [3:0] s_wlast,s_wvalid,
    output wire [3:0] s_wready,output wire [15:0] s_bid,output wire [7:0] s_bresp,
    output wire [3:0] s_bvalid,input wire [3:0] s_bready,
    input wire [15:0] s_arid,input wire [119:0] s_araddr,input wire [31:0] s_arlen,
    input wire [11:0] s_arsize,input wire [7:0] s_arburst,input wire [3:0] s_arlock,
    input wire [15:0] s_arcache,input wire [11:0] s_arprot,input wire [15:0] s_arqos,
    input wire [3:0] s_arvalid,output wire [3:0] s_arready,
    output wire [15:0] s_rid,output wire [511:0] s_rdata,output wire [7:0] s_rresp,
    output wire [3:0] s_rlast,s_rvalid,input wire [3:0] s_rready,
    output wire [3:0] m_awid,output wire [29:0] m_awaddr,output wire [7:0] m_awlen,
    output wire [2:0] m_awsize,output wire [1:0] m_awburst,output wire m_awlock,
    output wire [3:0] m_awcache,output wire [2:0] m_awprot,output wire [3:0] m_awqos,
    output wire m_awvalid,input wire m_awready,
    output wire [127:0] m_wdata,output wire [15:0] m_wstrb,output wire m_wlast,m_wvalid,
    input wire m_wready,input wire [3:0] m_bid,input wire [1:0] m_bresp,
    input wire m_bvalid,output wire m_bready,
    output wire [3:0] m_arid,output wire [29:0] m_araddr,output wire [7:0] m_arlen,
    output wire [2:0] m_arsize,output wire [1:0] m_arburst,output wire m_arlock,
    output wire [3:0] m_arcache,output wire [2:0] m_arprot,output wire [3:0] m_arqos,
    output wire m_arvalid,input wire m_arready,
    input wire [3:0] m_rid,input wire [127:0] m_rdata,input wire [1:0] m_rresp,
    input wire m_rlast,m_rvalid,output wire m_rready,
    output reg [31:0] accepted_reads,accepted_writes,completed_reads,completed_writes,
    output reg [31:0] rejected_reads,rejected_writes
);
    localparam W_IDLE=0,W_CHECK=1,W_ADDR=2,W_DATA=3,W_RESP=4,W_BAD_DATA=5,W_BAD_RESP=6;
    localparam R_IDLE=0,R_CHECK=1,R_ADDR=2,R_DATA=3,R_BAD=4;
    reg [2:0] ws,rs;
    reg [1:0] wr_rr,rd_rr,wr_owner,rd_owner;
    reg [3:0] wr_id,rd_id;
    reg [29:0] wr_addr,rd_addr;
    reg [7:0] wr_len,rd_len,wr_beat,rd_beat;
    reg [2:0] wr_size,rd_size,wr_prot,rd_prot;
    reg [1:0] wr_burst,rd_burst;
    reg wr_lock,rd_lock,wr_problem;
    reg [3:0] wr_cache,rd_cache,wr_qos,rd_qos;
    reg [31:0] wr_watchdog,rd_watchdog;
    reg [1:0] wr_pick,rd_pick;reg wr_found,rd_found;
    integer k,j;
    always @*begin
        wr_pick=wr_rr;rd_pick=rd_rr;wr_found=0;rd_found=0;
        for(integer n=0;n<4;n=n+1)begin
            if(!wr_found && s_awvalid[(wr_rr+n)%4])begin wr_pick=(wr_rr+n)%4;wr_found=1;end
            if(!rd_found && s_arvalid[(rd_rr+n)%4])begin rd_pick=(rd_rr+n)%4;rd_found=1;end
        end
    end
    function range_ok;
        input [1:0] owner;input write_transaction;input [29:0] address;input [30:0] ending;
        begin
            if(!ENFORCE_RANGES)range_ok=1;
            else case(owner)
                0:range_ok=ending<=31'h00800000;
                1:range_ok=write_transaction && address>=30'h01800000 && ending<=31'h02000000;
                2:range_ok=address>=30'h00800000 && ending<=(write_transaction ? 31'h01800000 : 31'h02000000);
                3:range_ok=ending<=31'h02000000 && (!write_transaction || ending<=31'h00800000 || address>=30'h01800000);
            endcase
        end
    endfunction
    wire [30:0] wr_end={1'b0,wr_addr}+({23'd0,wr_len}+31'd1)*31'd16;
    wire [30:0] rd_end={1'b0,rd_addr}+({23'd0,rd_len}+31'd1)*31'd16;
    wire wr_ok=wr_size==4 && wr_burst==1 && !wr_lock && wr_len<=31 && wr_addr[3:0]==0 &&
        {1'b0,wr_addr[11:0]}+({5'd0,wr_len}+13'd1)*13'd16<=4096 && range_ok(wr_owner,1'b1,wr_addr,wr_end);
    wire rd_ok=rd_size==4 && rd_burst==1 && !rd_lock && rd_len<=31 && rd_addr[3:0]==0 &&
        {1'b0,rd_addr[11:0]}+({5'd0,rd_len}+13'd1)*13'd16<=4096 && range_ok(rd_owner,1'b0,rd_addr,rd_end);
    assign m_awid={2'b0,wr_owner};assign m_awaddr=wr_addr;assign m_awlen=wr_len;
    assign m_awsize=wr_size;assign m_awburst=wr_burst;assign m_awlock=wr_lock;
    assign m_awcache=wr_cache;assign m_awprot=wr_prot;assign m_awqos=wr_qos;
    assign m_awvalid=ws==W_ADDR&&!reset;
    assign m_wdata=s_wdata[wr_owner*128+:128];assign m_wstrb=s_wstrb[wr_owner*16+:16];
    assign m_wlast=wr_beat==wr_len;
    assign m_wvalid=ws==W_DATA&&s_wvalid[wr_owner]&&!reset;
    assign m_bready=ws==W_RESP&&s_bready[wr_owner]&&!reset;
    assign m_arid={2'b0,rd_owner};assign m_araddr=rd_addr;assign m_arlen=rd_len;
    assign m_arsize=rd_size;assign m_arburst=rd_burst;assign m_arlock=rd_lock;
    assign m_arcache=rd_cache;assign m_arprot=rd_prot;assign m_arqos=rd_qos;
    assign m_arvalid=rs==R_ADDR&&!reset;
    assign m_rready=rs==R_DATA&&s_rready[rd_owner]&&!reset;
    wire wrong_bid=m_bid!={2'b0,wr_owner};
    wire wrong_read=m_rid!={2'b0,rd_owner} || m_rlast!=(rd_beat==rd_len);
    genvar port;
    generate for(port=0;port<4;port=port+1)begin: ports4
        assign s_awready[port]=ws==W_IDLE&&wr_found&&wr_pick==port&&!fence_required&&!reset;
        assign s_wready[port]=(ws==W_DATA ? m_wready : ws==W_BAD_DATA)&&wr_owner==port&&!reset;
        assign s_bid[port*4+:4]=wr_id;
        assign s_bresp[port*2+:2]=ws==W_BAD_RESP ? 2'b11 : ((wr_problem||wrong_bid) ? 2'b10 : m_bresp);
        assign s_bvalid[port]=(ws==W_BAD_RESP||(ws==W_RESP&&m_bvalid))&&wr_owner==port&&!reset;
        assign s_arready[port]=rs==R_IDLE&&rd_found&&rd_pick==port&&!fence_required&&!reset;
        assign s_rid[port*4+:4]=rd_id;
        assign s_rdata[port*128+:128]=rs==R_BAD ? 128'd0 : m_rdata;
        assign s_rresp[port*2+:2]=rs==R_BAD ? 2'b11 : (wrong_read ? 2'b10 : m_rresp);
        assign s_rlast[port]=rs==R_BAD ? rd_beat==rd_len : m_rlast;
        assign s_rvalid[port]=(rs==R_BAD||(rs==R_DATA&&m_rvalid))&&rd_owner==port&&!reset;
    end endgenerate
    wire wr_progress=(|(s_awready&s_awvalid))||(m_awvalid&&m_awready)||(m_wvalid&&m_wready)||
        (|(s_bvalid&s_bready))||(ws==W_BAD_DATA&&s_wvalid[wr_owner])||ws==W_CHECK;
    wire rd_progress=(|(s_arready&s_arvalid))||(m_arvalid&&m_arready)||(|(s_rvalid&s_rready))||rs==R_CHECK;
    always @(posedge clk)begin
        if(reset)begin
            ws<=W_IDLE;rs<=R_IDLE;wr_rr<=0;rd_rr<=0;wr_owner<=0;rd_owner<=0;wr_id<=0;rd_id<=0;
            wr_addr<=0;rd_addr<=0;wr_len<=0;rd_len<=0;wr_beat<=0;rd_beat<=0;
            wr_size<=0;rd_size<=0;wr_prot<=0;rd_prot<=0;wr_burst<=0;rd_burst<=0;
            wr_lock<=0;rd_lock<=0;wr_cache<=0;rd_cache<=0;wr_qos<=0;rd_qos<=0;wr_problem<=0;
            wr_watchdog<=0;rd_watchdog<=0;fence_required<=0;
            accepted_reads<=0;accepted_writes<=0;completed_reads<=0;completed_writes<=0;rejected_reads<=0;rejected_writes<=0;
        end else begin
            if(ws==W_IDLE||wr_progress)wr_watchdog<=0;else wr_watchdog<=wr_watchdog+1;
            if(rs==R_IDLE||rd_progress)rd_watchdog<=0;else rd_watchdog<=rd_watchdog+1;
            if((ws!=W_IDLE&&WATCHDOG_CYCLES>0&&wr_watchdog>=WATCHDOG_CYCLES-1&&!wr_progress)||
               (rs!=R_IDLE&&WATCHDOG_CYCLES>0&&rd_watchdog>=WATCHDOG_CYCLES-1&&!rd_progress))fence_required<=1;
            case(ws)
                W_IDLE:if(|(s_awvalid&s_awready))begin
                    wr_owner<=wr_pick;wr_id<=s_awid[wr_pick*4+:4];wr_addr<=s_awaddr[wr_pick*30+:30];
                    wr_len<=s_awlen[wr_pick*8+:8];wr_size<=s_awsize[wr_pick*3+:3];wr_burst<=s_awburst[wr_pick*2+:2];
                    wr_lock<=s_awlock[wr_pick];wr_cache<=s_awcache[wr_pick*4+:4];wr_prot<=s_awprot[wr_pick*3+:3];wr_qos<=s_awqos[wr_pick*4+:4];
                    wr_beat<=0;wr_problem<=0;accepted_writes<=accepted_writes+1;ws<=W_CHECK;
                end
                W_CHECK:if(wr_ok)ws<=W_ADDR;else begin rejected_writes<=rejected_writes+1;ws<=W_BAD_DATA;end
                W_ADDR:if(m_awready)ws<=W_DATA;
                W_DATA,W_BAD_DATA:if(s_wvalid[wr_owner]&&s_wready[wr_owner])begin
                    if(s_wlast[wr_owner]!=(wr_beat==wr_len))begin wr_problem<=1;fence_required<=1;end
                    if(wr_beat==wr_len)ws<=ws==W_BAD_DATA ? W_BAD_RESP : W_RESP;
                    else wr_beat<=wr_beat+1;
                end
                W_RESP,W_BAD_RESP:if(s_bvalid[wr_owner]&&s_bready[wr_owner])begin
                    if(ws==W_RESP&&wrong_bid)fence_required<=1;
                    completed_writes<=completed_writes+1;wr_rr<=wr_owner+1;ws<=W_IDLE;
                end
            endcase
            case(rs)
                R_IDLE:if(|(s_arvalid&s_arready))begin
                    rd_owner<=rd_pick;rd_id<=s_arid[rd_pick*4+:4];rd_addr<=s_araddr[rd_pick*30+:30];
                    rd_len<=s_arlen[rd_pick*8+:8];rd_size<=s_arsize[rd_pick*3+:3];rd_burst<=s_arburst[rd_pick*2+:2];
                    rd_lock<=s_arlock[rd_pick];rd_cache<=s_arcache[rd_pick*4+:4];rd_prot<=s_arprot[rd_pick*3+:3];rd_qos<=s_arqos[rd_pick*4+:4];
                    rd_beat<=0;accepted_reads<=accepted_reads+1;rs<=R_CHECK;
                end
                R_CHECK:if(rd_ok)rs<=R_ADDR;else begin rejected_reads<=rejected_reads+1;rs<=R_BAD;end
                R_ADDR:if(m_arready)rs<=R_DATA;
                R_DATA,R_BAD:if(s_rvalid[rd_owner]&&s_rready[rd_owner])begin
                    if(rs==R_DATA&&wrong_read)fence_required<=1;
                    if(s_rlast[rd_owner])begin completed_reads<=completed_reads+1;rd_rr<=rd_owner+1;rs<=R_IDLE;end
                    else rd_beat<=rd_beat+1;
                end
            endcase
        end
    end
endmodule
