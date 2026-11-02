// Existing wire-v1 application's 690-pixel packet window. One FIFO pass only.
// Earlier packets are provisional; final packet is held until stats/full drain.
module saved_packet_store #(parameter integer PIXELS_PER_PACKET=690)(
    input wire clk,reset,cancel,start,
    input wire in_valid,output wire in_ready,input wire [15:0] in_pixel,input wire in_eof,
    input wire analysis_complete,
    input wire [15:0] requested_packet_id,
    output wire ready,output reg [3:0] error,
    input wire read_en,input wire [15:0] read_addr,output reg [15:0] read_data
);
    (* ram_style="block" *) reg [15:0] pixels[0:PIXELS_PER_PACKET-1];
    reg full,last_packet,active;
    reg [10:0] count;
    reg [15:0] packet_id;
    assign in_ready=active && !full && !cancel && !reset;
    assign ready=active && full && packet_id==requested_packet_id && (!last_packet || analysis_complete) && !cancel && !reset;
    always @(posedge clk)begin
        if(reset || cancel)begin full<=0;last_packet<=0;active<=0;count<=0;packet_id<=0;error<=0;read_data<=0;end
        else if(start)begin full<=0;last_packet<=0;active<=1;count<=0;packet_id<=0;error<=0;end
        else begin
            if(in_valid && in_ready)begin
                pixels[count]<=in_pixel;count<=count+1;
                if(count==PIXELS_PER_PACKET-1 || in_eof)begin full<=1;last_packet<=in_eof;end
            end
            if(full && requested_packet_id!=packet_id)begin
                if(!last_packet && requested_packet_id==packet_id+1)begin packet_id<=requested_packet_id;count<=0;full<=0;end
                else begin error<=6;active<=0;end
            end
            if(read_en && ready)begin
                if(read_addr<count)read_data<=pixels[read_addr];
                // Legacy application prefetches exactly one word past the end
                // while emitting the final word's high byte. It consumes no data.
                else if(read_addr>count)begin error<=6;active<=0;end
            end
        end
    end
endmodule
