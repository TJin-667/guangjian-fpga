// Transactional H3, one addressed state-memory command outstanding at a time.
// Writes only the inactive bank. Commit requires all durable write responses
// and a successful, correctly tagged upstream frame completion.
// A flush ACK MUST fence all earlier writes before the bank can be reused.
module h3_fusion #(
    parameter integer MAX_WIDTH=1920, MAX_HEIGHT=1080,
    parameter integer WATCHDOG_CYCLES=100000000
)(
    input wire clk, reset, abort_frame,
    input wire cfg_valid, output wire cfg_ready,
    input wire cfg_new_sample,
    input wire [31:0] cfg_sample_id, cfg_request_id,
    input wire [1:0] cfg_channel,
    input wire [15:0] cfg_width,cfg_height,cfg_x,cfg_y,cfg_roi_width,cfg_roi_height,
    input wire in_valid, output wire in_ready,
    input wire [31:0] in_request_id,
    input wire [15:0] in_x,in_y,
    input wire signed [15:0] in_residual_n,
    input wire in_observation_valid,in_sof,in_eol,in_eof,
    input wire finish_valid, output wire finish_ready,
    input wire [31:0] finish_request_id,
    input wire [2:0] finish_error,
    output wire mem_valid, input wire mem_ready,
    output wire mem_write, output wire mem_bank,
    output wire [20:0] mem_address,
    output wire [31:0] mem_request_id,mem_write_data,
    input wire response_valid, output wire response_ready,
    input wire response_write,response_bank,response_error,
    input wire [20:0] response_address,
    input wire [31:0] response_request_id,response_data,
    output wire mem_flush_valid, input wire mem_flush_ready,
    output wire result_valid, input wire result_ready,
    output reg [2:0] result_error,
    output reg [31:0] result_request_id,
    output reg [31:0] written_count,
    output reg commit_pulse,committed_valid,committed_bank,
    output reg [31:0] committed_sample_id,committed_request_id,
    output reg [15:0] committed_width,committed_height,committed_x,committed_y,
    output reg [15:0] committed_roi_width,committed_roi_height
);
    localparam IDLE=0, INPUT_PIXEL=1, READ_REQ=2, READ_RSP=3, MERGE=4,
        WRITE_REQ=5, WRITE_RSP=6, WAIT_FINISH=7, RESULT=8, FLUSH=9;
    reg [3:0] state;
    reg flush_to_result,new_sample,target_bank,finish_seen,all_inputs_seen;
    reg [31:0] sample_id,watchdog;
    reg [1:0] channel;
    reg [15:0] width,height,x0,y0,rw,rh,x1,y1,x,y;
    reg [20:0] index;
    reg signed [15:0] residual_n;
    reg observation_valid,pixel_last;
    reg [31:0] previous,write_word;
    wire [31:0] merged;
    wire previous_ok,observation_ok;
    h3_merge merge_pixel(.previous(previous),.residual_n(residual_n),
        .observation_valid(observation_valid),.channel(channel),.merged(merged),
        .previous_ok(previous_ok),.observation_ok(observation_ok));
    wire [16:0] right={1'b0,cfg_x}+{1'b0,cfg_roi_width};
    wire [16:0] bottom={1'b0,cfg_y}+{1'b0,cfg_roi_height};
    wire geometry_ok=cfg_width>0 && cfg_height>0 && cfg_width<=MAX_WIDTH && cfg_height<=MAX_HEIGHT &&
        cfg_roi_width>0 && cfg_roi_height>0 && right<={1'b0,cfg_width} && bottom<={1'b0,cfg_height};
    wire history_ok=cfg_new_sample || (committed_valid && cfg_sample_id==committed_sample_id &&
        cfg_width==committed_width && cfg_height==committed_height && cfg_x==committed_x && cfg_y==committed_y &&
        cfg_roi_width==committed_roi_width && cfg_roi_height==committed_roi_height);
    wire active=state>=INPUT_PIXEL && state<=WAIT_FINISH;
    assign cfg_ready=state==IDLE && !reset;
    assign in_ready=state==INPUT_PIXEL && !reset && !abort_frame;
    assign finish_ready=active && !finish_seen && !reset && !abort_frame;
    wire accept_pixel=in_valid && in_ready;
    wire expected_last=x==x1-1 && y==y1-1;
    wire finish_bad=finish_valid && finish_ready && (finish_error!=0 || finish_request_id!=result_request_id ||
        !(all_inputs_seen || (accept_pixel && expected_last)));
    wire input_ok=in_request_id==result_request_id && in_x==x && in_y==y &&
        in_sof==(index==0) && in_eol==(x==x1-1) && in_eof==expected_last;
    assign mem_valid=(state==READ_REQ || state==WRITE_REQ) && !reset && !abort_frame && !finish_bad;
    assign mem_write=state==WRITE_REQ;
    assign mem_bank=mem_write ? target_bank : committed_bank;
    assign mem_address=index;
    assign mem_request_id=result_request_id;
    assign mem_write_data=write_word;
    assign response_ready=(state==READ_RSP || state==WRITE_RSP || state==FLUSH) && !reset;
    wire response_ok=!response_error && response_request_id==result_request_id && response_address==index &&
        response_write==(state==WRITE_RSP) && response_bank==(state==WRITE_RSP ? target_bank : committed_bank);
    assign mem_flush_valid=state==FLUSH && !reset;
    assign result_valid=state==RESULT && !reset;
    wire progress=accept_pixel || (mem_valid && mem_ready) || (response_valid && response_ready) ||
        (finish_valid && finish_ready) || state==MERGE;
    integer unused;
    always @(posedge clk) begin
        if(reset) begin
            state<=FLUSH;flush_to_result<=0;commit_pulse<=0;committed_valid<=0;committed_bank<=0;
            committed_sample_id<=0;committed_request_id<=0;
            committed_width<=0;committed_height<=0;committed_x<=0;committed_y<=0;committed_roi_width<=0;committed_roi_height<=0;
            result_error<=0;result_request_id<=0;written_count<=0;new_sample<=0;target_bank<=1;
            finish_seen<=0;all_inputs_seen<=0;sample_id<=0;watchdog<=0;channel<=0;
            width<=0;height<=0;x0<=0;y0<=0;rw<=0;rh<=0;x1<=0;y1<=0;x<=0;y<=0;index<=0;
            residual_n<=0;observation_valid<=0;pixel_last<=0;previous<=0;write_word<=0;
        end else begin
            commit_pulse<=0;
            if(!active || progress)watchdog<=0;else watchdog<=watchdog+1;
            if(active && (abort_frame || finish_bad || (WATCHDOG_CYCLES>0 && watchdog>=WATCHDOG_CYCLES-1 && !progress))) begin
                result_error<=abort_frame ? 3'd3 : (finish_bad ? 3'd4 : 3'd6);
                flush_to_result<=1;state<=FLUSH;
            end else begin
                if(finish_valid && finish_ready)finish_seen<=1;
                case(state)
                    IDLE: if(cfg_valid) begin
                        result_request_id<=cfg_request_id;result_error<=0;written_count<=0;
                        sample_id<=cfg_sample_id;channel<=cfg_channel;new_sample<=cfg_new_sample;target_bank<=!committed_bank;
                        width<=cfg_width;height<=cfg_height;x0<=cfg_x;y0<=cfg_y;rw<=cfg_roi_width;rh<=cfg_roi_height;
                        x1<=right[15:0];y1<=bottom[15:0];x<=cfg_x;y<=cfg_y;index<=0;
                        all_inputs_seen<=0;finish_seen<=0;
                        if(geometry_ok && history_ok)state<=INPUT_PIXEL;
                        else begin result_error<=1;state<=RESULT;end
                    end
                    INPUT_PIXEL: if(in_valid) begin
                        if(!input_ok)begin result_error<=2;flush_to_result<=1;state<=FLUSH;end
                        else begin
                            residual_n<=in_residual_n;observation_valid<=in_observation_valid;pixel_last<=expected_last;
                            if(expected_last)all_inputs_seen<=1;
                            if(new_sample)begin previous<=0;state<=MERGE;end else state<=READ_REQ;
                        end
                    end
                    READ_REQ: if(mem_ready)state<=READ_RSP;
                    READ_RSP: if(response_valid) begin
                        if(!response_ok)begin result_error<=5;flush_to_result<=1;state<=FLUSH;end
                        else begin previous<=response_data;state<=MERGE;end
                    end
                    MERGE: begin
                        if(!previous_ok || !observation_ok)begin result_error<=(!previous_ok ? 5 : 2);flush_to_result<=1;state<=FLUSH;end
                        else begin write_word<=merged;state<=WRITE_REQ;end
                    end
                    WRITE_REQ: if(mem_ready)state<=WRITE_RSP;
                    WRITE_RSP: if(response_valid) begin
                        if(!response_ok)begin result_error<=5;flush_to_result<=1;state<=FLUSH;end
                        else begin
                            written_count<=written_count+1;
                            if(pixel_last)state<=WAIT_FINISH;
                            else begin
                                index<=index+1;
                                if(x==x1-1)begin x<=x0;y<=y+1;end else x<=x+1;
                                state<=INPUT_PIXEL;
                            end
                        end
                    end
                    WAIT_FINISH: if(finish_seen || (finish_valid && finish_ready)) begin
                        committed_valid<=1;committed_bank<=target_bank;committed_sample_id<=sample_id;
                        committed_request_id<=result_request_id;committed_width<=width;committed_height<=height;
                        committed_x<=x0;committed_y<=y0;committed_roi_width<=rw;committed_roi_height<=rh;
                        commit_pulse<=1;state<=RESULT;
                    end
                    RESULT: if(result_ready)state<=IDLE;
                    FLUSH: if(mem_flush_ready)state<=flush_to_result ? RESULT : IDLE;
                    default: begin state<=FLUSH;flush_to_result<=0;committed_valid<=0;end
                endcase
            end
        end
    end
endmodule
