// Sole net-domain owner of FIFO clear/control and publisher release.
// A publisher descriptor remains in the mailbox until STOP is acknowledged.
module frozen_frame_owner #(parameter integer CLEAR_CYCLES=16,TIMEOUT_CYCLES=500000000)(
    input wire clk,reset,capture,cancel,
    input wire [255:0] capture_identity,
    input wire pub_valid,output wire pub_ready,input wire [255:0] pub_identity,
    input wire pub_bank,input wire [3:0] pub_error,
    output reg [255:0] active_identity,output reg active_bank,
    output reg reader_ctrl_toggle,reader_ctrl_enable,reader_ctrl_bank,input wire reader_ack_toggle,reader_seen_toggle,
    output wire rdfifo_clr,
    output reg analysis_start,analysis_cancel,input wire analysis_done,input wire [3:0] analysis_error,
    input wire image_complete,
    output wire busy,output reg failed,output reg [3:0] fail_code,
    output reg stats_commit,release_pulse,output reg [31:0] stale_drops,
    output wire [3:0] debug_state
);
    localparam IDLE=0,WAIT_PUBLISH=1,CLEAR=2,START_WAIT=3,PROCESS=4,STOP_WAIT=5,RELEASE=6,FAULT=7;
    reg [3:0] state;reg [255:0] wanted;
    reg [31:0] timer;reg [7:0] clear_count;
    reg stopping,committed;
    reg descriptor_checked,descriptor_matches;
    (* ASYNC_REG="TRUE" *) reg [2:0] ack_sync;
    (* ASYNC_REG="TRUE" *) reg [2:0] seen_sync;
    wire identity_matches=pub_identity[255:128]==wanted[255:128] && pub_identity[63:0]==wanted[63:0];
    assign busy=state!=IDLE;
    assign debug_state=state;
    assign rdfifo_clr=state==CLEAR;
    assign pub_ready=(((state==IDLE && !capture) || (state==WAIT_PUBLISH && pub_valid && descriptor_checked && !descriptor_matches)) && pub_error<4) || state==RELEASE;
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;wanted<=0;active_identity<=0;active_bank<=0;timer<=0;clear_count<=0;
            reader_ctrl_toggle<=0;reader_ctrl_enable<=0;reader_ctrl_bank<=0;ack_sync<=0;seen_sync<=0;
            analysis_start<=0;analysis_cancel<=0;failed<=0;fail_code<=0;stats_commit<=0;release_pulse<=0;stale_drops<=0;stopping<=0;committed<=0;descriptor_checked<=0;descriptor_matches<=0;
        end else begin
            ack_sync<={ack_sync[1:0],reader_ack_toggle};seen_sync<={seen_sync[1:0],reader_seen_toggle};analysis_start<=0;stats_commit<=0;release_pulse<=0;
            // Publisher holds its whole descriptor until ready. Register the
            // wide identity comparison before the stale-bank ready decision.
            if(!pub_valid || pub_ready)descriptor_checked<=0;
            else if(state==WAIT_PUBLISH && !descriptor_checked)begin
                descriptor_checked<=1;descriptor_matches<=identity_matches;
            end
            if(pub_valid && pub_ready && state!=RELEASE)stale_drops<=stale_drops+1;
            case(state)
                IDLE:if(capture)begin
                    wanted<=capture_identity;failed<=0;fail_code<=0;analysis_cancel<=0;timer<=0;committed<=0;stopping<=0;state<=WAIT_PUBLISH;
                end
                WAIT_PUBLISH:begin
                    timer<=timer+1;
                    if(pub_valid && descriptor_checked && descriptor_matches)begin
                        active_identity<=pub_identity;active_bank<=pub_bank;reader_ctrl_bank<=pub_bank;timer<=0;
                        if(pub_error>=4)begin failed<=1;fail_code<=pub_error;state<=FAULT;end
                        else if(pub_error!=0 || cancel)begin failed<=1;fail_code<=cancel ? 3 : pub_error;state<=RELEASE;end
                        else begin clear_count<=0;state<=CLEAR;end
                    end else if(timer==TIMEOUT_CYCLES-1)begin failed<=1;fail_code<=4;state<=FAULT;end
                    else if(cancel)begin failed<=1;fail_code<=3;end
                end
                CLEAR:begin
                    if(clear_count<CLEAR_CYCLES)clear_count<=clear_count+1;
                    timer<=timer+1;
                    if(cancel)begin failed<=1;fail_code<=3;end
                    if(clear_count==1)begin reader_ctrl_enable<=1;reader_ctrl_toggle<=~reader_ctrl_toggle;end
                    // Never release FIFO reset before UI has poisoned the old epoch.
                    if(clear_count>=CLEAR_CYCLES-1 && seen_sync[2]==reader_ctrl_toggle && clear_count>1)begin timer<=0;state<=START_WAIT;end
                    else if(timer==TIMEOUT_CYCLES-1)begin failed<=1;fail_code<=4;state<=FAULT;end
                end
                START_WAIT:begin
                    timer<=timer+1;
                    if(ack_sync[2]==reader_ctrl_toggle)begin
                        analysis_start<=1;timer<=0;state<=PROCESS;
                        if(cancel || failed)begin analysis_cancel<=1;failed<=1;fail_code<=3;end
                    end else if(timer==TIMEOUT_CYCLES-1)begin failed<=1;fail_code<=4;state<=FAULT;end
                    if(cancel)begin failed<=1;fail_code<=3;end
                end
                PROCESS:begin
                    timer<=timer+1;
                    if(cancel || (analysis_done && analysis_error!=0))begin
                        failed<=1;fail_code<=cancel ? 3 : analysis_error;analysis_cancel<=1;
                    end
                    if(analysis_done && analysis_error==0 && !failed && !cancel && !committed)begin committed<=1;stats_commit<=1;end
                    if(analysis_done && (image_complete || failed || cancel || analysis_error!=0))begin
                        reader_ctrl_enable<=0;reader_ctrl_toggle<=~reader_ctrl_toggle;timer<=0;state<=STOP_WAIT;stopping<=1;
                    end else if(timer==TIMEOUT_CYCLES-1)begin
                        failed<=1;fail_code<=4;analysis_cancel<=1;
                        reader_ctrl_enable<=0;reader_ctrl_toggle<=~reader_ctrl_toggle;timer<=0;state<=STOP_WAIT;stopping<=1;
                    end
                end
                STOP_WAIT:begin
                    timer<=timer+1;
                    if(ack_sync[2]==reader_ctrl_toggle)state<=RELEASE;
                    else if(timer==TIMEOUT_CYCLES-1)begin failed<=1;fail_code<=4;state<=FAULT;end
                end
                RELEASE:begin release_pulse<=1;analysis_cancel<=0;state<=IDLE;end
                FAULT:begin analysis_cancel<=1;end // Unknown bank/read completion: coherent reset required.
            endcase
        end
    end
endmodule
