// RGB565 payload formatter, no Ethernet/IP/UDP headers and no physical network.
// 1380-byte payload contract; packet boundaries may cross rows, never pixels.
module rgb565_payload # (parameter integer PAYLOAD_BYTES=1380)(
    input wire clk, reset, cancel,
    input wire in_valid, output wire in_ready,
    input wire [15:0] in_pixel, input wire in_sof, in_eof,
    output wire out_valid, input wire out_ready,
    output wire [7:0] out_byte,
    output wire packet_first, packet_last, frame_first, frame_last,
    output reg [15:0] packet_id,
    output wire [15:0] byte_index
);
    reg active, low_phase, first_word, last_word;
    reg [15:0] word;
    reg [15:0] offset;
    // One word at a time; upstream H1 elastic register absorbs brief stalls.
    assign in_ready = !active && !cancel && !reset;
    assign out_valid = active && !cancel && !reset;
    assign out_byte = low_phase ? word[7:0] : word[15:8];
    assign byte_index = offset;
    assign packet_first = offset==0;
    assign packet_last = low_phase && (offset==PAYLOAD_BYTES-1 || last_word);
    assign frame_first = first_word && !low_phase;
    assign frame_last = last_word && low_phase;
    always @(posedge clk) begin
        if (reset || cancel) begin
            active<=0; low_phase<=0; first_word<=0; last_word<=0;
            word<=0; offset<=0; packet_id<=0;
        end else begin
            if (in_valid && in_ready) begin
                word<=in_pixel; first_word<=in_sof; last_word<=in_eof;
                active<=1; low_phase<=0;
                if (in_sof) begin offset<=0; packet_id<=0; end
            end
            if (out_valid && out_ready) begin
                if (low_phase) begin
                    active<=0; low_phase<=0;
                    if (packet_last) begin offset<=0; packet_id<=packet_id+1; end
                    else offset<=offset+1;
                end else begin low_phase<=1; offset<=offset+1; end
            end
        end
    end
endmodule
