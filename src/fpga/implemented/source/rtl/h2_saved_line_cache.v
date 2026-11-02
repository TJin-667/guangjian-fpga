// Nine synchronous RGB565 line banks. Tags are published only on complete rows.
// Supports h2_background9's REFLECT_101 walk, not arbitrary historical reads.
module h2_saved_line_cache # (parameter integer MAX_WIDTH=1920)(
    input wire clk,reset,cancel,cfg_valid,input wire [15:0] cfg_width,cfg_height,
    input wire [31:0] cfg_request_id,
    input wire in_valid,output wire in_ready,input wire [15:0] in_pixel,in_x,in_y,
    input wire read_valid,output wire read_ready,input wire [21:0] read_address,
    input wire [31:0] read_request_id,
    output wire response_valid,input wire response_ready,output reg [21:0] response_address,
    output reg [31:0] response_request_id,output wire [15:0] response_rgb565,
    output reg [3:0] error,output reg [31:0] stored_pixels
);
    localparam REQUEST=0,LOOKUP=1,SELECT_ROW=2,READ_RAM=3,RAM_LATENCY=4,RESPONSE=5;
    reg active;reg [2:0] response_state;
    reg [15:0] width,height,write_row,write_column,max_requested_row,column;
    reg [31:0] request_id,total_pixels,row_start;
    reg [3:0] write_bank,response_bank;
    reg [15:0] response_pixel;
    reg [8:0] valid;
    reg [31:0] starts[0:8],ends[0:8];reg [15:0] rows[0:8];
    reg [3:0] hit;reg hit_valid;
    integer i;
    always @(*)begin
        hit=0;hit_valid=0;
        for(integer k=0;k<9;k=k+1)
            if(valid[k] && response_address>=starts[k] && response_address<ends[k])begin hit=k;hit_valid=1;end
    end
    assign in_ready=active && !cancel && !reset && write_row<height && write_row<=max_requested_row+4;
    wire write_fire=in_valid && in_ready;
    // Accept an immutable address first; a complete matching row may arrive
    // later. Lookup and RAM address each have a register boundary. This avoids
    // a H2 REFLECT arithmetic -> nine-row lookup -> BRAM address timing path.
    // Capacity/tag readiness must not depend on REFLECT_101 address arithmetic.
    // Capture that address first; check its range in the existing LOOKUP cycle.
    // Otherwise H2 px -> reflected x -> row address -> range compare -> request
    // CE forms a 16-level critical path in the actual 125 MHz board design.
    assign read_ready=active && !cancel && !reset && response_state==REQUEST && read_request_id==request_id;
    wire read_fire=read_valid && read_ready;
    wire [143:0] read_taps;
    genvar b;
    generate for(b=0;b<9;b=b+1)begin: banks
        (* ram_style="block" *) reg [15:0] memory[0:MAX_WIDTH-1];
        reg [15:0] tap;
        assign read_taps[b*16+:16]=tap;
        always @(posedge clk)begin
            if(write_fire && write_bank==b)memory[in_x]<=in_pixel;
            if(active && response_state==READ_RAM && !cancel && !reset)tap<=memory[column];
        end
    end endgenerate
    assign response_rgb565=response_pixel;
    assign response_valid=response_state==RESPONSE && active && !reset && !cancel;
    always @(posedge clk)begin
        if(reset || cancel)begin
            active<=0;response_state<=0;response_bank<=0;response_pixel<=0;valid<=0;error<=0;stored_pixels<=0;
            width<=0;height<=0;write_bank<=0;write_row<=0;write_column<=0;column<=0;max_requested_row<=0;
            request_id<=0;total_pixels<=0;row_start<=0;response_address<=0;response_request_id<=0;
            for(i=0;i<9;i=i+1)begin starts[i]<=0;ends[i]<=0;rows[i]<=0;end
        end else if(cfg_valid)begin
            active<=1;response_state<=0;response_pixel<=0;valid<=0;error<=0;stored_pixels<=0;
            width<=cfg_width;height<=cfg_height;request_id<=cfg_request_id;total_pixels<=cfg_width*cfg_height;
            write_bank<=0;write_row<=0;write_column<=0;column<=0;row_start<=0;max_requested_row<=0;
        end else begin
            if(write_fire)begin
                if(in_x!=write_column || in_x>=width || in_y!=write_row)begin error<=5;active<=0;end
                else begin
                    stored_pixels<=stored_pixels+1;
                    if(in_x==0)valid[write_bank]<=0;
                    if(in_x==width-1)begin
                        valid[write_bank]<=1;starts[write_bank]<=row_start;ends[write_bank]<=row_start+width;rows[write_bank]<=write_row;
                        write_bank<=write_bank==8 ? 0 : write_bank+1;write_row<=write_row+1;write_column<=0;row_start<=row_start+width;
                    end else write_column<=write_column+1;
                end
            end
            // Keep wrong-tag rejection immediate even while an older row waits.
            if(read_valid && active && read_request_id!=request_id)begin error<=2;active<=0;response_state<=REQUEST;end
            else if(read_fire)begin
                response_address<=read_address;response_request_id<=read_request_id;response_state<=LOOKUP;
            end else if(response_state==LOOKUP)begin
                if(response_address>=total_pixels)begin error<=2;active<=0;response_state<=REQUEST;end
                else if(hit_valid)begin
                    // Register the row selection before subtraction and watermark
                    // update. The row end is computed once when a row is sealed;
                    // no width adder lies on the nine-way address lookup path.
                    response_bank<=hit;response_state<=SELECT_ROW;
                end
            end else if(response_state==SELECT_ROW)begin
                column<=response_address-starts[response_bank];response_state<=READ_RAM;
                if(rows[response_bank]>max_requested_row)max_requested_row<=rows[response_bank];
            end else if(response_state==READ_RAM)response_state<=RAM_LATENCY;
            else if(response_state==RAM_LATENCY)begin
                // Separate the nine-bank RAM mux from RGB565 gray arithmetic.
                response_pixel<=read_taps[response_bank*16+:16];response_state<=RESPONSE;
            end
            else if(response_valid && response_ready)response_state<=REQUEST;
        end
    end
endmodule
