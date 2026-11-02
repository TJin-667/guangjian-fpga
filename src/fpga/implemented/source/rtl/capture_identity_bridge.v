// Coherent reset is shared with camera/DDR/control. Requests and cancellation
// carry immutable contexts; stale cancellation cannot poison the next request.
module capture_identity_bridge #(
    parameter integer FRAME_PIXELS=2073600,WRITE_TIMEOUT=250000000
)(
    input wire net_clk,cam_clk,net_reset,cam_reset,capture_enable,
    input wire capture,output wire capture_ready,input wire [399:0] capture_context,
    input wire cancel_request,input wire [255:0] cancel_identity,
    input wire cam_vsync,cam_href,input wire [7:0] cam_data,
    input wire wrfifo_full,wr_done_toggle,
    output wire wrfifo_clr,wrfifo_wren,wr_frame_bank,output wire [15:0] wrfifo_din,
    output wire pub_valid,input wire pub_ready,output wire [415:0] pub_data,
    output wire fatal_net,
    output wire event_start,event_end,event_drop,event_write_done,event_publish,
    output wire [255:0] event_identity,output wire [3:0] camera_state
);
    wire req_ready,req_valid,req_take;
    wire [399:0] req_data;
    wire cam_pub_valid,cam_pub_ready;wire [415:0] cam_pub_data;
    wire cancel_src_ready,cancel_dst_valid;wire [255:0] cancel_dst_data;
    reg cancel_pending,cancel_sent;
    reg [255:0] cancel_held,last_cancel;
    reg cancel_known;
    (* ASYNC_REG="TRUE" *) reg [2:0] enable_sync,fatal_sync;
    wire camera_fatal;
    wire cam_cancel=cancel_known &&
        ((camera_state!=0 && last_cancel[255:128]==event_identity[255:128] && last_cancel[63:0]==event_identity[63:0]) ||
         (req_valid && last_cancel[255:128]==req_data[399:272] && last_cancel[63:0]==req_data[207:144]));
    assign capture_ready=req_ready && cancel_src_ready && !cancel_pending && !fatal_net;
    assign fatal_net=fatal_sync[2];
    cdc_snapshot_mailbox #(.WIDTH(400)) requests(
        .src_clk(net_clk),.src_reset(net_reset),.src_valid(capture && capture_ready),.src_ready(req_ready),.src_data(capture_context),
        .dst_clk(cam_clk),.dst_reset(cam_reset),.dst_valid(req_valid),.dst_ready(req_take),.dst_data(req_data));
    cdc_snapshot_mailbox #(.WIDTH(256)) cancellations(
        .src_clk(net_clk),.src_reset(net_reset),.src_valid(cancel_pending),.src_ready(cancel_src_ready),.src_data(cancel_held),
        .dst_clk(cam_clk),.dst_reset(cam_reset),.dst_valid(cancel_dst_valid),.dst_ready(1'b1),.dst_data(cancel_dst_data));
    cdc_snapshot_mailbox #(.WIDTH(416)) published(
        .src_clk(cam_clk),.src_reset(cam_reset),.src_valid(cam_pub_valid),.src_ready(cam_pub_ready),.src_data(cam_pub_data),
        .dst_clk(net_clk),.dst_reset(net_reset),.dst_valid(pub_valid),.dst_ready(pub_ready),.dst_data(pub_data));
    frame_identity_tracker #(.FRAME_PIXELS(FRAME_PIXELS),.WRITE_TIMEOUT(WRITE_TIMEOUT)) camera(
        .cam_clk(cam_clk),.reset(cam_reset),.capture_enable(enable_sync[2]),.cam_vsync(cam_vsync),.cam_href(cam_href),.cam_data(cam_data),
        .request_valid(req_valid),.request_ready(req_take),.request_data(req_data),.cancel_active(cam_cancel),
        .wrfifo_full(wrfifo_full),.wr_done_toggle(wr_done_toggle),
        .wrfifo_clr(wrfifo_clr),.wrfifo_wren(wrfifo_wren),.wrfifo_din(wrfifo_din),.wr_frame_bank(wr_frame_bank),
        .pub_valid(cam_pub_valid),.pub_ready(cam_pub_ready),.pub_data(cam_pub_data),.fatal(camera_fatal),.dvp_sequence(),.publish_sequence(),
        .event_start(event_start),.event_end(event_end),.event_drop(event_drop),.event_write_done(event_write_done),.event_publish(event_publish),
        .event_identity(event_identity),.debug_state(camera_state));
    always @(posedge net_clk)begin
        if(net_reset)begin cancel_pending<=0;cancel_sent<=0;cancel_held<=0;fatal_sync<=0;end
        else begin
            fatal_sync<={fatal_sync[1:0],camera_fatal};
            if(capture)cancel_sent<=0;
            if(cancel_request && !cancel_sent && !cancel_pending)begin cancel_held<=cancel_identity;cancel_pending<=1;cancel_sent<=1;end
            if(cancel_pending && cancel_src_ready)cancel_pending<=0;
        end
    end
    always @(posedge cam_clk)begin
        if(cam_reset)begin enable_sync<=0;last_cancel<=0;cancel_known<=0;end
        else begin
            enable_sync<={enable_sync[1:0],capture_enable};
            if(cancel_dst_valid)begin last_cancel<=cancel_dst_data;cancel_known<=1;end
        end
    end
endmodule
