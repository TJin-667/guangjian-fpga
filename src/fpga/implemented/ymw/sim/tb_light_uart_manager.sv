`timescale 1ns/1ps
module tb_light_uart_manager;
    localparam CPB=16;
    reg clk=0,reset=1,start=0,rx=1;
    reg [3:0] mask=0;
    reg [7:0] brightness=0;
    wire tx,busy,done,error;
    integer transaction=0,command_count=0;
    reg [63:0] got;
    reg [7:0] value;
    always #4 clk=~clk;
    light_uart_manager #(.CLKS_PER_BIT(CPB),.ACK_TIMEOUT_CYCLES(1000),
        .CMD_GAP_CYCLES(50)) dut(.clk(clk),.reset(reset),.start(start),
        .mask(mask),.brightness(brightness),.uart_rx(rx),.uart_tx(tx),
        .busy(busy),.done(done),.error(error));

    task read_byte;
        output [7:0] b;
        integer k;
        begin
            @(negedge tx);
            repeat(CPB/2)@(posedge clk);
            #1;if(tx!==0)$fatal(1,"start bit");
            for(k=0;k<8;k=k+1)begin
                repeat(CPB)@(posedge clk);#1;b[k]=tx;
            end
            repeat(CPB)@(posedge clk);#1;
            if(tx!==1)$fatal(1,"stop bit");
        end
    endtask
    task reply_byte;
        input [7:0] b;
        integer k;
        begin
            @(negedge clk);rx=0;
            repeat(CPB)@(negedge clk);
            for(k=0;k<8;k=k+1)begin rx=b[k];repeat(CPB)@(negedge clk);end
            rx=1;repeat(CPB)@(negedge clk);
        end
    endtask
    initial forever begin
        got=0;
        repeat(8)begin read_byte(value);got={got[55:0],value};end
        if(transaction==0)begin
            case(command_count)
                0:if(got!==64'h2432313036343135)$fatal(1,"OFF CH1");
                1:if(got!==64'h2432323036343136)$fatal(1,"OFF CH2");
                2:if(got!==64'h2433333045303631)$fatal(1,"SET CH3 E0: %h",got);
                3:if(got!==64'h2432343036343130)$fatal(1,"OFF CH4");
            endcase
        end
        if(transaction==1 && got[55:48]!==8'h32)$fatal(1,"all off command");
        command_count=command_count+1;
        repeat(CPB)@(negedge clk);
        if(transaction==2)reply_byte(8'h26);
        else if(transaction!=3)reply_byte(8'h24);
    end
    task apply_mask;
        input [3:0] m;
        input expected_error;
        begin
            @(negedge clk);mask=m;brightness=8'he0;start=1;
            @(negedge clk);start=0;
            wait(done);#1;
            if(error!==expected_error)$fatal(1,"wrong outcome transaction %0d",transaction);
            if(busy!==0)$fatal(1,"busy after done");
            repeat(300)@(negedge clk);
        end
    endtask
    initial begin
        repeat(10)@(negedge clk);reset=0;
        apply_mask(4,0);
        if(command_count!=4)$fatal(1,"successful apply requires four ACKs");
        transaction=1;command_count=0;apply_mask(0,0);
        if(command_count!=4)$fatal(1,"all off count");
        transaction=2;command_count=0;apply_mask(1,1);
        if(command_count!=1)$fatal(1,"must abort on rejection");
        transaction=3;command_count=0;apply_mask(1,1);
        if(command_count!=1)$fatal(1,"must abort on missing ACK");
        $display("PASS: four-channel serial frames, success ACK, rejection, timeout");
        $finish;
    end
    initial begin #1000000;$fatal(1,"watchdog");end
endmodule
