// Frozen B1 evidence selection. Slots are 1=CH1-low ... 8=CH4-high.
// Word: [15:0] R_n, [19:16] source, [20] weak, [21] strong,
// [29:22] selected-source gray, [31:30] zero. source=0 means unknown.
module maxabs8_pixel(
    input wire [31:0] previous,
    input wire signed [15:0] residual_n,
    input wire [7:0] gray,
    input wire observation_valid,
    input wire [3:0] source,
    output wire [31:0] merged,
    output wire error
);
    wire signed [15:0] old_r=previous[15:0];
    wire [3:0] old_source=previous[19:16];
    // Widen before negation, including the malformed -32768 input case.
    wire [16:0] old_abs=old_r[15] ? -$signed({old_r[15],old_r}) : {1'b0,old_r};
    wire [16:0] new_abs=residual_n[15] ? -$signed({residual_n[15],residual_n}) : {1'b0,residual_n};
    wire known=old_source!=0;
    wire old_ok=previous[31:30]==0 && old_source<=8 && old_abs<=20655 &&
        (known ? (previous[20]==(old_abs>648) && previous[21]==(old_abs>1620) && old_source<source) : previous==0);
    assign error=!old_ok || source<1 || source>8 || new_abs>20655;
    wire replace_pixel=observation_valid && (!known || new_abs>old_abs);
    assign merged=replace_pixel ? {2'b0,gray,(new_abs>1620),(new_abs>648),source,residual_n} : previous;
endmodule
