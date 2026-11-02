// Candidate v2 semantic controller. Transport, PWM/I2C and camera/DDR adapters
// are separate. All interfaces are synchronous to clk. No command is sent to
// legacy firmware by this module. QUIESCE must retire both adapters completely.
module light_capture_transaction #(
    parameter integer RECOVERY_TIMEOUT_CYCLES=100000000
)(
    input wire clk,reset,abort_request,
    input wire [63:0] system_boot_id,
    input wire cfg_valid, output wire cfg_ready,
    input wire [7:0] cfg_peer_version,
    input wire [15:0] cfg_capabilities,
    input wire [63:0] cfg_boot_id,
    input wire [31:0] cfg_request_id,cfg_sample_id,cfg_levels,
    input wire [31:0] cfg_settle_cycles,cfg_timeout_cycles,
    input wire [15:0] cfg_width,cfg_height,
    input wire [7:0] cfg_discard_frames,
    input wire cfg_require_locked,
    output reg [63:0] time_tick,
    output wire [63:0] transaction_boot_id,
    output reg [31:0] result_request_id,result_sample_id,result_levels,
    output wire light_valid, input wire light_ready,
    output wire light_off,
    output wire [31:0] light_levels,
    input wire light_response_valid, output wire light_response_ready,
    input wire [63:0] light_response_boot_id,
    input wire [31:0] light_response_request_id,light_response_levels,
    input wire light_response_off,
    input wire [3:0] light_response_mask,
    input wire [7:0] light_response_error,
    output wire capture_valid, input wire capture_ready,
    output reg [31:0] capture_sequence,
    output wire capture_discard,
    output reg [15:0] capture_width,capture_height,
    input wire capture_response_valid, output wire capture_response_ready,
    input wire [63:0] capture_response_boot_id,
    input wire [31:0] capture_response_request_id,capture_response_sequence,
    input wire [31:0] capture_response_levels,capture_response_frame_id,capture_response_handle,capture_response_pixels,
    input wire [15:0] capture_response_width,capture_response_height,
    input wire [63:0] capture_response_start_tick,capture_response_end_tick,
    input wire capture_response_complete,capture_response_fresh,capture_response_locked,
    input wire [7:0] capture_response_error,
    output wire release_valid, input wire release_ready,
    output reg [31:0] frame_id,frame_handle,
    output reg [63:0] frame_start_tick,frame_end_tick,
    output reg frame_exposure_locked,
    input wire release_response_valid, output wire release_response_ready,
    input wire [63:0] release_response_boot_id,
    input wire [31:0] release_response_request_id,release_response_sequence,release_response_handle,
    input wire [7:0] release_response_error,
    output wire quiesce_valid, input wire quiesce_ready,
    input wire recover_valid, output wire recover_ready,
    output wire result_valid, input wire result_ready,
    output wire frame_owned, input wire frame_release,
    output reg [7:0] result_error,maintenance_error,
    output reg [7:0] discarded_frames,
    output reg safe_off_confirmed,
    output wire recovery_required,
    output reg cleanup_done
);
    localparam QUIESCE=0,IDLE=1,LIGHT_REQ=2,LIGHT_WAIT=3,SETTLE=4,CAP_REQ=5,CAP_WAIT=6,
        RELEASE_REQ=7,RELEASE_WAIT=8,HOLD=9,OFF_REQ=10,OFF_WAIT=11,FAIL_RESULT=12,FAULT=13;
    reg [3:0] state;
    reg [63:0] boot_id,issued_tick;
    reg [31:0] last_request_id,phase_timer,settle_remaining,timeout_cycles,expected_pixels;
    reg [7:0] remaining;
    reg require_locked,release_discard,result_consumed,report_failure,seen_frame;
    reg [31:0] previous_frame_id;
    wire unsupported=cfg_peer_version!=2 || (cfg_capabilities & 16'h0007)!=16'h0007 ||
        (cfg_require_locked && !cfg_capabilities[3]);
    wire bad_config=cfg_boot_id==0 || cfg_boot_id!=system_boot_id || cfg_request_id==0 || cfg_request_id<=last_request_id ||
        cfg_timeout_cycles==0 || cfg_width==0 || cfg_width>1920 || cfg_height==0 || cfg_height>1080;
    assign cfg_ready=state==IDLE && !reset;
    assign transaction_boot_id=boot_id;
    assign light_valid=((state==LIGHT_REQ && !abort_request) || state==OFF_REQ) && !reset;
    assign light_off=state==OFF_REQ || state==OFF_WAIT;
    assign light_levels=light_off ? 32'd0 : result_levels;
    assign light_response_ready=(state==LIGHT_WAIT || state==OFF_WAIT || state==QUIESCE) && !reset;
    assign capture_valid=state==CAP_REQ && !reset && !abort_request;
    assign capture_discard=remaining!=0;
    assign capture_response_ready=(state==CAP_WAIT || state==QUIESCE) && !reset;
    assign release_valid=state==RELEASE_REQ && !reset && !abort_request;
    assign release_response_ready=(state==RELEASE_WAIT || state==QUIESCE) && !reset;
    assign quiesce_valid=state==QUIESCE && !reset && system_boot_id!=0;
    assign recover_ready=state==FAULT && !reset;
    assign recovery_required=state==FAULT;
    assign result_valid=(state==FAIL_RESULT || (state==HOLD && !result_consumed)) && !reset && !abort_request;
    assign frame_owned=state==HOLD && !reset && !abort_request;
    wire light_ok=light_response_boot_id==boot_id && light_response_request_id==result_request_id &&
        light_response_off==light_off && light_response_levels==light_levels && light_response_mask==15 && light_response_error==0;
    wire capture_ok=capture_response_boot_id==boot_id && capture_response_request_id==result_request_id &&
        capture_response_sequence==capture_sequence && capture_response_levels==result_levels &&
        capture_response_width==capture_width && capture_response_height==capture_height && capture_response_pixels==expected_pixels &&
        capture_response_complete && capture_response_fresh && (!require_locked || capture_response_locked) &&
        capture_response_start_tick>=issued_tick && capture_response_end_tick>=capture_response_start_tick && capture_response_end_tick<=time_tick &&
        (!seen_frame || capture_response_frame_id!=previous_frame_id) && capture_response_error==0;
    wire release_ok=release_response_boot_id==boot_id && release_response_request_id==result_request_id &&
        release_response_sequence==capture_sequence && release_response_handle==frame_handle && release_response_error==0;
    wire request_active=state>=LIGHT_REQ && state<=HOLD;
    wire phase_wait=state==LIGHT_REQ || state==LIGHT_WAIT || state==CAP_REQ || state==CAP_WAIT || state==RELEASE_REQ || state==RELEASE_WAIT;
    wire phase_progress=(light_valid && light_ready) || (state==LIGHT_WAIT && light_response_valid) ||
        (capture_valid && capture_ready) || (state==CAP_WAIT && capture_response_valid) ||
        (release_valid && release_ready) || (state==RELEASE_WAIT && release_response_valid);
    wire timed_out=phase_wait && phase_timer>=timeout_cycles-1 && !phase_progress;
    wire off_timeout=(state==OFF_REQ || state==OFF_WAIT) && phase_timer>=RECOVERY_TIMEOUT_CYCLES-1 &&
        !((light_valid && light_ready) || (state==OFF_WAIT && light_response_valid));
    always @(posedge clk) begin
        if(reset) begin
            state<=QUIESCE;boot_id<=system_boot_id;time_tick<=0;issued_tick<=0;last_request_id<=0;
            phase_timer<=0;settle_remaining<=0;timeout_cycles<=1;expected_pixels<=0;remaining<=0;
            require_locked<=0;release_discard<=0;result_consumed<=0;report_failure<=0;seen_frame<=0;previous_frame_id<=0;
            result_request_id<=0;result_sample_id<=0;result_levels<=0;capture_sequence<=1;capture_width<=0;capture_height<=0;
            frame_id<=0;frame_handle<=0;frame_start_tick<=0;frame_end_tick<=0;frame_exposure_locked<=0;
            result_error<=0;maintenance_error<=0;discarded_frames<=0;safe_off_confirmed<=0;cleanup_done<=0;
        end else begin
            time_tick<=time_tick+1;cleanup_done<=0;
            if(phase_wait || state==OFF_REQ || state==OFF_WAIT)phase_timer<=phase_timer+1;else phase_timer<=0;
            if(request_active && (abort_request || timed_out)) begin
                if(state==HOLD && result_consumed)begin maintenance_error<=3;report_failure<=0;end
                else begin
                    result_error<=abort_request ? 3 : ((state==LIGHT_REQ || state==LIGHT_WAIT) ? 5 :
                        ((state==RELEASE_REQ || state==RELEASE_WAIT) ? 9 : 7));
                    report_failure<=1;
                end
                if(state==RELEASE_REQ || state==RELEASE_WAIT)begin
                    if(result_consumed)begin maintenance_error<=abort_request ? 3 : 9;report_failure<=0;end
                end
                state<=QUIESCE;safe_off_confirmed<=0;phase_timer<=0;
            end else if(off_timeout)begin
                maintenance_error<=8'h80;safe_off_confirmed<=0;
                // A timeout leaves an operation in flight. Fence it before recovery.
                state<=report_failure ? FAIL_RESULT : FAULT;
            end else case(state)
                QUIESCE:if(quiesce_ready && system_boot_id!=0)begin
                    if(result_request_id==0)boot_id<=system_boot_id;
                    phase_timer<=0;state<=OFF_REQ;
                end
                IDLE:if(cfg_valid)begin
                    boot_id<=cfg_boot_id;result_request_id<=cfg_request_id;result_sample_id<=cfg_sample_id;result_levels<=cfg_levels;
                    result_error<=unsupported ? 1 : (bad_config ? 2 : 0);
                    result_consumed<=0;report_failure<=1;discarded_frames<=0;maintenance_error<=0;
                    if(unsupported || bad_config)state<=FAIL_RESULT;
                    else begin
                        last_request_id<=cfg_request_id;capture_width<=cfg_width;capture_height<=cfg_height;expected_pixels<=cfg_width*cfg_height;
                        settle_remaining<=cfg_settle_cycles;remaining<=cfg_discard_frames;timeout_cycles<=cfg_timeout_cycles;
                        require_locked<=cfg_require_locked;capture_sequence<=1;phase_timer<=0;safe_off_confirmed<=0;seen_frame<=0;state<=LIGHT_REQ;
                    end
                end
                LIGHT_REQ:if(light_ready)begin state<=LIGHT_WAIT;phase_timer<=0;end
                LIGHT_WAIT:if(light_response_valid)begin
                    phase_timer<=0;
                    if(!light_ok)begin result_error<=4;report_failure<=1;state<=QUIESCE;end
                    else state<=settle_remaining==0 ? CAP_REQ : SETTLE;
                end
                SETTLE:begin
                    if(settle_remaining==1)begin settle_remaining<=0;state<=CAP_REQ;end
                    else settle_remaining<=settle_remaining-1;
                end
                CAP_REQ:if(capture_ready)begin issued_tick<=time_tick;phase_timer<=0;state<=CAP_WAIT;end
                CAP_WAIT:if(capture_response_valid)begin
                    phase_timer<=0;
                    if(!capture_ok)begin result_error<=6;report_failure<=1;state<=QUIESCE;end
                    else begin
                        frame_id<=capture_response_frame_id;frame_handle<=capture_response_handle;seen_frame<=1;previous_frame_id<=capture_response_frame_id;
                        frame_start_tick<=capture_response_start_tick;frame_end_tick<=capture_response_end_tick;frame_exposure_locked<=capture_response_locked;
                        if(remaining!=0)begin release_discard<=1;state<=RELEASE_REQ;end
                        else begin result_error<=0;result_consumed<=0;state<=HOLD;end
                    end
                end
                RELEASE_REQ:if(release_ready)begin phase_timer<=0;state<=RELEASE_WAIT;end
                RELEASE_WAIT:if(release_response_valid)begin
                    phase_timer<=0;
                    if(!release_ok)begin
                        if(result_consumed)begin maintenance_error<=8;report_failure<=0;end
                        else begin result_error<=8;report_failure<=1;end
                        state<=QUIESCE;
                    end else if(release_discard)begin
                        remaining<=remaining-1;discarded_frames<=discarded_frames+1;capture_sequence<=capture_sequence+1;state<=CAP_REQ;
                    end else begin report_failure<=0;state<=QUIESCE;end
                end
                HOLD:begin
                    if(result_ready)result_consumed<=1;
                    if(frame_release && (result_consumed || result_ready))begin
                        release_discard<=0;phase_timer<=0;state<=RELEASE_REQ;
                    end
                end
                OFF_REQ:if(light_ready)begin state<=OFF_WAIT;phase_timer<=0;end
                OFF_WAIT:if(light_response_valid)begin
                    phase_timer<=0;
                    if(!light_ok)begin maintenance_error<=8'h80;safe_off_confirmed<=0;state<=report_failure ? FAIL_RESULT : FAULT;end
                    else begin
                        safe_off_confirmed<=1;cleanup_done<=1;
                        if(maintenance_error[7])maintenance_error<=0;
                        state<=report_failure ? FAIL_RESULT : IDLE;
                    end
                end
                FAIL_RESULT:if(result_ready)state<=maintenance_error[7] ? FAULT : IDLE;
                FAULT:if(recover_valid)begin state<=QUIESCE;report_failure<=0;phase_timer<=0;end
                default:begin state<=QUIESCE;report_failure<=0;safe_off_confirmed<=0;end
            endcase
        end
    end
endmodule
