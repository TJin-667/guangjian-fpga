// Connect the existing net-clock H2 stream to the UI-clock durable writer.
// Four acknowledged immutable mailboxes: descriptor, records, finish, result.
// A finish is sent only AFTER the record mailbox has been acknowledged empty,
// so separate synchronizer phases cannot let finish overtake the final pixel.
// Both clock domains require coherent async reset/fence. No independent reset
// of one mailbox endpoint is a supported cancellation operation.
module h2_offload_cdc_bridge(
    input wire net_clk,net_reset,input wire ui_clk,ui_reset,
    input wire cfg_valid,output wire cfg_ready,input wire [31:0] cfg_cookie,cfg_request,
    input wire [15:0] cfg_width,cfg_height,
    input wire tap_valid,output wire tap_ready,input wire [31:0] tap_request,
    input wire [15:0] tap_x,tap_y,input wire signed [15:0] tap_residual_n,
    input wire [7:0] tap_gray,input wire tap_observation_valid,tap_sof,tap_eol,tap_eof,
    input wire tap_finish_valid,input wire [31:0] tap_finish_request,input wire [3:0] tap_finish_error,
    output wire result_valid,input wire result_ready,output wire [31:0] result_cookie,result_request,result_written,
    output wire [3:0] result_error,output wire result_fence,output reg active,
    output reg scratch_valid_ui,output reg [31:0] scratch_cookie_ui,scratch_request_ui,
    output reg [15:0] scratch_width_ui,scratch_height_ui,
    output wire perf_writer_start,perf_writer_finish,perf_writer_success,perf_writer_write,perf_writer_response,perf_writer_blocked,
    output wire [31:0] perf_writer_cookie,
    output wire [3:0] m_axi_awid,output wire [29:0] m_axi_awaddr,output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,output wire [1:0] m_axi_awburst,output wire m_axi_awvalid,input wire m_axi_awready,
    output wire [127:0] m_axi_wdata,output wire [15:0] m_axi_wstrb,output wire m_axi_wlast,m_axi_wvalid,input wire m_axi_wready,
    input wire [3:0] m_axi_bid,input wire [1:0] m_axi_bresp,input wire m_axi_bvalid,output wire m_axi_bready
);
    wire nr,ur;
    reset_release_sync u_net_reset(.clk(net_clk),.async_reset(net_reset||ui_reset),.reset(nr));
    reset_release_sync u_ui_reset(.clk(ui_clk),.async_reset(net_reset||ui_reset),.reset(ur));
    wire cfg_src_ready,cfg_dst_valid,cfg_dst_ready;wire [95:0] cfg_dst_data;
    wire record_src_ready,record_dst_valid,record_dst_ready;wire [95:0] record_dst_data;
    wire finish_src_ready,finish_dst_valid,finish_dst_ready;wire [95:0] finish_dst_data;
    wire result_src_ready;wire [127:0] result_dst_data;
    reg finish_sent;reg [31:0] net_cookie;
    reg finish_pending;reg [31:0] pending_finish_request;reg [3:0] pending_finish_error;
    reg ui_active,ui_finish_seen;reg [31:0] ui_cookie;
    wire writer_cfg_ready,writer_in_ready,writer_finish_ready,writer_result_valid,writer_result_ready,writer_fence;
    wire [3:0] writer_error;wire [31:0] writer_request,writer_written;
    assign cfg_ready=!active&&cfg_src_ready&&record_src_ready&&finish_src_ready&&!tap_finish_valid&&!result_valid&&!nr;
    assign tap_ready=active ? record_src_ready : !nr;
    cdc_snapshot_mailbox_offload #(.WIDTH(96)) u_cfg(
        .src_clk(net_clk),.src_reset(nr),.src_valid(cfg_valid&&cfg_ready),.src_ready(cfg_src_ready),
        .src_data({cfg_cookie,cfg_request,cfg_width,cfg_height}),
        .dst_clk(ui_clk),.dst_reset(ur),.dst_valid(cfg_dst_valid),.dst_ready(cfg_dst_ready),.dst_data(cfg_dst_data));
    cdc_snapshot_mailbox_offload #(.WIDTH(96)) u_records(
        .src_clk(net_clk),.src_reset(nr),.src_valid(tap_valid&&active),.src_ready(record_src_ready),
        .src_data({tap_request,tap_x,tap_y,tap_residual_n,tap_gray,4'd0,tap_sof,tap_eol,tap_eof,tap_observation_valid}),
        .dst_clk(ui_clk),.dst_reset(ur),.dst_valid(record_dst_valid),.dst_ready(record_dst_ready),.dst_data(record_dst_data));
    cdc_snapshot_mailbox_offload #(.WIDTH(96)) u_finish(
        .src_clk(net_clk),.src_reset(nr),
        .src_valid(active&&finish_pending&&!finish_sent&&record_src_ready&&!tap_valid),.src_ready(finish_src_ready),
        .src_data({pending_finish_request,net_cookie,pending_finish_error,28'd0}),
        .dst_clk(ui_clk),.dst_reset(ur),.dst_valid(finish_dst_valid),.dst_ready(finish_dst_ready),.dst_data(finish_dst_data));
    wire ui_can_publish=ui_finish_seen || writer_error==1;
    cdc_snapshot_mailbox_offload #(.WIDTH(128)) u_result(
        .src_clk(ui_clk),.src_reset(ur),.src_valid(writer_result_valid&&ui_active&&ui_can_publish&&!record_dst_valid),.src_ready(result_src_ready),
        .src_data({ui_cookie,writer_request,writer_written,27'd0,writer_fence,writer_error}),
        .dst_clk(net_clk),.dst_reset(nr),.dst_valid(result_valid),.dst_ready(result_ready),.dst_data(result_dst_data));
    assign result_cookie=result_dst_data[127:96];assign result_request=result_dst_data[95:64];assign result_written=result_dst_data[63:32];
    assign result_error=result_dst_data[3:0];assign result_fence=result_dst_data[4];
    assign cfg_dst_ready=writer_cfg_ready&&!ui_active;
    // On writer failure continue draining every already-issued producer record,
    // until the producer finish barrier arrives. Never reuse a stale mailbox.
    assign record_dst_ready=ui_active&&(writer_result_valid||writer_in_ready);
    assign finish_dst_ready=ui_active&&!record_dst_valid&&(writer_result_valid||writer_finish_ready);
    assign writer_result_ready=result_src_ready&&ui_active&&ui_can_publish&&!record_dst_valid;
    assign perf_writer_start=cfg_dst_valid&&cfg_dst_ready;
    assign perf_writer_finish=writer_result_valid;
    assign perf_writer_success=writer_error==0&&!writer_fence;
    assign perf_writer_write=m_axi_wvalid&&m_axi_wready;
    assign perf_writer_response=m_axi_bvalid&&m_axi_bready;
    assign perf_writer_blocked=(m_axi_awvalid&&!m_axi_awready)||(m_axi_wvalid&&!m_axi_wready);
    assign perf_writer_cookie=cfg_dst_data[95:64];
    wire [3:0] upstream_error=finish_dst_data[63:32]!=ui_cookie ? 4'd7 : finish_dst_data[31:28];
    h2_scratch_writer writer(.clk(ui_clk),.reset(ur),.abort_frame(1'b0),
        .cfg_valid(cfg_dst_valid&&!ui_active),.cfg_ready(writer_cfg_ready),.cfg_width(cfg_dst_data[31:16]),.cfg_height(cfg_dst_data[15:0]),
        .cfg_request(cfg_dst_data[63:32]),.cfg_base(30'h01800000),
        .in_valid(record_dst_valid&&ui_active&&!writer_result_valid),.in_ready(writer_in_ready),
        .in_request(record_dst_data[95:64]),.in_x(record_dst_data[63:48]),.in_y(record_dst_data[47:32]),
        .in_residual_n(record_dst_data[31:16]),.in_gray(record_dst_data[15:8]),.in_observation_valid(record_dst_data[0]),
        .in_sof(record_dst_data[3]),.in_eol(record_dst_data[2]),.in_eof(record_dst_data[1]),
        .finish_valid(finish_dst_valid&&ui_active&&!record_dst_valid&&!writer_result_valid),.finish_ready(writer_finish_ready),
        .finish_request(finish_dst_data[95:64]),.finish_error(upstream_error[3] ? 3'd7 : upstream_error[2:0]),
        .result_valid(writer_result_valid),.result_ready(writer_result_ready),.result_error(writer_error),.result_request(writer_request),
        .written_pixels(writer_written),.fence_required(writer_fence),
        .m_axi_awid(m_axi_awid),.m_axi_awaddr(m_axi_awaddr),.m_axi_awlen(m_axi_awlen),.m_axi_awsize(m_axi_awsize),.m_axi_awburst(m_axi_awburst),.m_axi_awvalid(m_axi_awvalid),.m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata),.m_axi_wstrb(m_axi_wstrb),.m_axi_wlast(m_axi_wlast),.m_axi_wvalid(m_axi_wvalid),.m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),.m_axi_bresp(m_axi_bresp),.m_axi_bvalid(m_axi_bvalid),.m_axi_bready(m_axi_bready));
    always @(posedge net_clk)begin
        if(nr)begin active<=0;finish_sent<=0;net_cookie<=0;finish_pending<=0;pending_finish_request<=0;pending_finish_error<=0;end
        else begin
            if(cfg_valid&&cfg_ready)begin active<=1;finish_sent<=0;finish_pending<=0;net_cookie<=cfg_cookie;end
            if(active&&tap_finish_valid&&!finish_sent&&!finish_pending)begin finish_pending<=1;pending_finish_request<=tap_finish_request;pending_finish_error<=tap_finish_error;end
            if(active&&finish_pending&&!finish_sent&&record_src_ready&&!tap_valid&&finish_src_ready)finish_sent<=1;
            if(result_valid&&result_ready)active<=0;
        end
    end
    always @(posedge ui_clk)begin
        if(ur)begin ui_active<=0;ui_cookie<=0;ui_finish_seen<=0;scratch_valid_ui<=0;scratch_cookie_ui<=0;scratch_request_ui<=0;scratch_width_ui<=0;scratch_height_ui<=0;end
        else begin
            if(cfg_dst_valid&&cfg_dst_ready)begin
                ui_active<=1;ui_cookie<=cfg_dst_data[95:64];ui_finish_seen<=0;scratch_valid_ui<=0;
                scratch_cookie_ui<=cfg_dst_data[95:64];scratch_request_ui<=cfg_dst_data[63:32];scratch_width_ui<=cfg_dst_data[31:16];scratch_height_ui<=cfg_dst_data[15:0];
            end
            if(finish_dst_valid&&finish_dst_ready)ui_finish_seen<=1;
            if(writer_result_valid&&writer_result_ready)begin ui_active<=0;scratch_valid_ui<=writer_error==0&&!writer_fence&&ui_finish_seen;end
        end
    end
endmodule
