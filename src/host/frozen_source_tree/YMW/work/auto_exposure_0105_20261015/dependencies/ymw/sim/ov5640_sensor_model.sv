`timescale 1ns/1ps
// Byte-level sensor peer driven only by physical SCCB START/STOP/clock edges.
module ov5640_sensor_model(inout wire sda,scl,input wire reset_n,
    input wire nack_all,hold_clock,corrupt_gain);
    reg drive_low=0;
    assign sda=drive_low?1'b0:1'bz;
    assign scl=hold_clock?1'b0:1'bz;
    reg [7:0] registers[0:65535];
    reg active=0,sending=0,wait_stop=0,want_read=0;
    integer bits=0,phase=0,writes=0,reads=0;
    reg [7:0] shift_byte=0,read_byte=0;
    reg [15:0] pointer=0;
    initial begin
        for(integer i=0;i<65536;i=i+1)registers[i]=0;
        registers[16'h300a]=8'h56;registers[16'h300b]=8'h40;
        registers[16'h3501]=2;registers[16'h350b]=16;
    end
    always @(negedge reset_n)begin active=0;sending=0;wait_stop=0;drive_low=0;bits=0;phase=0;end
    always @(negedge sda)if(reset_n && scl===1'b1)begin
        active=1;sending=0;wait_stop=0;bits=0;phase=0;shift_byte=0;want_read=0;
    end
    always @(posedge sda)if(scl===1'b1)begin active=0;sending=0;wait_stop=0;drive_low=0;end
    always @(posedge scl)if(reset_n && active && !wait_stop)begin
        if(sending)begin
            if(bits<8)bits=bits+1;
            else begin
                if(sda!==1'b1)$fatal(1,"Master failed to NACK final read byte");
                reads=reads+1;sending=0;wait_stop=1;bits=0;
            end
        end else if(bits<8)begin
            shift_byte={shift_byte[6:0],sda};bits=bits+1;
            if(bits==8 && phase==0)begin
                if(shift_byte!=8'h78 && shift_byte!=8'h79)$fatal(1,"Wrong sensor device address");
                want_read=shift_byte[0];
            end
        end else begin
            if(!nack_all)case(phase)
                0:if(want_read)begin
                    sending=1;read_byte=registers[pointer];
                    if(corrupt_gain && pointer==16'h350b)read_byte=read_byte^8'h01;
                end
                1:pointer[15:8]=shift_byte;
                2:pointer[7:0]=shift_byte;
                3:begin registers[pointer]=shift_byte;writes=writes+1;end
            endcase
            bits=0;shift_byte=0;phase=phase+1;
        end
    end
    always @(negedge scl)if(reset_n)begin
        if(!active || wait_stop)drive_low=0;
        else if(sending)drive_low=bits<8?!read_byte[7-bits]:0;
        else drive_low=bits==8 && !nack_all;
    end
endmodule
