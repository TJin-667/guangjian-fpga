`timescale 1ns/1ps
// Held full DDR frame -> rectangular selection -> original-pixel UDP packets.
// Last packet waits for complete source-frame drainage before releasing its bank.
module ddr_roi_packet_source #(
    parameter integer WIDTH=1920,HEIGHT=1080,PIXELS_PER_PACKET=690,
    parameter integer WAIT_TIMEOUT=250000000,FILL_TIMEOUT=125000000
)(
    input wire clk,reset,capture,release_frame,crop_enable,
    input wire [15:0] crop_x,crop_y,crop_width,crop_height,crop_packets,
    input wire [10:0] crop_last_pixels,
    input wire [15:0] requested_packet_id,
    input wire published_toggle,published_bank,
    output reg display_ack_toggle,rd_frame_bank,
    output wire rdfifo_clr,rdfifo_rden,
    input wire rdfifo_empty,
    input wire [15:0] rdfifo_dout,
    output wire busy,ready,
    output reg failed,
    output reg [2:0] fail_code,
    input wire read_en,
    input wire [15:0] read_addr,
    output reg [15:0] read_data
);
    localparam integer FRAME_PIXELS=WIDTH*HEIGHT;
    localparam integer PACKETS=(FRAME_PIXELS+PIXELS_PER_PACKET-1)/PIXELS_PER_PACKET;
    localparam integer LAST_PIXELS=FRAME_PIXELS-(PACKETS-1)*PIXELS_PER_PACKET;
    localparam [2:0] IDLE=0,WAIT_PUBLISH=1,CLEAR_FIFO=2,FILL=3,READY=4,FAIL=5,DRAIN=6;
    reg [2:0] state;
    (* ASYNC_REG="TRUE" *) reg [2:0] publish_sync,bank_sync;
    reg consumed_publish,active_publish;
    reg [15:0] loaded_packet_id,active_packets;
    reg [10:0] issued,written,last_pixels;
    reg [15:0] left,right,top,bottom,scan_x,scan_y;
    reg [31:0] scan_issued;
    reg [4:0] clear_count;
    reg [31:0] timer;
    reg read_issued_q,selected_q;
    (* ram_style="block" *) reg [15:0] packet_pixels[0:PIXELS_PER_PACKET-1];
    wire [10:0] needed=(loaded_packet_id==active_packets-1)?last_pixels:PIXELS_PER_PACKET;
    wire selected=scan_x>=left && scan_x<right && scan_y>=top && scan_y<bottom;
    assign busy=state!=IDLE;
    assign ready=state==READY && loaded_packet_id==requested_packet_id;
    assign rdfifo_clr=state==CLEAR_FIFO;
    assign rdfifo_rden=((state==FILL && issued<needed) || state==DRAIN) && scan_issued<FRAME_PIXELS && !rdfifo_empty;
    always @(posedge clk)begin
        if(reset)begin
            publish_sync<=0;bank_sync<=0;state<=IDLE;
            consumed_publish<=0;active_publish<=0;display_ack_toggle<=0;rd_frame_bank<=0;
            loaded_packet_id<=0;active_packets<=PACKETS;last_pixels<=LAST_PIXELS;
            issued<=0;written<=0;left<=0;right<=WIDTH;top<=0;bottom<=HEIGHT;
            scan_x<=0;scan_y<=0;scan_issued<=0;clear_count<=0;timer<=0;
            read_issued_q<=0;selected_q<=0;failed<=0;fail_code<=0;
        end else begin
            publish_sync<={publish_sync[1:0],published_toggle};bank_sync<={bank_sync[1:0],published_bank};
            read_issued_q<=rdfifo_rden;selected_q<=rdfifo_rden && selected;
            if(rdfifo_rden)begin
                scan_issued<=scan_issued+1'b1;
                if(scan_x==WIDTH-1)begin scan_x<=0;scan_y<=scan_y+1'b1;end
                else scan_x<=scan_x+1'b1;
            end
            if(release_frame && state!=IDLE)begin
                display_ack_toggle<=active_publish;consumed_publish<=active_publish;
                state<=IDLE;read_issued_q<=0;selected_q<=0;
            end else case(state)
                IDLE:if(capture)begin
                    failed<=0;fail_code<=0;timer<=0;state<=WAIT_PUBLISH;
                    if(crop_enable)begin
                        left<=crop_x;right<=crop_x+crop_width;top<=crop_y;bottom<=crop_y+crop_height;
                        active_packets<=crop_packets;last_pixels<=crop_last_pixels;
                        if(crop_width==0 || crop_height==0 || crop_packets==0 || crop_last_pixels==0 ||
                           crop_last_pixels>PIXELS_PER_PACKET ||
                           {1'b0,crop_x}+{1'b0,crop_width}>WIDTH ||
                           {1'b0,crop_y}+{1'b0,crop_height}>HEIGHT)begin failed<=1;fail_code<=4;state<=FAIL;end
                    end else begin left<=0;right<=WIDTH;top<=0;bottom<=HEIGHT;active_packets<=PACKETS;last_pixels<=LAST_PIXELS;end
                end
                WAIT_PUBLISH:begin
                    timer<=timer+1'b1;
                    if(publish_sync[2]!=consumed_publish)begin
                        active_publish<=publish_sync[2];rd_frame_bank<=bank_sync[2];clear_count<=0;timer<=0;state<=CLEAR_FIFO;
                    end else if(timer==WAIT_TIMEOUT-1)begin failed<=1;fail_code<=1;state<=FAIL;end
                end
                CLEAR_FIFO:begin
                    clear_count<=clear_count+1'b1;
                    if(clear_count==5'd15)begin
                        loaded_packet_id<=0;issued<=0;written<=0;scan_x<=0;scan_y<=0;scan_issued<=0;
                        read_issued_q<=0;selected_q<=0;timer<=0;state<=FILL;
                    end
                end
                FILL:begin
                    timer<=timer+1'b1;
                    if(rdfifo_rden && selected)issued<=issued+1'b1;
                    if(read_issued_q && selected_q)begin packet_pixels[written]<=rdfifo_dout;written<=written+1'b1;end
                    if(written==needed)begin
                        if(loaded_packet_id==active_packets-1)begin state<=DRAIN;timer<=0;end else state<=READY;
                    end else if(timer==FILL_TIMEOUT-1)begin failed<=1;fail_code<=2;state<=FAIL;end
                end
                DRAIN:begin
                    timer<=timer+1'b1;
                    if(scan_issued==FRAME_PIXELS && !read_issued_q)state<=READY;
                    else if(timer==FILL_TIMEOUT-1)begin failed<=1;fail_code<=2;state<=FAIL;end
                end
                READY:if(requested_packet_id!=loaded_packet_id)begin
                    if(requested_packet_id==loaded_packet_id+1'b1 && requested_packet_id<active_packets)begin
                        loaded_packet_id<=requested_packet_id;issued<=0;written<=0;timer<=0;state<=FILL;
                    end else begin failed<=1;fail_code<=3;state<=FAIL;end
                end
                FAIL:begin end
                default:begin failed<=1;fail_code<=4;state<=FAIL;end
            endcase
        end
    end
    always @(posedge clk)
        if(read_en && ready && read_addr<PIXELS_PER_PACKET)read_data<=packet_pixels[read_addr];
endmodule
