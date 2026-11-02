// tj-h3-rational81-v1. A tie keeps the earlier successful observation.
// Packed state: [14:0] magnitude, [15] negative, [17:16] source,
// [18] known, [22:19] observed-valid channel mask, [31:23] zero.
module h3_merge(
    input wire [31:0] previous,
    input wire signed [15:0] residual_n,
    input wire observation_valid,
    input wire [1:0] channel,
    output wire [31:0] merged,
    output wire previous_ok, observation_ok
);
    wire [15:0] magnitude=residual_n[15] ? -residual_n : residual_n;
    wire [3:0] channel_bit=4'b0001<<channel;
    wire [3:0] previous_source_bit=4'b0001<<previous[17:16];
    assign previous_ok=previous==0 || (previous[31:23]==0 && previous[18] &&
        previous[14:0]<=15'd20655 && (previous[14:0]!=0 || !previous[15]) &&
        ((previous[22:19] & previous_source_bit)!=0));
    assign observation_ok=!observation_valid || magnitude<=16'd20655;
    wire replace_value=!previous[18] || magnitude>{1'b0,previous[14:0]};
    wire [3:0] mask=previous[22:19] | channel_bit;
    wire [18:0] selected=replace_value ?
        {1'b1,channel,(residual_n[15] && magnitude!=0),magnitude[14:0]} : previous[18:0];
    assign merged=observation_valid ? {9'd0,mask,selected} : previous;
endmodule
