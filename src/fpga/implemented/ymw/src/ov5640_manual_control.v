`timescale 1ns/1ps
// Every SET/GET reads the sensor. A write ACK is insufficient for a lock.
module ov5640_manual_control(
    input wire clk, reset_n, config_ok, start, set_values,
    input wire [15:0] exposure_lines,
    input wire [9:0] gain16,
    output wire busy,
    output reg done, locked,
    output reg [2:0] error,
    output reg [15:0] generation,
    output reg [111:0] raw,
    output reg bus_start, bus_read,
    output reg [15:0] bus_address,
    output reg [7:0] bus_data,
    input wire bus_done,
    input wire [2:0] bus_error,
    input wire [7:0] bus_read_data
);
    localparam IDLE=0, ISSUE=1, WAIT_BUS=2, CHECK=3;
    reg [1:0] state;
    reg writing, requested_set, expected_valid;
    reg [3:0] index;
    reg [15:0] expected_exposure;
    reg [9:0] expected_gain;
    wire [19:0] actual_exposure={raw[99:96],raw[95:88],raw[87:80]};
    wire [9:0] actual_gain={raw[73:72],raw[71:64]};
    wire registers_match=raw[111:104]==8'h03 && raw[103:100]==0 &&
        actual_exposure=={expected_exposure,4'b0} && raw[79:74]==0 &&
        actual_gain==expected_gain && raw[63:48]==16'd2500 &&
        raw[47:32]==16'd1120 && raw[31:16]==0 && raw[15:0]==16'h5640;
    assign busy=state!=IDLE;
    always @(posedge clk or negedge reset_n) begin
        if(!reset_n)begin
            state<=IDLE;done<=0;locked<=0;error<=0;generation<=0;raw<=0;
            bus_start<=0;bus_read<=0;bus_address<=0;bus_data<=0;
            writing<=0;requested_set<=0;expected_valid<=0;index<=0;
            expected_exposure<=0;expected_gain<=0;
        end else begin
            done<=0;bus_start<=0;
            case(state)
                IDLE:if(start)begin
                    locked<=0;error<=0;raw<=0;index<=0;requested_set<=set_values;
                    if(!config_ok)begin error<=3;done<=1;expected_valid<=0;end
                    else if(set_values && (exposure_lines<1 || exposure_lines>1116 || gain16<16))begin
                        error<=3;done<=1;expected_valid<=0;
                    end else begin
                        writing<=set_values;
                        if(set_values)begin
                            expected_exposure<=exposure_lines;expected_gain<=gain16;expected_valid<=0;
                        end
                        state<=ISSUE;
                    end
                end
                ISSUE:begin
                    bus_start<=1;bus_read<=!writing;bus_data<=0;
                    if(writing)case(index)
                        0:begin bus_address<=16'h3503;bus_data<=8'h03;end
                        1:begin bus_address<=16'h3500;bus_data<={4'b0,expected_exposure[15:12]};end
                        2:begin bus_address<=16'h3501;bus_data<=expected_exposure[11:4];end
                        3:begin bus_address<=16'h3502;bus_data<={expected_exposure[3:0],4'b0};end
                        4:begin bus_address<=16'h350a;bus_data<={6'b0,expected_gain[9:8]};end
                        5:begin bus_address<=16'h350b;bus_data<=expected_gain[7:0];end
                        default:bus_address<=0;
                    endcase
                    else case(index)
                        0:bus_address<=16'h3503;
                        1:bus_address<=16'h3500;
                        2:bus_address<=16'h3501;
                        3:bus_address<=16'h3502;
                        4:bus_address<=16'h350a;
                        5:bus_address<=16'h350b;
                        6:bus_address<=16'h380c;
                        7:bus_address<=16'h380d;
                        8:bus_address<=16'h380e;
                        9:bus_address<=16'h380f;
                        10:bus_address<=16'h350c;
                        11:bus_address<=16'h350d;
                        12:bus_address<=16'h300a;
                        13:bus_address<=16'h300b;
                        default:bus_address<=0;
                    endcase
                    state<=WAIT_BUS;
                end
                WAIT_BUS:if(bus_done)begin
                    if(bus_error!=0)begin error<=1;locked<=0;expected_valid<=0;done<=1;state<=IDLE;end
                    else if(writing && index==5)begin writing<=0;index<=0;state<=ISSUE;end
                    else begin
                        if(!writing)raw[111-index*8 -: 8]<=bus_read_data;
                        if(!writing && index==13)state<=CHECK;
                        else begin index<=index+1'b1;state<=ISSUE;end
                    end
                end
                CHECK:begin
                    done<=1;state<=IDLE;
                    if((requested_set || expected_valid) && registers_match)begin
                        locked<=1;expected_valid<=1;
                        if(requested_set)generation<=generation+1'b1;
                    end else if(requested_set || expected_valid)begin
                        error<=2;locked<=0;expected_valid<=0;
                    end
                end
                default:begin state<=IDLE;error<=3;locked<=0;expected_valid<=0;done<=1;end
            endcase
        end
    end
endmodule
