`timescale 1ns/1ps
// Read one published 1080p RGB565 frame from the proven DDR3 frame buffer.
// A 690-pixel BRAM stages each UDP payload before the non-stallable GMII TX.
// The producer holds the published DDR bank until release_frame acknowledges it.
module ddr_packet_source #(
    parameter integer WIDTH=1920,
    parameter integer HEIGHT=1080,
    parameter integer PIXELS_PER_PACKET=690,
    parameter integer WAIT_TIMEOUT=250000000,
    parameter integer FILL_TIMEOUT=125000000
)(
    input wire clk, reset,
    input wire capture, release_frame,
    input wire [15:0] requested_packet_id,
    input wire published_toggle, published_bank,
    output reg display_ack_toggle,
    output reg rd_frame_bank,
    output wire rdfifo_clr, rdfifo_rden,
    input wire rdfifo_empty,
    input wire [15:0] rdfifo_dout,
    output wire busy, ready,
    output reg failed,
    output reg [2:0] fail_code,
    input wire read_en,
    input wire [15:0] read_addr,
    output reg [15:0] read_data
);
    localparam integer FRAME_PIXELS=WIDTH*HEIGHT;
    localparam integer PACKETS=(FRAME_PIXELS+PIXELS_PER_PACKET-1)/PIXELS_PER_PACKET;
    localparam integer LAST_PIXELS=FRAME_PIXELS-(PACKETS-1)*PIXELS_PER_PACKET;
    localparam [2:0] IDLE=0,WAIT_PUBLISH=1,CLEAR_FIFO=2,FILL=3,READY=4,FAIL=5;
    reg [2:0] state;
    (* ASYNC_REG="TRUE" *) reg [2:0] publish_sync,bank_sync;
    reg consumed_publish,active_publish;
    reg [15:0] loaded_packet_id;
    reg [10:0] issued,written;
    reg [4:0] clear_count;
    reg [31:0] timer;
    reg read_issued_q;
    (* ram_style="block" *) reg [15:0] packet_pixels [0:PIXELS_PER_PACKET-1];
    wire [10:0] needed=(requested_packet_id==PACKETS-1)?LAST_PIXELS:PIXELS_PER_PACKET;
    assign busy=state!=IDLE;
    // Mask old packet availability as soon as the core advances its packet id.
    assign ready=state==READY && loaded_packet_id==requested_packet_id;
    assign rdfifo_clr=state==CLEAR_FIFO;
    assign rdfifo_rden=state==FILL && issued<needed && !rdfifo_empty;

    always @(posedge clk) begin
        if(reset)begin
            publish_sync<=0;bank_sync<=0;
            state<=IDLE;consumed_publish<=0;active_publish<=0;
            display_ack_toggle<=0;rd_frame_bank<=0;
            loaded_packet_id<=0;issued<=0;written<=0;
            clear_count<=0;timer<=0;read_issued_q<=0;failed<=0;fail_code<=0;
        end else begin
            publish_sync<={publish_sync[1:0],published_toggle};
            bank_sync<={bank_sync[1:0],published_bank};
            read_issued_q<=rdfifo_rden;
            if(release_frame && state!=IDLE)begin
                display_ack_toggle<=active_publish;
                consumed_publish<=active_publish;
                state<=IDLE;
                read_issued_q<=0;
            end else case(state)
                IDLE:if(capture)begin
                    failed<=0;fail_code<=0;timer<=0;state<=WAIT_PUBLISH;
                end
                WAIT_PUBLISH:begin
                    timer<=timer+1'b1;
                    if(publish_sync[2]!=consumed_publish)begin
                        active_publish<=publish_sync[2];
                        rd_frame_bank<=bank_sync[2];
                        clear_count<=0;timer<=0;state<=CLEAR_FIFO;
                    end else if(timer==WAIT_TIMEOUT-1)begin failed<=1;fail_code<=1;state<=FAIL;end
                end
                CLEAR_FIFO:begin
                    clear_count<=clear_count+1'b1;
                    if(clear_count==5'd15)begin
                        loaded_packet_id<=0;issued<=0;written<=0;
                        timer<=0;state<=FILL;
                    end
                end
                FILL:begin
                    timer<=timer+1'b1;
                    if(rdfifo_rden)issued<=issued+1'b1;
                    if(read_issued_q)begin
                        packet_pixels[written]<=rdfifo_dout;
                        written<=written+1'b1;
                    end
                    if(written==needed)state<=READY;
                    else if(timer==FILL_TIMEOUT-1)begin failed<=1;fail_code<=2;state<=FAIL;end
                end
                READY:if(requested_packet_id!=loaded_packet_id)begin
                    if(requested_packet_id==loaded_packet_id+1'b1 && requested_packet_id<PACKETS)begin
                        loaded_packet_id<=requested_packet_id;
                        issued<=0;written<=0;timer<=0;state<=FILL;
                    end else begin failed<=1;fail_code<=3;state<=FAIL;end
                end
                FAIL:begin end
                default:begin failed<=1;fail_code<=4;state<=FAIL;end
            endcase
        end
    end
    // Match the old camera snapshot's one-cycle synchronous BRAM read contract.
    always @(posedge clk)
        if(read_en && ready && read_addr<PIXELS_PER_PACKET)
            read_data<=packet_pixels[read_addr];
endmodule
