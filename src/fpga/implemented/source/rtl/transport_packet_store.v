`timescale 1ns/1ps
// One 1380-byte packet window; the saved RGB stream still feeds original H1/H2.
// Packed words retain the legacy synchronous high/low byte prefetch interface.
module transport_packet_store(
    input wire clk,reset,cancel,start,input wire [7:0] pixel_format,
    input wire [21:0] total_pixels,
    input wire in_valid,output wire in_ready,input wire [15:0] in_pixel,input wire in_eof,
    input wire analysis_complete,input wire [15:0] requested_packet_id,
    output wire ready,output reg [3:0] error,
    input wire read_en,input wire [15:0] read_addr,output reg [15:0] read_data,
    output reg [63:0] payload_crc64,output reg [31:0] payload_bytes,
    output reg encoding_complete
);
    (* ram_style="block" *) reg [15:0] words[0:689];
    reg active,full,last_packet;
    reg [7:0] format,high_byte;
    reg [10:0] count;
    reg [15:0] packet_id;
    reg [21:0] pixels,total;
    reg [31:0] expected_bytes;
    reg rgb_pending,rgb_low,rgb_eof;
    reg [15:0] rgb_pixel;
    wire gray_in_ready,gray_valid,gray_eof,gray_done;
    wire [1:0] gray_error;
    wire [7:0] gray_byte;
    wire sink_ready=active && !full && !reset && !cancel && !start && error==0;
    wire data_valid=(format==8'h31 || format==8'h32) ? gray_valid : rgb_pending;
    wire [7:0] data_byte=(format==8'h31 || format==8'h32) ? gray_byte : (rgb_low ? rgb_pixel[7:0] : rgb_pixel[15:8]);
    wire data_eof=(format==8'h31 || format==8'h32) ? gray_eof : (rgb_pending && rgb_low && rgb_eof);
    assign in_ready=active && !reset && !cancel && !start && error==0 &&
        ((format==8'h31 || format==8'h32) ? gray_in_ready : (!rgb_pending && !full));
    assign ready=active && full && packet_id==requested_packet_id &&
        (!last_packet || (analysis_complete && encoding_complete)) && !reset && !cancel && !start && error==0;
    dual_view_encoder encoder(
        .clk(clk),.reset(reset),.cancel(cancel),.start(start && (pixel_format==8'h31 || pixel_format==8'h32)),.dual_view(pixel_format==8'h32),.total_pixels(total_pixels),
        .in_valid(in_valid && active && (format==8'h31 || format==8'h32) && error==0),.in_ready(gray_in_ready),
        .in_pixel(in_pixel),.in_eof(in_eof),.out_valid(gray_valid),.out_ready(sink_ready && (format==8'h31 || format==8'h32)),
        .out_byte(gray_byte),.out_eof(gray_eof),.done(gray_done),.error(gray_error));
    function [63:0] crc_byte;
        input [63:0] seed;input [7:0] value;
        reg [63:0] c;integer b;
        begin
            c=seed^{value,56'd0};
            for(b=0;b<8;b=b+1)c=c[63] ? (c<<1)^64'h42f0e1eba9ea3693 : c<<1;
            crc_byte=c;
        end
    endfunction
    always @(posedge clk)begin
        if(reset || cancel)begin
            active<=0;full<=0;last_packet<=0;format<=1;high_byte<=0;count<=0;packet_id<=0;
            pixels<=0;total<=0;expected_bytes<=0;rgb_pending<=0;rgb_low<=0;rgb_eof<=0;rgb_pixel<=0;
            read_data<=0;payload_crc64<=0;payload_bytes<=0;encoding_complete<=0;error<=0;
        end else if(start)begin
            // A second start is an error, rather than a partial frame restart.
            if(active)begin active<=0;full<=0;error<=6;encoding_complete<=0;end
            else begin
                active<=(pixel_format==1 || pixel_format==8'h31 || pixel_format==8'h32) && total_pixels>0 && total_pixels<=22'd2073600;
                error<=((pixel_format!=1 && pixel_format!=8'h31 && pixel_format!=8'h32) || total_pixels==0 || total_pixels>22'd2073600)?6:0;
                format<=pixel_format;total<=total_pixels;pixels<=0;full<=0;last_packet<=0;count<=0;packet_id<=0;
                expected_bytes<=pixel_format==8'h32 ? ({10'd0,total_pixels}*3)+(({10'd0,total_pixels}+7)>>3) : pixel_format==8'h31 ? {10'd0,total_pixels}+(({10'd0,total_pixels}+7)>>3) : {9'd0,total_pixels,1'b0};
                payload_crc64<=0;payload_bytes<=0;encoding_complete<=0;rgb_pending<=0;rgb_low<=0;read_data<=0;
            end
        end else if(active)begin
            if(in_valid && in_ready)begin
                if(pixels>=total || in_eof!=(pixels==total-1))begin error<=6;active<=0;end
                else begin
                    pixels<=pixels+1;
                    if(format==1)begin rgb_pixel<=in_pixel;rgb_eof<=in_eof;rgb_pending<=1;rgb_low<=0;end
                end
            end
            if(data_valid && sink_ready)begin
                if(payload_bytes>=expected_bytes || data_eof!=(payload_bytes==expected_bytes-1))begin error<=6;active<=0;end
                else begin
                    if(!count[0])high_byte<=data_byte;
                    if(count[0] || data_eof)words[count[10:1]]<=count[0] ? {high_byte,data_byte} : {data_byte,8'd0};
                    count<=count+1;payload_bytes<=payload_bytes+1;payload_crc64<=crc_byte(payload_crc64,data_byte);
                    if(count==1379 || data_eof)begin full<=1;last_packet<=data_eof;end
                    if(data_eof)encoding_complete<=1;
                    if(format==1)begin
                        if(rgb_low)begin rgb_pending<=0;rgb_low<=0;end else rgb_low<=1;
                    end
                end
            end
            if(requested_packet_id!=packet_id)begin
                if(full && !last_packet && requested_packet_id==packet_id+1)begin packet_id<=requested_packet_id;count<=0;full<=0;end
                else begin error<=6;active<=0;end
            end
            if(read_en && ready)begin
                if(read_addr<((count+1)>>1))read_data<=words[read_addr];
                // One unused word beyond a packet is prefetched by legacy TX.
                else if(read_addr>((count+1)>>1))begin error<=6;active<=0;end
            end
            if((format==8'h31 || format==8'h32) && gray_error!=0)begin error<=6;active<=0;encoding_complete<=0;end
        end
    end
endmodule
