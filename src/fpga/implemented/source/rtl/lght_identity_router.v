// Optional commands 8..13, versioned sidecar 0x85. Legacy 1..7 controls are
// replayed byte-for-byte; all existing 20-byte image headers/1380 payload remain.
// Metadata is snapshotted before transmission and cannot change mid-datagram.
module lght_identity_router(
    input wire clk,reset,busy,input wire [31:0] request_counter,
    input wire rx_start,rx_valid,rx_done,rx_error,input wire [7:0] rx_data,
    input wire [47:0] rx_mac,input wire [31:0] rx_ip,input wire [15:0] rx_port,
    output reg legacy_rx_start,legacy_rx_valid,legacy_rx_done,output wire legacy_rx_error,
    output reg [7:0] legacy_rx_data,output reg [47:0] legacy_rx_mac,output reg [31:0] legacy_rx_ip,output reg [15:0] legacy_rx_port,
    input wire legacy_tx_start,input wire [15:0] legacy_tx_length,input wire [47:0] legacy_tx_mac,
    input wire [31:0] legacy_tx_ip,input wire [15:0] legacy_tx_port,input wire [7:0] legacy_tx_data,
    output wire legacy_tx_ready,legacy_tx_req,legacy_tx_done,
    input wire tx_ready,tx_req,tx_done,output wire tx_start,output wire [15:0] tx_length,
    output wire [47:0] tx_mac,output wire [31:0] tx_ip,output wire [15:0] tx_port,output wire [7:0] tx_data,
    output reg [63:0] session_id,output reg session_changed,cancel_capture,
    output reg [7:0] pixel_format,output reg format_changed,
    output reg [7:0] settle_frames,discard_frames,
    output reg mask_write,mask_seal,output reg [31:0] mask_word_address,mask_word_data,
    output reg [15:0] mask_width,mask_height,mask_generation,mask_crc,input wire [2:0] mask_result,
    input wire last_valid,input wire [7:0] last_format,input wire [31:0] last_payload_bytes,input wire [63:0] last_payload_crc64,input wire [255:0] last_identity,input wire [63:0] last_parameters,last_geometry,
    input wire [319:0] last_statistics,input wire [191:0] last_features,input wire [63:0] last_rgb_crc64,input wire last_bank,input wire [1:0] last_flags,
    input wire [15:0] last_wait_counts,input wire [31:0] stale_drops,last_fifo_reads,input wire [3:0] fail_code,
    output reg off_req_valid,input wire off_req_ready,output reg [7:0] off_req_op,output reg [63:0] off_req_args,output reg [15:0] off_req_seq,
    input wire off_rsp_valid,output wire off_rsp_ready,input wire [15:0] off_rsp_bytes,
    output wire [10:0] off_rsp_address,input wire [7:0] off_rsp_data,output wire off_rsp_done,
    output reg [31:0] router_drops
);
    reg [7:0] mem[0:19];reg [5:0] count;
    reg [1:0] replay;reg [4:0] replay_index;
    reg diag_pending,diag_start,diag_metadata,diag_capabilities;
    reg off_wait,diag_extended;reg [15:0] extended_bytes;
    reg [1:0] tx_owner,mask_wait;
    reg [15:0] diag_index,diag_seq;
    reg [7:0] diag_command,diag_result;
    reg [47:0] diag_mac;reg [31:0] diag_ip;reg [15:0] diag_port;
    reg [1279:0] diag_payload;
    wire [63:0] args={mem[12],mem[13],mem[14],mem[15],mem[16],mem[17],mem[18],mem[19]};
    wire envelope=count==20 && {mem[0],mem[1],mem[2],mem[3]}==32'h4c474854 && mem[4]==1 && {mem[8],mem[9],mem[10],mem[11]}==32'h000a0000;
    wire new_command=mem[5]>=8 && mem[5]<=31;
    wire [7:0] flags={4'd0,last_flags[0],last_flags[1],(last_identity[255:192]!=0),last_valid};
    wire [1279:0] snapshot={8'd2,flags,{4'd0,fail_code},8'd0,16'h0109,last_identity[15:0],last_identity,
        7'd0,last_bank,8'd0,last_parameters,last_geometry,last_statistics,last_wait_counts,stale_drops,last_fifo_reads,request_counter,last_features,last_rgb_crc64,last_format,8'd0,16'd0,last_payload_bytes,last_payload_crc64};
    reg [7:0] diag_data;
    wire [15:0] diag_length=diag_extended ? extended_bytes+16'd10 : diag_metadata ? 16'd170 : (diag_capabilities ? 16'd32 : 16'd20);
    always @(*)begin
        diag_data=0;
        case(diag_index)
            0:diag_data=8'h4c;1:diag_data=8'h47;2:diag_data=8'h48;3:diag_data=8'h54;
            4:diag_data=1;5:diag_data=diag_extended ? 8'h88 : diag_metadata ? 8'h85 : (diag_capabilities ? 8'h86 : 8'h81);
            6:diag_data=diag_seq[15:8];7:diag_data=diag_seq[7:0];8:diag_data=diag_extended ? extended_bytes[15:8] : 0;9:diag_data=diag_extended ? extended_bytes[7:0] : (diag_metadata ? 160 : (diag_capabilities ? 22 : 10));
            default:begin
                if(diag_extended && diag_index>=10)diag_data=off_rsp_data;
                else if((diag_metadata || diag_capabilities) && diag_index>=10 && diag_index<diag_length)diag_data=diag_payload[1279-(diag_index-10)*8-:8];
                else case(diag_index)
                    10:diag_data=diag_command;11:diag_data=diag_result;
                    12,13:diag_data=8'hff;14:diag_data=0;15:diag_data={7'd0,busy};
                    16:diag_data=0;17:diag_data=8'hff;default:diag_data=0;
                endcase
            end
        endcase
    end
    assign legacy_rx_error=0;
    assign off_rsp_ready=off_wait&&!off_req_valid&&!diag_pending&&tx_owner!=2;
    assign off_rsp_address=diag_index>=10 ? diag_index-10 : 0;
    assign off_rsp_done=tx_owner==2&&tx_done&&diag_extended;
    assign legacy_tx_ready=tx_ready && tx_owner==0 && !diag_pending && !off_wait && mask_wait==0;
    assign legacy_tx_req=tx_req && tx_owner==1;
    assign legacy_tx_done=tx_done && tx_owner==1;
    assign tx_start=(tx_owner==0 && legacy_tx_start) || diag_start;
    assign tx_length=tx_owner==2 ? diag_length : legacy_tx_length;
    assign tx_mac=tx_owner==2 ? diag_mac : legacy_tx_mac;
    assign tx_ip=tx_owner==2 ? diag_ip : legacy_tx_ip;
    assign tx_port=tx_owner==2 ? diag_port : legacy_tx_port;
    assign tx_data=tx_owner==2 ? diag_data : legacy_tx_data;
    always @(posedge clk)begin
        if(reset)begin
            count<=0;replay<=0;replay_index<=0;legacy_rx_start<=0;legacy_rx_valid<=0;legacy_rx_done<=0;legacy_rx_data<=0;
            legacy_rx_mac<=0;legacy_rx_ip<=0;legacy_rx_port<=0;diag_pending<=0;diag_start<=0;diag_metadata<=0;
            tx_owner<=0;mask_wait<=0;diag_index<=0;diag_seq<=0;diag_command<=0;diag_result<=0;diag_mac<=0;diag_ip<=0;diag_port<=0;diag_payload<=0;
            session_id<=0;session_changed<=0;cancel_capture<=0;pixel_format<=1;format_changed<=0;diag_capabilities<=0;settle_frames<=1;discard_frames<=3;
            off_req_valid<=0;off_req_op<=0;off_req_args<=0;off_req_seq<=0;off_wait<=0;diag_extended<=0;extended_bytes<=0;
            mask_write<=0;mask_seal<=0;mask_word_address<=0;mask_word_data<=0;mask_width<=0;mask_height<=0;mask_generation<=0;mask_crc<=0;router_drops<=0;
        end else begin
            legacy_rx_start<=0;legacy_rx_valid<=0;legacy_rx_done<=0;diag_start<=0;session_changed<=0;cancel_capture<=0;format_changed<=0;mask_write<=0;mask_seal<=0;
            if(off_req_valid&&off_req_ready)off_req_valid<=0;
            if(off_rsp_valid&&off_rsp_ready)begin off_wait<=0;diag_extended<=1;extended_bytes<=off_rsp_bytes;diag_pending<=1;end
            if(rx_start)begin
                count<=0;
                if(replay!=0)router_drops<=router_drops+1;
            end else if(rx_valid && replay==0)begin if(count<20)mem[count]<=rx_data;if(count<21)count<=count+1;end
            if(rx_done && replay==0)begin
                count<=0;
                if(rx_error || !envelope)router_drops<=router_drops+1;
                else if(!new_command)begin
                    legacy_rx_mac<=rx_mac;legacy_rx_ip<=rx_ip;legacy_rx_port<=rx_port;replay<=1;replay_index<=0;
                end else if(diag_pending || off_wait || mask_wait!=0 || tx_owner==2)router_drops<=router_drops+1;
                else begin
                    diag_seq<={mem[6],mem[7]};diag_command<=mem[5];diag_result<=0;diag_metadata<=0;diag_capabilities<=0;diag_extended<=0;
                    diag_mac<=rx_mac;diag_ip<=rx_ip;diag_port<=rx_port;diag_pending<=1;
                    case(mem[5])
                        16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31:begin
                            off_req_valid<=1;off_req_op<=mem[5];off_req_args<=args;off_req_seq<={mem[6],mem[7]};off_wait<=1;diag_pending<=0;
                        end
                        8:begin
                            if(busy)diag_result<=3;
                            else if(args==0)diag_result<=2;
                            else if(args!=session_id)begin session_id<=args;session_changed<=1;pixel_format<=1;format_changed<=1;end
                        end
                        9:if(args==0)begin diag_metadata<=1;diag_payload<=snapshot;end else diag_result<=2;
                        10:begin
                            if(busy)diag_result<=3;
                            else begin mask_word_address<=args[63:32];mask_word_data<=args[31:0];mask_write<=1;mask_wait<=2;diag_pending<=0;end
                        end
                        11:begin
                            if(busy)diag_result<=3;
                            else begin mask_width<=args[63:48];mask_height<=args[47:32];mask_generation<=args[31:16];mask_crc<=args[15:0];mask_seal<=1;mask_wait<=2;diag_pending<=0;end
                        end
                        12:begin
                            if(busy)diag_result<=3;
                            else if(args[63:48]>255 || args[47:32]>255 || args[31:0]!=0)diag_result<=2;
                            else begin settle_frames<=args[55:48];discard_frames<=args[39:32];end
                        end
                        14:begin
                            if(args!=0)diag_result<=2;
                            else begin
                                diag_capabilities<=1;
                                diag_payload<={8'd1,16'h0109,pixel_format,8'h07,8'd0,16'd1380,16'd1920,16'd1080,64'h42f0e1eba9ea3693,16'd1,1104'd0};
                            end
                        end
                        15:begin
                            if(busy)diag_result<=3;
                            else if(session_id==0 || (args!=64'd1 && args!=64'h31 && args!=64'h32))diag_result<=2;
                            else if(pixel_format!=args[7:0])begin pixel_format<=args[7:0];format_changed<=1;end
                        end
                        13:begin
                            if(!busy || request_counter==0 || args[31:0]!=0 || args[63:32]!=request_counter)diag_result<=2;
                            else cancel_capture<=1;
                        end
                    endcase
                end
            end
            case(replay)
                1:begin legacy_rx_start<=1;replay<=2;end
                2:begin legacy_rx_valid<=1;legacy_rx_data<=mem[replay_index];replay_index<=replay_index+1;if(replay_index==19)replay<=3;end
                3:begin legacy_rx_done<=1;replay<=0;end
            endcase
            if(mask_wait==2)mask_wait<=1;
            else if(mask_wait==1)begin mask_wait<=0;diag_result<={5'd0,mask_result};diag_pending<=1;end
            if(tx_owner==0)begin
                if(legacy_tx_start)tx_owner<=1;
                else if(diag_pending && tx_ready)begin tx_owner<=2;diag_index<=0;diag_start<=1;end
            end else begin
                if(tx_owner==2 && tx_req)diag_index<=diag_index+1;
                if(tx_done)begin
                    if(tx_owner==2)diag_pending<=0;
                    tx_owner<=0;
                end
            end
        end
    end
endmodule
