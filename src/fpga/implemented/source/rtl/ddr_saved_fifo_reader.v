// One-clock-latency FIFO -> elastic saved-native stream. Never random DDR reads.
// mask_data is the synchronous response to mask_read/mask_address, also one clock.
module ddr_saved_fifo_reader #(
    parameter integer MAX_WIDTH=1920,MAX_HEIGHT=1080,STALL_LIMIT=125000000
)(
    input wire clk,reset,cancel,
    input wire cfg_valid,output wire cfg_ready,input wire cfg_source_complete,
    input wire [15:0] cfg_full_width,cfg_full_height,cfg_x,cfg_y,cfg_width,cfg_height,
    input wire [31:0] cfg_request_id,
    output wire rdfifo_rden,input wire rdfifo_empty,input wire [15:0] rdfifo_dout,
    output wire mask_read,output wire [21:0] mask_address,input wire mask_data,
    output reg out_valid,input wire out_ready,output reg [15:0] out_pixel,out_x,out_y,
    output reg out_mask,out_sof,out_eol,out_eof,
    output reg [31:0] out_request_id,
    output wire result_valid,input wire result_ready,output reg [3:0] result_error,
    output reg [31:0] issued_reads,returned_reads,saved_pixels
);
    localparam IDLE=0,READ=1,DRAIN=2,DONE=3;
    reg [1:0] state;
    reg [15:0] fw,fh,left,top,right,bottom,width,height,x,y,qx,qy;
    reg pending,qselected,qlast,dropping;
    reg [31:0] next_saved,stall;
    wire selected=x>=left && x<right && y>=top && y<bottom;
    wire last=x==fw-1 && y==fh-1;
    wire [16:0] cr={1'b0,cfg_x}+{1'b0,cfg_width},cb={1'b0,cfg_y}+{1'b0,cfg_height};
    wire config_ok=cfg_source_complete && cfg_full_width>0 && cfg_full_height>0 &&
        cfg_full_width<=MAX_WIDTH && cfg_full_height<=MAX_HEIGHT &&
        cfg_width>=9 && cfg_height>=9 && cr<=cfg_full_width && cb<=cfg_full_height;
    assign cfg_ready=state==IDLE && !reset;
    assign rdfifo_rden=state==READ && !pending && (!out_valid || dropping || cancel) && !rdfifo_empty && !reset;
    assign mask_read=rdfifo_rden && selected && !dropping && !cancel;
    assign mask_address=next_saved[21:0];
    assign result_valid=state==DONE && !reset;
    always @(posedge clk)begin
        if(reset)begin
            state<=IDLE;out_valid<=0;pending<=0;dropping<=0;result_error<=0;
            fw<=0;fh<=0;left<=0;top<=0;right<=0;bottom<=0;width<=0;height<=0;
            x<=0;y<=0;qx<=0;qy<=0;qselected<=0;qlast<=0;next_saved<=0;stall<=0;
            issued_reads<=0;returned_reads<=0;saved_pixels<=0;out_request_id<=0;
            out_pixel<=0;out_x<=0;out_y<=0;out_mask<=0;out_sof<=0;out_eol<=0;out_eof<=0;
        end else begin
            if(out_valid && out_ready)begin out_valid<=0;saved_pixels<=saved_pixels+1;end
            if(cancel && (state==READ || state==DRAIN))begin dropping<=1;out_valid<=0;result_error<=3;end
            case(state)
                IDLE:if(cfg_valid)begin
                    fw<=cfg_full_width;fh<=cfg_full_height;left<=cfg_x;top<=cfg_y;
                    right<=cr[15:0];bottom<=cb[15:0];width<=cfg_width;height<=cfg_height;
                    x<=0;y<=0;pending<=0;out_valid<=0;dropping<=0;next_saved<=0;stall<=0;
                    issued_reads<=0;returned_reads<=0;saved_pixels<=0;out_request_id<=cfg_request_id;result_error<=0;
                    if(config_ok)state<=READ;else begin result_error<=1;state<=DONE;end
                end
                READ:begin
                    if(rdfifo_rden)begin
                        pending<=1;qx<=x;qy<=y;qselected<=selected;qlast<=last;issued_reads<=issued_reads+1;
                        if(x==fw-1)begin x<=0;y<=y+1;end else x<=x+1;
                        stall<=0;
                    end else if(pending)begin
                        pending<=0;returned_reads<=returned_reads+1;stall<=0;
                        if(qselected && !dropping && !cancel)begin
                            out_valid<=1;out_pixel<=rdfifo_dout;out_mask<=mask_data;
                            out_x<=qx-left;out_y<=qy-top;next_saved<=next_saved+1;
                            out_sof<=qx==left && qy==top;out_eol<=qx==right-1;out_eof<=qx==right-1 && qy==bottom-1;
                        end
                        if(qlast)state<=DRAIN;
                    end else if(!out_valid || out_ready || dropping)begin
                        stall<=stall+1;
                        if(stall==STALL_LIMIT-1)begin result_error<=4;out_valid<=0;state<=DONE;end
                    end
                end
                DRAIN:if(!out_valid || out_ready || dropping || cancel)state<=DONE;
                DONE:if(result_ready)state<=IDLE;
            endcase
        end
    end
endmodule
