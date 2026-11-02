// Request-driven DVP capture. Context arrives through a held snapshot mailbox.
// Every accepted frame starts at a fresh VSYNC, closes at the next VSYNC, then
// waits for the existing DDR write-completion toggle before publication.
module frame_identity_tracker #(
    parameter integer FRAME_PIXELS=1920*1080,WRITE_TIMEOUT=250000000
)(
    input wire cam_clk,reset,capture_enable,cam_vsync,cam_href,input wire [7:0] cam_data,
    input wire request_valid,output wire request_ready,input wire [399:0] request_data,
    input wire cancel_active,
    input wire wrfifo_full,wr_done_toggle,
    output reg wrfifo_clr,output reg wrfifo_wren,output reg [15:0] wrfifo_din,output reg wr_frame_bank,
    output wire pub_valid,input wire pub_ready,output wire [415:0] pub_data,
    output reg fatal,output reg [31:0] dvp_sequence,publish_sequence,
    output reg event_start,event_end,event_drop,event_write_done,event_publish,
    output wire [255:0] event_identity,output wire [3:0] debug_state
);
    localparam IDLE=0,BOUNDARY=1,WAIT_FRAMES=2,CAPTURE=3,WAIT_WRITE=4,PUBLISH=5,WAIT_RELEASE=6,ERROR=7;
    reg [3:0] state;
    reg [255:0] base_identity,frame_identity;
    reg [63:0] parameters,geometry;
    reg [15:0] flags;
    reg bank,vsync_d,byte_phase,bad,cancelled,old_done,wait_open;
    reg [7:0] first_byte,settle_left,discard_left,settle_done,discard_done;
    reg [31:0] pixel_count,timer,wait_pixels;
    reg [4:0] clear_count;reg [3:0] pub_error;
    (* ASYNC_REG="TRUE" *) reg [2:0] done_sync;
    wire boundary=cam_vsync && !vsync_d;
    assign request_ready=state==IDLE && !reset && !fatal;
    assign pub_valid=state==PUBLISH && !reset;
    assign pub_data={frame_identity,parameters,geometry,bank,pub_error,flags[1:0],settle_done,discard_done,9'd0};
    assign event_identity=frame_identity;
    assign debug_state=state;
    always @(posedge cam_clk)begin
        if(reset)begin
            state<=IDLE;base_identity<=0;frame_identity<=0;parameters<=0;geometry<=0;flags<=0;
            bank<=0;vsync_d<=0;byte_phase<=0;bad<=0;cancelled<=0;old_done<=0;wait_open<=0;
            first_byte<=0;settle_left<=0;discard_left<=0;settle_done<=0;discard_done<=0;
            pixel_count<=0;wait_pixels<=0;timer<=0;clear_count<=0;pub_error<=0;fatal<=0;
            wrfifo_clr<=0;wrfifo_wren<=0;wrfifo_din<=0;wr_frame_bank<=0;done_sync<=0;dvp_sequence<=0;publish_sequence<=0;
            event_start<=0;event_end<=0;event_drop<=0;event_write_done<=0;event_publish<=0;
        end else begin
            done_sync<={done_sync[1:0],wr_done_toggle};vsync_d<=cam_vsync;
            wrfifo_wren<=0;event_start<=0;event_end<=0;event_drop<=0;event_write_done<=0;event_publish<=0;
            // A registered level drives the vendor FIFO asynchronous reset;
            // combinational counter decode could otherwise glitch that pin.
            wrfifo_clr<=clear_count>1;
            if(clear_count!=0)clear_count<=clear_count-1;
            if(boundary)begin
                if(dvp_sequence==32'hffffffff)begin fatal<=1;state<=ERROR;end
                else dvp_sequence<=dvp_sequence+1;
                byte_phase<=0;
            end
            if(cancel_active && state!=IDLE)cancelled<=1;
            if(!capture_enable && state!=IDLE && state!=PUBLISH && state!=WAIT_RELEASE)begin fatal<=1;state<=ERROR;end
            else if((!fatal || state==PUBLISH || state==WAIT_RELEASE) && !(boundary && dvp_sequence==32'hffffffff))case(state)
                IDLE:if(request_valid)begin
                    base_identity<=request_data[399:144];frame_identity<=request_data[399:144];
                    parameters<=request_data[143:80];geometry<=request_data[79:16];flags<=request_data[15:0];
                    settle_left<=request_data[95:88];discard_left<=request_data[87:80]; // parameters low two bytes
                    settle_done<=0;discard_done<=0;cancelled<=cancel_active;pub_error<=0;wait_open<=0;wait_pixels<=0;
                    state<=BOUNDARY;
                end
                BOUNDARY:if(boundary && capture_enable)begin
                    wait_open<=1;wait_pixels<=0;byte_phase<=0;
                    if(settle_left==0 && discard_left==0 && !cancelled && !cancel_active)begin
                        state<=CAPTURE;pixel_count<=0;bad<=0;old_done<=done_sync[2];clear_count<=16;wrfifo_clr<=1;wr_frame_bank<=bank;
                        frame_identity<={base_identity[255:128],dvp_sequence+1,32'd0,base_identity[63:0]};event_start<=1;
                    end else if(cancelled || cancel_active)begin pub_error<=3;state<=PUBLISH;end
                    else state<=WAIT_FRAMES;
                end
                WAIT_FRAMES:begin
                    if(cam_href)begin
                        byte_phase<=~byte_phase;
                        if(byte_phase)wait_pixels<=wait_pixels+1;
                    end else byte_phase<=0;
                    if(boundary)begin
                        byte_phase<=0;wait_pixels<=0;event_drop<=1;
                        if(wait_open && wait_pixels==FRAME_PIXELS && !byte_phase)begin
                            if(settle_left!=0)begin settle_left<=settle_left-1;settle_done<=settle_done+1;end
                            else if(discard_left!=0)begin discard_left<=discard_left-1;discard_done<=discard_done+1;end
                            if((settle_left==1 && discard_left==0) || (settle_left==0 && discard_left==1))begin
                                if(cancelled || cancel_active)begin pub_error<=3;state<=PUBLISH;end
                                else begin
                                    state<=CAPTURE;pixel_count<=0;bad<=0;old_done<=done_sync[2];clear_count<=16;wrfifo_clr<=1;wr_frame_bank<=bank;
                                    frame_identity<={base_identity[255:128],dvp_sequence+1,32'd0,base_identity[63:0]};event_start<=1;
                                end
                            end
                        end
                        if(cancelled || cancel_active)begin pub_error<=3;state<=PUBLISH;end
                    end
                end
                CAPTURE:begin
                    if(!cam_href)byte_phase<=0;
                    else if(clear_count==0)begin
                        if(!byte_phase)begin first_byte<=cam_data;byte_phase<=1;end
                        else begin
                            byte_phase<=0;pixel_count<=pixel_count+1;
                            if(pixel_count>=FRAME_PIXELS || wrfifo_full)bad<=1;
                            else begin wrfifo_wren<=1;wrfifo_din<={first_byte,cam_data};end
                        end
                    end
                    if(boundary)begin
                        event_end<=1;byte_phase<=0;timer<=0;
                        if(bad || byte_phase || pixel_count!=FRAME_PIXELS)begin fatal<=1;pub_error<=4;state<=PUBLISH;end
                        else state<=WAIT_WRITE;
                    end
                end
                WAIT_WRITE:begin
                    timer<=timer+1;
                    if(done_sync[2]!=old_done)begin
                        event_write_done<=1;pub_error<=cancelled || cancel_active ? 3 : 0;
                        if(publish_sequence==32'hffffffff)begin fatal<=1;pub_error<=6;state<=PUBLISH;end
                        else begin
                            publish_sequence<=publish_sequence+1;
                            frame_identity[95:64]<=publish_sequence+1;state<=PUBLISH;
                        end
                    end else if(timer==WRITE_TIMEOUT-1)begin fatal<=1;pub_error<=5;state<=PUBLISH;end
                end
                PUBLISH:if(pub_ready)begin event_publish<=1;state<=WAIT_RELEASE;end
                WAIT_RELEASE:begin
                    // The enclosing publisher mailbox returns readiness only after
                    // net owner consumes descriptor following its STOP acknowledgement.
                    if(pub_ready)begin
                        if(fatal)state<=ERROR;
                        else begin bank<=~bank;state<=IDLE;end
                    end
                end
                ERROR:begin end
            endcase
        end
    end
endmodule
