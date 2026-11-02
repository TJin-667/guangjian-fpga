// Synchronous mask read, 32-bit contiguous host writes. CRC16-CCITT is calculated
// over big-endian word bytes; sealing binds exact dimensions and ROI generation.
module board_mask_store #(parameter integer MAX_PIXELS=2073600)(
    input wire clk,reset,locked,write_valid,seal_valid,
    input wire [31:0] write_address,write_data,
    input wire [15:0] seal_width,seal_height,seal_generation,seal_crc,
    output reg valid,output reg [15:0] width,height,generation,
    output reg [2:0] result,
    input wire mask_read,input wire [21:0] mask_address,output wire mask_data
);
    localparam WORDS=(MAX_PIXELS+31)/32;
    (* ram_style="block" *) reg [31:0] memory[0:WORDS-1];
    reg [31:0] next_word,last_word,last_address;
    reg [15:0] crc;
    reg [31:0] pixels_limit,read_word;
    reg [4:0] read_bit;
    reg read_valid;
    assign mask_data=read_valid ? read_word[31-read_bit] : 1'b0;
    wire [31:0] seal_pixels=seal_width*seal_height;
    function [15:0] crc_byte;
        input [15:0] seed;input [7:0] value;
        reg [15:0] c;integer i;
        begin c=seed^{value,8'd0};for(i=0;i<8;i=i+1)c=c[15] ? (c<<1)^16'h1021 : c<<1;crc_byte=c;end
    endfunction
    wire [15:0] crc_next=crc_byte(crc_byte(crc_byte(crc_byte(write_address==0 ? 16'hffff : crc,write_data[31:24]),write_data[23:16]),write_data[15:8]),write_data[7:0]);
    always @(posedge clk)begin
        if(reset)begin valid<=0;width<=0;height<=0;generation<=0;result<=0;next_word<=0;last_word<=0;last_address<=0;crc<=16'hffff;pixels_limit<=0;read_word<=0;read_bit<=0;read_valid<=0;end
        else begin
            result<=0;
            if(write_valid)begin
                if(locked)result<=3;
                else if(write_address>=WORDS)begin result<=2;valid<=0;end
                // Compare with the registered last accepted address. Computing
                // write_address+1 before the retry comparison formed a 32-bit
                // carry -> comparison -> distant BRAM enable setup path.
                // No word/CRC/counter advances for an exact last-word retry.
                else if(next_word!=0 && write_address==last_address && write_data==last_word)begin end
                else if(write_address==0 || write_address==next_word)begin
                    memory[write_address]<=write_data;next_word<=write_address+1;last_word<=write_data;last_address<=write_address;crc<=crc_next;valid<=0;
                end else begin result<=2;valid<=0;end
            end
            if(seal_valid)begin
                if(locked)result<=3;
                else if(seal_pixels==0 || seal_pixels>MAX_PIXELS || next_word!=(seal_pixels+31)/32 || crc!=seal_crc)begin result<=2;valid<=0;end
                else begin valid<=1;width<=seal_width;height<=seal_height;generation<=seal_generation;pixels_limit<=seal_pixels;end
            end
            if(mask_read)begin
                read_word<=memory[mask_address>>5];read_bit<=mask_address[4:0];read_valid<=valid && mask_address<pixels_limit;
            end
        end
    end
endmodule
