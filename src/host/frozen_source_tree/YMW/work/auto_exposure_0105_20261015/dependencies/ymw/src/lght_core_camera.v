`timescale 1ns/1ps
// Application layer. RX bytes are tentative until rx_done && !rx_error.
// TX is pull-only: data remains available every cycle of tx_req.
module lght_core_camera #(
    parameter integer WIDTH=320, HEIGHT=240,
    parameter integer CAM_WIDTH=1920, CAM_HEIGHT=1080,
    parameter [15:0] INITIAL_FRAME_ID=0,
    // Diagnostic pacing: at 125 MHz, 12500 cycles add 100 us between packets.
    parameter integer PACKET_GAP_CYCLES=12500,
    parameter integer CONTROL_TIMEOUT_CYCLES=125000000
)(
    input wire clk, reset,
    input wire light_busy,light_done,light_error,
    output reg light_start,
    output reg [3:0] light_mask,
    output reg [7:0] light_brightness,
    input wire rx_start, rx_valid, rx_done, rx_error,
    input wire [7:0] rx_data,
    input wire [47:0] rx_mac,
    input wire [31:0] rx_ip,
    input wire [15:0] rx_port,
    input wire tx_ready, tx_req, tx_done,
    input wire camera_config_ok, camera_busy, camera_ready, camera_failed,
    input wire [2:0] camera_fail_code,
    input wire [15:0] camera_pixel,
    input wire manual_busy, manual_done, manual_locked,
    input wire [2:0] manual_error,
    input wire [111:0] manual_raw,
    input wire [15:0] manual_generation,
    output reg manual_start, manual_set,
    output reg [15:0] manual_exposure,
    output reg [9:0] manual_gain16,
    output reg camera_crop_enable,
    output reg [15:0] camera_roi_x,camera_roi_y,camera_roi_width,camera_roi_height,camera_roi_packets,
    output reg [10:0] camera_roi_last_pixels,
    output reg camera_capture, camera_release,
    output wire [15:0] camera_packet_id,
    output wire camera_read_en,
    output wire [15:0] camera_read_addr,
    output reg tx_start,
    output reg [15:0] tx_length,
    output reg [47:0] tx_mac,
    output reg [31:0] tx_ip,
    output reg [15:0] tx_port,
    output reg [7:0] tx_data,
    output reg frame_busy,
    output reg [31:0] commands, frames_started, rx_dropped
);
    localparam integer FRAME_BYTES=WIDTH*HEIGHT*2;
    localparam integer PACKETS=(FRAME_BYTES+1379)/1380;
    localparam integer CAM_BYTES=CAM_WIDTH*CAM_HEIGHT*2;
    localparam integer CAM_PACKETS=(CAM_BYTES+1379)/1380;
    localparam IDLE=0, START=1, SEND=2, WAIT_READY=3;
    reg [1:0] state;
    reg [2:0] mode; // 0 ACK, 1 STATUS, 2 frame, 3 CAMERA_STATUS, 4 ROI_STATUS
    reg [7:0] mem [0:19];
    reg [5:0] count;
    wire [7:0] cmd_type=mem[5];
    wire [15:0] seq={mem[6],mem[7]};
    wire [63:0] args={mem[12],mem[13],mem[14],mem[15],mem[16],mem[17],mem[18],mem[19]};
    wire [15:0] a0=args[63:48], a1=args[47:32], a2=args[31:16], a3=args[15:0];
    wire envelope=count==20 && {mem[0],mem[1],mem[2],mem[3]}==32'h4c474854 &&
                  mem[4]==1 && {mem[8],mem[9],mem[10],mem[11]}==32'h000a0000;
    reg pending, status_phase, light_wait;
    reg roi_start,roi_wait,roi_reply;
    reg [15:0] roi_req_x,roi_req_y,roi_req_width,roi_req_height;
    wire roi_busy,roi_done,roi_error,roi_valid;
    wire [15:0] roi_x,roi_y,roi_width,roi_height,roi_packets,roi_generation;
    wire [31:0] roi_pixels;
    wire [10:0] roi_last_pixels;
    reg [31:0] camera_roi_pixels;
    reg [15:0] roi_status_x,roi_status_y,roi_status_width,roi_status_height,roi_status_packets,roi_status_generation;
    reg [31:0] roi_status_pixels;
    reg [10:0] roi_status_last_pixels;
    reg roi_status_valid;
    reg roi_cache_valid;
    reg [47:0] roi_cache_mac;
    reg [31:0] roi_cache_ip;
    reg [15:0] roi_cache_port,roi_cache_seq,roi_cache_generation;
    reg [63:0] roi_cache_args;
    reg [15:0] roi_cache_x,roi_cache_y,roi_cache_width,roi_cache_height,roi_cache_packets;
    reg [31:0] roi_cache_pixels;
    reg [10:0] roi_cache_last_pixels;
    wire roi_cached=roi_cache_valid && roi_cache_mac==rx_mac && roi_cache_ip==rx_ip &&
        roi_cache_port==rx_port && roi_cache_seq==seq;
    roi_config_ctrl #(.WIDTH(CAM_WIDTH),.HEIGHT(CAM_HEIGHT)) u_roi_config(
        .clk(clk),.reset(reset),.start(roi_start),
        .request_x(roi_req_x),.request_y(roi_req_y),.request_width(roi_req_width),.request_height(roi_req_height),
        .busy(roi_busy),.done(roi_done),.error(roi_error),.valid(roi_valid),
        .x(roi_x),.y(roi_y),.width(roi_width),.height(roi_height),.packets(roi_packets),
        .generation(roi_generation),.pixels(roi_pixels),.last_pixels(roi_last_pixels));
    reg manual_wait, manual_reply;
    integer manual_watchdog;
    reg [7:0] manual_status_flags,manual_status_error;
    reg [111:0] manual_status_raw;
    reg [15:0] manual_status_generation;
    reg manual_cache_valid;
    reg [47:0] manual_cache_mac;
    reg [31:0] manual_cache_ip;
    reg [15:0] manual_cache_port,manual_cache_seq;
    reg [7:0] manual_cache_kind,manual_cache_result,manual_cache_flags,manual_cache_error;
    reg [63:0] manual_cache_args;
    reg [111:0] manual_cache_raw;
    reg [15:0] manual_cache_generation;
    wire manual_cached=manual_cache_valid && manual_cache_mac==rx_mac &&
        manual_cache_ip==rx_ip && manual_cache_port==rx_port && manual_cache_seq==seq;
    reg [7:0] ptype, presult;
    reg [15:0] pseq, pframe, pbusy;
    reg [47:0] pmac;
    reg [31:0] pip;
    reg [15:0] pport;
    reg [15:0] frame_id, packet_id;
    reg [47:0] fmac, cache_mac;
    reg [31:0] fip, cache_ip;
    reg [15:0] fport, cache_port, cache_seq, cache_frame;
    reg [63:0] cache_args;
    reg cache_valid, source_counter, source_camera, camera_started;
    reg [15:0] camera_pixel_hold;
    reg [15:0] index, plen, last_error;
    reg [15:0] packet_gap_count;
    reg [31:0] byte_offset;
    reg [15:0] packet_byte_offset;
    reg [15:0] x,y;
    reg [15:0] status_state, status_error;
    reg [31:0] status_commands,status_frames,status_dropped;
    wire cached=cache_valid && cache_mac==rx_mac && cache_ip==rx_ip && cache_port==rx_port && cache_seq==seq;
    wire [31:0] selected_frame_bytes=source_camera?(camera_roi_pixels<<1):FRAME_BYTES;
    wire [15:0] selected_packets=source_camera?camera_roi_packets:PACKETS;
    wire [15:0] selected_last_bytes=source_camera?{4'b0,camera_roi_last_pixels,1'b0}:FRAME_BYTES-(PACKETS-1)*1380;
    wire [15:0] selected_width=source_camera?camera_roi_width:WIDTH;
    wire [15:0] selected_height=source_camera?camera_roi_height:HEIGHT;
    wire camera_prefetch=state==IDLE && frame_busy && source_camera &&
                         camera_started && camera_ready && !pending;
    wire camera_next=state==SEND && mode==2 && source_camera && tx_req &&
                     index>=20 && !byte_offset[0];
    assign camera_packet_id=packet_id;
    assign camera_read_en=camera_prefetch || camera_next;
    // The DDR source stages one UDP packet at a time in a small local RAM.
    // Reset this address for every packet; byte_offset still tracks the frame.
    assign camera_read_addr=camera_prefetch?packet_byte_offset[15:1]:packet_byte_offset[15:1]+16'd1;
    reg [7:0] result_code;
    always @* begin
        result_code=0;
        case(cmd_type)
            1: if(a0>15 || a1>255 || a2!=0 || a3!=0) result_code=2;
               else if(light_busy || light_wait || frame_busy || camera_busy || manual_busy || manual_wait || roi_busy || roi_wait) result_code=1;
            2: if(a0>3 ||
                  (a1!=0 && a1!=(a0==3?roi_width:(a0==2?CAM_WIDTH:WIDTH))) ||
                  (a2!=0 && a2!=(a0==3?roi_height:(a0==2?CAM_HEIGHT:HEIGHT))) ||
                  (a0!=3 && a3!=0) || (a0==3 && (!roi_valid || a3!=roi_generation))) result_code=2;
               else if(cached && cache_args!=args) result_code=2;
               else if(!cached && frame_busy) result_code=1;
               else if(manual_busy || manual_wait || light_busy || light_wait || roi_busy || roi_wait) result_code=1;
               else if(!cached && a0>=2 && camera_busy) result_code=1;
               else if(a0>=2 && (!camera_config_ok || !manual_locked)) result_code=4;
            3: if(args!=0) result_code=2;
            4,5:begin
                if((cmd_type==4 && (a0<1 || a0>1116 || a1<16 || a1>1023 || a2!=0 || a3!=0)) ||
                   (cmd_type==5 && args!=0) ||
                   (manual_cached && (manual_cache_kind!=cmd_type || manual_cache_args!=args)))result_code=2;
                else if(manual_cached)result_code=manual_cache_result;
                else if(frame_busy || camera_busy || light_busy || light_wait || manual_busy || manual_wait || roi_busy || roi_wait)result_code=1;
                else if(!camera_config_ok)result_code=4;
            end
            6:begin
                if(a2==0 || a3==0 || {1'b0,a0}+{1'b0,a2}>CAM_WIDTH ||
                   {1'b0,a1}+{1'b0,a3}>CAM_HEIGHT || (roi_cached && roi_cache_args!=args))result_code=2;
                else if(roi_cached)result_code=0;
                else if(frame_busy || camera_busy || light_busy || light_wait || manual_busy || manual_wait || roi_busy || roi_wait)result_code=1;
            end
            7:if(args!=0)result_code=2;
            default:result_code=3;
        endcase
    end
    reg [15:0] color;
    always @* begin
        // ceil(k*WIDTH/8) thresholds implement floor(x*8/WIDTH) exactly,
        // including widths not divisible by eight, without a datapath divider.
        if(x<(WIDTH+7)/8)color=16'hffff;
        else if(x<(2*WIDTH+7)/8)color=16'hffe0;
        else if(x<(3*WIDTH+7)/8)color=16'h07ff;
        else if(x<(4*WIDTH+7)/8)color=16'h07e0;
        else if(x<(5*WIDTH+7)/8)color=16'hf81f;
        else if(x<(6*WIDTH+7)/8)color=16'hf800;
        else if(x<(7*WIDTH+7)/8)color=16'h001f;
        else color=0;
        if(x==0 || y==0)color=0;
    end
    // Packet metadata is frozen for the complete packet, including STATUS.
    always @* begin
        tx_data=0;
        case(index)
            0:tx_data="L";1:tx_data="G";2:tx_data="H";3:tx_data="T";
            4:tx_data=1;
            5:tx_data=mode==2?8'h90:(mode==1?8'h82:(mode==3?8'h83:(mode==4?8'h84:8'h81)));
            6:tx_data=mode==2?frame_id[15:8]:pseq[15:8];
            7:tx_data=mode==2?frame_id[7:0]:pseq[7:0];
            default:begin
                if(mode==2)begin
                    case(index)
                        8:tx_data=packet_id[15:8];9:tx_data=packet_id[7:0];
                        10:tx_data=selected_packets[15:8];11:tx_data=selected_packets[7:0];
                        12:tx_data=plen[15:8];13:tx_data=plen[7:0];
                        14:tx_data=selected_width[15:8];15:tx_data=selected_width[7:0];
                        16:tx_data=selected_height[15:8];17:tx_data=selected_height[7:0];
                        18:tx_data=1;
                        19:tx_data={6'b0,(packet_id==selected_packets-1),(packet_id==0)};
                        default:tx_data=source_camera?
                            (byte_offset[0]?camera_pixel_hold[7:0]:camera_pixel[15:8]):
                            (source_counter?byte_offset[7:0]:(byte_offset[0]?color[7:0]:color[15:8]));
                    endcase
                end else if(mode==0)begin
                    case(index)
                        8:tx_data=0;9:tx_data=10;10:tx_data=ptype;11:tx_data=presult;
                        12:tx_data=pframe[15:8];13:tx_data=pframe[7:0];
                        14:tx_data=pbusy[15:8];15:tx_data=pbusy[7:0];16:tx_data=0;17:tx_data=127;
                        default:tx_data=0;
                    endcase
                end else if(mode==4)begin
                    case(index)
                        8:tx_data=0;9:tx_data=22;10:tx_data=1;11:tx_data={7'b0,roi_status_valid};
                        12:tx_data=roi_status_x[15:8];13:tx_data=roi_status_x[7:0];
                        14:tx_data=roi_status_y[15:8];15:tx_data=roi_status_y[7:0];
                        16:tx_data=roi_status_width[15:8];17:tx_data=roi_status_width[7:0];
                        18:tx_data=roi_status_height[15:8];19:tx_data=roi_status_height[7:0];
                        20:tx_data=roi_status_packets[15:8];21:tx_data=roi_status_packets[7:0];
                        22:tx_data={5'b0,roi_status_last_pixels[10:8]};23:tx_data=roi_status_last_pixels[7:0];
                        24:tx_data=roi_status_generation[15:8];25:tx_data=roi_status_generation[7:0];
                        26:tx_data=roi_status_pixels[31:24];27:tx_data=roi_status_pixels[23:16];
                        28:tx_data=roi_status_pixels[15:8];29:tx_data=roi_status_pixels[7:0];
                        default:tx_data=0;
                    endcase
                end else if(mode==3)begin
                    case(index)
                        8:tx_data=0;9:tx_data=22;
                        10:tx_data=1;11:tx_data=manual_status_flags;
                        12:tx_data=manual_status_error;13:tx_data=0;
                        28:tx_data=manual_status_generation[15:8];29:tx_data=manual_status_generation[7:0];
                        30:tx_data=0;31:tx_data=0;
                        default:if(index>=14 && index<=27)tx_data=manual_status_raw[111-(index-14)*8 -: 8];
                    endcase
                end else begin
                    case(index)
                        8:tx_data=0;9:tx_data=22;10:tx_data=0;11:tx_data=0;
                        12:tx_data=1;13:tx_data=4;14:tx_data=0;15:tx_data=127;
                        16:tx_data=status_state[15:8];17:tx_data=status_state[7:0];
                        18:tx_data=status_error[15:8];19:tx_data=status_error[7:0];
                        20:tx_data=status_commands[31:24];21:tx_data=status_commands[23:16];
                        22:tx_data=status_commands[15:8];23:tx_data=status_commands[7:0];
                        24:tx_data=status_frames[31:24];25:tx_data=status_frames[23:16];
                        26:tx_data=status_frames[15:8];27:tx_data=status_frames[7:0];
                        28:tx_data=status_dropped[31:24];29:tx_data=status_dropped[23:16];
                        30:tx_data=status_dropped[15:8];31:tx_data=status_dropped[7:0];
                        default:tx_data=0;
                    endcase
                end
            end
        endcase
    end
    always @(posedge clk) begin
        if(reset)begin
            count<=0;pending<=0;status_phase<=0;light_wait<=0;
            roi_start<=0;roi_wait<=0;roi_reply<=0;
            roi_req_x<=0;roi_req_y<=0;roi_req_width<=0;roi_req_height<=0;
            camera_crop_enable<=0;camera_roi_x<=0;camera_roi_y<=0;camera_roi_width<=CAM_WIDTH;camera_roi_height<=CAM_HEIGHT;
            camera_roi_packets<=CAM_PACKETS;camera_roi_pixels<=CAM_WIDTH*CAM_HEIGHT;
            camera_roi_last_pixels<=CAM_WIDTH*CAM_HEIGHT-(CAM_PACKETS-1)*690;
            roi_status_x<=0;roi_status_y<=0;roi_status_width<=CAM_WIDTH;roi_status_height<=CAM_HEIGHT;
            roi_status_packets<=CAM_PACKETS;roi_status_pixels<=CAM_WIDTH*CAM_HEIGHT;
            roi_status_last_pixels<=CAM_WIDTH*CAM_HEIGHT-(CAM_PACKETS-1)*690;roi_status_generation<=0;roi_status_valid<=0;
            roi_cache_valid<=0;roi_cache_mac<=0;roi_cache_ip<=0;roi_cache_port<=0;roi_cache_seq<=0;roi_cache_args<=0;
            roi_cache_generation<=0;roi_cache_x<=0;roi_cache_y<=0;roi_cache_width<=0;roi_cache_height<=0;
            roi_cache_packets<=0;roi_cache_last_pixels<=0;roi_cache_pixels<=0;
            manual_wait<=0;manual_reply<=0;manual_watchdog<=0;
            manual_start<=0;manual_set<=0;manual_exposure<=0;manual_gain16<=0;
            manual_status_flags<=0;manual_status_error<=0;manual_status_raw<=0;manual_status_generation<=0;
            manual_cache_valid<=0;manual_cache_mac<=0;manual_cache_ip<=0;manual_cache_port<=0;
            manual_cache_seq<=0;manual_cache_kind<=0;manual_cache_result<=0;manual_cache_flags<=0;
            manual_cache_error<=0;manual_cache_args<=0;manual_cache_raw<=0;manual_cache_generation<=0;
            light_start<=0;light_mask<=0;light_brightness<=0;state<=IDLE;mode<=0;
            tx_start<=0;tx_length<=0;tx_mac<=0;tx_ip<=0;tx_port<=0;index<=0;plen<=0;
            frame_busy<=0;frame_id<=INITIAL_FRAME_ID;packet_id<=0;byte_offset<=0;packet_byte_offset<=0;x<=0;y<=0;
            commands<=0;frames_started<=0;rx_dropped<=0;last_error<=0;cache_valid<=0;
            cache_mac<=0;cache_ip<=0;cache_port<=0;cache_seq<=0;cache_frame<=0;cache_args<=0;
            fmac<=0;fip<=0;fport<=0;source_counter<=0;source_camera<=0;camera_started<=0;
            camera_capture<=0;camera_release<=0;camera_pixel_hold<=0;
            ptype<=0;presult<=0;pseq<=0;pframe<=0;pbusy<=0;pmac<=0;pip<=0;pport<=0;
            packet_gap_count<=0;
            status_state<=0;status_error<=0;status_commands<=0;status_frames<=0;status_dropped<=0;
        end else begin
            tx_start<=0;camera_capture<=0;camera_release<=0;light_start<=0;manual_start<=0;roi_start<=0;
            if(roi_wait && roi_done)begin
                roi_wait<=0;presult<=roi_error?8'd2:8'd0;
                roi_status_x<=roi_x;roi_status_y<=roi_y;roi_status_width<=roi_width;roi_status_height<=roi_height;
                roi_status_packets<=roi_packets;roi_status_last_pixels<=roi_last_pixels;
                roi_status_pixels<=roi_pixels;roi_status_generation<=roi_generation;roi_status_valid<=roi_valid;
                roi_cache_valid<=!roi_error;roi_cache_x<=roi_x;roi_cache_y<=roi_y;
                roi_cache_width<=roi_width;roi_cache_height<=roi_height;roi_cache_packets<=roi_packets;
                roi_cache_pixels<=roi_pixels;roi_cache_generation<=roi_generation;roi_cache_last_pixels<=roi_last_pixels;
            end
            if(!camera_config_ok)manual_cache_valid<=0;
            if(manual_wait)begin
                if(manual_done || manual_watchdog>=CONTROL_TIMEOUT_CYCLES-1)begin
                    manual_wait<=0;presult<=(manual_done && manual_error==0)?0:5;
                    manual_status_flags<=manual_done?{7'b0,manual_locked}:0;
                    manual_status_error<=manual_done?{5'b0,manual_error}:8'd4;
                    manual_status_raw<=manual_done?manual_raw:0;
                    manual_status_generation<=manual_done?manual_generation:0;
                    manual_cache_valid<=1;manual_cache_result<=(manual_done && manual_error==0)?0:5;
                    manual_cache_flags<=manual_done?{7'b0,manual_locked}:0;
                    manual_cache_error<=manual_done?{5'b0,manual_error}:8'd4;
                    manual_cache_raw<=manual_done?manual_raw:0;
                    manual_cache_generation<=manual_done?manual_generation:0;
                end else manual_watchdog<=manual_watchdog+1;
            end
            if(light_wait && light_done)begin
                light_wait<=0;presult<=light_error?8'd4:8'd0;
            end
            if(camera_next)camera_pixel_hold<=camera_pixel;
            if(frame_busy && source_camera && camera_busy)camera_started<=1;
            if(rx_start)count<=0;
            else if(rx_valid)begin
                if(count<20)mem[count]<=rx_data;
                if(count<21)count<=count+1'b1;
            end
            if(rx_done)begin
                count<=0;
                if(rx_error || !envelope)begin rx_dropped<=rx_dropped+1;last_error<=1;end
                else if(pending)begin rx_dropped<=rx_dropped+1;last_error<=2;end
                else begin
                    pending<=1;status_phase<=0;ptype<=cmd_type;pseq<=seq;presult<=result_code;
                    manual_reply<=0;roi_reply<=0;
                    if(cmd_type==6 && result_code==0)begin
                        roi_reply<=1;
                        if(roi_cached)begin
                            roi_status_x<=roi_cache_x;roi_status_y<=roi_cache_y;roi_status_width<=roi_cache_width;roi_status_height<=roi_cache_height;
                            roi_status_packets<=roi_cache_packets;roi_status_last_pixels<=roi_cache_last_pixels;
                            roi_status_pixels<=roi_cache_pixels;roi_status_generation<=roi_cache_generation;roi_status_valid<=1;
                        end else begin
                            roi_start<=1;roi_wait<=1;roi_req_x<=a0;roi_req_y<=a1;roi_req_width<=a2;roi_req_height<=a3;
                            roi_cache_mac<=rx_mac;roi_cache_ip<=rx_ip;roi_cache_port<=rx_port;
                            roi_cache_seq<=seq;roi_cache_args<=args;roi_cache_valid<=0;
                        end
                    end
                    if(cmd_type==7 && result_code==0)begin
                        roi_reply<=1;roi_status_x<=roi_x;roi_status_y<=roi_y;
                        roi_status_width<=roi_width;roi_status_height<=roi_height;roi_status_packets<=roi_packets;
                        roi_status_last_pixels<=roi_last_pixels;roi_status_pixels<=roi_pixels;
                        roi_status_generation<=roi_generation;roi_status_valid<=roi_valid;
                    end
                    pmac<=rx_mac;pip<=rx_ip;pport<=rx_port;pframe<=16'hffff;pbusy<={15'b0,frame_busy};
                    commands<=commands+1;
                    if(result_code==2)last_error<=3;
                    if(result_code==3)last_error<=4;
                    if(cmd_type==4 || cmd_type==5)begin
                        if(manual_cached && manual_cache_kind==cmd_type && manual_cache_args==args)begin
                            manual_reply<=1;manual_status_flags<=manual_cache_flags;
                            manual_status_error<=manual_cache_error;manual_status_raw<=manual_cache_raw;
                            manual_status_generation<=manual_cache_generation;
                        end else if(result_code==0)begin
                            manual_start<=1;manual_set<=cmd_type==4;manual_exposure<=a0;manual_gain16<=a1[9:0];
                            manual_wait<=1;manual_reply<=1;manual_watchdog<=0;
                            manual_cache_mac<=rx_mac;manual_cache_ip<=rx_ip;manual_cache_port<=rx_port;
                            manual_cache_seq<=seq;manual_cache_kind<=cmd_type;manual_cache_args<=args;
                            manual_cache_valid<=0;
                        end
                    end
                    if(cmd_type==1 && result_code==0)begin
                        light_mask<=a0[3:0];light_brightness<=a1[7:0];
                        light_start<=1;light_wait<=1;
                    end
                    if(cmd_type==2 && result_code==0)begin
                        if(cached)pframe<=cache_frame;
                        else begin
                            pframe<=frame_id+1'b1;pbusy<=1;
                            frame_id<=frame_id+1'b1;frame_busy<=1;packet_id<=0;byte_offset<=0;packet_byte_offset<=0;x<=0;y<=0;
                            fmac<=rx_mac;fip<=rx_ip;fport<=rx_port;
                            source_counter<=a0==1;source_camera<=a0>=2;camera_started<=0;
                            camera_crop_enable<=a0==3;
                            camera_roi_x<=a0==3?roi_x:0;camera_roi_y<=a0==3?roi_y:0;
                            camera_roi_width<=a0==3?roi_width:CAM_WIDTH;camera_roi_height<=a0==3?roi_height:CAM_HEIGHT;
                            camera_roi_packets<=a0==3?roi_packets:CAM_PACKETS;
                            camera_roi_last_pixels<=a0==3?roi_last_pixels:CAM_WIDTH*CAM_HEIGHT-(CAM_PACKETS-1)*690;
                            camera_roi_pixels<=a0==3?roi_pixels:CAM_WIDTH*CAM_HEIGHT;
                            if(a0>=2)camera_capture<=1;
                            frames_started<=frames_started+1;
                            cache_valid<=1;cache_mac<=rx_mac;cache_ip<=rx_ip;cache_port<=rx_port;
                            cache_seq<=seq;cache_args<=args;cache_frame<=frame_id+1'b1;
                        end
                    end
                end
            end
            case(state)
                IDLE:begin
                    index<=0;
                    if(pending && !light_wait && !manual_wait && !roi_wait)begin
                        mode<=status_phase?(roi_reply?4:(manual_reply?3:1)):0;tx_length<=status_phase?32:20;
                        tx_mac<=pmac;tx_ip<=pip;tx_port<=pport;
                        // High bits are diagnostic only; original low status bits remain unchanged.
                        // state[15:6]=packet ID modulo 1024, state[5]=DDR source failed.
                        // error[10:8]=source reason, error[7:0]=legacy error.
                        status_state<={packet_id[9:0],camera_failed,camera_config_ok,1'b1,1'b0,light_busy,frame_busy};
                        status_error<={5'b0,camera_fail_code,last_error[7:0]};
                        status_commands<=commands;status_frames<=frames_started;status_dropped<=rx_dropped;
                        state<=START;
                    end else if(frame_busy)begin
                        if(source_camera && camera_started && camera_failed)begin
                            frame_busy<=0;camera_release<=1;last_error<=5;
                        end else if(!source_camera || (camera_started && camera_ready))begin
                            mode<=2;
                            plen<=packet_id==selected_packets-1?
                                selected_last_bytes:1380;
                            tx_length<=packet_id==selected_packets-1?
                                20+selected_last_bytes:1400;
                            tx_mac<=fmac;tx_ip<=fip;tx_port<=fport;state<=START;
                        end
                    end
                end
                START:if(tx_ready)begin tx_start<=1;state<=SEND;end
                SEND:begin
                    if(tx_req)begin
                        index<=index+1'b1;
                        if(mode==2 && index>=20)begin
                            byte_offset<=byte_offset+1;
                            packet_byte_offset<=packet_byte_offset+1'b1;
                            if(byte_offset[0])begin
                                if(x==WIDTH-1)begin x<=0;y<=y+1'b1;end else x<=x+1'b1;
                            end
                        end
                    end
                    if(tx_done)begin state<=WAIT_READY;packet_gap_count<=0;end
                end
                WAIT_READY:if(tx_ready)begin
                    if(mode==2 && packet_gap_count<PACKET_GAP_CYCLES)
                        packet_gap_count<=packet_gap_count+1'b1;
                    else begin
                        state<=IDLE;
                        if(mode==0)begin
                            if((ptype==3 && presult==0) || manual_reply || roi_reply)status_phase<=1;
                            else pending<=0;
                        end else if(mode==1 || mode==3 || mode==4)begin pending<=0;status_phase<=0;manual_reply<=0;roi_reply<=0;end
                        else if(packet_id==selected_packets-1)begin
                            frame_busy<=0;
                            if(source_camera)camera_release<=1;
                        end
                        else begin packet_id<=packet_id+1'b1;packet_byte_offset<=0;end
                    end
                end
            endcase
        end
    end
endmodule
