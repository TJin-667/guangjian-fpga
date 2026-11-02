// Contract tj-image-v1: OpenCV RGB565 bit replication, integer BT.601 gray.
// Exhaustive 65536-color validation is performed against the installed OpenCV.
(* use_dsp = "no" *)
module rgb565_gray(input wire [15:0] pixel, output wire [7:0] gray);
    wire [7:0] r = {pixel[15:11], pixel[15:13]};
    wire [7:0] g = {pixel[10:5], pixel[10:9]};
    wire [7:0] b = {pixel[4:0], pixel[4:2]};
    wire [23:0] weighted = r * 24'd9798 + g * 24'd19235 + b * 24'd3735 + 24'd16384;
    assign gray = weighted[22:15];
endmodule
