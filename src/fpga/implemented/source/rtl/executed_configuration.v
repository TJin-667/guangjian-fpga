// Net-domain evidence from REAL executor start/done/readback ports. GET does
// not increment the configuration epoch; failed/unfinished settings invalidate it.
module executed_configuration(
    input wire clk,reset,manual_start,manual_set,manual_done,manual_locked,
    input wire [2:0] manual_error,input wire [111:0] manual_raw,input wire [15:0] manual_generation,
    input wire light_start,light_done,light_error,input wire [3:0] light_mask,input wire [7:0] light_brightness,
    input wire [7:0] settle_frames,discard_frames,
    output reg [31:0] config_epoch,output reg [15:0] light_generation,
    output wire [63:0] parameters,output wire valid,output reg epoch_fault
);
    reg cam_pending,cam_set,light_pending,cam_valid,light_valid;
    reg [15:0] exposure,gain;reg [3:0] held_mask,applied_mask;
    reg [7:0] held_brightness,applied_brightness;
    wire camera_change=cam_pending && cam_set && manual_done && manual_locked && manual_error==0;
    wire light_change=light_pending && light_done && !light_error;
    wire [32:0] next_epoch={1'b0,config_epoch}+{32'd0,camera_change}+{32'd0,light_change};
    assign parameters={exposure,gain,4'd0,applied_mask,applied_brightness,settle_frames,discard_frames};
    assign valid=cam_valid && light_valid && !cam_pending && !light_pending && !epoch_fault;
    always @(posedge clk)begin
        if(reset)begin
            cam_pending<=0;cam_set<=0;light_pending<=0;cam_valid<=0;light_valid<=0;
            exposure<=0;gain<=0;held_mask<=0;applied_mask<=0;held_brightness<=0;applied_brightness<=0;
            config_epoch<=0;light_generation<=0;epoch_fault<=0;
        end else begin
            if(manual_start)begin cam_pending<=1;cam_set<=manual_set;cam_valid<=0;end
            if(light_start)begin light_pending<=1;light_valid<=0;held_mask<=light_mask;held_brightness<=light_brightness;end
            if(cam_pending && manual_done)begin
                cam_pending<=0;cam_valid<=manual_locked && manual_error==0;
                if(manual_locked && manual_error==0)begin
                    exposure<={manual_raw[99:96],manual_raw[95:88],manual_raw[87:84]};
                    gain<={6'd0,manual_raw[73:72],manual_raw[71:64]};
                end
            end
            if(light_pending && light_done)begin
                light_pending<=0;light_valid<=!light_error;
                if(!light_error)begin applied_mask<=held_mask;applied_brightness<=held_brightness;light_generation<=light_generation+1;end
            end
            if(camera_change || light_change)begin
                if(next_epoch[32])begin epoch_fault<=1;cam_valid<=0;light_valid<=0;end
                else config_epoch<=next_epoch[31:0];
            end
        end
    end
endmodule
