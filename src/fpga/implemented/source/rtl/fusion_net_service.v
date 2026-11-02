// LGHT extension operations 16..25,31. Requests remain 20-byte commands.
// Response 0x88 body: 64-byte identity/status header + <=1024 raw R32 bytes.
// Exact table upload is CRC32-sealed; result data also carries CRC32. Transport
// sequence numbers are monotonic modulo 16 bits, with one immutable last reply.
module fusion_net_service #(
    parameter integer RPC_TIMEOUT_CYCLES=125000000
)(
    input wire clk,reset,session_changed,input wire [63:0] session_id,
    input wire rpc_valid,output wire rpc_ready,input wire [7:0] rpc_op,input wire [63:0] rpc_args,input wire [15:0] rpc_seq,
    output reg rpc_response_valid,input wire rpc_response_ready,output reg [15:0] rpc_response_bytes,
    input wire [10:0] rpc_response_address,output wire [7:0] rpc_response_data,input wire rpc_response_done,
    input wire legacy_busy,configuration_valid,mask_matches,input wire [63:0] parameters,geometry,
    input wire [15:0] roi_generation,mask_generation,input wire [31:0] request_counter,config_epoch,
    input wire capture_pulse,producer_release,producer_failed,
    input wire last_valid,input wire [255:0] last_identity,input wire [63:0] last_parameters,last_geometry,
    output reg group_lock,output wire capture_inhibit,output wire work_busy,output reg association_error,
    output reg fallback_finish,output wire [31:0] fallback_request,
    output reg bridge_cfg_valid,input wire bridge_cfg_ready,
    output wire [31:0] bridge_cfg_cookie,bridge_cfg_request,output wire [15:0] bridge_cfg_width,bridge_cfg_height,
    input wire bridge_active,bridge_result_valid,output wire bridge_result_ready,
    input wire [31:0] bridge_result_cookie,bridge_result_request,bridge_result_written,input wire [3:0] bridge_result_error,input wire bridge_result_fence,
    output reg ui_cmd_valid,input wire ui_cmd_ready,output reg [511:0] ui_cmd_data,
    input wire ui_reply_valid,output wire ui_reply_ready,input wire [255:0] ui_reply_data,
    input wire stream_valid,output wire stream_ready,input wire [191:0] stream_data,
    input wire perf_h2_start,perf_h2_valid,perf_h2_ready,perf_h2_finish,perf_h2_success,
    input wire ui_fault
);
    localparam IDLE=0,ARM_SEND=1,UI_SEND=2,UI_WAIT=3,BUILD=4,PROFILE_COPY=5;
    reg [2:0] state;
    reg [31:0] configuration_words[0:7];
    reg [15:0] group_low,group_high;
    reg [63:0] group_id,group_geometry;reg [127:0] group_digest;
    reg [15:0] group_roi_generation,group_mask_generation;
    reg [31:0] arm_cookie,arm_request,arm_epoch,last_arm_cookie;
    reg [63:0] arm_session,arm_parameters;
    reg [3:0] arm_slot;
    reg armed,capture_seen,scratch_ready,job_busy,fatal;
    reg [3:0] scratch_error;reg [31:0] scratch_written;
    reg [255:0] ui_snapshot;
    reg [31:0] ticket_counter,waiting_ticket,rpc_timer;
    reg [7:0] held_op,reply_status;reg [63:0] held_args;reg [15:0] held_seq;
    reg ui_dispatched,sequence_valid,remember_reply;reg [15:0] latest_seq;
    reg tx_locked,last_reply_valid;reg [15:0] last_seq,last_response_bytes;
    reg [7:0] last_op;reg [63:0] last_args;reg [511:0] response_header,last_header;
    (* ram_style="distributed" *) reg [7:0] response_payload[0:1023];
    reg [31:0] fetch_bytes,fetch_packet,received_bytes,payload_crc;
    reg data_error,copy_busy,copy_allowed;
    reg [127:0] copy_word;reg [4:0] copy_bytes,copy_byte;reg [9:0] copy_base;
    reg [7:0] copy_value;
    wire [7:0] ui_kind=ui_reply_data[255:248],ui_status=ui_reply_data[151:144];
    wire [31:0] ui_ticket=ui_reply_data[247:216],ui_cookie=ui_reply_data[215:184],ui_request=ui_reply_data[183:152];
    wire [3:0] done_slots=ui_snapshot[143:140];
    wire published=ui_snapshot[139];
    wire [31:0] frame_pixels={16'd0,group_geometry[31:16]}*{16'd0,group_geometry[15:0]};
    // Keep all 42 bits before comparing; a large packet index must not wrap
    // into the published buffer when shifted to a byte offset.
    wire [41:0] requested_offset={rpc_args[63:32],10'd0};
    wire [32:0] group_bytes={1'b0,frame_pixels}<<2;
    wire [15:0] sequence_delta=rpc_seq-latest_seq;
    wire sequence_forward=!sequence_valid||(sequence_delta!=0&&sequence_delta<16'h8000);
    wire expected_settings=parameters[63:48]==(rpc_args[0] ? group_low : group_high)&&parameters[47:32]==16&&
        parameters[31:28]==0&&parameters[27:24]==(4'b0001<<((rpc_args[3:0]-1)>>1))&&parameters[23:16]==128&&parameters[15:8]==1&&parameters[7:0]==3;
    assign rpc_ready=state==IDLE&&!rpc_response_valid&&!tx_locked&&!reset;
    assign rpc_response_data=rpc_response_address<64 ? response_header[511-rpc_response_address*8-:8] : response_payload[rpc_response_address-64];
    assign capture_inhibit=group_lock&&!armed;
    assign work_busy=job_busy||(bridge_active&&capture_seen)||(state!=IDLE&&state!=BUILD&&state!=ARM_SEND)||fatal||ui_fault;
    assign bridge_cfg_cookie=arm_cookie;assign bridge_cfg_request=arm_request;
    assign bridge_cfg_width=group_geometry[31:16];assign bridge_cfg_height=group_geometry[15:0];
    assign bridge_result_ready=1'b1;assign fallback_request=arm_request;assign ui_reply_ready=!reset;
    assign stream_ready=copy_busy&&copy_byte==copy_bytes-1&&!reset;
    always @*copy_value=copy_word[copy_byte*8+:8];
    function [31:0] crc_byte(input [31:0] old,input [7:0] value);
        reg [31:0] c;begin c=old^value;for(integer bitno=0;bitno<8;bitno=bitno+1)c=c[0] ? (c>>1)^32'hedb88320 : c>>1;crc_byte=c;end
    endfunction
    function [511:0] make_header(input [7:0] status,input [31:0] data_bytes,input [31:0] crc);
        reg [7:0] flags;begin
            flags={group_lock,scratch_ready,armed,bridge_active,(state==UI_WAIT),job_busy,published,(fatal||ui_fault)};
            make_header={8'd1,held_op,status,flags,arm_cookie,arm_request,group_id,group_digest,group_geometry,
                (held_op==23 ? fetch_packet : held_args[63:32]),data_bytes,crc,waiting_ticket,4'd0,done_slots,4'd0,arm_slot,
                association_error,3'd0,scratch_error,8'd9};
        end
    endfunction
    task respond(input [7:0] status,input [31:0] length,input [31:0] crc);
        begin
            response_header<=make_header(status,length,crc);rpc_response_bytes<=64+length;rpc_response_valid<=1;tx_locked<=1;
            if(remember_reply)begin last_header<=make_header(status,length,crc);last_response_bytes<=64+length;last_seq<=held_seq;last_op<=held_op;last_args<=held_args;last_reply_valid<=1;end
            state<=IDLE;
        end
    endtask
    task send_ui(input [7:0] operation,input [63:0] arguments,input [31:0] frame_cookie);
        begin
            if(ticket_counter==32'hffffffff)begin fatal<=1;reply_status<=6;state<=BUILD;end
            else begin
                ticket_counter<=ticket_counter+1;waiting_ticket<=ticket_counter+1;
                ui_cmd_data<={operation,ticket_counter+32'd1,frame_cookie,arguments,group_id,group_digest,group_geometry[31:16],group_geometry[15:0],152'd0};
                ui_cmd_valid<=1;ui_dispatched<=1;rpc_timer<=0;state<=UI_SEND;
            end
        end
    endtask
    // PROFILE pages reuse the immutable response buffer and existing reply CDC.
    reg [223:0] profile_data;reg [5:0] profile_index,profile_length;
    wire [7:0] profile_byte=profile_data[223-profile_index*8-:8];
    wire [31:0] profile_next_crc=crc_byte(payload_crc,profile_byte);
    // Exactly one synchronous write port preserves distributed RAM inference.
    wire reply_write=(copy_busy&&copy_allowed)||(state==PROFILE_COPY);
    wire [9:0] reply_write_address=(state==PROFILE_COPY) ? profile_index : copy_base+copy_byte;
    wire [7:0] reply_write_byte=(state==PROFILE_COPY) ? profile_byte : copy_value;
    always @(posedge clk)if(!reset&&reply_write)response_payload[reply_write_address]<=reply_write_byte;
    wire h2_clear=(state==IDLE&&rpc_valid&&rpc_ready&&sequence_forward&&rpc_op==18&&!group_lock)||
        (state==IDLE&&rpc_valid&&rpc_ready&&sequence_forward&&rpc_op==17&&!group_lock)||
        (state==ARM_SEND&&bridge_cfg_valid&&bridge_cfg_ready)||
        (session_changed&&!group_lock);
    wire h2_busy,h2_valid,h2_overflow;wire [31:0] h2_cycles,h2_pixels,h2_stalls,h2_blocked;
    stage_cycle_meter h2_meter(.clk(clk),.reset(reset),.clear(h2_clear),
        .start(perf_h2_start&&capture_seen),.finish(perf_h2_finish),.success(perf_h2_success&&!association_error),
        .event0(perf_h2_valid&&perf_h2_ready),.event1(perf_h2_valid&&!perf_h2_ready),.blocked(perf_h2_valid&&!perf_h2_ready),
        .busy(h2_busy),.valid(h2_valid),.overflow(h2_overflow),.cycles(h2_cycles),.count0(h2_pixels),.count1(h2_stalls),.blocked_cycles(h2_blocked));
    task start_profile(input [223:0] data,input [5:0] length);
        begin profile_data<=data;profile_index<=0;profile_length<=length;payload_crc<=32'hffffffff;state<=PROFILE_COPY;end
    endtask
    integer n;
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;group_lock<=0;group_low<=400;group_high<=800;profile_data<=0;profile_index<=0;profile_length<=0;group_id<=0;group_geometry<=0;group_digest<=0;group_roi_generation<=0;group_mask_generation<=0;
            arm_cookie<=0;arm_request<=0;arm_epoch<=0;last_arm_cookie<=0;arm_session<=0;arm_parameters<=0;arm_slot<=0;
            armed<=0;capture_seen<=0;scratch_ready<=0;job_busy<=0;fatal<=0;association_error<=0;fallback_finish<=0;
            scratch_error<=0;scratch_written<=0;ui_snapshot<=0;ticket_counter<=0;waiting_ticket<=0;rpc_timer<=0;
            held_op<=0;held_args<=0;held_seq<=0;reply_status<=0;tx_locked<=0;last_reply_valid<=0;last_seq<=0;last_op<=0;last_args<=0;
            ui_dispatched<=0;sequence_valid<=0;latest_seq<=0;remember_reply<=0;
            response_header<=0;last_header<=0;rpc_response_valid<=0;rpc_response_bytes<=0;last_response_bytes<=0;bridge_cfg_valid<=0;
            ui_cmd_valid<=0;ui_cmd_data<=0;fetch_bytes<=0;fetch_packet<=0;received_bytes<=0;payload_crc<=32'hffffffff;
            data_error<=0;copy_busy<=0;copy_allowed<=0;copy_word<=0;copy_bytes<=0;copy_byte<=0;copy_base<=0;
            for(n=0;n<6;n=n+1)configuration_words[n]<=0;configuration_words[6]<=400;configuration_words[7]<=800;
        end else begin
            if(ui_cmd_valid&&ui_cmd_ready)ui_cmd_valid<=0;
            if(rpc_response_valid&&rpc_response_ready)rpc_response_valid<=0;
            if(rpc_response_done)tx_locked<=0;
            if(ui_fault)fatal<=1;
            if(session_changed&&!group_lock&&!bridge_active&&!job_busy&&state==IDLE)begin last_reply_valid<=0;sequence_valid<=0;scratch_ready<=0;armed<=0;configuration_words[6]<=400;configuration_words[7]<=800;end
            if(capture_pulse&&armed)begin
                armed<=0;capture_seen<=1;
                if(session_id!=arm_session||config_epoch!=arm_epoch||parameters!=arm_parameters||geometry!=group_geometry||
                    roi_generation!=group_roi_generation||mask_generation!=group_mask_generation||!mask_matches||!configuration_valid||request_counter+1!=arm_request)association_error<=1;
            end
            if(producer_release&&capture_seen&&bridge_active)fallback_finish<=1;
            if(bridge_result_valid)begin
                armed<=0;capture_seen<=0;fallback_finish<=0;scratch_written<=bridge_result_written;scratch_error<=bridge_result_error;
                scratch_ready<=bridge_result_error==0&&!bridge_result_fence&&!association_error&&bridge_result_cookie==arm_cookie&&bridge_result_request==arm_request&&bridge_result_written==frame_pixels;
            end
            if(ui_reply_valid)begin
                if(ui_kind!=3)ui_snapshot<=ui_reply_data;
                if(ui_kind==1)begin
                    job_busy<=0;scratch_error<=ui_status[3:0];if(ui_status==0&&ui_cookie==arm_cookie&&ui_request==arm_request)scratch_ready<=0;
                end
                if(state==UI_WAIT&&ui_ticket==waiting_ticket&&ui_kind==3&&held_op==26)begin
                    if(ui_status!=0||ui_cookie!=arm_cookie||ui_request!=arm_request||!ui_reply_data[128]||ui_reply_data[129])begin reply_status<=2;state<=BUILD;end
                    else start_profile({32'h474a5039,held_args[63:32],32'd100000000,ui_reply_data[127:0]},28);
                end
                if(state==UI_WAIT&&ui_ticket==waiting_ticket&&(ui_kind==0||ui_kind==2))begin
                    reply_status<=(held_op==26&&ui_status==0) ? 8'd7 : ui_status;state<=BUILD;
                    if(ui_status==0)begin
                        if(held_op==17)begin group_lock<=1;last_arm_cookie<=0;scratch_ready<=0;arm_slot<=0;arm_cookie<=0;arm_request<=0;scratch_error<=0;end
                        if(held_op==22)job_busy<=1;
                        if(held_op==24||held_op==25)begin group_lock<=0;scratch_ready<=0;armed<=0;end
                    end
                end
            end
            if(stream_valid&&!copy_busy)begin
                copy_busy<=1;copy_word<=stream_data[127:0];copy_byte<=0;copy_base<={stream_data[158:153],4'd0};
                copy_bytes<=stream_data[152:148]>0&&stream_data[152:148]<=16 ? stream_data[152:148] : 16;
                copy_allowed<=state==UI_WAIT&&held_op==23&&stream_data[191:160]==waiting_ticket;
                if(state==UI_WAIT&&held_op==23&&(stream_data[191:160]!=waiting_ticket||stream_data[159]||stream_data[152:148]==0||stream_data[152:148]>16||
                    received_bytes!={21'd0,stream_data[159:153],4'd0}||stream_data[147]!=(received_bytes+stream_data[152:148]==fetch_bytes)))data_error<=1;
            end else if(copy_busy)begin
                if(copy_allowed)begin payload_crc<=crc_byte(payload_crc,copy_value);end
                if(copy_byte==copy_bytes-1)begin copy_busy<=0;if(copy_allowed)received_bytes<=received_bytes+copy_bytes;end
                else copy_byte<=copy_byte+1;
            end
            if(state==UI_SEND||state==UI_WAIT)begin
                rpc_timer<=rpc_timer+1;
                if(rpc_timer==RPC_TIMEOUT_CYCLES-1)begin fatal<=1;reply_status<=6;state<=BUILD;end
            end
            case(state)
                IDLE:if(rpc_valid&&rpc_ready)begin
                    held_op<=rpc_op;held_args<=rpc_args;held_seq<=rpc_seq;reply_status<=0;
                    ui_dispatched<=0;remember_reply<=1;
                    if(sequence_forward)begin sequence_valid<=1;latest_seq<=rpc_seq;end
                    if(last_reply_valid&&rpc_seq==last_seq&&rpc_op==last_op&&rpc_args==last_args)begin
                        response_header<=last_header;rpc_response_bytes<=last_response_bytes;rpc_response_valid<=1;tx_locked<=1;
                    end else if(!sequence_forward || (last_reply_valid&&rpc_seq==last_seq))begin reply_status<=2;remember_reply<=0;state<=BUILD;end
                    else if((fatal||ui_fault)&&rpc_op!=19&&rpc_op!=31)begin reply_status<=6;state<=BUILD;end
                    else if(session_id==0&&rpc_op!=19&&rpc_op!=31)begin reply_status<=2;state<=BUILD;end
                    else case(rpc_op)
                        16:begin
                            if(group_lock||bridge_active||job_busy)reply_status<=3;
                            else if(rpc_args[63:32]>=8||(rpc_args[63:32]>=6&&(rpc_args[31:0]<1||rpc_args[31:0]>1116)))reply_status<=2;
                            else configuration_words[rpc_args[34:32]]<=rpc_args[31:0];state<=BUILD;
                        end
                        17:begin
                            if(group_lock||bridge_active||job_busy||legacy_busy||!mask_matches)begin reply_status<=3;state<=BUILD;end
                            else if(configuration_words[6]<1||configuration_words[7]>1116||configuration_words[6]>=configuration_words[7])begin reply_status<=2;state<=BUILD;end
                            else begin
                                group_low<=configuration_words[6][15:0];group_high<=configuration_words[7][15:0];
                                group_id<={configuration_words[0],configuration_words[1]};group_digest<={configuration_words[2],configuration_words[3],configuration_words[4],configuration_words[5]};
                                group_geometry<=geometry;group_roi_generation<=roi_generation;group_mask_generation<=mask_generation;
                                state<=BUILD; // stage snapshot before constructing the UI command
                            end
                        end
                        18:begin
                            if(!group_lock||bridge_active||scratch_ready||job_busy||legacy_busy||!bridge_cfg_ready)begin reply_status<=3;state<=BUILD;end
                            else if(rpc_args[63:32]==0||rpc_args[63:32]<=last_arm_cookie||rpc_args[31:0]!=done_slots+1||rpc_args[31:0]>8||!configuration_valid||!expected_settings||
                                geometry!=group_geometry||roi_generation!=group_roi_generation||mask_generation!=group_mask_generation||!mask_matches||request_counter==32'hffffffff)begin reply_status<=2;state<=BUILD;end
                            else begin
                                arm_cookie<=rpc_args[63:32];last_arm_cookie<=rpc_args[63:32];arm_slot<=rpc_args[3:0];arm_request<=request_counter+1;arm_epoch<=config_epoch;
                                arm_session<=session_id;arm_parameters<=parameters;association_error<=0;capture_seen<=0;fallback_finish<=0;scratch_error<=0;
                                bridge_cfg_valid<=1;state<=ARM_SEND;
                            end
                        end
                        19,31:state<=BUILD;
                        26:begin
                            if(!group_lock||legacy_busy||bridge_active||job_busy||done_slots==0||done_slots!=arm_slot)begin reply_status<=3;state<=BUILD;end
                            else if(rpc_args[63:32]>2||rpc_args[31:0]!=arm_cookie||!h2_valid||h2_overflow||h2_pixels!=frame_pixels)begin reply_status<=2;state<=BUILD;end
                            else if(rpc_args[63:32]==0)start_profile({32'h474a5039,32'd0,32'd125000000,h2_cycles,h2_pixels,h2_stalls,h2_blocked},28);
                            else state<=BUILD;
                        end
                        27:begin
                            if(rpc_args!=0)begin reply_status<=2;state<=BUILD;end
                            else start_profile({32'h474a4339,(group_lock ? group_low : configuration_words[6][15:0]),(group_lock ? group_high : configuration_words[7][15:0]),16'd16,8'd128,8'd3,16'd1116,8'd1,8'd9,96'd0},16);
                        end
                        20,21:begin
                            if(!group_lock||!scratch_ready||job_busy||legacy_busy)begin reply_status<=3;state<=BUILD;end
                            else begin ui_cmd_valid<=0;state<=BUILD;end
                        end
                        22:begin
                            if(!scratch_ready||job_busy||legacy_busy)begin reply_status<=3;state<=BUILD;end
                            else if(rpc_args[63:32]!=arm_cookie||rpc_args[31:0]!=arm_slot||!last_valid||last_identity[255:192]!=arm_session||last_identity[191:160]!=arm_request||
                                last_identity[159:128]!=arm_epoch||last_identity[63:48]!=group_roi_generation||last_parameters!=arm_parameters||last_geometry!=group_geometry)begin reply_status<=2;state<=BUILD;end
                            else state<=BUILD;
                        end
                        23:begin
                            if(!published||job_busy||legacy_busy||bridge_active||rpc_args[31:0]!=group_id[31:0])begin reply_status<=3;state<=BUILD;end
                            else if(requested_offset>=group_bytes)begin reply_status<=2;state<=BUILD;end
                            else begin
                                fetch_packet<=rpc_args[63:32];fetch_bytes<=group_bytes-requested_offset>=1024 ? 1024 : group_bytes-requested_offset;
                                received_bytes<=0;payload_crc<=32'hffffffff;data_error<=0;state<=BUILD;
                            end
                        end
                        24,25:begin
                            if(job_busy||bridge_active||legacy_busy||rpc_args!=group_id)begin reply_status<=3;state<=BUILD;end
                            else state<=BUILD;
                        end
                        default:begin reply_status<=2;state<=BUILD;end
                    endcase
                end
                ARM_SEND:if(bridge_cfg_valid&&bridge_cfg_ready)begin bridge_cfg_valid<=0;armed<=1;state<=BUILD;end
                UI_SEND:if(ui_cmd_valid&&ui_cmd_ready)begin ui_cmd_valid<=0;state<=UI_WAIT;rpc_timer<=0;end
                PROFILE_COPY:begin
                    payload_crc<=profile_next_crc;
                    if(profile_index==profile_length-1)respond(0,{26'd0,profile_length},~profile_next_crc);
                    else profile_index<=profile_index+1;
                end
                BUILD:begin
                    if(reply_status!=0)respond(reply_status,0,0);
                    else if(!ui_dispatched&&held_op==17)send_ui(1,0,0);
                    else if(!ui_dispatched&&held_op==20)send_ui(2,held_args,arm_cookie);
                    else if(!ui_dispatched&&held_op==21)send_ui(3,held_args,arm_cookie);
                    else if(!ui_dispatched&&held_op==22)send_ui(4,{28'd0,arm_slot,arm_request},arm_cookie);
                    else if(!ui_dispatched&&held_op==23)send_ui(6,{(fetch_packet<<10),fetch_bytes},arm_cookie);
                    else if(!ui_dispatched&&held_op==24)send_ui(5,held_args,0);
                    else if(!ui_dispatched&&held_op==25)send_ui(8,held_args,0);
                    else if(!ui_dispatched&&held_op==26)send_ui(9,held_args,arm_cookie);
                    else if(held_op==23)begin
                        if(data_error||received_bytes!=fetch_bytes)respond(7,0,0);else respond(0,fetch_bytes,~payload_crc);
                    end else respond(0,0,0);
                end
            endcase
        end
    end
endmodule
