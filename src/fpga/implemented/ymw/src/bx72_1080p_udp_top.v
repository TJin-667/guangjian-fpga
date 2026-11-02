`timescale 1ns/1ps
// Experimental full-resolution single-frame transport, no HDMI output.
// OV5640 DVP -> DDR3 completed frame -> one-packet BRAM -> paced UDP.
module bx72_1080p_udp_top(
    input wire reset_n,clk_50m,
    input wire rgmii_rx_clk_i,rgmii_rxdv,
    input wire [3:0] rgmii_rxd,
    output wire rgmii_tx_clk,rgmii_txen,
    output wire [3:0] rgmii_txd,
    output wire eth_rstn,eth_mdc,eth_mdio,
    output wire [1:0] led,
    input wire light_uart_rx,
    output wire light_uart_tx,
    output wire cam_xclk,
    inout wire cam_sda,
    inout wire cam_scl,
    input wire cam_pclk,cam_vsync,cam_href,
    input wire [7:0] cam_data,
    inout wire [31:0] ddr3_dq,
    inout wire [3:0] ddr3_dqs_n,ddr3_dqs_p,
    output wire [14:0] ddr3_addr,
    output wire [2:0] ddr3_ba,
    output wire ddr3_ras_n,ddr3_cas_n,ddr3_we_n,ddr3_reset_n,
    output wire [0:0] ddr3_ck_p,ddr3_ck_n,ddr3_cke,ddr3_cs_n,ddr3_odt,
    output wire [3:0] ddr3_dm
);
    localparam integer FRAME_PIXELS=1920*1080;
    localparam integer FRAME_BYTES=FRAME_PIXELS*2;
    localparam integer BANK1_BASE=32'h00400000;
    // Declare cross-section nets before their first use (Vivado SV elaboration).
    wire net_clk,net_locked;
    wire [7:0] rx_data_byte;

    // MIG and SCCB clocks from the proven HDMI/DDR project.
    wire clk50,clk200,sys_locked;
    sys_pll u_sys_pll(.clk_out1(clk50),.clk_out2(clk200),
        .resetn(reset_n),.locked(sys_locked),.clk_in1(clk_50m));
    wire cam_clkfb_raw,cam_clkfb,cam_clk24_raw,cam_clk24,cam_clk_locked;
    MMCME2_BASE #(.BANDWIDTH("OPTIMIZED"),.CLKFBOUT_MULT_F(24.0),
        .CLKIN1_PERIOD(20.0),.CLKOUT0_DIVIDE_F(50.0),
        .DIVCLK_DIVIDE(1),.STARTUP_WAIT("FALSE")) u_cam_mmcm(
        .CLKFBOUT(cam_clkfb_raw),.CLKFBOUTB(),.CLKOUT0(cam_clk24_raw),.CLKOUT0B(),
        .CLKOUT1(),.CLKOUT1B(),.CLKOUT2(),.CLKOUT2B(),.CLKOUT3(),.CLKOUT3B(),
        .CLKOUT4(),.CLKOUT5(),.CLKOUT6(),.LOCKED(cam_clk_locked),
        .CLKFBIN(cam_clkfb),.CLKIN1(clk_50m),.PWRDWN(1'b0),.RST(~reset_n));
    BUFG u_cam_fb_buf(.I(cam_clkfb_raw),.O(cam_clkfb));
    BUFG u_cam_out_buf(.I(cam_clk24_raw),.O(cam_clk24));
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE"),.INIT(1'b0),.SRTYPE("SYNC"))
    u_cam_xclk_oddr(.Q(cam_xclk),.C(cam_clk24),.CE(1'b1),
        .D1(1'b1),.D2(1'b0),.R(1'b0),.S(1'b0));
    wire camera_config_ok,camera_config_done,camera_ack_error;
    wire camera_sda_i,camera_scl_i,camera_sda_low,camera_scl_low;
    // Explicit pin buffers preserve open-drain drive and actual pin readback.
    IOBUF u_sccb_sda(.I(1'b0),.T(~camera_sda_low),.O(camera_sda_i),.IO(cam_sda));
    IOBUF u_sccb_scl(.I(1'b0),.T(~camera_scl_low),.O(camera_scl_i),.IO(cam_scl));
    wire control_bus_start,control_bus_read,control_bus_done;
    wire [15:0] control_bus_address;
    wire [7:0] control_bus_data,control_bus_read_data;
    wire [2:0] control_bus_error;
    wire manual_start,manual_set,manual_busy,manual_done,manual_locked;
    wire [15:0] manual_exposure,manual_generation;
    wire [9:0] manual_gain16;
    wire [2:0] manual_error;
    wire [111:0] manual_raw;
    wire manual_reset_n=reset_n && sys_locked && cam_clk_locked && net_locked;
    ov5640_sccb_config u_config(.clk_50m(clk50),
        .reset_n(manual_reset_n),
        .cam_sda_i(camera_sda_i),.cam_scl_i(camera_scl_i),
        .cam_sda_low(camera_sda_low),.cam_scl_low(camera_scl_low),.config_ok(camera_config_ok),
        .config_done(camera_config_done),.ack_error(camera_ack_error),
        .control_start(control_bus_start),.control_read(control_bus_read),
        .control_address(control_bus_address),.control_data(control_bus_data),
        .control_done(control_bus_done),.control_error(control_bus_error),.control_read_data(control_bus_read_data));
    ov5640_manual_bridge u_manual(.net_clk(net_clk),.camera_clk(clk50),.reset_n(manual_reset_n),
        .start(manual_start),.set_values(manual_set),.exposure_lines(manual_exposure),.gain16(manual_gain16),
        .busy(manual_busy),.done(manual_done),.locked(manual_locked),.error(manual_error),
        .generation(manual_generation),.raw(manual_raw),.config_ok(camera_config_ok),
        .bus_start(control_bus_start),.bus_read(control_bus_read),.bus_address(control_bus_address),
        .bus_data(control_bus_data),.bus_done(control_bus_done),.bus_error(control_bus_error),.bus_read_data(control_bus_read_data));

    // Reuse complete-frame DDR3 producer. It holds one published bank until
    // the UDP consumer explicitly acknowledges the frame after all packets.
    wire ddr3_init_done;
    wire wrfifo_clr,wrfifo_wren,wrfifo_full,wr_frame_bank,wr_done_toggle;
    wire [15:0] wrfifo_din,wrfifo_wr_count;
    wire rdfifo_clr,rdfifo_rden,rdfifo_empty,rd_frame_bank;
    wire [15:0] rdfifo_dout,rdfifo_rd_count;
    wire published_bank,publish_toggle,frame_published,capture_error;
    wire display_ack_toggle;
    ov5640_capture_1080p #(.FRAME_PIXELS(FRAME_PIXELS),.WARMUP_FRAMES(4))
    u_capture(.cam_pclk(cam_pclk),.reset_n(reset_n && sys_locked && cam_clk_locked),
        .capture_enable(camera_config_ok && ddr3_init_done),
        .cam_vsync(cam_vsync),.cam_href(cam_href),.cam_data(cam_data),
        .wrfifo_full(wrfifo_full),.wr_done_toggle(wr_done_toggle),
        .display_ack_toggle(display_ack_toggle),.wrfifo_clr(wrfifo_clr),
        .wrfifo_wren(wrfifo_wren),.wrfifo_din(wrfifo_din),
        .wr_frame_bank(wr_frame_bank),.published_bank(published_bank),
        .publish_toggle(publish_toggle),.frame_published(frame_published),
        .capture_error(capture_error));
    ddr3_ctrl_2port #(.FIFO_DW(16),.WR_BYTE_ADDR_BEGIN(0),
        .WR_BYTE_ADDR_END(FRAME_BYTES-1),.RD_BYTE_ADDR_BEGIN(0),
        .RD_BYTE_ADDR_END(FRAME_BYTES-1),.FRAME_BYTES(FRAME_BYTES),
        .BANK1_BASE(BANK1_BASE),.FIFO_ADDR_DEPTH(64)) u_ddr3(
        .ddr3_clk200m(clk200),.ddr3_rst_n(reset_n && sys_locked),
        .ddr3_init_done(ddr3_init_done),
        .wrfifo_clr(wrfifo_clr),.wrfifo_clk(cam_pclk),
        .wrfifo_wren(wrfifo_wren),.wrfifo_din(wrfifo_din),
        .wr_frame_bank(wr_frame_bank),.wr_done_toggle(wr_done_toggle),
        .wrfifo_full(wrfifo_full),.wrfifo_wr_cnt(wrfifo_wr_count),
        .rdfifo_clr(rdfifo_clr),.rdfifo_clk(net_clk),
        .rdfifo_rden(rdfifo_rden),.rd_frame_bank(rd_frame_bank),
        .rdfifo_dout(rdfifo_dout),.rdfifo_empty(rdfifo_empty),
        .rdfifo_rd_cnt(rdfifo_rd_count),
        .ddr3_dq(ddr3_dq),.ddr3_dqs_n(ddr3_dqs_n),.ddr3_dqs_p(ddr3_dqs_p),
        .ddr3_addr(ddr3_addr),.ddr3_ba(ddr3_ba),
        .ddr3_ras_n(ddr3_ras_n),.ddr3_cas_n(ddr3_cas_n),.ddr3_we_n(ddr3_we_n),
        .ddr3_reset_n(ddr3_reset_n),.ddr3_ck_p(ddr3_ck_p),.ddr3_ck_n(ddr3_ck_n),
        .ddr3_cke(ddr3_cke),.ddr3_cs_n(ddr3_cs_n),.ddr3_dm(ddr3_dm),
        .ddr3_odt(ddr3_odt));

    // Ethernet clock and proven UDP/RGMII path.
    wire net_clk_in,net_clk_raw,net_fb_raw,net_fb;
    IBUF u_net_ibuf(.I(rgmii_rx_clk_i),.O(net_clk_in));
    MMCME2_BASE #(.BANDWIDTH("OPTIMIZED"),.CLKFBOUT_MULT_F(8.0),
        .CLKIN1_PERIOD(8.0),.CLKOUT0_DIVIDE_F(8.0),
        .DIVCLK_DIVIDE(1),.STARTUP_WAIT("FALSE")) u_net_mmcm(
        .CLKFBOUT(net_fb_raw),.CLKFBOUTB(),.CLKOUT0(net_clk_raw),.CLKOUT0B(),
        .CLKOUT1(),.CLKOUT1B(),.CLKOUT2(),.CLKOUT2B(),.CLKOUT3(),.CLKOUT3B(),
        .CLKOUT4(),.CLKOUT5(),.CLKOUT6(),.LOCKED(net_locked),
        .CLKFBIN(net_fb),.CLKIN1(net_clk_in),.PWRDWN(1'b0),.RST(~reset_n));
    BUFG u_net_fb_buf(.I(net_fb_raw),.O(net_fb));
    BUFG u_net_out_buf(.I(net_clk_raw),.O(net_clk));
    reg [2:0] reset_pipe;
    always @(posedge net_clk or negedge reset_n)
        if(!reset_n)reset_pipe<=3'b111;
        else if(!net_locked)reset_pipe<=3'b111;
        else reset_pipe<={reset_pipe[1:0],1'b0};
    wire net_reset=reset_pipe[2];
    (* ASYNC_REG="TRUE" *) reg [2:0] config_net_sync;
    always @(posedge net_clk)
        if(net_reset)config_net_sync<=0;
        else config_net_sync<={config_net_sync[1:0],
                               camera_config_ok && ddr3_init_done};

    wire [7:0] rx_data,tx_data,gmii_txd;
    wire rx_clk,rx_dv,rx_er,rx_start,rx_valid,rx_done,rx_error;
    wire [47:0] peer_mac,tx_mac;
    wire [31:0] peer_ip,tx_ip;
    wire [15:0] peer_port,tx_port,tx_length;
    wire tx_start,tx_ready,tx_req,tx_done,frame_busy;
    wire gmii_tx_clk,gmii_txen;
    wire [31:0] commands,frames,dropped;
    wire source_capture,source_release,source_read_en,source_busy,source_ready;
    wire source_failed,source_crop;
    wire [15:0] source_roi_x,source_roi_y,source_roi_width,source_roi_height,source_roi_packets;
    wire [10:0] source_roi_last_pixels;
    wire [2:0] source_fail_code;
    wire [15:0] source_read_addr,source_pixel,source_packet_id;
    assign eth_rstn=1'b1;assign eth_mdc=1'b1;assign eth_mdio=1'b1;
    rgmii_to_gmii u_input(.reset(net_reset),.rgmii_rx_clk(net_clk),
        .rgmii_rxd(rgmii_rxd),.rgmii_rxdv(rgmii_rxdv),
        .gmii_rx_clk(rx_clk),.gmii_rxdv(rx_dv),.gmii_rxd(rx_data),.gmii_rxer(rx_er));
    lght_udp_rx u_rx(.clk(net_clk),.reset(net_reset),.gmii_dv(rx_dv),
        .gmii_er(rx_er),.gmii_data(rx_data),.start(rx_start),
        .valid(rx_valid),.done(rx_done),.error(rx_error),.data(rx_data_byte),
        .peer_mac(peer_mac),.peer_ip(peer_ip),.peer_port(peer_port));
    wire light_start,light_busy,light_done,light_error;
    wire [3:0] light_mask;
    wire [7:0] light_brightness;
    light_uart_manager u_light(.clk(net_clk),.reset(net_reset),
        .start(light_start),.mask(light_mask),.brightness(light_brightness),
        .uart_rx(light_uart_rx),.uart_tx(light_uart_tx),
        .busy(light_busy),.done(light_done),.error(light_error));
    lght_core_camera #(.CAM_WIDTH(1920),.CAM_HEIGHT(1080),
        .PACKET_GAP_CYCLES(12500)) u_core(
        .clk(net_clk),.reset(net_reset || !manual_reset_n),
        .light_busy(light_busy),.light_done(light_done),.light_error(light_error),
        .light_start(light_start),.light_mask(light_mask),.light_brightness(light_brightness),
        .rx_start(rx_start),.rx_valid(rx_valid),
        .rx_done(rx_done),.rx_error(rx_error),.rx_data(rx_data_byte),
        .rx_mac(peer_mac),.rx_ip(peer_ip),.rx_port(peer_port),
        .tx_ready(tx_ready),.tx_req(tx_req),.tx_done(tx_done),
        .camera_config_ok(config_net_sync[2]),.camera_busy(source_busy),
        .camera_ready(source_ready),.camera_failed(source_failed),
        .camera_fail_code(source_fail_code),
        .manual_busy(manual_busy),.manual_done(manual_done),.manual_locked(manual_locked),
        .manual_error(manual_error),.manual_raw(manual_raw),.manual_generation(manual_generation),
        .manual_start(manual_start),.manual_set(manual_set),.manual_exposure(manual_exposure),.manual_gain16(manual_gain16),
        .camera_pixel(source_pixel),.camera_capture(source_capture),
        .camera_release(source_release),.camera_packet_id(source_packet_id),
        .camera_crop_enable(source_crop),.camera_roi_x(source_roi_x),.camera_roi_y(source_roi_y),
        .camera_roi_width(source_roi_width),.camera_roi_height(source_roi_height),
        .camera_roi_packets(source_roi_packets),.camera_roi_last_pixels(source_roi_last_pixels),
        .camera_read_en(source_read_en),.camera_read_addr(source_read_addr),
        .tx_start(tx_start),.tx_length(tx_length),.tx_mac(tx_mac),
        .tx_ip(tx_ip),.tx_port(tx_port),.tx_data(tx_data),
        .frame_busy(frame_busy),.commands(commands),
        .frames_started(frames),.rx_dropped(dropped));
    ddr_roi_packet_source u_source(.clk(net_clk),.reset(net_reset),
        .capture(source_capture),.release_frame(source_release),
        .crop_enable(source_crop),.crop_x(source_roi_x),.crop_y(source_roi_y),
        .crop_width(source_roi_width),.crop_height(source_roi_height),
        .crop_packets(source_roi_packets),.crop_last_pixels(source_roi_last_pixels),
        .requested_packet_id(source_packet_id),
        .published_toggle(publish_toggle),.published_bank(published_bank),
        .display_ack_toggle(display_ack_toggle),.rd_frame_bank(rd_frame_bank),
        .rdfifo_clr(rdfifo_clr),.rdfifo_rden(rdfifo_rden),
        .rdfifo_empty(rdfifo_empty),.rdfifo_dout(rdfifo_dout),
        .busy(source_busy),.ready(source_ready),.failed(source_failed),
        .fail_code(source_fail_code),
        .read_en(source_read_en),.read_addr(source_read_addr),
        .read_data(source_pixel));
    lght_udp_tx u_tx(.clk125m(net_clk),.reset_p(net_reset),
        .tx_en_pulse(tx_start),.tx_done(tx_done),.tx_ready(tx_ready),
        .dst_mac(tx_mac),.src_mac(48'h000a3501fec0),
        .dst_ip(tx_ip),.src_ip(32'hc0a80002),
        .dst_port(tx_port),.src_port(16'd5000),.data_length(tx_length),
        .payload_req_o(tx_req),.payload_dat_i(tx_data),
        .gmii_tx_clk(gmii_tx_clk),.gmii_txen(gmii_txen),.gmii_txd(gmii_txd));
    gmii_to_rgmii u_output(.reset_n(!net_reset),.gmii_tx_clk(gmii_tx_clk),
        .gmii_txd(gmii_txd),.gmii_txen(gmii_txen),.gmii_txer(1'b0),
        .rgmii_tx_clk(rgmii_tx_clk),.rgmii_txd(rgmii_txd),
        .rgmii_txen(rgmii_txen));
    assign led={frame_busy,config_net_sync[2]};
endmodule
