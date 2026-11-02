`timescale 1ns / 1ps

// OV5640 8-bit DVP receiver for 1920x1080 RGB565.
// Register 0x4300 is configured to 0x61, therefore each pixel arrives as:
//   byte 0 = {R[4:0], G[5:3]}, byte 1 = {G[2:0], B[4:0]}.
// VSYNC marks the boundary between frames.  HREF is the only qualification
// used for image bytes, which avoids relying on the length of the VSYNC pulse.
module ov5640_capture_1080p #(
    parameter integer FRAME_PIXELS = 1920*1080,
    parameter integer WARMUP_FRAMES = 4
) (
    input  wire        cam_pclk,
    input  wire        reset_n,
    input  wire        capture_enable,
    input  wire        cam_vsync,
    input  wire        cam_href,
    input  wire [7:0]  cam_data,

    input  wire        wrfifo_full,
    input  wire        wr_done_toggle,
    input  wire        display_ack_toggle,
    output wire        wrfifo_clr,
    output reg         wrfifo_wren,
    output reg  [15:0] wrfifo_din,
    output reg         wr_frame_bank,

    output reg         published_bank,
    output reg         publish_toggle,
    output reg         frame_published,
    output reg         capture_error
);
    reg [2:0] enable_sync;
    reg [2:0] done_sync;
    reg [2:0] ack_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] reset_sync;
    reg       vsync_d;

    reg [4:0] clear_count;
    reg [7:0] first_byte;
    reg       byte_phase;
    reg [21:0] pixel_count;
    reg [3:0] warmup_count;
    reg       capture_active;
    reg       capture_bad;
    reg       input_frame_complete;
    reg       waiting_ack;
    reg       expected_done_toggle;
    reg       write_bank;

    wire ready = enable_sync[2];
    wire cam_reset_n = reset_sync[1];
    wire frame_boundary = cam_vsync && !vsync_d;
    assign wrfifo_clr = (clear_count != 0);

    // Assert immediately, release on cam_pclk.  The data-path registers then
    // use a synchronous reset, so wrfifo_wren does not asynchronously control
    // the block-RAM write-enable inside the asynchronous FIFO.
    always @(posedge cam_pclk or negedge reset_n) begin
        if (!reset_n)
            reset_sync <= 2'b00;
        else
            reset_sync <= {reset_sync[0], 1'b1};
    end

    always @(posedge cam_pclk) begin
        if (!cam_reset_n) begin
            enable_sync <= 3'b000;
            done_sync   <= 3'b000;
            ack_sync    <= 3'b000;
        end else begin
            enable_sync <= {enable_sync[1:0], capture_enable};
            done_sync   <= {done_sync[1:0], wr_done_toggle};
            ack_sync    <= {ack_sync[1:0], display_ack_toggle};
        end
    end

    always @(posedge cam_pclk) begin
        if (!cam_reset_n) begin
            vsync_d               <= 1'b0;
            clear_count           <= 5'd0;
            first_byte            <= 8'd0;
            byte_phase            <= 1'b0;
            pixel_count           <= 22'd0;
            warmup_count          <= 4'd0;
            capture_active        <= 1'b0;
            capture_bad           <= 1'b0;
            input_frame_complete  <= 1'b0;
            waiting_ack           <= 1'b0;
            expected_done_toggle  <= 1'b0;
            write_bank            <= 1'b0;
            wr_frame_bank         <= 1'b0;
            wrfifo_wren           <= 1'b0;
            wrfifo_din            <= 16'd0;
            published_bank        <= 1'b0;
            publish_toggle        <= 1'b0;
            frame_published       <= 1'b0;
            capture_error         <= 1'b0;
        end else begin
            vsync_d     <= cam_vsync;
            wrfifo_wren <= 1'b0;

            if (clear_count != 0)
                clear_count <= clear_count - 1'b1;

            if (!ready) begin
                clear_count          <= 5'd0;
                byte_phase           <= 1'b0;
                pixel_count          <= 22'd0;
                warmup_count         <= 4'd0;
                capture_active       <= 1'b0;
                capture_bad          <= 1'b0;
                input_frame_complete <= 1'b0;
                waiting_ack          <= 1'b0;
                write_bank           <= 1'b0;
                wr_frame_bank        <= 1'b0;
                published_bank       <= 1'b0;
                publish_toggle       <= 1'b0;
                frame_published      <= 1'b0;
                capture_error        <= 1'b0;
            end else begin
                // Publish only when every pixel was received and MIG has
                // acknowledged every burst.  This prevents partially written
                // frames from ever being shown.
                if (input_frame_complete && (done_sync[2] != expected_done_toggle)) begin
                    input_frame_complete <= 1'b0;
                    published_bank       <= write_bank;
                    publish_toggle       <= ~publish_toggle;
                    waiting_ack          <= 1'b1;
                    frame_published      <= 1'b1;
                end

                if (waiting_ack && (ack_sync[2] == publish_toggle)) begin
                    waiting_ack <= 1'b0;
                    write_bank  <= ~write_bank;
                end

                if (frame_boundary) begin
                    byte_phase <= 1'b0;

                    // The rising VSYNC edge closes the previous frame.
                    if (capture_active) begin
                        capture_active <= 1'b0;
                        if (!capture_bad && (pixel_count == FRAME_PIXELS)) begin
                            input_frame_complete <= 1'b1;
                        end else begin
                            input_frame_complete <= 1'b0;
                            capture_error <= 1'b1;
                        end
                    end

                    if (warmup_count < WARMUP_FRAMES) begin
                        warmup_count <= warmup_count + 1'b1;
                    end else if (!capture_active && !input_frame_complete && !waiting_ack) begin
                        // Reset both the async write FIFO and its DDR address
                        // pointer while VSYNC is active, before the first HREF.
                        clear_count          <= 5'd16;
                        pixel_count          <= 22'd0;
                        capture_bad          <= 1'b0;
                        capture_active       <= 1'b1;
                        expected_done_toggle <= done_sync[2];
                        wr_frame_bank        <= write_bank;
                    end
                end

                if (!cam_href) begin
                    byte_phase <= 1'b0;
                end else if (capture_active && (clear_count == 0)) begin
                    if (!byte_phase) begin
                        first_byte <= cam_data;
                        byte_phase <= 1'b1;
                    end else begin
                        byte_phase <= 1'b0;
                        if (pixel_count < FRAME_PIXELS) begin
                            if (!wrfifo_full) begin
                                wrfifo_din  <= {first_byte, cam_data};
                                wrfifo_wren <= 1'b1;
                                pixel_count <= pixel_count + 1'b1;
                            end else begin
                                capture_bad   <= 1'b1;
                                capture_error <= 1'b1;
                            end
                        end
                    end
                end
            end
        end
    end
endmodule
