"""Derive experimental 0106 glue from committed 0105 source; no board tools."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PIN='9c2fb8e05ee02a5c8f8024d31a3fd934f7107124'
TJ='TJ/work/fpga_image_pipeline/'

def replace(text, old, new):
    if text.count(old)!=1:raise ValueError('nonunique patch anchor: '+old[:90])
    return text.replace(old,new)

def generate():
    sources={}
    def read(relative):
        data=subprocess.check_output(['git','show',PIN+':'+relative],cwd=REPO)
        if (REPO/relative).read_bytes()!=data:raise ValueError('local source differs from pinned Git: '+relative)
        sources[relative]=hashlib.sha256(data).hexdigest()
        return data.decode('utf-8').replace('\r\n','\n')
    out=HERE/'derived';out.mkdir(exist_ok=True)
    s=read(TJ+'rtl/tj_frozen_packet_source.v')
    s=replace(s,'input wire clk,reset,capture,release_frame,cancel,invalidate_metadata,','input wire clk,reset,capture,release_frame,cancel,invalidate_metadata,\n    input wire [7:0] pixel_format,input wire [31:0] capture_pixel_count,')
    s=replace(s,'output reg last_valid,output reg [255:0] last_identity,','output reg last_valid,output reg [255:0] last_identity,\n    output reg [7:0] last_format,output reg [31:0] last_payload_bytes,output reg [63:0] last_payload_crc64,')
    s=replace(s,'    wire analysis_start,analysis_cancel,analysis_done;','''    wire analysis_start,analysis_cancel,analysis_done;
    reg [7:0] capture_format;
    wire [63:0] payload_crc64;wire [31:0] payload_bytes;wire encoding_complete;''')
    s=replace(s,'    reg [63:0] geometry;', '''    reg [63:0] geometry;
    wire owner_analysis_done=analysis_done && (analysis_error!=0 || encoding_complete);
    reg [21:0] total_saved_pixels;''')
    s=s.replace('!analysis_done','!owner_analysis_done')
    s=replace(s,'.analysis_done(analysis_done),.analysis_error(analysis_error),','.analysis_done(owner_analysis_done),.analysis_error(analysis_error),')
    s=replace(s,'    saved_packet_store packets(','    transport_packet_store packets(')
    s=replace(s,'.in_valid(saved_valid),.in_ready(saved_ready),.in_pixel(saved_pixel),.in_eof(last_saved),',''' .pixel_format(capture_format),.total_pixels(total_saved_pixels[21:0]),
        .payload_crc64(payload_crc64),.payload_bytes(payload_bytes),.encoding_complete(encoding_complete),
        .in_valid(saved_valid),.in_ready(saved_ready),.in_pixel(saved_pixel),.in_eof(last_saved),''')
    s=replace(s,'if(reset)begin geometry<=0;', 'if(reset)begin total_saved_pixels<=0;capture_format<=1;last_format<=1;last_payload_bytes<=0;last_payload_crc64<=0;geometry<=0;')
    s=replace(s,'geometry<=capture_geometry;expected_parameters<=capture_parameters;','total_saved_pixels<=capture_pixel_count[21:0];capture_format<=pixel_format;last_format<=pixel_format;last_payload_bytes<=0;last_payload_crc64<=0;geometry<=capture_geometry;expected_parameters<=capture_parameters;')
    s=replace(s,'if(stats_commit)begin','if(stats_commit)begin\n                last_format<=capture_format;last_payload_bytes<=payload_bytes;last_payload_crc64<=payload_crc64;')
    s=replace(s,'!failed && owner_error==0 && analysis_done && analysis_error==0', '!failed && owner_error==0 && owner_analysis_done && analysis_error==0 && packet_error==0')
    (out/'tj_frozen_packet_source.v').write_text(s,encoding='utf-8',newline='\n')

    s=read(TJ+'integration/lght_core_camera_identity.v')
    s=replace(s,'input wire clk, reset,session_changed,identity_configuration_valid,','input wire clk, reset,session_changed,identity_configuration_valid,\n    input wire [7:0] pixel_format,output reg [31:0] camera_roi_pixels,')
    s=replace(s,'    reg [31:0] camera_roi_pixels;','')
    s=replace(s,'    wire [31:0] selected_frame_bytes=source_camera?(camera_roi_pixels<<1):FRAME_BYTES;','''    reg [7:0] active_format;
    wire gray_layout_ready,gray_layout_error;wire [31:0] gray_bytes;
    wire [15:0] gray_packets,gray_last_bytes;
    transport_layout layout(
        .clk(clk),.reset(reset),.cancel(session_changed),.start(camera_capture && active_format==8'h31),
        .pixel_format(active_format),.total_pixels(camera_roi_pixels[21:0]),.ready(gray_layout_ready),
        .error(gray_layout_error),.total_bytes(gray_bytes),.packet_count(gray_packets),.last_bytes(gray_last_bytes));
    wire [31:0] selected_frame_bytes=source_camera ?
        (active_format==8'h31 ? gray_bytes : (camera_roi_pixels<<1)) : FRAME_BYTES;''')
    s=replace(s,'wire [15:0] selected_packets=source_camera?camera_roi_packets:PACKETS;','wire [15:0] selected_packets=source_camera ? (active_format==8\'h31 ? gray_packets : camera_roi_packets) : PACKETS;')
    s=replace(s,'wire [15:0] selected_last_bytes=source_camera?{4\'b0,camera_roi_last_pixels,1\'b0}:FRAME_BYTES-(PACKETS-1)*1380;', 'wire [15:0] selected_last_bytes=source_camera ? (active_format==8\'h31 ? gray_last_bytes : {4\'b0,camera_roi_last_pixels,1\'b0}) : FRAME_BYTES-(PACKETS-1)*1380;')
    s=replace(s,'camera_started && camera_ready && !pending;', 'camera_started && camera_ready && (active_format!=8\'h31 || gray_layout_ready) && !pending;')
    s=replace(s,'if(source_camera && camera_started && camera_failed)begin', 'if(source_camera && ((camera_started && camera_failed) || (active_format==8\'h31 && gray_layout_error)))begin')
    s=replace(s,'else if(!source_camera || (camera_started && camera_ready))begin', 'else if(!source_camera || (camera_started && camera_ready && (active_format!=8\'h31 || gray_layout_ready)))begin')
    s=replace(s,'18:tx_data=1;','18:tx_data=source_camera ? active_format : 1;')
    s=replace(s,'12:tx_data=1;13:tx_data=5;','12:tx_data=1;13:tx_data=6;')
    s=replace(s,'frame_busy<=0;frame_id<=INITIAL_FRAME_ID;', 'active_format<=1;frame_busy<=0;frame_id<=INITIAL_FRAME_ID;')
    s=replace(s,'source_counter<=a0==1;source_camera<=a0>=2;', 'active_format<=a0>=2 ? pixel_format : 1;source_counter<=a0==1;source_camera<=a0>=2;')
    (out/'lght_core_camera_identity.v').write_text(s,encoding='utf-8',newline='\n')

    s=read(TJ+'rtl/lght_identity_router.v')
    s=replace(s,'output reg [63:0] session_id,output reg session_changed,cancel_capture,', 'output reg [63:0] session_id,output reg session_changed,cancel_capture,\n    output reg [7:0] pixel_format,output reg format_changed,')
    s=replace(s,'input wire last_valid,input wire [255:0] last_identity,', 'input wire last_valid,input wire [7:0] last_format,input wire [31:0] last_payload_bytes,input wire [63:0] last_payload_crc64,input wire [255:0] last_identity,')
    s=replace(s,'reg diag_pending,diag_start,diag_metadata;', 'reg diag_pending,diag_start,diag_metadata,diag_capabilities;')
    s=replace(s,'mem[5]>=8 && mem[5]<=13', 'mem[5]>=8 && mem[5]<=15')
    s=replace(s,"snapshot={8'd1,flags", "snapshot={8'd2,flags")
    s=replace(s,"16'h0105,last_identity", "16'h0106,last_identity")
    s=replace(s,"last_features,last_rgb_crc64,128'd0};", "last_features,last_rgb_crc64,last_format,8'd0,16'd0,last_payload_bytes,last_payload_crc64};")
    s=replace(s,"wire [15:0] diag_length=diag_metadata ? 16'd170 : 16'd20;", "wire [15:0] diag_length=diag_metadata ? 16'd170 : (diag_capabilities ? 16'd32 : 16'd20);")
    s=replace(s,"5:diag_data=diag_metadata ? 8'h85 : 8'h81;", "5:diag_data=diag_metadata ? 8'h85 : (diag_capabilities ? 8'h86 : 8'h81);")
    s=replace(s,'9:diag_data=diag_metadata ? 160 : 10;', '9:diag_data=diag_metadata ? 160 : (diag_capabilities ? 22 : 10);')
    s=replace(s,'if(diag_metadata && diag_index>=10 && diag_index<170)', 'if((diag_metadata || diag_capabilities) && diag_index>=10 && diag_index<diag_length)')
    s=replace(s,'session_id<=0;session_changed<=0;cancel_capture<=0;', 'session_id<=0;session_changed<=0;cancel_capture<=0;pixel_format<=1;format_changed<=0;diag_capabilities<=0;')
    s=replace(s,'diag_start<=0;session_changed<=0;cancel_capture<=0;mask_write<=0;', 'diag_start<=0;session_changed<=0;cancel_capture<=0;format_changed<=0;mask_write<=0;')
    s=replace(s,'diag_result<=0;diag_metadata<=0;', 'diag_result<=0;diag_metadata<=0;diag_capabilities<=0;')
    s=replace(s,'begin session_id<=args;session_changed<=1;end', 'begin session_id<=args;session_changed<=1;pixel_format<=1;format_changed<=1;end')
    s=replace(s,'                        13:begin', '''                        14:begin
                            if(args!=0)diag_result<=2;
                            else begin
                                diag_capabilities<=1;
                                diag_payload<={8'd1,16'h0106,pixel_format,8'h03,8'd0,16'd1380,16'd1920,16'd1080,64'h42f0e1eba9ea3693,16'd1,1104'd0};
                            end
                        end
                        15:begin
                            if(busy)diag_result<=3;
                            else if(session_id==0 || (args!=64'd1 && args!=64'h31))diag_result<=2;
                            else if(pixel_format!=args[7:0])begin pixel_format<=args[7:0];format_changed<=1;end
                        end
                        13:begin''')
    (out/'lght_identity_router.v').write_text(s,encoding='utf-8',newline='\n')

    s=read(TJ+'integration/bx72_ddr_identity_top.v')
    s=replace(s,'wire session_changed,cancel_capture,config_valid,epoch_fault;', 'wire session_changed,cancel_capture,config_valid,epoch_fault;\n    wire [7:0] pixel_format,last_format;wire format_changed;\n    wire [31:0] last_payload_bytes,source_roi_pixels;wire [63:0] last_payload_crc64;')
    s=replace(s,'.session_id(session_id),.session_changed(session_changed),.cancel_capture(cancel_capture),', '.pixel_format(pixel_format),.format_changed(format_changed),\n        .last_format(last_format),.last_payload_bytes(last_payload_bytes),.last_payload_crc64(last_payload_crc64),\n        .session_id(session_id),.session_changed(session_changed),.cancel_capture(cancel_capture),')
    s=replace(s,'.clk(net_clk),.reset(net_reset),.session_changed(session_changed),.identity_configuration_valid(config_valid),', '.clk(net_clk),.reset(net_reset),.camera_roi_pixels(source_roi_pixels),.pixel_format(pixel_format),.session_changed(session_changed || format_changed),.identity_configuration_valid(config_valid),')
    s=replace(s,'.cancel(cancel_capture || rd_fault_sync[2]),.invalidate_metadata(session_changed),', '.cancel(cancel_capture || rd_fault_sync[2]),.invalidate_metadata(session_changed || format_changed),\n        .capture_pixel_count(source_roi_pixels),.pixel_format(pixel_format),.last_format(last_format),.last_payload_bytes(last_payload_bytes),.last_payload_crc64(last_payload_crc64),')
    (out/'bx72_ddr_identity_top.v').write_text(s,encoding='utf-8',newline='\n')
    result={'base_commit':PIN,'input_sha256':sources,'derived_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.v'))},'firmware':'0x0106 experimental, not deployed','board_operations':False}
    (out/'SOURCE_MANIFEST.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':print(json.dumps(generate(),indent=2))
